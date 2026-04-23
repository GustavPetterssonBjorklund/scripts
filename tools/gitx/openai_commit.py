import json
import re
import urllib.error
import urllib.request

from config import get_config_value, get_openai_api_key
from dataclasses import dataclass
from typing import Any, Callable, Optional


ProgressCallback = Callable[[str], None]


@dataclass
class OpenAIResponse:
    output_text: str | None = None
    used_truncated_diff: bool = False

def extract_response_text(data: dict[str, Any]) -> Optional[str]:
    if data.get("output_text"):
        return data["output_text"].strip()

    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def generate_commit_message(
    diff: str,
    progress: ProgressCallback | None = None,
) -> Optional[OpenAIResponse]:
    if progress:
        progress("Reading AI commit configuration...")
    try:
        max_diff_chars = int(get_config_value("ai_max_diff_chars") or "20000")
    except ValueError:
        print("ai_max_diff_chars must be an integer.")
        return None

    original_diff_chars = len(diff)
    diff_files = split_diff_by_file(diff)
    if progress:
        if diff_files:
            progress(f"Analyzing {len(diff_files)} staged files for relevant context...")
        else:
            progress("Analyzing staged diff context...")

    diff, truncated = prepare_commit_diff(diff, max_diff_chars)

    if progress:
        if truncated:
            progress(f"Built excerpted context within {max_diff_chars} characters.")
        else:
            progress(f"Using full staged diff ({original_diff_chars} characters).")

        progress("Building commit-message prompt...")
    prompt = build_commit_prompt(diff, truncated)

    if progress:
        progress("Waiting for OpenAI to generate the commit message...")
    text = request_openai_text(prompt, max_output_tokens=120)
    if text is None:
        return None

    if progress:
        progress("Received AI commit message.")

    return OpenAIResponse(
        output_text=text,
        used_truncated_diff=truncated
    )


def build_commit_prompt(diff: str, truncated: bool) -> str:
    diff_files = split_diff_by_file(diff)
    summary = build_change_summary(diff_files, truncated)
    prompt = (
        "Generate a git commit message for the staged diff below.\n"
        "Return only the raw commit message text.\n"
        "Do not wrap it in quotes, markdown, JSON, code fences, or explanation.\n"
        "Do not include labels like 'Subject:' or 'Body:'.\n"
        "Use this exact format:\n"
        "activity(scope): short info\n"
        "\n"
        "- concise detail\n"
        "- concise detail\n"
        "The subject must be under 72 characters.\n"
        "The body must contain 2-4 concise bullet points with more detailed info.\n"
        "Choose activity from: feat, fix, docs, refactor, test, chore, build, ci, style, perf.\n"
        "Choose a concrete lowercase scope only from the staged file paths or visible changed code; never use an unstaged or merely suggested project name.\n"
        "Prefer the changed command, package, or top-level tool as scope over an internal mechanism such as ai, prompt, config, or parser.\n"
        "Use imperative mood and describe the user-facing behavior change, not just the implementation technique.\n"
        "Treat removed code, deleted files, and narrowed behavior as important changes to describe, not just added code.\n"
        "If the structured summary says removals dominate or a subsystem/app/install flow was deleted, prefer a refactor/chore style subject about that removal unless the visible changes clearly show a larger user-facing feature.\n"
        "Make each body bullet explain a distinct important outcome visible from the staged changes.\n"
        "If the diff changes scope selection or context leakage, mention that directly.\n"
    )
    if truncated:
        prompt += "\nThe diff was excerpted; use the complete changed-file list for scope and the visible per-file excerpts for details.\n"
    prompt += f"\nStructured change summary:\n{summary}\n\nStaged diff:\n{diff}"
    return prompt


