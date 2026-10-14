"""Run the same development checks locally and in CI."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-only", action="store_true", help="CI matrix: omit actionlint"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commands = [
        ["ruff", "format", "--check", "."],
        ["ruff", "check", "."],
        ["ty", "check"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "scripts/release_checks.py"],
    ]
    if not args.python_only:
        commands.append(["actionlint"])
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
