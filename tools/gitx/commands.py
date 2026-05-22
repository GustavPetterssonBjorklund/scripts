import sys
from collections.abc import Callable
import re

from config import ensure_project_rules_file, get_project_rules, projects_config_path
from git_runner import output, run
from openai_commit import clean_commit_message, generate_commit_message, generate_merge_resolution
from openai_tag import generate_tag_suggestion
from openai_validate import ValidationResponse, validate_diff
from tui import (
    approve_generated_commit_message,
    approve_generated_tag,
    approve_validation_findings,
    choose_checkout_branch,
    choose_merge_action,
    edit_file,
    CheckoutBranch,
    MergeBranch,
    MergeConflict,
    run_validation_with_loading,
    show_validation_result,
)


def add(git_args: list[str]):
    return run(["git", "add", *git_args] if git_args else ["git", "add", "."])


def commit(git_args: list[str]):
    if not git_args:
        return run(["git", "commit"])

    flag_args = [arg for arg in git_args if arg.startswith("--")]
    message_args = [arg for arg in git_args if not arg.startswith("--")]
    ai = "--ai" in flag_args
    validate = "--validate" in flag_args
    unknown_flags = [arg for arg in flag_args if arg not in ("--ai", "--validate")]
    if (ai or validate) and (unknown_flags or message_args):
        print("Usage: gitx c [message] | gitx c --validate | gitx c --ai [--validate]")
        return 1

    if not ai and not validate:
        if any(arg.startswith("-") for arg in git_args):
            return run(["git", "commit", *git_args])
        return run(["git", "commit", "-m", " ".join(git_args)])

    diff = _staged_diff()
    if diff is None:
        return 1

    if not ai:
        if validate and _run_validation(diff, prompt_to_continue=True) != 0:
            return 1
        return run(["git", "commit"])

    validation_response = None
    if validate:
        validation_response = run_validation_with_loading(lambda progress: _validation_response(diff, progress))
        if validation_response is None:
            return 1
        if not isinstance(validation_response, ValidationResponse):
            print("AI validation failed: unexpected validation response.")
            return 1
        if validation_response.used_truncated_diff:
            print("Note: staged diff was truncated before validation.")
        if validation_response.passed:
            print("AI validation passed.")
        elif not sys.stdin.isatty() or not sys.stdout.isatty():
            print("\nAI validation findings:")
            print(validation_response.output_text)
            print("Commit cancelled because validation produced findings.")
            return 1

    used_truncated_diff = False

    def generate_message(progress: Callable[[str], None]) -> str | None:
        nonlocal used_truncated_diff
        response = generate_commit_message(diff, progress)
        if not response or not response.output_text:
            return None
        used_truncated_diff = response.used_truncated_diff
        message = clean_commit_message(response.output_text)
        return message if message.strip() else None

    validation_findings = None
    if validation_response and not validation_response.passed:
        validation_findings = validation_response.output_text

    approved_message = approve_generated_commit_message(generate_message, validation_findings)
    if approved_message is None:
        print("Commit cancelled.")
        return 1

    if used_truncated_diff:
        print("Note: staged diff was truncated before generating the commit message.")

    return run(["git", "commit", "-m", approved_message])


def validate(git_args: list[str]):
    if git_args == ["--edit-rules"]:
        return edit_rules()

    if git_args:
        print("Usage: gitx validate [--edit-rules]")
        return 1

    diff = _staged_diff()
    if diff is None:
        return 1

    return _run_validation(diff, prompt_to_continue=False)


def tag(git_args: list[str]):
    if git_args != ["--ai"]:
        return run(["git", "tag", *git_args])

    context = _tag_context()
    if context is None:
        return 1

    suggestion = approve_generated_tag(
        lambda progress: generate_tag_suggestion(
            previous_tags=context["previous_tags"],
            latest_tag=context["latest_tag"],
            recent_commits=context["recent_commits"],
            progress=progress,
        ),
        previous_info=context["previous_info"],
        latest_tag=context["latest_tag"],
    )
    if suggestion is None:
        print("Tag cancelled.")
        return 1

    tag_name, message = suggestion
    return run(["git", "tag", "-a", tag_name, "-m", message])


