import curses
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Sequence
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


def _draw_approval_screen(
    stdscr: CursesWindow,
    message: str,
    actions: Sequence[str],
    selected: int,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    usable_width = max(20, width - 4)

    _add_line(stdscr, 1, 2, "AI commit message", curses.A_BOLD)
    _add_line(stdscr, 3, 2, "Review the generated message before committing.")

    message_lines = _wrap_message(message, usable_width)
    box_top = 5
    box_height = min(max(5, len(message_lines) + 2), max(5, height - 10))
    box_bottom = box_top + box_height - 1

    if height >= 12 and width >= 30:
        _draw_box(stdscr, box_top, 1, box_bottom, width - 2)
        for index, line in enumerate(message_lines[:box_height - 2], start=box_top + 1):
            _add_line(stdscr, index, 3, line[:usable_width])

    button_y = min(height - 4, box_bottom + 2)
    x = 2
    for index, action in enumerate(actions):
        label = f" {action} "
        attr = curses.A_REVERSE if index == selected else curses.A_NORMAL
        _add_line(stdscr, button_y, x, label, attr)
        x += len(label) + 2

    _add_line(stdscr, height - 2, 2, "Enter: select  e/m: modify  y: approve  n/q: reject")
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


def _wrap_message(message: str, width: int) -> list[str]:
    lines: list[str] = []
    for raw_line in message.splitlines():
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=width) or [""])
    return lines or [message]
