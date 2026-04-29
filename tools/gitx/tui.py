import curses
import os
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from _curses import window as CursesWindow


def approve_commit_message(message: str) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_approve_commit_message(message)

    try:
        return curses.wrapper(lambda stdscr: _approval_screen(stdscr, message))
    except curses.error:
        return prompt_approve_commit_message(message)


def prompt_approve_commit_message(message: str) -> str | None:
    print("\nGenerated commit message:")
    print(message)
    answer = input("\nModify this commit message? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        message = _edit_message_in_editor(message)

    answer = input("\nApprove this commit message? [y/N] ").strip().lower()
    return message if answer in ("y", "yes") else None


def edit_file(path: str) -> bool:
    try:
        result = subprocess.run([*_editor_command(), path], check=False)
    except OSError as error:
        print(f"Failed to open editor: {error}")
        return False
    return result.returncode == 0


def approve_generated_commit_message(
    generate_message: Callable[[Callable[[str], None]], str | None],
    validation_findings: str | None = None,
) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        if validation_findings and not prompt_approve_validation_findings(validation_findings):
            return None
        print("\nGenerating AI commit message...")
        message = generate_message(lambda _message: None)
        return prompt_approve_commit_message(message) if message else None

    try:
        return curses.wrapper(
            lambda stdscr: _generated_commit_message_flow(
                stdscr,
                generate_message,
                validation_findings,
            )
        )
    except curses.error:
        if validation_findings and not prompt_approve_validation_findings(validation_findings):
            return None
        print("\nGenerating AI commit message...")
        message = generate_message(lambda message: print(message))
        return prompt_approve_commit_message(message) if message else None


@dataclass
class TagApproval:
    tag: str
    message: str


def approve_generated_tag(
    generate_suggestion: Callable[[Callable[[str], None]], object],
    previous_info: str,
    latest_tag: str,
) -> tuple[str, str] | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("\nPrevious tag info:")
        print(previous_info)
        print("\nGenerating AI tag suggestion...")
        suggestion = generate_suggestion(lambda _message: None)
        return prompt_approve_tag(suggestion, latest_tag) if suggestion else None

    try:
        return curses.wrapper(
            lambda stdscr: _generated_tag_flow(
                stdscr,
                generate_suggestion,
                previous_info,
                latest_tag,
            )
        )
    except curses.error:
        print("\nPrevious tag info:")
        print(previous_info)
        print("\nGenerating AI tag suggestion...")
        suggestion = generate_suggestion(lambda message: print(message))
        return prompt_approve_tag(suggestion, latest_tag) if suggestion else None


def prompt_approve_tag(suggestion: object, latest_tag: str) -> tuple[str, str] | None:
    approval = _tag_approval_from_suggestion(suggestion)
    if approval is None:
        return None

    print("\nSuggested tag:")
    print(approval.tag)
    print("\nSuggested tag message:")
    print(approval.message)

    bump = input("\nBump major, minor, patch, custom, or keep? [keep] ").strip().lower()
    if bump in ("major", "minor", "patch"):
        approval.tag = bump_version_tag(latest_tag or approval.tag, bump)
        print(f"Updated tag: {approval.tag}")
    elif bump in ("custom", "c"):
        custom_tag = input("Tag: ").strip()
        if custom_tag:
            approval.tag = custom_tag

    answer = input("\nModify tag and message in editor? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        approval = _edit_tag_approval_in_editor(approval)

    answer = input("\nCreate this annotated tag? [y/N] ").strip().lower()
    return (approval.tag, approval.message) if answer in ("y", "yes") else None


def approve_validation_findings(findings: str) -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_approve_validation_findings(findings)

    try:
        return curses.wrapper(lambda stdscr: _validation_screen(stdscr, findings))
    except curses.error:
        return prompt_approve_validation_findings(findings)


def prompt_approve_validation_findings(findings: str) -> bool:
    print("\nAI validation findings:")
    print(_colorize_validation_findings(findings))
    answer = input("\nContinue anyway? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def show_validation_result(message: str) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(message)
        return

    try:
        curses.wrapper(lambda stdscr: _validation_result_screen(stdscr, message))
    except curses.error:
        print(_colorize_validation_findings(message))


def run_validation_with_loading(
    validate: Callable[[Callable[[str], None]], object],
) -> object:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return validate(lambda _message: None)

    try:
        return curses.wrapper(lambda stdscr: _run_validation_with_loading(stdscr, validate))
    except curses.error:
        print("\nValidating staged diff...")
        return validate(lambda message: print(message))


def _approval_screen(stdscr: CursesWindow, message: str) -> str | None:
    curses.curs_set(0)
    stdscr.keypad(True)

    selected = 0
    actions = ["Approve", "Modify", "Reject"]

    while True:
        _draw_approval_screen(stdscr, message, actions, selected)
        key = stdscr.getch()

        if key == curses.KEY_LEFT:
            selected = (selected - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected = (selected + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected = (selected + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("e"), ord("E"), ord("m"), ord("M")):
            message = _edit_message(stdscr, message)
        elif key in (ord("y"), ord("Y")):
            return message
        elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            if actions[selected] == "Approve":
                return message
            if actions[selected] == "Reject":
                return None
            message = _edit_message(stdscr, message)


def _generated_commit_message_flow(
    stdscr: CursesWindow,
    generate_message: Callable[[Callable[[str], None]], str | None],
    validation_findings: str | None,
) -> str | None:
    curses.curs_set(0)
    stdscr.keypad(True)

    if validation_findings and not _validation_screen(stdscr, validation_findings):
        return None

    status: queue.Queue[str] = queue.Queue()
    message = _run_with_loading(
        stdscr,
        title="Generating commit message",
        subtitle="Preparing staged context before calling OpenAI.",
        body="Starting AI commit-message generation...",
        callback=lambda: generate_message(status.put),
        status=status,
    )
    if not isinstance(message, str) or not message:
        return None

    return _approval_screen(stdscr, message)


def _generated_tag_flow(
    stdscr: CursesWindow,
    generate_suggestion: Callable[[Callable[[str], None]], object],
    previous_info: str,
    latest_tag: str,
) -> tuple[str, str] | None:
    curses.curs_set(0)
    stdscr.keypad(True)

    if not _tag_info_screen(stdscr, previous_info):
        return None

    status: queue.Queue[str] = queue.Queue()
    suggestion = _run_with_loading(
        stdscr,
        title="Generating tag suggestion",
        subtitle="Reviewing recent tags and commits before calling OpenAI.",
        body="Starting AI tag suggestion...",
        callback=lambda: generate_suggestion(status.put),
        status=status,
    )
    approval = _tag_approval_from_suggestion(suggestion)
    if approval is None:
        return None

    return _tag_approval_screen(stdscr, approval, latest_tag)


def _tag_info_screen(stdscr: CursesWindow, previous_info: str) -> bool:
    while True:
        _draw_review_screen(
            stdscr,
            title="Previous tag info",
            subtitle="Recent tags used as context for the next version.",
            body=previous_info,
            actions=["Continue"],
            selected=0,
            footer="Enter: continue  q/Esc: cancel",
        )
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            return True
        if key in (ord("q"), ord("Q"), 27):
            return False


def _tag_approval_screen(stdscr: CursesWindow, approval: TagApproval, latest_tag: str) -> tuple[str, str] | None:
    selected = 0
    actions = ["Approve", "Patch", "Minor", "Major", "Modify", "Reject"]

    while True:
        body = f"Tag: {approval.tag}\n\nMessage:\n{approval.message}"
        _draw_review_screen(
            stdscr,
            title="AI tag suggestion",
            subtitle="Review the tag, choose a version bump, or edit the message.",
            body=body,
            actions=actions,
            selected=selected,
            footer="Enter: select  p/m/M: bump  e: edit  y: approve  n/q: reject",
        )
        key = stdscr.getch()

        if key == curses.KEY_LEFT:
            selected = (selected - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected = (selected + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected = (selected + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("p"), ord("P")):
            approval.tag = bump_version_tag(latest_tag or approval.tag, "patch")
        elif key == ord("m"):
            approval.tag = bump_version_tag(latest_tag or approval.tag, "minor")
        elif key == ord("M"):
            approval.tag = bump_version_tag(latest_tag or approval.tag, "major")
        elif key in (ord("e"), ord("E")):
            approval = _edit_tag_approval(stdscr, approval)
        elif key in (ord("y"), ord("Y")):
            return approval.tag, approval.message
        elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            action = actions[selected]
            if action == "Approve":
                return approval.tag, approval.message
            if action == "Reject":
                return None
            if action in ("Patch", "Minor", "Major"):
                approval.tag = bump_version_tag(latest_tag or approval.tag, action.lower())
            if action == "Modify":
                approval = _edit_tag_approval(stdscr, approval)


def _validation_screen(stdscr: CursesWindow, findings: str) -> bool:
    curses.curs_set(0)
    stdscr.keypad(True)

    selected = 0
    actions = ["Continue", "Cancel"]

    while True:
        _draw_review_screen(
            stdscr,
            title="AI validation findings",
            subtitle="Review the findings before continuing.",
            body=findings,
            actions=actions,
            selected=selected,
            footer="Enter: select  y: continue  n/q: cancel",
        )
        key = stdscr.getch()

        if key == curses.KEY_LEFT:
            selected = (selected - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected = (selected + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected = (selected + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
            return False
        elif key in (curses.KEY_ENTER, 10, 13):
            return actions[selected] == "Continue"


def _run_with_loading(
    stdscr: CursesWindow,
    title: str,
    subtitle: str,
    body: str,
    callback: Callable[[], object],
    status: queue.Queue[str] | None = None,
) -> object:
    results: queue.Queue[tuple[str, object] | tuple[str, BaseException]] = queue.Queue()

    def target() -> None:
        try:
            results.put(("result", callback()))
        except BaseException as error:
            results.put(("error", error))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    spinner = "|/-\\"
    frame = 0
    current_body = body
    _draw_loading_screen(stdscr, title, subtitle, f"{spinner[frame % len(spinner)]} {current_body}")
    frame += 1
    while thread.is_alive():
        if status:
            while True:
                try:
                    current_body = status.get_nowait()
                except queue.Empty:
                    break
        _draw_loading_screen(stdscr, title, subtitle, f"{spinner[frame % len(spinner)]} {current_body}")
        frame += 1
        time.sleep(0.12)

    kind, value = results.get()
    if kind == "error":
        raise value
    return value


def _run_validation_with_loading(
    stdscr: CursesWindow,
    validate: Callable[[Callable[[str], None]], object],
) -> object:
    curses.curs_set(0)
    stdscr.keypad(True)
    status: queue.Queue[str] = queue.Queue()

    return _run_with_loading(
        stdscr,
        title="Validating staged diff",
        subtitle="Checking changed files against project rules.",
        body="Preparing validation...",
        callback=lambda: validate(status.put),
        status=status,
    )


def _draw_loading_screen(
    stdscr: CursesWindow,
    title: str,
    subtitle: str,
    body: str,
) -> None:
    _draw_review_screen(
        stdscr,
        title=title,
        subtitle=subtitle,
        body=body,
        actions=[],
        selected=0,
        footer="Waiting for response...",
    )


def _validation_result_screen(stdscr: CursesWindow, message: str) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)

    while True:
        _draw_review_screen(
            stdscr,
            title="AI validation result",
            subtitle="Review the staged diff validation result.",
            body=message,
            actions=["Close"],
            selected=0,
            footer="Enter/q/Esc: close",
        )
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q"), 27):
            return


def _draw_approval_screen(
    stdscr: CursesWindow,
    message: str,
    actions: Sequence[str],
    selected: int,
) -> None:
    _draw_review_screen(
        stdscr,
        title="AI commit message",
        subtitle="Review the generated message before committing.",
        body=message,
        actions=actions,
        selected=selected,
        footer="Enter: select  e/m: modify  y: approve  n/q: reject",
    )


def _draw_review_screen(
    stdscr: CursesWindow,
    title: str,
    subtitle: str,
    body: str,
    actions: Sequence[str],
    selected: int,
    footer: str,
) -> None:
    stdscr.erase()
    _init_colors()
    height, width = stdscr.getmaxyx()
    usable_width = max(20, width - 4)

    _add_line(stdscr, 1, 2, title, curses.A_BOLD)
    _add_line(stdscr, 3, 2, subtitle)

    message_lines = _wrap_message_with_severity(body, usable_width)
    box_top = 5
    box_height = min(max(5, len(message_lines) + 2), max(5, height - 10))
    box_bottom = box_top + box_height - 1

    if height >= 12 and width >= 30:
        _draw_box(stdscr, box_top, 1, box_bottom, width - 2)
        for index, (line, severity) in enumerate(message_lines[:box_height - 2], start=box_top + 1):
            _add_line(stdscr, index, 3, line[:usable_width], _severity_attr(severity))

    button_y = min(height - 4, box_bottom + 2)
    x = 2
    for index, action in enumerate(actions):
        label = f" {action} "
        attr = _action_attr(action, selected=index == selected)
        _add_line(stdscr, button_y, x, label, attr)
        x += len(label) + 2

    _add_line(stdscr, height - 2, 2, footer)
    stdscr.refresh()


def _edit_message(stdscr: CursesWindow, message: str) -> str:
    curses.def_prog_mode()
    curses.endwin()
    try:
        return _edit_message_in_editor(message)
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.clear()
        stdscr.refresh()


def _edit_tag_approval(stdscr: CursesWindow, approval: TagApproval) -> TagApproval:
    curses.def_prog_mode()
    curses.endwin()
    try:
        return _edit_tag_approval_in_editor(approval)
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.clear()
        stdscr.refresh()


def _edit_tag_approval_in_editor(approval: TagApproval) -> TagApproval:
    content = f"Tag: {approval.tag}\n\nMessage:\n{approval.message.rstrip()}\n"
    edited = _edit_text_in_editor(content, ".TAG_EDITMSG")
    return parse_tag_approval(edited) or approval


def _edit_message_in_editor(message: str) -> str:
    edited = _edit_text_in_editor(message.rstrip() + "\n", ".COMMIT_EDITMSG")
    return edited.strip() or message


def _edit_text_in_editor(content: str, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(
        "w+",
        encoding="utf-8",
        suffix=suffix,
        delete=False,
    ) as file:
        path = file.name
        file.write(content)

    try:
        command = _editor_command()
        result = subprocess.run([*command, path], check=False)
        if result.returncode != 0:
            return content

        with open(path, encoding="utf-8") as file:
            return file.read()
    except OSError:
        return content
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _tag_approval_from_suggestion(suggestion: object) -> TagApproval | None:
    tag = getattr(suggestion, "tag", "")
    message = getattr(suggestion, "message", "")
    if not isinstance(tag, str) or not tag.strip():
        return None
    if not isinstance(message, str) or not message.strip():
        return None
    return TagApproval(tag=tag.strip(), message=message.strip())


def parse_tag_approval(text: str) -> TagApproval | None:
    lines = text.splitlines()
    tag = ""
    message_lines: list[str] = []
    in_message = False

    for line in lines:
        if line.lower().startswith("tag:"):
            tag = line.split(":", 1)[1].strip()
            in_message = False
            continue
        if line.lower().startswith("message:"):
            message_lines.append(line.split(":", 1)[1].strip())
            in_message = True
            continue
        if in_message:
            message_lines.append(line.rstrip())

    message = "\n".join(message_lines).strip()
    if not tag or not message:
        return None
    return TagApproval(tag=tag, message=message)


def bump_version_tag(tag: str, bump: str) -> str:
    match = re_match_version_tag(tag)
    if match is None:
        prefix = "v" if tag.startswith("v") else ""
        return f"{prefix}0.1.0" if bump == "minor" else f"{prefix}1.0.0" if bump == "major" else f"{prefix}0.0.1"

    prefix, major, minor, patch = match
    if bump == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"{prefix}{major}.{minor}.{patch}"


def re_match_version_tag(tag: str) -> tuple[str, int, int, int] | None:
    match = re.match(r"^([^\d]*)(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", tag.strip())
    if not match:
        return None
    return (
        match.group(1),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
    )


def _editor_command() -> list[str]:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    return shlex.split(editor)


def _draw_box(
    stdscr: CursesWindow,
    top: int,
    left: int,
    bottom: int,
    right: int,
) -> None:
    stdscr.addch(top, left, "+")
    stdscr.addch(top, right, "+")
    stdscr.addch(bottom, left, "+")
    stdscr.addch(bottom, right, "+")

    for x in range(left + 1, right):
        stdscr.addch(top, x, "-")
        stdscr.addch(bottom, x, "-")
    for y in range(top + 1, bottom):
        stdscr.addch(y, left, "|")
        stdscr.addch(y, right, "|")


def _add_line(
    stdscr: CursesWindow,
    y: int,
    x: int,
    text: str,
    attr: int = curses.A_NORMAL,
) -> None:
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    stdscr.addstr(y, x, text[:max(0, width - x - 1)], attr)


def _wrap_message_with_severity(message: str, width: int) -> list[tuple[str, str | None]]:
    lines: list[tuple[str, str | None]] = []
    for raw_line in message.splitlines():
        severity = _line_severity(raw_line)
        if not raw_line.strip():
            lines.append(("", None))
            continue
        for line in textwrap.wrap(raw_line, width=width) or [""]:
            lines.append((line, severity))
    return lines or [(message, None)]


def _line_severity(line: str) -> str | None:
    stripped = line.lstrip().lower()
    if ". [" in stripped:
        stripped = stripped.split(". ", 1)[1]
    for severity in ("high", "medium", "low"):
        if stripped.startswith(f"[{severity}]"):
            return severity
    return None


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    _safe_init_pair(1, curses.COLOR_RED)
    _safe_init_pair(2, curses.COLOR_YELLOW)
    _safe_init_pair(3, curses.COLOR_CYAN)
    _safe_init_pair(4, curses.COLOR_GREEN)


def _safe_init_pair(pair: int, foreground: int) -> None:
    try:
        curses.init_pair(pair, foreground, -1)
    except curses.error:
        pass


def _severity_attr(severity: str | None) -> int:
    if severity == "high":
        return curses.color_pair(1) | curses.A_BOLD
    if severity == "medium":
        return curses.color_pair(2) | curses.A_BOLD
    if severity == "low":
        return curses.color_pair(3)
    return curses.A_NORMAL


def _action_attr(action: str, selected: bool) -> int:
    base = curses.A_REVERSE if selected else curses.A_NORMAL
    if action in ("Continue", "Approve", "Close"):
        return base | curses.color_pair(4)
    if action in ("Cancel", "Reject"):
        return base | curses.color_pair(1)
    return base


def _colorize_validation_findings(text: str) -> str:
    colors = {
        "high": "\033[91;1m",
        "medium": "\033[93;1m",
        "low": "\033[96m",
    }
    reset = "\033[0m"
    output: list[str] = []
    for line in text.splitlines():
        severity = _line_severity(line)
        if severity:
            output.append(f"{colors[severity]}{line}{reset}")
        else:
            output.append(line)
    return "\n".join(output)