def merge(git_args: list[str]):
    if git_args:
        return run(["git", "merge", *git_args])

    while True:
        context = _merge_context()
        if context is None:
            return 1

        action = choose_merge_action(
            branches=context["branches"],
            current_branch=context["current_branch"],
            status=context["status"],
            preview_for_branch=_merge_preview,
            merge_in_progress=context["merge_in_progress"],
            conflicts=context["conflicts"],
            conflict_context_for_path=_merge_conflict_context,
            ai_resolution_for_path=_generate_ai_merge_resolution,
        )
        if action is None:
            print("Merge cancelled.")
            return 1

        if action.action == "abort":
            return run(["git", "merge", "--abort"])
        if action.action == "continue":
            return run(["git", "merge", "--continue"])
        if action.action == "use-current":
            if not action.path:
                print("No conflicted file selected.")
                return 1
            result = run(["git", "checkout", "--ours", "--", action.path])
            if result != 0:
                return result
            result = run(["git", "add", action.path])
            if result != 0:
                return result
            continue
        if action.action == "use-incoming":
            if not action.path:
                print("No conflicted file selected.")
                return 1
            result = run(["git", "checkout", "--theirs", "--", action.path])
            if result != 0:
                return result
            result = run(["git", "add", action.path])
            if result != 0:
                return result
            continue
        if action.action == "use-both":
            if not action.path:
                print("No conflicted file selected.")
                return 1
            if not _resolve_conflict_file(action.path, "both"):
                return 1
            result = run(["git", "add", action.path])
            if result != 0:
                return result
            continue
        if action.action == "use-ai":
            print("AI merge proposals are reviewed in the terminal UI before applying.")
            continue
        if action.action == "apply-ai":
            if not action.path or not action.content:
                print("No AI merge proposal selected.")
                return 1
            if not _write_ai_merge_resolution(action.path, action.content):
                return 1
            result = run(["git", "add", action.path])
            if result != 0:
                return result
            continue
        if action.action == "edit-conflict":
            if not action.path:
                print("No conflicted file selected.")
                return 1
            if not edit_file(action.path):
                return 1
            continue
        if action.action == "add-conflict":
            if not action.path:
                print("No conflicted file selected.")
                return 1
            result = run(["git", "add", action.path])
            if result != 0:
                return result
            continue
        if action.action == "add-all-conflicts":
            paths = [conflict.path for conflict in context["conflicts"]]
            if not paths:
                print("No conflicted files to add.")
                continue
            result = run(["git", "add", *paths])
            if result != 0:
                return result
            continue
        if action.action != "merge" or not action.branch:
            print("Merge cancelled.")
            return 1

        command = ["git", "merge"]
        if action.mode == "no-ff":
            command.append("--no-ff")
        elif action.mode == "squash":
            command.append("--squash")
        command.append(action.branch)
        return run(command)


def checkout(git_args: list[str]):
    if git_args:
        return run(["git", "checkout", *git_args])

    context = _checkout_context()
    if context is None:
        return 1

    action = choose_checkout_branch(
        branches=context["branches"],
        current_branch=context["current_branch"],
    )
    if action is None:
        print("Checkout cancelled.")
        return 1

    branch = action.branch
    if branch.kind == "remote":
        return run(["git", "checkout", "--track", branch.name])
    return run(["git", "checkout", branch.name])


def _checkout_context() -> dict[str, object] | None:
    if _repo_root() is None:
        return None

    current_result = output(["git", "symbolic-ref", "--quiet", "--short", "HEAD"])
    if current_result.returncode != 0:
        current_result = output(["git", "rev-parse", "--short", "HEAD"])
    if current_result.returncode != 0:
        print(current_result.stderr.strip() or "Failed to read current branch.")
        return None
    current_branch = current_result.stdout.strip()

    branches = _checkout_branches(current_branch)
    if branches is None:
        return None

    return {"current_branch": current_branch, "branches": branches}


def _checkout_branches(current_branch: str) -> list[CheckoutBranch] | None:
    branch_result = output([
        "git",
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname)%09%(refname:short)%09%(upstream:short)%09%(committerdate:relative)%09%(subject)",
        "refs/heads",
        "refs/remotes",
    ])
    if branch_result.returncode != 0:
        print(branch_result.stderr.strip() or "Failed to read branches.")
        return None

    return parse_checkout_branches(branch_result.stdout, current_branch)


