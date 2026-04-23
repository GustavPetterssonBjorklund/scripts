import curses
import os
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
from collections.abc import Callable, Sequence
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


def _edit_message_in_editor(message: str) -> str:
    with tempfile.NamedTemporaryFile(
        "w+",
        encoding="utf-8",
        suffix=".COMMIT_EDITMSG",
        delete=False,
    ) as file:
        path = file.name
        file.write(message.rstrip() + "\n")

    try:
        command = _editor_command()
        result = subprocess.run([*command, path], check=False)
        if result.returncode != 0:
            return message

        with open(path, encoding="utf-8") as file:
            edited = file.read().strip()
        return edited or message
    except OSError:
        return message
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
