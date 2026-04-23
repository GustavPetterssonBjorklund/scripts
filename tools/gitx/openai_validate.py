import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

from config import ProjectRules, get_config_value
from openai_commit import request_openai_text, split_diff_by_file


class Severity(IntEnum):
    HIGH = 3
    MEDIUM = 2
    LOW = 1


@dataclass
class ValidationFinding:
    severity: str
    title: str
    detail: str = ""
    file: str = ""
    line: str = ""
    snippet: str = ""
    rule: str = ""


@dataclass
class ValidationResponse:
    output_text: str
    passed: bool
    findings: list[ValidationFinding]
    used_truncated_diff: bool = False


@dataclass
class ValidationFileResult:
    index: int
    file_path: str
    passed: bool
    findings: list[ValidationFinding]


ProgressCallback = Callable[[str], None]


def validate_diff(
    diff: str,
    project_rules: ProjectRules,
    progress: ProgressCallback | None = None,
) -> Optional[ValidationResponse]:
    try:
        max_diff_chars = int(get_config_value("ai_max_diff_chars") or "20000")
    except ValueError:
        print("ai_max_diff_chars must be an integer.")
        return None

    findings: list[ValidationFinding] = []
    used_truncated_diff = False
    all_passed = True
    diff_files = split_diff_by_file(diff)
    if not diff_files:
        diff_files = [("", diff.strip())]

    jobs: list[tuple[int, str, str, bool]] = []
    total_files = len(diff_files)
    for index, (file_path, file_diff) in enumerate(diff_files, start=1):
        file_diff = file_diff.strip()
        if not file_diff:
            continue

        file_diff, truncated = _truncate_diff(file_diff, max_diff_chars)
        used_truncated_diff = used_truncated_diff or truncated
        jobs.append((index, file_path, file_diff, truncated))

    if not jobs:
        return ValidationResponse("AI validation passed.", True, [], used_truncated_diff)

    if progress:
        progress(f"Validating {len(jobs)} files in parallel...")

    results: list[ValidationFileResult] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = [
            executor.submit(_validate_file_diff, project_rules, index, total_files, file_path, file_diff, truncated, progress)
            for index, file_path, file_diff, truncated in jobs
        ]

        for future in as_completed(futures):
            result = future.result()
            if result is None:
                return None
            results.append(result)

    for result in sorted(results, key=lambda item: item.index):
        all_passed = all_passed and result.passed
        findings.extend(result.findings)

    if progress:
        progress("Finished validating staged diff.")

    if findings:
        output_text = format_validation_findings(findings)
    elif all_passed:
        output_text = "AI validation passed."
    else:
        output_text = "AI validation failed, but no findings were returned."

    return ValidationResponse(
        output_text=output_text,
        passed=all_passed and not findings,
        findings=findings,
        used_truncated_diff=used_truncated_diff,
    )


def _validate_file_diff(
    project_rules: ProjectRules,
    index: int,
    total_files: int,
    file_path: str,
    file_diff: str,
    truncated: bool,
    progress: ProgressCallback | None,
) -> ValidationFileResult | None:
    display_path = file_path or "(unknown file)"
    if progress:
        progress(f"Validating {index}/{total_files}: {display_path}")

    prompt = _build_validation_prompt(project_rules, file_path, file_diff, truncated)
    text = request_openai_text(prompt, max_output_tokens=500)
    if text is None:
        return None

    passed, findings = _parse_validation_output(text.strip(), file_path)
    if progress:
        progress(f"Finished {index}/{total_files}: {display_path}")

    return ValidationFileResult(index, file_path, passed, findings)