def parse_checkout_branches(text: str, current_branch: str) -> list[CheckoutBranch]:
    branches: list[CheckoutBranch] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        padded = parts + ["", "", ""]
        refname, short_name, upstream, updated, subject = (part.strip() for part in padded[:5])
        if not short_name or short_name.endswith("/HEAD"):
            continue

        if refname.startswith("refs/heads/"):
            branch = CheckoutBranch(
                name=short_name,
                display_name=short_name,
                kind="local",
                remote="",
                upstream=upstream,
                updated=updated,
                subject=subject,
                is_current=short_name == current_branch,
            )
        elif refname.startswith("refs/remotes/"):
            if refname.endswith("/HEAD") or "/" not in short_name:
                continue
            remote, display_name = short_name.split("/", 1)
            branch = CheckoutBranch(
                name=short_name,
                display_name=display_name,
                kind="remote",
                remote=remote,
                upstream="",
                updated=updated,
                subject=subject,
            )
        else:
            continue

        key = (branch.kind, branch.name)
        if key in seen:
            continue
        seen.add(key)
        branches.append(branch)

    return branches


def _merge_context() -> dict[str, object] | None:
    if _repo_root() is None:
        return None

    current_result = output(["git", "symbolic-ref", "--quiet", "--short", "HEAD"])
    if current_result.returncode != 0:
        current_result = output(["git", "rev-parse", "--short", "HEAD"])
    if current_result.returncode != 0:
        print(current_result.stderr.strip() or "Failed to read current branch.")
        return None
    current_branch = current_result.stdout.strip()

    status_result = output(["git", "status", "--short"])
    if status_result.returncode != 0:
        print(status_result.stderr.strip() or "Failed to read git status.")
        return None

    merge_head = output(["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"])
    branches = _merge_branches(current_branch)
    if branches is None:
        return None

    return {
        "current_branch": current_branch,
        "status": status_result.stdout.strip(),
        "merge_in_progress": merge_head.returncode == 0,
        "branches": branches,
        "conflicts": parse_merge_conflicts(status_result.stdout),
    }


def _merge_branches(current_branch: str) -> list[MergeBranch] | None:
    branch_result = output([
        "git",
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname:short)%09%(upstream:short)%09%(committerdate:relative)%09%(subject)",
        "refs/heads",
        "refs/remotes",
    ])
    if branch_result.returncode != 0:
        print(branch_result.stderr.strip() or "Failed to read branches.")
        return None

    return parse_merge_branches(branch_result.stdout, current_branch)


def parse_merge_branches(text: str, current_branch: str) -> list[MergeBranch]:
    branches: list[MergeBranch] = []
    seen: set[str] = set()

    for line in text.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        padded = parts + ["", "", ""]
        name, upstream, updated, subject = (part.strip() for part in padded[:4])
        if name == current_branch or name.endswith("/HEAD"):
            continue
        if name in seen:
            continue
        seen.add(name)
        branches.append(MergeBranch(name=name, upstream=upstream, updated=updated, subject=subject))

    return branches


def parse_merge_conflicts(text: str) -> list[MergeConflict]:
    conflicts: list[MergeConflict] = []
    seen: set[str] = set()

    for line in text.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        if not _is_unmerged_status(status):
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path or path in seen:
            continue
        seen.add(path)
        conflicts.append(MergeConflict(path=path, status=status))

    return conflicts


