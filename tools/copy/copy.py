#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import select
import shutil
import subprocess
import sys
from typing import Sequence


PROGRAM_NAME = "copy"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description=(
            "Copy stdin, arguments, or the previous tmux command transcript "
            "to the system clipboard."
        ),
    )
    parser.add_argument(
        "-p",
        "--primary",
        action="store_true",
        help="copy to the primary selection when supported",
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="text to copy; when omitted, stdin or tmux pane recovery is used",
    )
    return parser


def run_command(command: Sequence[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
    )


def run_clipboard_command(command: Sequence[str], text: str) -> bool:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        assert process.stdin is not None
        process.stdin.write(text)
        process.stdin.close()
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        return True

    return process.returncode == 0


def read_tmux_previous_command(invocations: Sequence[str]) -> str | None:
    tmux_socket = os.environ.get("TMUX")
    tmux_pane = os.environ.get("TMUX_PANE")
    if not tmux_socket or not tmux_pane or shutil.which("tmux") is None:
        return None

    capture = run_command(["tmux", "capture-pane", "-p", "-J", "-S", "-", "-t", tmux_pane])
    if capture.returncode != 0:
        return None

    lines = capture.stdout.splitlines()
    if not lines:
        return None

    invocation_index = None
    matched_invocation = None
    for index in range(len(lines) - 1, -1, -1):
        for invocation in invocations:
            if lines[index].endswith(invocation):
                invocation_index = index
                matched_invocation = invocation
                break
        if invocation_index is not None:
            break

    if invocation_index is None or invocation_index < 1:
        trimmed_lines = list(lines)
        while trimmed_lines and not trimmed_lines[-1]:
            trimmed_lines.pop()

        if len(trimmed_lines) < 2:
            return None

        current_prompt = trimmed_lines[-1]
        prompt_indexes = [
            index for index, line in enumerate(trimmed_lines[:-1])
            if line.startswith(current_prompt)
        ]

        if len(prompt_indexes) < 2:
            return None

        start_index = prompt_indexes[-2]
        end_index = prompt_indexes[-1]
        recovered = "\n".join(trimmed_lines[start_index:end_index])
        if recovered:
            recovered += "\n"
        return recovered or None

    current_line = lines[invocation_index]
    candidate_lines = lines[:invocation_index]
    prompt_prefix = current_line[: -len(matched_invocation)]

    start_index = 0
    if prompt_prefix:
        for index in range(len(candidate_lines) - 1, -1, -1):
            if candidate_lines[index].startswith(prompt_prefix):
                start_index = index
                break

    recovered = "\n".join(candidate_lines[start_index:])
    if recovered:
        recovered += "\n"
    return recovered or None


def stdin_has_data() -> bool:
    if sys.stdin.isatty():
        return False

    ready, _, _ = select.select([sys.stdin], [], [], 0)
    return bool(ready)


def resolve_text(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.text:
        return " ".join(args.text)

    invocations = [PROGRAM_NAME]
    if args.primary:
        invocations.extend([f"{PROGRAM_NAME} --primary", f"{PROGRAM_NAME} -p"])

    recovered = read_tmux_previous_command(invocations)
    if recovered is not None:
        return recovered

    if stdin_has_data():
        return sys.stdin.read()

    parser.exit(
        2,
        f"{PROGRAM_NAME}: expected stdin, text arguments, or an active tmux pane\n",
    )


def copy_with_backend(text: str, *, primary: bool) -> bool:
    backends: list[list[str]] = []

    if shutil.which("wl-copy") is not None:
        command = ["wl-copy"]
        if primary:
            command.append("--primary")
        backends.append(command)

    if not primary and shutil.which("pbcopy") is not None:
        backends.append(["pbcopy"])

    if shutil.which("xclip") is not None:
        selection = "primary" if primary else "clipboard"
        backends.append(["xclip", "-selection", selection])

    if shutil.which("xsel") is not None:
        selection = "--primary" if primary else "--clipboard"
        backends.append(["xsel", selection, "--input"])

    for command in backends:
        if run_clipboard_command(command, text):
            return True

    return False


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    text = resolve_text(args, parser)
    if copy_with_backend(text, primary=args.primary):
        return 0

    sys.stderr.write(
        "copy: no working clipboard backend found\n\n"
        "Install one of:\n"
        "  - wl-clipboard for Wayland\n"
        "  - xclip or xsel for X11\n\n"
        "On macOS, pbcopy is used automatically.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
