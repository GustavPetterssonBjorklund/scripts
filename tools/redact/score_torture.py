#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        prog="score_torture",
        description="Run redact against the torture fixture and score it against explicit expectations.",
    )
    parser.add_argument(
        "--input",
        default=str(script_dir / "torture_test.txt"),
        help="path to the torture input fixture",
    )
    parser.add_argument(
        "--expectations",
        default=str(script_dir / "torture_expectations.json"),
        help="path to the expectation file",
    )
    parser.add_argument(
        "--redact-script",
        default=str(script_dir / "redact.py"),
        help="path to the redact implementation to run",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help="limit scoring to one or more sections, e.g. --section 21 --section 22",
    )
    parser.add_argument(
        "--dump-output",
        help="optional file path to write the produced redacted output",
    )
    return parser.parse_args()


def load_expectations(path: Path, sections: set[str]) -> list[dict[str, str]]:
    data = json.loads(path.read_text())
    checks = data.get("must_redact", [])
    if sections:
        checks = [check for check in checks if check.get("section") in sections]
    return checks


def run_redact(redact_script: Path, input_text: str) -> str:
    result = subprocess.run(
        [sys.executable, str(redact_script), "--yes"],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def check_expectation(output: str, check: dict[str, str]) -> tuple[bool, str]:
    expect = check.get("expect", "redact")
    description = check["description"]

    if "literal" in check:
        value = check["literal"]
        present = value in output
        if expect == "keep":
            return present, f"expected to keep literal `{value}`"
        return not present, f"expected to redact literal `{value}`"

    pattern = check["regex"]
    present = re.search(pattern, output, re.MULTILINE) is not None
    if expect == "keep":
        return present, f"expected to keep regex `{pattern}`"
    return not present, f"expected to redact regex `{pattern}`"


def main() -> int:
    args = parse_args()
    sections = set(args.section)
    input_path = Path(args.input)
    expectations_path = Path(args.expectations)
    redact_script = Path(args.redact_script)

    checks = load_expectations(expectations_path, sections)
    if not checks:
        print("No expectations selected.", file=sys.stderr)
        return 2

    output = run_redact(redact_script, input_path.read_text())
    if args.dump_output:
        Path(args.dump_output).write_text(output)

    failures: dict[str, list[str]] = defaultdict(list)
    passes = 0
    for check in checks:
        ok, message = check_expectation(output, check)
        if ok:
            passes += 1
            continue
        failures[check.get("section", "?")].append(f"{check['description']}: {message}")

    total = len(checks)
    print(f"Score: {passes}/{total} ({(passes / total) * 100:.1f}%)")
    if not failures:
        print("No expectation failures.")
        return 0

    print("Failures:")
    for section in sorted(failures):
        print(f"  Section {section}:")
        for failure in failures[section]:
            print(f"    - {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
