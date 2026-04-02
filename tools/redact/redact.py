#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Match

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
HILITE = "\033[30;103m"


@dataclass(frozen=True)
class Rule:
    name: str
    label: str
    base_score: int
    pattern: re.Pattern[str]
    description: str
    group: int = 0
    span_getter: Callable[[Match[str]], tuple[int, int]] | None = None
    validator: Callable[[Match[str], str], bool] | None = None
    scorer: Callable[[Match[str], str, int], int] | None = None

    def span(self, match: Match[str]) -> tuple[int, int]:
        if self.span_getter is not None:
            return self.span_getter(match)
        return match.span(self.group)


@dataclass(frozen=True)
class Candidate:
    start: int
    end: int
    label: str
    score: int
    value: str
    rule_name: str
    description: str


def clamp_score(value: int) -> int:
    return max(0, min(100, value))


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def span_from_first_group(*groups: int) -> Callable[[Match[str]], tuple[int, int]]:
    def getter(match: Match[str]) -> tuple[int, int]:
        for group in groups:
            start, end = match.span(group)
            if start != -1:
                return start, end
        raise ValueError("No matching capture group for span")

    return getter


def is_likely_secret_assignment(match: Match[str], value: str) -> bool:
    cleaned = strip_quotes(value).strip()
    if len(cleaned) < 6:
        return False
    if cleaned.lower() in {
        "<redacted>",
        "redacted",
        "true",
        "false",
        "null",
        "none",
        "yes",
        "no",
        "basic",
        "bearer",
    }:
        return False
    if re.fullmatch(r"\d{1,7}", cleaned):
        return False
    return True


def score_secret_assignment(match: Match[str], value: str, base_score: int) -> int:
    key_name = match.group(1).lower()
    cleaned = strip_quotes(value).strip()
    score = base_score
    if len(cleaned) >= 20:
        score += 5
    if any(token in key_name for token in ("password", "secret", "api", "token")):
        score += 5
    if re.search(r"[A-Z]", cleaned) and re.search(r"\d", cleaned):
        score += 3
    if re.search(r"[^A-Za-z0-9]", cleaned):
        score += 2
    return clamp_score(score)


def is_valid_email(_: Match[str], value: str) -> bool:
    _, _, domain = value.rpartition("@")
    return domain.lower() not in {"example.com"}


def is_valid_unicode_email(_: Match[str], value: str) -> bool:
    local_part, _, domain = value.rpartition("@")
    return bool(local_part) and any(ord(char) > 127 or char == "\u200b" for char in local_part) and bool(domain)


def is_valid_ipv4(_: Match[str], value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)


def score_ipv4(_: Match[str], value: str, base_score: int) -> int:
    first, second, *_ = [int(part) for part in value.split(".")]
    private = (
        first == 10
        or first == 127
        or (first == 172 and 16 <= second <= 31)
        or (first == 192 and second == 168)
    )
    return base_score + (3 if private else 8)