def prepare_commit_diff(diff: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(diff)
    if len(diff) <= max_chars:
        return diff, False

    diff_files = split_diff_by_file(diff)
    if not diff_files:
        return diff[:max_chars], True

    manifest = _build_changed_file_manifest(diff_files)
    if len(manifest) >= max_chars:
        return _truncate_text(manifest, max_chars), True

    remaining = max_chars - len(manifest) - len("\n\nDiff excerpts by file:\n")
    if remaining <= 0:
        return _truncate_text(manifest, max_chars), True

    excerpts = _build_file_excerpts(diff_files, remaining)
    prepared = f"{manifest}\n\nDiff excerpts by file:\n{excerpts}".strip()
    return _truncate_text(prepared, max_chars), True


def build_change_summary(diff_files: list[tuple[str, str]], truncated: bool) -> str:
    if not diff_files:
        return "- No staged file changes detected"

    stats = [_file_change_stats(file_path, file_diff) for file_path, file_diff in diff_files]
    added_files = sum(1 for stat in stats if stat["status"] == "added")
    modified_files = sum(1 for stat in stats if stat["status"] == "modified")
    deleted_files = sum(1 for stat in stats if stat["status"] == "deleted")
    renamed_files = sum(1 for stat in stats if stat["status"] == "renamed")
    total_additions = sum(int(stat["additions"]) for stat in stats)
    total_deletions = sum(int(stat["deletions"]) for stat in stats)

    lines = [
        f"- File counts: {added_files} added, {modified_files} modified, {deleted_files} deleted, {renamed_files} renamed",
        f"- Changed lines: +{total_additions} / -{total_deletions}",
        f"- Dominant change: {_dominant_change_label(stats, total_additions, total_deletions)}",
    ]
    if truncated:
        lines.append("- Diff mode: excerpted context; prefer summary and complete path list for high-level intent")

    scope_candidates = _scope_candidates(diff_files)
    if scope_candidates:
        lines.append(f"- Scope candidates: {', '.join(scope_candidates)}")

    deleted_paths = [str(stat["path"]) for stat in stats if stat["status"] == "deleted"]
    if deleted_paths:
        lines.append(f"- Deleted paths: {', '.join(deleted_paths[:6])}")
        if len(deleted_paths) > 6:
            lines.append(f"- Additional deleted paths: {len(deleted_paths) - 6} more")

    major_removed_groups = _major_deleted_groups(deleted_paths)
    if major_removed_groups:
        lines.append(f"- Major removals: {', '.join(major_removed_groups[:4])}")

    impactful_files = _top_impact_files(stats)
    if impactful_files:
        lines.append("- Highest-impact files:")
        lines.extend(f"  {entry}" for entry in impactful_files)

    return "\n".join(lines)


def split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    current_path = ""
    current_lines: list[str] = []

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current_lines:
                files.append((current_path, "\n".join(current_lines).strip()))
            current_path = _extract_diff_path(line)
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        files.append((current_path, "\n".join(current_lines).strip()))

    return files


def _extract_diff_path(header_line: str) -> str:
    match = re.match(r"diff --git a/(.+?) b/(.+)$", header_line)
    if not match:
        return ""
    return match.group(2)


def _file_change_stats(file_path: str, file_diff: str) -> dict[str, object]:
    additions, deletions = _count_content_changes(file_diff)
    status = "modified"
    if "\nnew file mode " in f"\n{file_diff}":
        status = "added"
    elif "\ndeleted file mode " in f"\n{file_diff}":
        status = "deleted"
    elif "\nrename from " in f"\n{file_diff}" or "\nrename to " in f"\n{file_diff}":
        status = "renamed"

    return {
        "path": file_path or "(unknown file)",
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "impact": additions + deletions,
    }


def _build_changed_file_manifest(diff_files: list[tuple[str, str]]) -> str:
    lines = ["Changed files (complete staged path list):"]
    for file_path, file_diff in diff_files:
        display_path = file_path or "(unknown file)"
        additions, deletions = _count_content_changes(file_diff)
        change_summary = f", +{additions}/-{deletions} changed lines" if additions or deletions else ""
        lines.append(f"- {display_path} ({len(file_diff)} diff chars{change_summary})")

    scope_candidates = _scope_candidates(diff_files)
    if scope_candidates:
        lines.append("")
        lines.append("Scope candidates from staged paths, strongest first:")
        lines.extend(f"- {scope}" for scope in scope_candidates)
    return "\n".join(lines)


def _dominant_change_label(
    stats: list[dict[str, object]],
    total_additions: int,
    total_deletions: int,
) -> str:
    deleted_files = [stat for stat in stats if stat["status"] == "deleted"]
    if deleted_files and len(deleted_files) >= max(3, len(stats) // 2):
        groups = _major_deleted_groups([str(stat["path"]) for stat in deleted_files])
        if groups:
            return f"removal-heavy; deleted subsystem candidates: {', '.join(groups[:2])}"
        return "removal-heavy; deleted files dominate"
    if total_deletions > total_additions * 2:
        return "removal-heavy; deleted lines dominate"
    if total_additions > total_deletions * 2:
        return "addition-heavy; new code dominates"
    return "mixed update"


def _major_deleted_groups(paths: list[str]) -> list[str]:
    groups: dict[str, int] = {}
    for path in paths:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            key = "/".join(parts[:2])
        elif parts:
            key = parts[0]
        else:
            continue
        groups[key] = groups.get(key, 0) + 1
    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))
    return [f"{path} ({count} files)" for path, count in ordered if count >= 2]


