import curses
import difflib
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


@dataclass
class MergeBranch:
    name: str
    upstream: str
    updated: str
    subject: str


@dataclass
class MergeConflict:
    path: str
    status: str


@dataclass
class MergeAction:
    action: str
    branch: str = ""
    mode: str = "merge"
    path: str = ""
    content: str = ""


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


def choose_merge_action(
    branches: Sequence[MergeBranch],
    current_branch: str,
    status: str,
    preview_for_branch: Callable[[str], str],
    merge_in_progress: bool = False,
    conflicts: Sequence[MergeConflict] = (),
    conflict_context_for_path: Callable[[str], str] | None = None,
    ai_resolution_for_path: Callable[[str, Callable[[str], None]], str | None] | None = None,
) -> MergeAction | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_choose_merge_action(branches, current_branch, status, merge_in_progress, conflicts)

    try:
        return curses.wrapper(
            lambda stdscr: _merge_manager_screen(
                stdscr,
                branches,
                current_branch,
                status,
                preview_for_branch,
                merge_in_progress,
                conflicts,
                conflict_context_for_path,
                ai_resolution_for_path,
            )
        )
    except curses.error:
        return prompt_choose_merge_action(branches, current_branch, status, merge_in_progress, conflicts)


def prompt_choose_merge_action(
    branches: Sequence[MergeBranch],
    current_branch: str,
    status: str,
    merge_in_progress: bool = False,
    conflicts: Sequence[MergeConflict] = (),
) -> MergeAction | None:
    print(f"\nCurrent branch: {current_branch}")
    if status.strip():
        print("\nWorking tree status:")
        print(status)
    else:
        print("\nWorking tree clean.")

    if merge_in_progress:
        if conflicts:
            print("\nConflicted files:")
            for index, conflict in enumerate(conflicts, start=1):
                print(f"  {index}. {conflict.status} {conflict.path}")
        answer = input(
            "\nCurrent, incoming, both, edit, add, continue, abort, or cancel? [cancel] "
        ).strip().lower()
        if answer in ("current", "ours", "o") and conflicts:
            selected = input("Conflict number to resolve with current? ").strip()
            if selected.isdigit() and 0 < int(selected) <= len(conflicts):
                return MergeAction("use-current", path=conflicts[int(selected) - 1].path)
            return None
        if answer in ("incoming", "theirs", "t") and conflicts:
            selected = input("Conflict number to resolve with incoming? ").strip()
            if selected.isdigit() and 0 < int(selected) <= len(conflicts):
                return MergeAction("use-incoming", path=conflicts[int(selected) - 1].path)
            return None
        if answer in ("both", "b") and conflicts:
            selected = input("Conflict number to keep both sides? ").strip()
            if selected.isdigit() and 0 < int(selected) <= len(conflicts):
                return MergeAction("use-both", path=conflicts[int(selected) - 1].path)
            return None
        if answer in ("edit", "e") and conflicts:
            selected = input("Conflict number to edit? ").strip()
            if selected.isdigit() and 0 < int(selected) <= len(conflicts):
                return MergeAction("edit-conflict", path=conflicts[int(selected) - 1].path)
            return None
        if answer in ("add", "stage", "s") and conflicts:
            selected = input("Conflict number to add? ").strip()
            if selected.isdigit() and 0 < int(selected) <= len(conflicts):
                return MergeAction("add-conflict", path=conflicts[int(selected) - 1].path)
            return None
        if answer in ("add-all", "stage-all", "all"):
            return MergeAction("add-all-conflicts")
        if answer in ("continue", "c"):
            return MergeAction("continue")
        if answer in ("abort", "a"):
            return MergeAction("abort")
        return None

    if not branches:
        print("No branches available to merge.")
        return None

    print("\nBranches:")
    for index, branch in enumerate(branches, start=1):
        detail = branch.subject or branch.updated
        print(f"  {index}. {branch.name}" + (f" - {detail}" if detail else ""))

    selected = input("\nBranch number or name to merge? ").strip()
    if not selected:
        return None

    branch_name = selected
    if selected.isdigit():
        index = int(selected) - 1
        if index < 0 or index >= len(branches):
            print("Invalid branch selection.")
            return None
        branch_name = branches[index].name

    mode = input("Mode: merge, no-ff, or squash? [merge] ").strip().lower() or "merge"
    if mode not in ("merge", "no-ff", "squash"):
        print("Invalid merge mode.")
        return None

    answer = input(f"\nRun git merge {branch_name}? [y/N] ").strip().lower()
    return MergeAction("merge", branch=branch_name, mode=mode) if answer in ("y", "yes") else None


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