def is_valid_phone(_: Match[str], value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        return False
    if len(set(digits)) <= 1:
        return False

    groups = [group for group in re.split(r"\D+", value.strip()) if group]
    if len(groups) >= 3 and all(len(group) == 4 for group in groups):
        return False
    return True


def is_valid_credit_card(_: Match[str], value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for index, digit in enumerate(reverse_digits):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0


def score_credit_card(_: Match[str], value: str, base_score: int) -> int:
    digits = re.sub(r"\D", "", value)
    if digits.startswith(("34", "37", "4", "5", "6")):
        return base_score + 5
    return base_score


def is_valid_ssn(_: Match[str], value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) == 9 and digits != "000000000"


def is_valid_cookie_value(match: Match[str], value: str) -> bool:
    cookie_name = match.group(1).lower()
    cleaned = value.strip()
    if len(cleaned) < 8:
        return False
    return cookie_name in {"session", "sessionid", "csrftoken", "csrf", "auth_token", "authtoken"}


def score_cookie_value(match: Match[str], value: str, base_score: int) -> int:
    cookie_name = match.group(1).lower()
    if cookie_name in {"session", "sessionid", "auth_token", "authtoken"}:
        return base_score + 8
    return base_score


def is_valid_iban(_: Match[str], value: str) -> bool:
    compact = re.sub(r"\s+", "", value).upper()
    return 15 <= len(compact) <= 34 and compact[:2].isalpha() and compact[2:4].isdigit()


def is_valid_mac(_: Match[str], value: str) -> bool:
    compact = value.replace(":", "").replace("-", "")
    return len(compact) == 12 and all(char in "0123456789abcdefABCDEF" for char in compact)


RULES = [
    Rule(
        name="private_key",
        label="Private key block",
        base_score=100,
        pattern=re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
        description="PEM private keys are almost always sensitive.",
    ),
    Rule(
        name="auth_header",
        label="Authorization token",
        base_score=96,
        pattern=re.compile(r"(?im)^(authorization\s*:\s*(?:bearer|token)\s+)(\S+)\s*$"),
        group=2,
        description="HTTP authorization headers often carry live credentials.",
    ),
    Rule(
        name="basic_auth",
        label="Basic auth credential",
        base_score=93,
        pattern=re.compile(r"(?i)\b(?:authorization\s*:\s*basic|basic auth\s*:?)\s+([A-Za-z0-9+/=]{12,})"),
        group=1,
        description="Basic auth payloads often decode directly to usernames and passwords.",
    ),
    Rule(
        name="bearer_token",
        label="Bearer token",
        base_score=92,
        pattern=re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._=-]{12,})"),
        group=1,
        description="Bearer tokens are direct credentials.",
    ),
    Rule(
        name="url_password",
        label="URL password",
        base_score=95,
        pattern=re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:@]*):([^@\s/]+)@[^/\s]+", re.IGNORECASE),
        group=2,
        description="Credentials embedded in URLs are high risk.",
    ),
    Rule(
        name="sops_encrypted_value",
        label="SOPS encrypted value",
        base_score=98,
        pattern=re.compile(r"ENC\[[^\]\n]+]"),
        description="SOPS encrypted values should be redacted as a whole to avoid metadata leakage.",
    ),
    Rule(
        name="age_secret_key",
        label="Age private key",
        base_score=99,
        pattern=re.compile(r"\bAGE-SECRET-KEY-1[A-Z0-9]{20,}\b"),
        description="Age secret keys are high-risk long-lived credentials.",
    ),
    Rule(
        name="aws_access_key",
        label="AWS access key",
        base_score=94,
        pattern=re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b"),
        description="AWS access keys can expose cloud accounts.",
    ),
    Rule(
        name="github_token",
        label="GitHub token",
        base_score=95,
        pattern=re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        description="GitHub personal and app tokens should not be shared.",
    ),
    Rule(
        name="openai_token",
        label="API token",
        base_score=95,
        pattern=re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        description="Long-lived API keys are high risk.",
    ),
    Rule(
        name="stripe_key",
        label="API token",
        base_score=95,
        pattern=re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9_-]{16,}\b"),
        description="Live and test Stripe keys should still be treated as secrets.",
    ),
    Rule(
        name="split_secret_part",
        label="Secret-looking assignment",
        base_score=84,
        pattern=re.compile(
            r"""(?im)^(?:.*\b(?:api(?:[_ -]?key)?|token|secret)\b.*\bpart\s*\d+\s*:\s*)(\S+)\s*$"""
        ),
        group=1,
        description="Secret fragments are often split across labeled parts.",
    ),
    Rule(
        name="jwt",
        label="JWT",
        base_score=88,
        pattern=re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9._-]{8,}\.[A-Za-z0-9._-]{8,}\b"),
        description="JWTs can grant direct application access.",
    ),
    Rule(
        name="slack_token",
        label="Slack token",
        base_score=94,
        pattern=re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        description="Slack tokens provide workspace access.",
    ),
    Rule(
        name="discord_token",
        label="Discord token",
        base_score=90,
        pattern=re.compile(r"\bmfa\.[A-Za-z0-9._-]{20,}\b"),
        description="Discord MFA tokens are account credentials.",
    ),
    Rule(
        name="secret_assignment",
        label="Secret-looking assignment",
        base_score=86,
        pattern=re.compile(
            r"""(?im)(?:["']?)((?:password|passwd|pwd|passcode|pin|secret|api(?:[_ -]?key)?|token|session(?:[_ -]?token)?|access(?:[_ -]?token)?|refresh(?:[_ -]?token)?|client(?:[_ -]?secret)?|stripe(?:[_ -]?secret)?|session(?:[_ -]?secret)?|nextauth(?:[_ -]?secret)?|aws(?:[_ -]?secret(?:[_ -]?access(?:[_ -]?key)?)?)|secret(?:[_ -]?access(?:[_ -]?key)?)?))(?:["']?)\s*(?::|=|=>|->)\s*(?:'([^']+)'|"([^"]+)"|([^\s,;'"&]+))"""
        ),
        span_getter=span_from_first_group(2, 3, 4),
        validator=is_likely_secret_assignment,
        scorer=score_secret_assignment,
        description="Variable names and long values suggest a secret.",
    ),
    Rule(
        name="xml_secret",
        label="Secret-looking assignment",
        base_score=86,
        pattern=re.compile(
            r"""(?is)<((?:password|passwd|passcode|pin|token|secret|session_token|access_token|refresh_token))>\s*([^<\n]+?)\s*</\1>"""
        ),
        group=2,
        validator=is_likely_secret_assignment,
        scorer=score_secret_assignment,
        description="Sensitive values often appear under obvious XML tags.",
    ),
    Rule(
        name="concatenated_secret",
        label="Secret-looking assignment",
        base_score=84,
        pattern=re.compile(
            r"""(?im)\b(password|passwd|passcode|token|secret)\b\s*(?::|=)\s*((?:"[^"\n]*"\s*\+\s*)+"[^"\n]*")"""
        ),
        group=2,
        description="Secrets are sometimes assembled from multiple string literals.",
    ),
    Rule(
        name="encoded_secret",
        label="Encoded secret",
        base_score=82,
        pattern=re.compile(
            r"""(?im)\b(?:base64(?:\([^)\n]*\))?|b64|encoded)\b[^:\n]*(?:password|token|secret)[^:\n]*:\s*([A-Za-z0-9+/=]{12,})"""
        ),
        group=1,
        description="Encoded blobs can still contain directly reusable secrets.",
    ),
    Rule(
        name="credit_card",
        label="Credit card number",
        base_score=85,
        pattern=re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        validator=is_valid_credit_card,
        scorer=score_credit_card,
        description="Payment card numbers are sensitive financial data.",
    ),
    Rule(
        name="iban",
        label="IBAN",
        base_score=80,
        pattern=re.compile(r"(?<!\w)[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?!\w)"),
        validator=is_valid_iban,
        description="Bank account identifiers are sensitive financial data.",
    ),
    Rule(
        name="ssn",
        label="SSN",
        base_score=82,
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        validator=is_valid_ssn,
        description="Government identifiers are sensitive personal data.",
    ),
    Rule(
        name="passport",
        label="Passport number",
        base_score=74,
        pattern=re.compile(r"(?im)\bpassport\b\s*(?::|=)\s*([A-Z0-9]{6,12})\b"),
        group=1,
        description="Passport numbers are sensitive personal identifiers.",
    ),
    Rule(
        name="driver_license",
        label="Driver license",
        base_score=72,
        pattern=re.compile(r"(?im)\bdriver\s*license\b\s*(?::|=)\s*([A-Z0-9-]{5,16})\b"),
        group=1,
        description="Driver license numbers are sensitive personal identifiers.",
    ),
    Rule(
        name="email",
        label="Email address",
        base_score=55,
        pattern=re.compile(r"(?<![A-Za-z0-9._%+*\-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        validator=is_valid_email,
        description="Email addresses are personally identifying data.",
    ),
    Rule(
        name="quoted_email",
        label="Email address",
        base_score=58,
        pattern=re.compile(r'"(?:[^"\\]|\\.)+"@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
        description="Quoted local-parts are unusual but still valid email addresses.",
    ),
    Rule(
        name="unicode_email",
        label="Email address",
        base_score=58,
        pattern=re.compile(r"(?<![A-Za-z0-9._%+*\-])[\w.%+\-\u200b]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        validator=is_valid_unicode_email,
        description="Unicode and zero-width characters are used to disguise email addresses.",
    ),
    Rule(
        name="phone",
        label="Phone number",
        base_score=52,
        pattern=re.compile(r"(?<![\w-])(?:\+?\d[\d .()-]{8,}\d)(?![\w-])"),
        validator=is_valid_phone,
        description="Phone numbers are personally identifying data.",
    ),
    Rule(
        name="cookie_value",
        label="Session cookie",
        base_score=78,
        pattern=re.compile(r"(?i)\b(sessionid|session|csrftoken|csrf|auth_token|authtoken)\s*=\s*([^;\s\"']+)"),
        group=2,
        validator=is_valid_cookie_value,
        scorer=score_cookie_value,
        description="Session-oriented cookies can authenticate requests.",
    ),
    Rule(
        name="mac_address",
        label="MAC address",
        base_score=50,
        pattern=re.compile(r"(?im)\bmac(?:\s+address)?\b\s*[:=]\s*([A-Fa-f0-9]{12}|(?:[A-Fa-f0-9]{2}[:-]){5}[A-Fa-f0-9]{2})\b"),
        group=1,
        validator=is_valid_mac,
        description="Device identifiers can still be sensitive in operational logs.",
    ),
    Rule(
        name="ipv4",
        label="IPv4 address",
        base_score=42,
        pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        validator=is_valid_ipv4,
        scorer=score_ipv4,
        description="Network addresses can still be sensitive in logs or config.",
    ),
]


def detect_candidates(text: str, min_score: int) -> list[Candidate]:
    raw_candidates: list[Candidate] = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            start, end = rule.span(match)
            if start == -1 or end == -1 or start == end:
                continue
            value = text[start:end]
            if rule.validator is not None and not rule.validator(match, value):
                continue
            score = rule.base_score
            if rule.scorer is not None:
                score = rule.scorer(match, value, score)
            score = clamp_score(score)
            if score < min_score:
                continue
            raw_candidates.append(
                Candidate(
                    start=start,
                    end=end,
                    label=rule.label,
                    score=score,
                    value=value,
                    rule_name=rule.name,
                    description=rule.description,
                )
            )

    chosen: list[Candidate] = []
    for candidate in sorted(
        raw_candidates,
        key=lambda item: (-item.score, -(item.end - item.start), item.start),
    ):
        overlaps = any(
            not (candidate.end <= existing.start or candidate.start >= existing.end)
            for existing in chosen
        )
        if not overlaps:
            chosen.append(candidate)

    return expand_repeated_literals(text, sorted(chosen, key=lambda item: item.start))


def should_expand_literal(candidate: Candidate) -> bool:
    return (
        candidate.score >= 80
        and 8 <= len(candidate.value) <= 256
        and "\n" not in candidate.value
        and "<redacted>" not in candidate.value
    )


def is_secret_boundary(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        return True
    return not (text[index].isalnum() or text[index] in {"_", "-", "."})


def expand_repeated_literals(text: str, candidates: list[Candidate]) -> list[Candidate]:
    known_ranges = [(candidate.start, candidate.end) for candidate in candidates]
    chosen = list(candidates)
    literal_sources: dict[str, Candidate] = {}

    for candidate in candidates:
        if should_expand_literal(candidate):
            existing = literal_sources.get(candidate.value)
            if existing is None or candidate.score > existing.score:
                literal_sources[candidate.value] = candidate

    for value, source in sorted(literal_sources.items(), key=lambda item: (-len(item[0]), item[0])):
        start = 0
        while True:
            index = text.find(value, start)
            if index == -1:
                break
            end = index + len(value)
            if not is_secret_boundary(text, index - 1) or not is_secret_boundary(text, end):
                start = index + 1
                continue
            overlaps = any(not (end <= left or index >= right) for left, right in known_ranges)
            if not overlaps:
                chosen.append(
                    Candidate(
                        start=index,
                        end=end,
                        label=source.label,
                        score=max(70, source.score - 5),
                        value=value,
                        rule_name=source.rule_name,
                        description=f"Repeated value previously identified as {source.label.lower()}.",
                    )
                )
                known_ranges.append((index, end))
            start = index + 1

    return sorted(chosen, key=lambda item: item.start)


def preview_value(value: str, width: int = 70) -> str:
    condensed = value.replace("\n", r"\n")
    if len(condensed) <= width:
        return condensed
    half = max(10, (width - 5) // 2)
    return f"{condensed[:half]} ... {condensed[-half:]}"


def render_excerpt(text: str, start: int, end: int, width: int) -> str:
    context = max(20, (width // 2) - 5)
    left_start = max(0, start - context)
    right_end = min(len(text), end + context)

    left = text[left_start:start].replace("\n", r"\n")
    middle = text[start:end].replace("\n", r"\n")
    right = text[end:right_end].replace("\n", r"\n")

    if left_start > 0:
        left = "..." + left
    if right_end < len(text):
        right = right + "..."

    if len(middle) > width:
        middle = preview_value(text[start:end], max(20, width // 2))

    return f"{DIM}{left}{RESET}{HILITE}{middle}{RESET}{DIM}{right}{RESET}"


def score_color(score: int) -> str:
    if score >= 90:
        return RED
    if score >= 70:
        return YELLOW
    return GREEN


def prompt_for_decisions(
    text: str, candidates: list[Candidate], replacement: str, tty_in, tty_out
) -> list[bool]:
    decisions: list[bool] = []
    sticky_rule_decisions: dict[str, bool] = {}
    width = shutil.get_terminal_size(fallback=(100, 30)).columns

    for index, candidate in enumerate(candidates, start=1):
        if candidate.rule_name in sticky_rule_decisions:
            decisions.append(sticky_rule_decisions[candidate.rule_name])
            continue

        while True:
            tty_out.write("\033[2J\033[H")
            tty_out.write(f"{BOLD}redact{RESET} {DIM}{index}/{len(candidates)}{RESET}\n\n")
            tty_out.write(f"Type: {BOLD}{candidate.label}{RESET}\n")
            tty_out.write(
                f"Sensitivity: {score_color(candidate.score)}{candidate.score}/100{RESET}\n"
            )
            tty_out.write(f"Why: {candidate.description}\n")
            tty_out.write(
                f"Preview: {preview_value(candidate.value, max(20, min(80, width - 10)))}\n\n"
            )
            tty_out.write(
                f"{render_excerpt(text, candidate.start, candidate.end, max(20, width - 4))}\n\n"
            )
            tty_out.write(
                f"Replace with {BOLD}{replacement}{RESET}? "
                "[Enter/r] redact  [k] keep  [a] redact-all-type  [s] keep-all-type  [q] abort\n> "
            )
            tty_out.flush()

            choice = tty_in.readline()
            if choice == "":
                raise KeyboardInterrupt
            choice = choice.strip().lower()

            if choice in {"", "r"}:
                decisions.append(True)
                break
            if choice == "k":
                decisions.append(False)
                break
            if choice == "a":
                sticky_rule_decisions[candidate.rule_name] = True
                decisions.append(True)
                break
            if choice == "s":
                sticky_rule_decisions[candidate.rule_name] = False
                decisions.append(False)
                break
            if choice == "q":
                raise KeyboardInterrupt

    tty_out.write("\033[2J\033[H")
    tty_out.flush()
    return decisions


def apply_redactions(text: str, candidates: list[Candidate], decisions: list[bool], replacement: str) -> str:
    parts: list[str] = []
    cursor = 0
    for candidate, should_redact in zip(candidates, decisions):
        parts.append(text[cursor:candidate.start])
        if should_redact:
            parts.append(replacement)
        else:
            parts.append(text[candidate.start:candidate.end])
        cursor = candidate.end
    parts.append(text[cursor:])
    return "".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="redact",
        description="Inspect stdin for likely sensitive values and interactively redact them.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=40,
        help="minimum sensitivity score to show or redact (default: %(default)s)",
    )
    parser.add_argument(
        "--replace",
        default="<redacted>",
        help="replacement text to emit for redacted values (default: %(default)s)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="redact every detected candidate without prompting",
    )
    return parser.parse_args()


def print_no_tty_error() -> int:
    print(
        "redact: no interactive tty available. Pipe input into `redact --yes` for non-interactive mode.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    args = parse_args()

    if not 0 <= args.min_score <= 100:
        print("redact: --min-score must be between 0 and 100", file=sys.stderr)
        return 2

    text = sys.stdin.read()
    candidates = detect_candidates(text, args.min_score)

    if not candidates:
        sys.stdout.write(text)
        return 0

    if args.yes:
        decisions = [True] * len(candidates)
    else:
        try:
            tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
            tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
        except OSError:
            return print_no_tty_error()

        with tty_in, tty_out:
            try:
                decisions = prompt_for_decisions(text, candidates, args.replace, tty_in, tty_out)
            except KeyboardInterrupt:
                tty_out.write("redact: aborted; no output written\n")
                tty_out.flush()
                return 130

    sys.stdout.write(apply_redactions(text, candidates, decisions, args.replace))
    return 0


if __name__ == "__main__":
    sys.exit(main())