def _top_impact_files(stats: list[dict[str, object]]) -> list[str]:
    ordered = sorted(
        stats,
        key=lambda stat: (-int(stat["impact"]), str(stat["path"])),
    )
    entries: list[str] = []
    for stat in ordered[:5]:
        impact = int(stat["impact"])
        if impact <= 0:
            continue
        entries.append(
            f"- {stat['path']} ({stat['status']}, +{stat['additions']} / -{stat['deletions']})"
        )
    return entries


def _scope_candidates(diff_files: list[tuple[str, str]]) -> list[str]:
    candidates: dict[str, tuple[int, int]] = {}
    for index, (file_path, _) in enumerate(diff_files):
        scope = _scope_from_path(file_path)
        if not scope:
            continue

        score = _scope_score(file_path)
        previous = candidates.get(scope)
        if previous is None:
            candidates[scope] = (score, index)
        else:
            candidates[scope] = (max(previous[0], score), previous[1])

    ordered = sorted(candidates.items(), key=lambda item: (-item[1][0], item[1][1], item[0]))
    return [scope for scope, _ in ordered[:5]]


def _scope_score(file_path: str) -> int:
    parts = [part for part in file_path.split("/") if part]
    if len(parts) >= 2 and parts[0] in ("tools", "pkgs", "apps", "packages", "crates"):
        return 3
    if _is_low_signal_path(file_path):
        return 0
    if parts and parts[0] in ("assets", "static", "public", "images"):
        return 1
    return 2


def _scope_from_path(file_path: str) -> str:
    parts = [part for part in file_path.split("/") if part]
    if len(parts) >= 2 and parts[0] in ("tools", "pkgs", "apps", "packages", "crates"):
        return _normalize_scope(parts[1])
    if len(parts) >= 2 and parts[0] in ("legacy", "docs"):
        return _normalize_scope(parts[0])
    if parts:
        return _normalize_scope(parts[0].split(".")[0])
    return ""