def _merge_manager_screen(
    stdscr: CursesWindow,
    branches: Sequence[MergeBranch],
    current_branch: str,
    status: str,
    preview_for_branch: Callable[[str], str],
    merge_in_progress: bool,
    conflicts: Sequence[MergeConflict],
    conflict_context_for_path: Callable[[str], str] | None,
    ai_resolution_for_path: Callable[[str, Callable[[str], None]], str | None] | None,
) -> MergeAction | None:
    curses.curs_set(0)
    stdscr.keypad(True)

    if merge_in_progress:
        return _merge_in_progress_screen(
            stdscr,
            current_branch,
            status,
            conflicts,
            conflict_context_for_path,
            ai_resolution_for_path,
        )

    if not branches:
        _message_screen(
            stdscr,
            title="Merge manager",
            subtitle=f"Current branch: {current_branch}",
            body="No other local or remote branches are available to merge.",
        )
        return None

    selected_branch = 0
    selected_action = 0
    actions = ["Merge", "No-ff", "Squash", "Cancel"]
    preview = preview_for_branch(branches[selected_branch].name)

    while True:
        _draw_merge_manager(
            stdscr,
            branches,
            selected_branch,
            actions,
            selected_action,
            current_branch,
            status,
            preview,
        )
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k"), ord("K")):
            selected_branch = (selected_branch - 1) % len(branches)
            preview = preview_for_branch(branches[selected_branch].name)
        elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
            selected_branch = (selected_branch + 1) % len(branches)
            preview = preview_for_branch(branches[selected_branch].name)
        elif key == curses.KEY_LEFT:
            selected_action = (selected_action - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected_action = (selected_action + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected_action = (selected_action + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("s"), ord("S")):
            return MergeAction("merge", branch=branches[selected_branch].name, mode="squash")
        elif key in (ord("f"), ord("F")):
            return MergeAction("merge", branch=branches[selected_branch].name, mode="no-ff")
        elif key in (ord("m"), ord("M"), ord("y"), ord("Y")):
            return MergeAction("merge", branch=branches[selected_branch].name, mode="merge")
        elif key in (ord("q"), ord("Q"), ord("n"), ord("N"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            action = actions[selected_action]
            if action == "Cancel":
                return None
            mode = "no-ff" if action == "No-ff" else action.lower()
            return MergeAction("merge", branch=branches[selected_branch].name, mode=mode)


def _merge_in_progress_screen(
    stdscr: CursesWindow,
    current_branch: str,
    status: str,
    conflicts: Sequence[MergeConflict],
    conflict_context_for_path: Callable[[str], str] | None,
    ai_resolution_for_path: Callable[[str, Callable[[str], None]], str | None] | None,
) -> MergeAction | None:
    if conflicts:
        return _merge_conflict_screen(
            stdscr,
            current_branch,
            status,
            conflicts,
            conflict_context_for_path,
            ai_resolution_for_path,
        )

    selected = 0
    actions = ["Continue", "Abort", "Cancel"]

    while True:
        _draw_review_screen(
            stdscr,
            title="Merge in progress",
            subtitle=f"Current branch: {current_branch}",
            body=status or "Git reports a merge in progress.",
            actions=actions,
            selected=selected,
            footer="Enter: select  c: continue  a: abort  q/Esc: cancel",
        )
        key = stdscr.getch()

        if key == curses.KEY_LEFT:
            selected = (selected - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected = (selected + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected = (selected + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("c"), ord("C")):
            return MergeAction("continue")
        elif key in (ord("a"), ord("A")):
            return MergeAction("abort")
        elif key in (ord("q"), ord("Q"), ord("n"), ord("N"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            action = actions[selected]
            if action == "Continue":
                return MergeAction("continue")
            if action == "Abort":
                return MergeAction("abort")
            if action == "Cancel":
                return None


def _merge_conflict_screen(
    stdscr: CursesWindow,
    current_branch: str,
    status: str,
    conflicts: Sequence[MergeConflict],
    conflict_context_for_path: Callable[[str], str] | None,
    ai_resolution_for_path: Callable[[str, Callable[[str], None]], str | None] | None,
) -> MergeAction | None:
    selected_conflict = 0
    selected_action = 0
    context_scroll = 0
    actions = ["Ours", "Theirs", "Both", "AI", "Edit", "Stage", "Cont", "Abort"]
    context = _conflict_context(conflict_context_for_path, conflicts[selected_conflict].path)

    while True:
        height, width = stdscr.getmaxyx()
        context_width = _merge_context_width(width)
        context_lines = _wrap_merge_context(context, context_width)
        context_visible_rows = _merge_context_visible_rows(height)
        context_scroll = _clamp_scroll(context_scroll, len(context_lines), context_visible_rows)

        _draw_merge_conflicts(
            stdscr,
            current_branch,
            status,
            conflicts,
            selected_conflict,
            context_lines,
            context_scroll,
            actions,
            selected_action,
        )
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k"), ord("K")):
            selected_conflict = (selected_conflict - 1) % len(conflicts)
            context = _conflict_context(conflict_context_for_path, conflicts[selected_conflict].path)
            context_scroll = 0
        elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
            selected_conflict = (selected_conflict + 1) % len(conflicts)
            context = _conflict_context(conflict_context_for_path, conflicts[selected_conflict].path)
            context_scroll = 0
        elif key in (curses.KEY_NPAGE, ord("]")):
            context_scroll = _clamp_scroll(context_scroll + max(1, context_visible_rows - 1), len(context_lines), context_visible_rows)
        elif key in (curses.KEY_PPAGE, ord("[")):
            context_scroll = _clamp_scroll(context_scroll - max(1, context_visible_rows - 1), len(context_lines), context_visible_rows)
        elif key in (ord("d"), ord("D")):
            context_scroll = _clamp_scroll(context_scroll + max(1, context_visible_rows // 2), len(context_lines), context_visible_rows)
        elif key in (ord("u"), ord("U")):
            context_scroll = _clamp_scroll(context_scroll - max(1, context_visible_rows // 2), len(context_lines), context_visible_rows)
        elif key == curses.KEY_LEFT:
            selected_action = (selected_action - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected_action = (selected_action + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected_action = (selected_action + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (ord("o"), ord("O")):
            return MergeAction("use-current", path=conflicts[selected_conflict].path)
        elif key in (ord("t"), ord("T")):
            return MergeAction("use-incoming", path=conflicts[selected_conflict].path)
        elif key in (ord("b"), ord("B")):
            return MergeAction("use-both", path=conflicts[selected_conflict].path)
        elif key in (ord("i"), ord("I")):
            action = _ai_merge_resolution_flow(stdscr, conflicts[selected_conflict].path, ai_resolution_for_path)
            if action is not None:
                return action
        elif key in (ord("e"), ord("E")):
            return MergeAction("edit-conflict", path=conflicts[selected_conflict].path)
        elif key in (ord("s"), ord("S")):
            return MergeAction("add-conflict", path=conflicts[selected_conflict].path)
        elif key in (ord("c"), ord("C")):
            return MergeAction("continue")
        elif key in (ord("a"), ord("A")):
            return MergeAction("abort")
        elif key in (ord("q"), ord("Q"), ord("n"), ord("N"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            action = actions[selected_action]
            if action == "Ours":
                return MergeAction("use-current", path=conflicts[selected_conflict].path)
            if action == "Theirs":
                return MergeAction("use-incoming", path=conflicts[selected_conflict].path)
            if action == "Both":
                return MergeAction("use-both", path=conflicts[selected_conflict].path)
            if action == "AI":
                merge_action = _ai_merge_resolution_flow(stdscr, conflicts[selected_conflict].path, ai_resolution_for_path)
                if merge_action is not None:
                    return merge_action
            if action == "Edit":
                return MergeAction("edit-conflict", path=conflicts[selected_conflict].path)
            if action == "Stage":
                return MergeAction("add-conflict", path=conflicts[selected_conflict].path)
            if action == "Cont":
                return MergeAction("continue")
            if action == "Abort":
                return MergeAction("abort")


def _message_screen(stdscr: CursesWindow, title: str, subtitle: str, body: str) -> None:
    while True:
        _draw_review_screen(
            stdscr,
            title=title,
            subtitle=subtitle,
            body=body,
            actions=["Close"],
            selected=0,
            footer="Enter/q/Esc: close",
        )
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q"), 27):
            return


def _ai_merge_resolution_flow(
    stdscr: CursesWindow,
    path: str,
    ai_resolution_for_path: Callable[[str, Callable[[str], None]], str | None] | None,
) -> MergeAction | None:
    if ai_resolution_for_path is None:
        _message_screen(
            stdscr,
            title="AI merge resolution",
            subtitle=path,
            body="No AI merge resolver is available.",
        )
        return None

    original = _read_text_file(path)
    if original is None:
        _message_screen(
            stdscr,
            title="AI merge resolution",
            subtitle=path,
            body="Failed to read the original conflicted file for review.",
        )
        return None

    status: queue.Queue[str] = queue.Queue()
    proposal = _run_with_loading(
        stdscr,
        title="AI merge resolution",
        subtitle=path,
        body="Preparing selected conflict for OpenAI...",
        callback=lambda: ai_resolution_for_path(path, status.put),
        status=status,
    )
    if not isinstance(proposal, str) or not proposal:
        _message_screen(
            stdscr,
            title="AI merge resolution",
            subtitle=path,
            body="AI did not return a merge proposal.",
        )
        return None

    return _ai_merge_approval_screen(stdscr, path, original, proposal)


def _ai_merge_approval_screen(stdscr: CursesWindow, path: str, original: str, proposal: str) -> MergeAction | None:
    selected_action = 0
    scroll = 0
    actions = ["Approve", "Edit", "Reject"]

    while True:
        height, width = stdscr.getmaxyx()
        context_width = _merge_context_width(width)
        proposal_lines = _wrap_ai_merge_diff(original, proposal, context_width)
        hunk_starts = _diff_hunk_starts(proposal_lines)
        visible_rows = _review_visible_rows(height)
        scroll = _clamp_scroll(scroll, len(proposal_lines), visible_rows)

        _draw_ai_merge_approval(stdscr, path, proposal_lines, scroll, actions, selected_action)
        key = stdscr.getch()

        if key == curses.KEY_LEFT:
            selected_action = (selected_action - 1) % len(actions)
        elif key in (curses.KEY_RIGHT, 9):
            selected_action = (selected_action + 1) % len(actions)
        elif key in (ord("h"), ord("l")):
            selected_action = (selected_action + (-1 if key == ord("h") else 1)) % len(actions)
        elif key in (curses.KEY_NPAGE, ord("]"), ord("d"), ord("D")):
            scroll = _clamp_scroll(scroll + max(1, visible_rows - 1), len(proposal_lines), visible_rows)
        elif key in (curses.KEY_PPAGE, ord("["), ord("u"), ord("U")):
            scroll = _clamp_scroll(scroll - max(1, visible_rows - 1), len(proposal_lines), visible_rows)
        elif key in (ord("n"), ord("N")):
            scroll = _next_hunk_scroll(hunk_starts, scroll, visible_rows, len(proposal_lines))
        elif key in (ord("p"), ord("P")):
            scroll = _previous_hunk_scroll(hunk_starts, scroll, visible_rows, len(proposal_lines))
        elif key in (ord("y"), ord("Y")):
            return MergeAction("apply-ai", path=path, content=proposal)
        elif key in (ord("e"), ord("E")):
            proposal = _edit_text(stdscr, proposal, ".MERGE_AI")
            scroll = 0
        elif key in (ord("q"), ord("Q"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            action = actions[selected_action]
            if action == "Approve":
                return MergeAction("apply-ai", path=path, content=proposal)
            if action == "Edit":
                proposal = _edit_text(stdscr, proposal, ".MERGE_AI")
                scroll = 0
            if action == "Reject":
                return None


def _draw_merge_manager(
    stdscr: CursesWindow,
    branches: Sequence[MergeBranch],
    selected_branch: int,
    actions: Sequence[str],
    selected_action: int,
    current_branch: str,
    status: str,
    preview: str,
) -> None:
    stdscr.erase()
    _init_colors()
    height, width = stdscr.getmaxyx()
    usable_width = max(20, width - 4)

    _add_line(stdscr, 1, 2, "Merge manager", curses.A_BOLD)
    status_summary = "clean" if not status.strip() else "changes present"
    _add_line(stdscr, 3, 2, f"Current branch: {current_branch}  Working tree: {status_summary}")

    button_y = height - 4
    list_top = 5
    list_bottom = min(max(list_top + 3, height // 2), max(list_top + 3, button_y - 7))
    preview_top = list_bottom + 2
    preview_bottom = button_y - 2

    if height >= 16 and width >= 40 and list_bottom > list_top + 1:
        _draw_box(stdscr, list_top, 1, list_bottom, width - 2)
        visible_rows = max(1, list_bottom - list_top - 1)
        start = min(max(0, selected_branch - visible_rows // 2), max(0, len(branches) - visible_rows))
        for row, branch in enumerate(branches[start:start + visible_rows], start=list_top + 1):
            index = start + row - list_top - 1
            marker = ">" if index == selected_branch else " "
            detail_parts = [part for part in (branch.upstream, branch.updated, branch.subject) if part]
            detail = " | ".join(detail_parts)
            label = f"{marker} {branch.name}" + (f" - {detail}" if detail else "")
            attr = curses.A_REVERSE if index == selected_branch else curses.A_NORMAL
            _add_line(stdscr, row, 3, label[:usable_width], attr)

    if height >= 18 and width >= 40 and preview_bottom > preview_top + 2:
        _draw_box(stdscr, preview_top, 1, preview_bottom, width - 2)
        selected_name = branches[selected_branch].name
        _add_line(stdscr, preview_top, 3, f" Commits in {selected_name} not in {current_branch} ")
        preview_lines = _wrap_message_with_severity(preview or "No unique commits found.", usable_width)
        for row, (line, severity) in enumerate(preview_lines[:preview_bottom - preview_top - 1], start=preview_top + 1):
            _add_line(stdscr, row, 3, line[:usable_width], _severity_attr(severity))

    x = 2
    for index, action in enumerate(actions):
        label = f" {action} "
        _add_line(stdscr, button_y, x, label, _action_attr(action, selected=index == selected_action))
        x += len(label) + 2

    _add_line(stdscr, height - 2, 2, "Up/down: branch  Enter: select  m: merge  f: no-ff  s: squash  q/Esc: cancel")
    stdscr.refresh()


def _draw_merge_conflicts(
    stdscr: CursesWindow,
    current_branch: str,
    status: str,
    conflicts: Sequence[MergeConflict],
    selected_conflict: int,
    context_lines: Sequence[tuple[str, str | None]],
    context_scroll: int,
    actions: Sequence[str],
    selected_action: int,
) -> None:
    stdscr.erase()
    _init_colors()
    height, width = stdscr.getmaxyx()
    usable_width = max(20, width - 4)
    context_width = _merge_context_width(width)

    _add_line(stdscr, 1, 2, "Merge conflicts", curses.A_BOLD)
    _add_line(stdscr, 3, 2, f"Current branch: {current_branch}  Conflicts: {len(conflicts)}")

    button_y = height - 4
    list_top = 5
    list_bottom = min(max(list_top + 3, height // 3), max(list_top + 3, button_y - 8))
    context_top = list_bottom + 2
    context_bottom = button_y - 2
    if height >= 14 and width >= 40:
        _draw_box(stdscr, list_top, 1, list_bottom, width - 2)
        visible_rows = max(1, list_bottom - list_top - 1)
        start = min(max(0, selected_conflict - visible_rows // 2), max(0, len(conflicts) - visible_rows))
        for row, conflict in enumerate(conflicts[start:start + visible_rows], start=list_top + 1):
            index = start + row - list_top - 1
            marker = ">" if index == selected_conflict else " "
            label = f"{marker} {conflict.status} {conflict.path}"
            attr = curses.A_REVERSE if index == selected_conflict else curses.A_NORMAL
            _add_line(stdscr, row, 3, label[:usable_width], attr)
    elif status:
        _add_line(stdscr, list_top, 2, status[:usable_width])

    if height >= 18 and width >= 40 and context_bottom > context_top + 2:
        _draw_box(stdscr, context_top, 1, context_bottom, width - 2)
        _add_line(stdscr, context_top, 3, f" {conflicts[selected_conflict].path} ")
        visible_rows = context_bottom - context_top - 1
        visible_lines = context_lines[context_scroll:context_scroll + visible_rows]
        for row, (line, style) in enumerate(visible_lines, start=context_top + 1):
            _add_line(stdscr, row, 3, line[:context_width], _semantic_attr(style))
        if len(context_lines) > visible_rows:
            scroll_label = f" {context_scroll + 1}-{min(context_scroll + visible_rows, len(context_lines))}/{len(context_lines)} "
            _add_line(stdscr, context_top, max(3, width - len(scroll_label) - 3), scroll_label, curses.A_DIM)

    _draw_action_row(stdscr, button_y, actions, selected_action)

    _add_line(stdscr, height - 2, 2, "Up/down: file  [/]: scroll  o: ours  t: theirs  b: both  i: AI  e: edit  s: stage  c: continue")
    stdscr.refresh()


def _draw_ai_merge_approval(
    stdscr: CursesWindow,
    path: str,
    proposal_lines: Sequence[tuple[str, str | None]],
    scroll: int,
    actions: Sequence[str],
    selected_action: int,
) -> None:
    stdscr.erase()
    _init_colors()
    height, width = stdscr.getmaxyx()
    context_width = _merge_context_width(width)

    _add_line(stdscr, 1, 2, "AI merge proposal", curses.A_BOLD)
    _add_line(stdscr, 3, 2, path)

    box_top = 5
    button_y = height - 4
    box_bottom = button_y - 2
    if height >= 12 and width >= 40 and box_bottom > box_top + 2:
        _draw_box(stdscr, box_top, 1, box_bottom, width - 2)
        visible_rows = box_bottom - box_top - 1
        visible_lines = proposal_lines[scroll:scroll + visible_rows]
        for row, (line, style) in enumerate(visible_lines, start=box_top + 1):
            _add_line(stdscr, row, 3, line[:context_width], _semantic_attr(style))
        if len(proposal_lines) > visible_rows:
            scroll_label = f" {scroll + 1}-{min(scroll + visible_rows, len(proposal_lines))}/{len(proposal_lines)} "
            _add_line(stdscr, box_top, max(3, width - len(scroll_label) - 3), scroll_label, curses.A_DIM)

    _draw_action_row(stdscr, button_y, actions, selected_action)
    _add_line(stdscr, height - 2, 2, "[/]: scroll  n/p: hunk  y: approve+stage  e: edit proposal  q: reject")
    stdscr.refresh()


def _conflict_context(conflict_context_for_path: Callable[[str], str] | None, path: str) -> str:
    if conflict_context_for_path is None:
        return "No conflict context provider is available."
    return conflict_context_for_path(path)


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except (UnicodeDecodeError, OSError):
        return None


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


def _edit_text(stdscr: CursesWindow, text: str, suffix: str) -> str:
    curses.def_prog_mode()
    curses.endwin()
    try:
        edited = _edit_text_in_editor(text.rstrip() + "\n", suffix)
        return edited if edited.strip() else text
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
    try:
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
    except curses.error:
        pass


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
    try:
        stdscr.addstr(y, x, text[:max(0, width - x - 1)], attr)
    except curses.error:
        pass


def _draw_action_row(
    stdscr: CursesWindow,
    y: int,
    actions: Sequence[str],
    selected: int,
) -> None:
    _init_colors()
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or width < 12:
        return

    labels = [_action_label(action) for action in actions]
    total_width = sum(len(label) for label in labels)
    if total_width <= width - 4:
        x = 2
        for index, label in enumerate(labels):
            _add_line(stdscr, y, x, label, _action_attr(actions[index], selected=index == selected))
            x += len(label)
        return

    selected_label = _action_label(actions[selected])
    prefix = f"{selected + 1}/{len(actions)} "
    _add_line(stdscr, y, 2, prefix, curses.A_DIM)
    _add_line(stdscr, y, 2 + len(prefix), selected_label, _action_attr(actions[selected], selected=True))
    hint = " left/right "
    if 2 + len(prefix) + len(selected_label) + len(hint) < width:
        _add_line(stdscr, y, 2 + len(prefix) + len(selected_label) + 1, hint, curses.A_DIM)


def _action_label(action: str) -> str:
    shortcuts = {
        "Ours": "o",
        "Theirs": "t",
        "Both": "b",
        "AI": "i",
        "Edit": "e",
        "Stage": "s",
        "Cont": "c",
        "Abort": "a",
        "Merge": "m",
        "No-ff": "f",
        "Squash": "s",
        "Cancel": "q",
        "Continue": "c",
        "Cont": "c",
        "Approve": "y",
        "Reject": "n",
        "Close": "q",
    }
    shortcut = shortcuts.get(action)
    if not shortcut:
        return f" {action} "
    return f" {shortcut}:{action} "


def _merge_context_width(terminal_width: int) -> int:
    return max(20, min(80, terminal_width - 6))


def _merge_context_visible_rows(terminal_height: int) -> int:
    button_y = terminal_height - 4
    list_top = 5
    list_bottom = min(max(list_top + 3, terminal_height // 3), max(list_top + 3, button_y - 8))
    context_top = list_bottom + 2
    context_bottom = button_y - 2
    if terminal_height < 18:
        return 0
    return max(0, context_bottom - context_top - 1)


def _review_visible_rows(terminal_height: int) -> int:
    if terminal_height < 12:
        return 0
    return max(0, terminal_height - 12)


def _clamp_scroll(scroll: int, total_lines: int, visible_rows: int) -> int:
    if visible_rows <= 0 or total_lines <= visible_rows:
        return 0
    return max(0, min(scroll, total_lines - visible_rows))


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


def _wrap_merge_context(message: str, width: int) -> list[tuple[str, str | None]]:
    lines: list[tuple[str, str | None]] = []
    active_block: str | None = None

    for raw_line in message.splitlines():
        style, active_block = _merge_context_style(raw_line, active_block)
        if not raw_line.strip():
            lines.append(("", None))
            continue
        for line in textwrap.wrap(
            raw_line,
            width=width,
            subsequent_indent="  " if raw_line.startswith("  ") else "",
        ) or [""]:
            lines.append((line, style))

    return lines or [(message, None)]


def _wrap_code_context(message: str, width: int) -> list[tuple[str, str | None]]:
    lines: list[tuple[str, str | None]] = []
    for raw_line in message.splitlines():
        style = _code_line_style(raw_line)
        if not raw_line:
            lines.append(("", None))
            continue
        for line in textwrap.wrap(raw_line, width=width, replace_whitespace=False, drop_whitespace=False) or [""]:
            lines.append((line, style))
    return lines or [("", None)]


def _wrap_ai_merge_diff(original: str, proposal: str, width: int) -> list[tuple[str, str | None]]:
    diff_lines = list(difflib.unified_diff(
        original.splitlines(),
        proposal.splitlines(),
        fromfile="original",
        tofile="ai proposal",
        lineterm="",
        n=3,
    ))
    if not diff_lines:
        diff_lines = ["No text differences between original and AI proposal."]

    lines: list[tuple[str, str | None]] = []
    for raw_line in diff_lines:
        style = _diff_line_style(raw_line)
        for line in textwrap.wrap(
            raw_line,
            width=width,
            subsequent_indent=_diff_wrap_indent(raw_line),
            replace_whitespace=False,
            drop_whitespace=False,
        ) or [""]:
            lines.append((line, style))
    return lines


def _diff_line_style(line: str) -> str | None:
    if line.startswith("@@"):
        return "hunk"
    if line.startswith("---"):
        return "removed-heading"
    if line.startswith("+++"):
        return "added-heading"
    if line.startswith("-"):
        return "removed"
    if line.startswith("+"):
        return "added"
    return None


def _diff_wrap_indent(line: str) -> str:
    if line.startswith(("+", "-", " ")):
        return line[:1] + " "
    return "  "


def _diff_hunk_starts(lines: Sequence[tuple[str, str | None]]) -> list[int]:
    return [index for index, (_line, style) in enumerate(lines) if style == "hunk"]


def _next_hunk_scroll(hunk_starts: Sequence[int], current: int, visible_rows: int, total_lines: int) -> int:
    for hunk_start in hunk_starts:
        if hunk_start > current:
            return _clamp_scroll(hunk_start, total_lines, visible_rows)
    return _clamp_scroll(hunk_starts[0], total_lines, visible_rows) if hunk_starts else current


def _previous_hunk_scroll(hunk_starts: Sequence[int], current: int, visible_rows: int, total_lines: int) -> int:
    previous = [hunk_start for hunk_start in hunk_starts if hunk_start < current]
    if previous:
        return _clamp_scroll(previous[-1], total_lines, visible_rows)
    return _clamp_scroll(hunk_starts[-1], total_lines, visible_rows) if hunk_starts else current


def _code_line_style(line: str) -> str | None:
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "/*", "*")):
        return "muted"
    if stripped.startswith(("def ", "class ", "function ", "const ", "let ", "var ", "import ", "from ")):
        return "heading"
    if stripped.startswith(("+", "-")):
        return "both"
    return None


def _merge_context_style(line: str, active_block: str | None) -> tuple[str | None, str | None]:
    stripped = line.strip()
    lowered = stripped.lower()

    if not stripped:
        return None, active_block
    if lowered.startswith("git options:"):
        return "heading", None
    if lowered.startswith("conflict "):
        return "heading", None
    if lowered.startswith("current / ours:"):
        return "current-heading", "current"
    if lowered.startswith("incoming / theirs:"):
        return "incoming-heading", "incoming"
    if lowered.startswith("base:"):
        return "base-heading", "base"
    if lowered.startswith("- current:"):
        return "current", None
    if lowered.startswith("- incoming:"):
        return "incoming", None
    if lowered.startswith("- both:"):
        return "both", None
    if lowered.startswith("- editor:"):
        return "editor", None
    if line.startswith("  ") and active_block:
        return active_block, active_block
    if stripped.startswith("<") and stripped.endswith(">"):
        return "muted", active_block
    if lowered.startswith("... ") or " more line(s)" in lowered:
        return "muted", active_block
    return None, active_block


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
    _safe_init_pair(5, curses.COLOR_BLUE)
    _safe_init_pair(6, curses.COLOR_MAGENTA)
    _safe_init_pair(7, curses.COLOR_WHITE)


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


def _semantic_attr(style: str | None) -> int:
    if style == "heading":
        return curses.A_BOLD
    if style == "current-heading":
        return curses.color_pair(4) | curses.A_BOLD
    if style == "incoming-heading":
        return curses.color_pair(3) | curses.A_BOLD
    if style == "base-heading":
        return curses.color_pair(2) | curses.A_BOLD
    if style == "current":
        return curses.color_pair(4)
    if style == "incoming":
        return curses.color_pair(3)
    if style == "base":
        return curses.color_pair(2)
    if style == "both":
        return curses.color_pair(6)
    if style == "editor":
        return curses.color_pair(5)
    if style == "muted":
        return curses.A_DIM
    if style == "removed-heading":
        return curses.color_pair(1) | curses.A_BOLD
    if style == "added-heading":
        return curses.color_pair(4) | curses.A_BOLD
    if style == "removed":
        return curses.color_pair(1)
    if style == "added":
        return curses.color_pair(4)
    if style == "hunk":
        return curses.color_pair(6) | curses.A_BOLD
    return curses.A_NORMAL


def _action_attr(action: str, selected: bool) -> int:
    base = curses.A_REVERSE if selected else curses.A_NORMAL
    if action in ("Continue", "Cont", "Approve", "Close", "Merge"):
        return base | curses.color_pair(4)
    if action in ("Cancel", "Reject", "Abort"):
        return base | curses.color_pair(1)
    if action == "Ours":
        return base | curses.color_pair(4)
    if action == "Theirs":
        return base | curses.color_pair(3)
    if action == "Both":
        return base | curses.color_pair(6)
    if action == "AI":
        return base | curses.color_pair(6) | curses.A_BOLD
    if action == "Edit":
        return base | curses.color_pair(5)
    if action == "Stage":
        return base | curses.color_pair(2)
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
