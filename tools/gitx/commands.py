import sys
from collections.abc import Callable

from config import ensure_project_rules_file, get_project_rules, projects_config_path
from git_runner import output, run
from openai_commit import clean_commit_message, generate_commit_message
from openai_validate import ValidationResponse, validate_diff
from tui import (
    approve_generated_commit_message,
    approve_validation_findings,
    edit_file,
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
    if unknown_flags or (message_args and (ai or validate)):
        print("Usage: gitx c [message] | gitx c --validate | gitx c --ai [--validate]")
        return 1

    if not ai and not validate:
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

    def generate_message() -> str | None:
        nonlocal used_truncated_diff
        response = generate_commit_message(diff)
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


def push(git_args: list[str]):
    return run(["git", "push", *git_args] if git_args else ["git", "push"])


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