def _build_validation_prompt(project_rules: ProjectRules, file_path: str, file_diff: str, truncated: bool) -> str:
    prompt = (
        "Review the staged git diff for this one file against the project-specific rules below.\n"
        "Focus only on concrete issues visible in the diff or directly implied by the rules.\n"
        "Do not report missing tests or validation for command wiring unless the diff includes test files or the rule explicitly requires tests for this exact file.\n"
        "Do not comment on unrelated style preferences.\n"
        "Return only valid JSON. Do not wrap it in markdown.\n"
        "Use this shape:\n"
        '{"passed": true, "findings": []}\n'
        "or:\n"
        '{"passed": false, "findings": ['
        '{"severity": "high|medium|low", "title": "short finding", '
        '"detail": "one sentence explanation", "file": "optional path", '
        '"line": "optional line number", "snippet": "exact code snippet from the diff", '
        '"rule": "optional matching project rule"}'
        "]}\n"
        "Keep findings under 8 items.\n"
        "If you mention a location, include the exact code snippet from the diff, not a paraphrase.\n"
        "\n"
        f"Project path:\n{project_rules.path}\n"
        "\n"
        f"Project rules:\n{project_rules.rules}\n"
        "\n"
        f"File being reviewed:\n{file_path or '(unknown file)'}\n"
    )
    if truncated:
        prompt += "\nThe diff was truncated; validate only the visible changes.\n"
    prompt += f"\nStaged diff for this file:\n{file_diff}"
    return prompt


def _truncate_diff(diff: str, max_diff_chars: int) -> tuple[str, bool]:
    truncated = len(diff) > max_diff_chars
    return diff[:max_diff_chars], truncated


def format_validation_findings(findings: list[ValidationFinding]) -> str:
    if not findings:
        return "AI validation passed."

    lines: list[str] = []
    for index, finding in enumerate(_sort_findings(findings), start=1):
        label = finding.severity.lower()
        lines.append(f"{index}. [{label}] {finding.title}")
        if finding.file:
            lines.append(f"   File: {finding.file}")
        if finding.line:
            lines.append(f"   Line: {finding.line}")
        if finding.snippet:
            lines.append("   Snippet:")
            lines.extend(_indent_block(finding.snippet).splitlines())
        if finding.rule:
            lines.append(f"   Rule: {finding.rule}")
        if finding.detail:
            lines.append(f"   Detail: {finding.detail}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _parse_validation_output(text: str, default_file: str = "") -> tuple[bool, list[ValidationFinding]]:
    if text.strip().upper() == "PASS":
        return True, []

    try:
        data = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        findings = _parse_legacy_findings(text, default_file)
        return not findings, findings

    if not isinstance(data, dict):
        return False, _parse_legacy_findings(text, default_file)

    raw_findings = data.get("findings", [])
    findings = _coerce_findings(raw_findings, default_file)
    passed = bool(data.get("passed")) and not findings
    return passed, findings

def _coerce_findings(raw_findings: object, default_file: str = "") -> list[ValidationFinding]:
    if not isinstance(raw_findings, list):
        return []

    findings: list[ValidationFinding] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        severity = _normalize_severity(str(raw.get("severity", "medium")))
        title = str(raw.get("title") or raw.get("finding") or "").strip()
        detail = str(raw.get("detail") or raw.get("description") or "").strip()
        file = str(raw.get("file") or raw.get("path") or "").strip()
        line = str(raw.get("line") or raw.get("line_number") or "").strip()
        snippet = str(raw.get("snippet") or raw.get("code") or raw.get("excerpt") or "").strip()
        rule = str(raw.get("rule") or "").strip()
        if not title and detail:
            title, detail = detail, ""
        if title:
            findings.append(ValidationFinding(severity, title, detail, file or default_file, line, snippet, rule))
    return findings


def _parse_legacy_findings(text: str, default_file: str = "") -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for line in text.splitlines():
        stripped = line.strip()
        severity = _severity_from_line(stripped)
        if severity:
            title = stripped.split("]", 1)[1].strip()
            findings.append(ValidationFinding(severity, title, file=default_file))
    if findings:
        return findings
    if text.strip():
        return [ValidationFinding("medium", text.strip(), file=default_file)]
    return []


def _severity_from_line(line: str) -> str | None:
    lowered = line.lower()
    for severity in ("high", "medium", "low"):
        if lowered.startswith(f"[{severity}]"):
            return severity
    return None


def _normalize_severity(value: str) -> str:
    lowered = value.strip().lower()
    return lowered if lowered in ("high", "medium", "low") else "medium"


def _sort_findings(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    return sorted(findings, key=lambda item: Severity[item.severity.upper()], reverse=True)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _indent_block(text: str, prefix: str = "      ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())