def _is_unmerged_status(status: str) -> bool:
    return status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def _merge_conflict_context(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as file:
            text = file.read()
    except UnicodeDecodeError:
        return "Binary or non-UTF-8 file. Open it in an editor or resolve it with git."
    except OSError as error:
        return f"Failed to read conflict file: {error}"

    return format_conflict_context(text)


def format_conflict_context(text: str) -> str:
    conflicts = _parse_conflict_blocks(text)
    if not conflicts:
        return "\n".join([
            "No conflict markers found in the working tree file.",
            "",
            "Git options:",
            "- Current: git checkout --ours -- <file>",
            "- Incoming: git checkout --theirs -- <file>",
            "- Both: keep both sides only when conflict markers are present",
            "- Editor: open the file manually",
        ])

    conflict = conflicts[0]
    lines = [
        "Git options:",
        "- Current: keep our side / HEAD / --ours",
        "- Incoming: keep their side / merged branch / --theirs",
        "- Both: keep current followed by incoming and remove markers",
        "- Editor: open the file manually",
        "",
        f"Conflict 1 of {len(conflicts)}",
        "",
        "Current / ours:",
        *_limit_context_lines(conflict["ours"]),
    ]
    if conflict["base"]:
        lines.extend(["", "Base:", *_limit_context_lines(conflict["base"])])
    lines.extend(["", "Incoming / theirs:", *_limit_context_lines(conflict["theirs"])])
    if len(conflicts) > 1:
        lines.extend(["", f"{len(conflicts) - 1} more conflict(s) in this file. Open editor for full context."])
    return "\n".join(lines)


def resolve_conflict_markers(text: str, choice: str) -> str | None:
    if choice not in ("ours", "theirs", "both"):
        return None

    output_lines: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    state = "normal"
    found = False

    for line in text.splitlines(keepends=True):
        if line.startswith("<<<<<<< "):
            found = True
            state = "ours"
            ours = []
            theirs = []
            continue
        if state == "ours" and line.startswith("||||||| "):
            state = "base"
            continue
        if state in ("ours", "base") and line.startswith("======="):
            state = "theirs"
            continue
        if state == "theirs" and line.startswith(">>>>>>> "):
            if choice == "ours":
                output_lines.extend(ours)
            elif choice == "theirs":
                output_lines.extend(theirs)
            else:
                output_lines.extend(ours)
                output_lines.extend(theirs)
            state = "normal"
            continue

        if state == "normal":
            output_lines.append(line)
        elif state == "ours":
            ours.append(line)
        elif state == "theirs":
            theirs.append(line)

    if state != "normal" or not found:
        return None
    return "".join(output_lines)


def _resolve_conflict_file(path: str, choice: str) -> bool:
    try:
        with open(path, encoding="utf-8") as file:
            text = file.read()
    except UnicodeDecodeError:
        print(f"{path} is not UTF-8 text. Open it in an editor to resolve it manually.")
        return False
    except OSError as error:
        print(f"Failed to read {path}: {error}")
        return False

    resolved = resolve_conflict_markers(text, choice)
    if resolved is None:
        print(f"No complete conflict markers found in {path}.")
        return False

    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(resolved)
    except OSError as error:
        print(f"Failed to write {path}: {error}")
        return False
    return True


def _generate_ai_merge_resolution(path: str, progress: Callable[[str], None]) -> str | None:
    try:
        with open(path, encoding="utf-8") as file:
            text = file.read()
    except UnicodeDecodeError:
        print(f"{path} is not UTF-8 text. Open it in an editor to resolve it manually.")
        return None
    except OSError as error:
        print(f"Failed to read {path}: {error}")
        return None

    if "<<<<<<< " not in text or "=======" not in text or ">>>>>>> " not in text:
        print(f"No complete conflict markers found in {path}.")
        return None

    resolved = generate_merge_resolution(path, text, progress=progress)
    if resolved is None:
        return None
    if _has_conflict_markers(resolved):
        print("AI returned content that still contains conflict markers. Open the file in an editor to resolve it manually.")
        return None
    return resolved


def _write_ai_merge_resolution(path: str, resolved: str) -> bool:
    if _has_conflict_markers(resolved):
        print("AI proposal still contains conflict markers. Edit or reject it before applying.")
        return False
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(resolved)
    except OSError as error:
        print(f"Failed to write {path}: {error}")
        return False
    return True


def _has_conflict_markers(text: str) -> bool:
    return "<<<<<<< " in text or "\n=======\n" in text or ">>>>>>> " in text


def _parse_conflict_blocks(text: str) -> list[dict[str, list[str]]]:
    conflicts: list[dict[str, list[str]]] = []
    ours: list[str] = []
    base: list[str] = []
    theirs: list[str] = []
    state = "normal"

    for line in text.splitlines():
        if line.startswith("<<<<<<< "):
            state = "ours"
            ours = []
            base = []
            theirs = []
            continue
        if state == "ours" and line.startswith("||||||| "):
            state = "base"
            continue
        if state in ("ours", "base") and line.startswith("======="):
            state = "theirs"
            continue
        if state == "theirs" and line.startswith(">>>>>>> "):
            conflicts.append({"ours": ours, "base": base, "theirs": theirs})
            state = "normal"
            continue

        if state == "ours":
            ours.append(line)
        elif state == "base":
            base.append(line)
        elif state == "theirs":
            theirs.append(line)

    return conflicts


def _limit_context_lines(lines: list[str], limit: int = 12) -> list[str]:
    if not lines:
        return ["  <empty>"]
    clipped = lines[:limit]
    output = [f"  {line}" for line in clipped]
    if len(lines) > limit:
        output.append(f"  ... {len(lines) - limit} more line(s)")
    return output


def _merge_preview(branch: str) -> str:
    result = output(["git", "log", "--oneline", "--decorate=short", "-n", "12", f"HEAD..{branch}"])
    if result.returncode != 0:
        return result.stderr.strip() or "Failed to read branch preview."
    return result.stdout.strip()


def push(git_args: list[str]):
    return run(["git", "push", *git_args] if git_args else ["git", "push"])


def _tag_context() -> dict[str, str] | None:
    latest_tag = _latest_version_tag()

    tags_result = output([
        "git",
        "for-each-ref",
        "--sort=-creatordate",
        "--count=5",
        "--format=%(refname:short)%09%(creatordate:short)%09%(subject)",
        "refs/tags",
    ])
    if tags_result.returncode != 0:
        print(tags_result.stderr.strip() or "Failed to read previous tags.")
        return None

    log_range = f"{latest_tag}..HEAD" if latest_tag else "HEAD"
    commits_result = output(["git", "log", "--oneline", "--decorate=short", "-n", "30", log_range])
    if commits_result.returncode != 0:
        print(commits_result.stderr.strip() or "Failed to read recent commits.")
        return None

    previous_tags = tags_result.stdout.strip() or "No previous tags."
    recent_commits = commits_result.stdout.strip()
    if not recent_commits:
        print("No commits since the latest tag.")
        return None

    previous_info = f"Latest tag: {latest_tag or 'none'}\n\nRecent tags:\n{previous_tags}"
    return {
        "latest_tag": latest_tag,
        "previous_tags": previous_tags,
        "previous_info": previous_info,
        "recent_commits": recent_commits,
    }


def _latest_version_tag() -> str:
    tags_result = output(["git", "tag", "--list"])
    if tags_result.returncode == 0:
        version_tags = [
            (version, tag)
            for tag in tags_result.stdout.splitlines()
            if (version := _parse_version_tag(tag)) is not None
        ]
        if version_tags:
            return max(version_tags, key=lambda item: item[0])[1]

    latest_tag_result = output(["git", "describe", "--tags", "--abbrev=0"])
    return latest_tag_result.stdout.strip() if latest_tag_result.returncode == 0 else ""


def _parse_version_tag(tag: str) -> tuple[int, int, int] | None:
    match = re.match(r"^[^\d]*(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", tag.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def clone(git_args: list[str]):
    if not git_args:
        print("Please provide a repository URL to clone.")
        return 1
    return run(["git", "clone", *git_args])


def checkout_branch(git_args: list[str]):
    if not git_args:
        print("Please provide a branch name.")
        return 1
    return run(["git", "checkout", "-b", *git_args])


def edit_rules():
    project_path = _repo_root()
    if project_path is None:
        return 1

    rules_file = ensure_project_rules_file(project_path)
    if rules_file is None:
        return 1

    print(f"Editing gitx project rules at {rules_file}")
    return 0 if edit_file(str(rules_file)) else 1


def _staged_diff() -> str | None:
    diff_result = output(["git", "diff", "--cached"])
    if diff_result.returncode != 0:
        print(diff_result.stderr.strip() or "Failed to read staged diff.")
        return None

    diff = diff_result.stdout.strip()
    if not diff:
        print("No staged changes. Stage files first with gitx a or git add.")
        return None

    return diff


def _run_validation(diff: str, prompt_to_continue: bool) -> int:
    response = run_validation_with_loading(lambda progress: _validation_response(diff, progress))
    if response is None:
        return 1
    if not isinstance(response, ValidationResponse):
        print("AI validation failed: unexpected validation response.")
        return 1

    if response.used_truncated_diff:
        print("Note: staged diff was truncated before validation.")

    if response.passed:
        if prompt_to_continue:
            print("AI validation passed.")
        else:
            show_validation_result("AI validation passed.")
        return 0

    if not prompt_to_continue:
        show_validation_result("AI validation findings:\n\n" + response.output_text)
        return 1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("\nAI validation findings:")
        print(response.output_text)
        print("Commit cancelled because validation produced findings.")
        return 1

    return 0 if approve_validation_findings(response.output_text) else 1


def _validation_response(
    diff: str,
    progress: Callable[[str], None] | None = None,
) -> ValidationResponse | None:
    project_path = _repo_root()
    if project_path is None:
        return None

    rules = get_project_rules(project_path)
    if not rules:
        _print_missing_project_rules(project_path)
        return None

    return validate_diff(diff, rules, progress=progress)


def _repo_root() -> str | None:
    root_result = output(["git", "rev-parse", "--show-toplevel"])
    if root_result.returncode != 0:
        print(root_result.stderr.strip() or "Failed to find git repository root.")
        return None

    return root_result.stdout.strip()


def _print_missing_project_rules(project_path: str) -> None:
    print(f"No gitx project rules found for {project_path}.")
    print(f"Run gitx validate --edit-rules or add a matching [[project]] entry to {projects_config_path()}.")
    print("Example:")
    print("[[project]]")
    print(f'path = "{project_path}"')
    print('rules = ["Update docs for public CLI behavior changes."]')
