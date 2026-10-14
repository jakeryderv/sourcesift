"""Regressions for version drift and accidental release decisions."""

import json
from pathlib import Path

import pytest

from scripts.release_checks import (
    validate_change,
    validate_tag,
    validate_title,
    validate_versions,
)


@pytest.fixture
def package(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sourcesift"\nversion = "0.1.0"\n'
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "sourcesift"\nversion = "0.1.0"\n'
    )
    (tmp_path / ".release-please-manifest.json").write_text(json.dumps({".": "0.1.0"}))
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0](https://example.com) (2026-10-14)\n"
    )
    return tmp_path


def test_consistent_release(package: Path) -> None:
    assert validate_versions(package) == "0.1.0"
    validate_tag("0.1.0", "v0.1.0")
    validate_change("0.1.0", "0.0.1", release_pr=True)


@pytest.mark.parametrize(
    "filename", ["uv.lock", ".release-please-manifest.json", "CHANGELOG.md"]
)
def test_version_drift_is_rejected(package: Path, filename: str) -> None:
    path = package / filename
    path.write_text(path.read_text().replace("0.1.0", "0.0.1"))
    with pytest.raises(ValueError):
        validate_versions(package)


@pytest.mark.parametrize(
    "version,base,is_release",
    [("0.1.0", "0.0.1", False), ("0.0.1", "0.1.0", True), ("0.1.0", "0.1.0", True)],
)
def test_invalid_version_changes(version: str, base: str, is_release: bool) -> None:
    with pytest.raises(ValueError):
        validate_change(version, base, is_release)


def test_ordinary_pr_can_keep_current_version() -> None:
    validate_change("0.1.0", "0.1.0", release_pr=False)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.0.1", "v0.1.0-extra"])
def test_tag_mismatch_is_rejected(tag: str) -> None:
    with pytest.raises(ValueError):
        validate_tag("0.1.0", tag)


@pytest.mark.parametrize(
    "title",
    [
        "feat(cli): add ask command",
        "fix!: change result contract",
        "chore(main): release 0.1.0",
        "docs: clarify sources",
    ],
)
def test_conventional_titles(title: str) -> None:
    validate_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Add feature",
        "feat:",
        "feat: ",
        "feat: ok\nfix: surprise",
        " feat: leading space",
        "unknown: change",
    ],
)
def test_invalid_titles(title: str) -> None:
    with pytest.raises(ValueError):
        validate_title(title)


def test_release_pr_identity_and_dispatched_head(package: Path, monkeypatch) -> None:
    from scripts.release_checks import validate_pr

    monkeypatch.setattr(
        "scripts.release_checks.subprocess.check_output",
        lambda *args, **kwargs: '[project]\nversion = "0.0.1"\n',
    )
    pr = {
        "title": "chore(main): release 0.1.0",
        "user": {"login": "github-actions[bot]"},
        "head": {
            "sha": "current-head",
            "ref": "release-please--branches--main--components--sourcesift",
            "repo": {"full_name": "jakeryderv/sourcesift"},
        },
        "base": {"sha": "base-sha", "ref": "main"},
        "labels": [{"name": "autorelease: pending"}],
    }
    validate_pr(package, pr, "jakeryderv/sourcesift", "current-head")
    with pytest.raises(ValueError, match="current PR head"):
        validate_pr(package, pr, "jakeryderv/sourcesift", "stale-head")
    pr["user"]["login"] = "someone-else"
    with pytest.raises(ValueError, match="only in the Release Please PR"):
        validate_pr(package, pr, "jakeryderv/sourcesift", "current-head")
