import curses
import sys
import textwrap


def approve_commit_message(message):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_approve_commit_message(message)

    try:
        return curses.wrapper(lambda stdscr: _approval_screen(stdscr, message))
    except curses.error:
        return prompt_approve_commit_message(message)


def prompt_approve_commit_message(message):
    print("\nGenerated commit message:")
    print(message)
    answer = input("\nApprove this commit message? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _approval_screen(stdscr, message):
    curses.curs_set(0)
    stdscr.keypad(True)

    selected = 0
    actions = ["Approve", "Reject"]

    while True:
        _draw_approval_screen(stdscr, message, actions, selected)
        key = stdscr.getch()

        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
            selected = 1 - selected
        elif key in (ord("h"), ord("l")):
            selected = 1 - selected
        elif key in (ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
            return False
        elif key in (curses.KEY_ENTER, 10, 13):
            return selected == 0


def _draw_approval_screen(stdscr, message, actions, selected):
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

    _add_line(stdscr, height - 2, 2, "Enter: select  y: approve  n/q: reject")
    stdscr.refresh()


def _draw_box(stdscr, top, left, bottom, right):
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


def _add_line(stdscr, y, x, text, attr=curses.A_NORMAL):
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    stdscr.addstr(y, x, text[:max(0, width - x - 1)], attr)


def _wrap_message(message, width):
    lines = []
    for raw_line in message.splitlines():
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=width) or [""])
    return lines or [message]
