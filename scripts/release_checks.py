"""Validate release metadata and PR policy without changing files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

from packaging.version import Version

TITLE = re.compile(
    r"(?:feat|fix|perf|deps|docs|style|refactor|test|build|ci|chore|revert)"
    r"(?:\([a-zA-Z0-9_./-]+\))?!?: \S[^\r\n]*"
)
RELEASE_BRANCH = "release-please--branches--main--components--sourcesift"


def validate_title(title: str) -> None:
    if not TITLE.fullmatch(title) or title != title.strip():
        raise ValueError(
            "Use a Conventional Commit PR title, e.g. feat(cli): add ask command"
        )


def validate_versions(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    parsed = Version(version)
    if str(parsed) != version:
        raise ValueError("Package version must use normalized Python version syntax")
    manifest = json.loads((root / ".release-please-manifest.json").read_text())
    if manifest.get(".") != version:
        raise ValueError("Release Please manifest and pyproject.toml versions differ")
    lock = tomllib.loads((root / "uv.lock").read_text())
    packages = [p for p in lock["package"] if p["name"] == project["name"]]
    if len(packages) != 1 or packages[0]["version"] != version:
        raise ValueError("uv.lock project version differs; run uv lock")
    changelog = (root / "CHANGELOG.md").read_text()
    if not re.search(
        rf"^## (?:\[{re.escape(version)}\]|{re.escape(version)})(?:[ (]|$)",
        changelog,
        re.MULTILINE,
    ):
        raise ValueError("CHANGELOG.md lacks an entry for the package version")
    return version


def validate_change(version: str, base_version: str, release_pr: bool) -> None:
    if version != base_version:
        if not release_pr:
            raise ValueError("Change package versions only in the Release Please PR")
        if Version(version) <= Version(base_version):
            raise ValueError("Release version must increase")
    elif release_pr:
        raise ValueError("Release PR must increase the package version")


def validate_tag(version: str, tag: str) -> None:
    if tag != f"v{version}":
        raise ValueError(f"Release tag {tag!r} does not match v{version}")


def validate_pr(
    root: Path, pr: dict, repository: str, head_sha: str | None = None
) -> None:
    validate_title(pr["title"])
    if head_sha and pr["head"]["sha"] != head_sha:
        raise ValueError("Dispatched CI must check the current PR head commit")
    if pr["base"]["ref"] != "main":
        raise ValueError("PR must target main")
    release_pr = (
        pr["user"]["login"] == "github-actions[bot]"
        and pr["head"]["repo"]["full_name"] == repository
        and pr["head"]["ref"] == RELEASE_BRANCH
        and "autorelease: pending" in {label["name"] for label in pr["labels"]}
    )
    base = subprocess.check_output(
        ["git", "show", f"{pr['base']['sha']}:pyproject.toml"], cwd=root, text=True
    )
    validate_change(
        validate_versions(root), tomllib.loads(base)["project"]["version"], release_pr
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--pr-json", type=Path)
    parser.add_argument("--head-sha")
    parser.add_argument("--repository", default="jakeryderv/sourcesift")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = validate_versions(root)
    if args.tag:
        validate_tag(version, args.tag)
    if args.pr_json:
        validate_pr(
            root, json.loads(args.pr_json.read_text()), args.repository, args.head_sha
        )
    print(f"Release metadata valid: {version}")


if __name__ == "__main__":
    main()
