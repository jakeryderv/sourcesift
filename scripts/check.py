"""Run the same development checks locally and in CI."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--python-only", action="store_true", help="Omit actionlint")
    group.add_argument(
        "--quality-only",
        action="store_true",
        help="Only lint, format, types, and hook configuration",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commands = [
        ["ruff", "format", "--check", "."],
        ["ruff", "check", "."],
        ["ty", "check"],
        ["pre-commit", "validate-config"],
    ]
    if not args.quality_only:
        commands.extend(
            [
                [sys.executable, "-m", "pytest", "-q", "-m", "not network"],
                [sys.executable, "scripts/release_checks.py"],
            ]
        )
    if not args.python_only and not args.quality_only:
        commands.append(["actionlint"])
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