def _normalize_scope(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return normalized


def _build_file_excerpts(diff_files: list[tuple[str, str]], max_chars: int) -> str:
    if not diff_files or max_chars <= 0:
        return ""

    metadata_by_file = [(file_path, _metadata_excerpt(file_diff)) for file_path, file_diff in diff_files]
    base_cost = sum(len(metadata) + len("\n\n") for _, metadata in metadata_by_file)
    sample_budget = max(0, max_chars - base_cost)
    weighted_files = [(file_path, file_diff) for file_path, file_diff in diff_files if not _is_low_signal_path(file_path)]
    if not weighted_files:
        weighted_files = diff_files
    sample_per_file = max(0, sample_budget // len(weighted_files))

    chunks: list[str] = []
    for file_path, file_diff in diff_files:
        metadata = _metadata_excerpt(file_diff)
        if _is_low_signal_path(file_path):
            chunks.append(metadata)
            continue

        sample = _sample_changed_lines(file_diff, sample_per_file)
        chunks.append(f"{metadata}\n{sample}".strip() if sample else metadata)

    return _truncate_text("\n\n".join(chunks), max_chars)


def _metadata_excerpt(file_diff: str) -> str:
    lines: list[str] = []
    for line in file_diff.splitlines():
        if (
            line.startswith("diff --git ")
            or line.startswith("index ")
            or line.startswith("new file mode ")
            or line.startswith("deleted file mode ")
            or line.startswith("rename from ")
            or line.startswith("rename to ")
            or line.startswith("Binary files ")
            or line.startswith("@@")
        ):
            lines.append(line)
    additions, deletions = _count_content_changes(file_diff)
    if additions or deletions:
        lines.append(f"content changes: +{additions} / -{deletions}")
    return "\n".join(lines) or file_diff.splitlines()[0]


def _sample_changed_lines(file_diff: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    removed_lines: list[str] = []
    added_lines: list[str] = []
    for line in file_diff.splitlines():
        if not _is_content_change_line(line):
            continue
        if line.startswith("-"):
            removed_lines.append(line)
        else:
            added_lines.append(line)

    sampled_lines = _take_balanced_changed_lines(removed_lines, added_lines, max_chars)
    return "\n".join(sampled_lines)


def _count_content_changes(file_diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in file_diff.splitlines():
        if not _is_content_change_line(line):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _take_balanced_changed_lines(removed_lines: list[str], added_lines: list[str], max_chars: int) -> list[str]:
    groups: list[list[str]] = []
    if removed_lines:
        groups.append(removed_lines)
    if added_lines:
        groups.append(added_lines)
    if not groups:
        return []

    total_lines = sum(len(group) for group in groups)
    min_reserved_chars = sum(min(len(group), 1) for group in groups)
    if min_reserved_chars > max_chars:
        return _fill_from_groups(groups, max_chars)

    quotas = [0] * len(groups)
    remaining_slots = total_lines
    remaining_budget = max_chars

    for index, group in enumerate(groups):
        shortest = min(len(line) + 1 for line in group)
        quotas[index] = 1
        remaining_slots -= 1
        remaining_budget -= shortest

    if remaining_slots > 0 and remaining_budget > 0:
        for index, group in enumerate(groups):
            extra_capacity = len(group) - quotas[index]
            if extra_capacity <= 0:
                continue
            share = max(0, int(remaining_budget * extra_capacity / remaining_slots))
            quotas[index] += _fit_lines(group, quotas[index], share)

    selected: list[str] = []
    for index, group in enumerate(groups):
        selected.extend(group[:quotas[index]])

    used_chars = sum(len(line) + 1 for line in selected)
    if used_chars > max_chars:
        return _fill_from_groups(groups, max_chars)

    remaining_lines = [group[quotas[index]:] for index, group in enumerate(groups)]
    remaining_budget = max_chars - used_chars
    selected.extend(_fill_from_groups(remaining_lines, remaining_budget))
    return selected


def _fit_lines(lines: list[str], start_index: int, budget: int) -> int:
    used = 0
    taken = 0
    for line in lines[start_index:]:
        cost = len(line) + 1
        if used + cost > budget:
            break
        used += cost
        taken += 1
    return taken


def _fill_from_groups(groups: list[list[str]], max_chars: int) -> list[str]:
    selected: list[str] = []
    used = 0
    index = 0
    while True:
        progressed = False
        for group in groups:
            if index >= len(group):
                continue
            line = group[index]
            cost = len(line) + 1
            if used + cost > max_chars:
                continue
            selected.append(line)
            used += cost
            progressed = True
        if not progressed:
            break
        index += 1
    return selected


def _is_content_change_line(line: str) -> bool:
    if not line.startswith(("+", "-")):
        return False
    return not line.startswith(("+++", "---"))


def _is_low_signal_path(file_path: str) -> bool:
    low_signal_extensions = {
        ".ai",
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lock",
        ".pdf",
        ".png",
        ".svg",
        ".webp",
    }
    return any(file_path.lower().endswith(extension) for extension in low_signal_extensions)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = "\n[excerpt truncated]"
    if max_chars <= len(suffix):
        return text[:max_chars]
    return text[: max_chars - len(suffix)].rstrip() + suffix


def request_openai_text(prompt: str, max_output_tokens: int) -> Optional[str]:
    api_key = get_openai_api_key()
    if not api_key:
        print("OpenAI API key is not set.")
        print("Set OPENAI_API_KEY or add openai_api_key to ~/.config/gitx/config.")
        return None

    model = get_config_value("ai_model") or "gpt-5.4-mini"
    payload = json.dumps({
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"OpenAI API request failed: HTTP {error.code}")
        print(detail)
        return None
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"OpenAI API request failed: {error}")
        return None

    return extract_response_text(data)


def clean_commit_message(message: str) -> str:
    lines = message.strip().strip('"').splitlines()

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(line.rstrip() for line in lines)
