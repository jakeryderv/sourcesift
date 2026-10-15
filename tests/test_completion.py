"""Picker matching, workspace boundaries, and ignore semantics."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sourcesift import InputError
from sourcesift.completion import (
    attachment_path,
    discover_files,
    fuzzy_matches,
    mention,
    mentioned_paths,
)


def test_discovery_ignores_hidden_nested_and_symlink_files(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nignored/\n")
    for name in ["README.md", "debug.log", ".env"]:
        (tmp_path / name).write_text("content")
    for name in ["ignored", "docs", "node_modules", ".venv"]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "file.md").write_text("content")
    (tmp_path / "docs/.gitignore").write_text("file.md\n!keep.log\n")
    (tmp_path / "docs/keep.log").write_text("content")
    (tmp_path / "link.md").symlink_to(tmp_path / "README.md")
    (tmp_path / "linked-dir").symlink_to(tmp_path / "docs", target_is_directory=True)
    assert discover_files(tmp_path).paths == ("README.md", "docs/keep.log")
    assert not discover_files(tmp_path).limited


def test_discovery_respects_parent_repository_rules_and_limits(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("docs/secret.md\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "secret.md").write_text("secret")
    (docs / "public.md").write_text("public")
    assert discover_files(docs).paths == ("public.md",)
    assert discover_files(tmp_path, max_entries=0).limited
    assert discover_files(tmp_path, seconds=0).limited


def test_discovery_errors_and_depth_limit(tmp_path, monkeypatch):
    current = tmp_path
    for _ in range(22):
        current = current / "nested"
        current.mkdir()
    assert discover_files(tmp_path).limited
    (tmp_path / ".gitignore").write_text("x" * 65537)
    with pytest.raises(InputError, match="limit"):
        discover_files(tmp_path)
    (tmp_path / ".gitignore").unlink()
    monkeypatch.setattr(
        "sourcesift.completion.os.scandir",
        lambda path: (_ for _ in ()).throw(PermissionError()),
    )
    with pytest.raises(InputError, match="Cannot list"):
        discover_files(tmp_path)


def test_attachment_paths_revalidated_at_send(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("notes")
    assert attachment_path(tmp_path, "notes.md") == target
    for invalid in ["../elsewhere", "/absolute", "missing", "."]:
        with pytest.raises(InputError, match="attachment"):
            attachment_path(tmp_path, invalid)
    target.unlink()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(InputError, match="attachment"):
        attachment_path(tmp_path, "notes.md")


def test_fuzzy_subsequence_ranking_and_no_matches():
    result = fuzzy_matches("ctx", ["/quit", "/context", "/cancel"])
    assert result == [("/context", (1, 4, 6))]
    assert fuzzy_matches("zz", ["README.md"]) == []
    assert fuzzy_matches("read", ["docs/readme.md", "README.md"])[0][0] == "README.md"
    assert len(fuzzy_matches("", [str(i) for i in range(100)])) == 30


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1))
def test_quoted_mentions_roundtrip(path):
    assert mentioned_paths("Read " + mention(path) + " please") == {path}


def test_mentions_do_not_treat_email_as_attachment():
    assert mentioned_paths('email@example.org @notes.md @"two words.md"') == {
        "notes.md",
        "two words.md",
    }
    assert mentioned_paths('@"bad\\q"') == set()
