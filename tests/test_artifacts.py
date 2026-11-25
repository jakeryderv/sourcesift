"""Artifacts are checked text that the application, not the model, writes to disk."""

import io
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from sourcesift import (
    Artifact,
    Figure,
    InputError,
    Reference,
    Result,
    Settings,
    artifact_from_answer,
    cli,
    load_settings,
    render_qmd,
    save_artifacts,
)
from sourcesift.artifacts import (
    artifact_filename,
    artifact_problem,
    csl_reference,
    new_artifact_folder,
)

WHEN = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
TABLE = {
    "name": "Debt",
    "columns": [{"name": "Date", "kind": "time"}, {"name": "Total", "unit": "USD"}],
    "rows": [["2026-10-13", 38000000000100.5], ["2026-10-14", 38000000000300.5]],
}


def reference(key="S1", **changes):
    values = {
        "id": key,
        "title": "New [library]\n# Injected heading",
        "url": "https://example.com/a_(b)",
        "requested_url": "https://example.com/feed",
        "retrieved_from": "https://example.com/feed",
        "publisher": "example.com",
        "author": "Ana  Writer",
        "published_at": WHEN,
        "retrieved_at": WHEN,
        "kind": "feed_summary",
        "limitations": ("Only the feed summary was retrieved.",),
    }
    return Reference.model_validate(values | changes)


def figure(key="F1"):
    return Figure(
        id=key,
        title="Debt",
        kind="line",
        x="Date",
        y=("Total",),
        source_id="us-treasury",
        evidence_ids=("S2",),
        table=TABLE,
    )


def artifact(markdown="The library was **approved** [S1].", **changes):
    values = {"id": "A1", "title": "Library: news", "updated_at": WHEN}
    return Artifact.model_validate(values | {"markdown": markdown} | changes)


def result(**changes):
    values = {
        "answer": "The library was **approved** [S1].\n\n![Debt](F1)",
        "model": "example/test",
        "limitations": ("Only the feed summary was retrieved.",),
        "references": (reference(), reference("S2", title="Debt data")),
        "figures": (figure(),),
    }
    return Result.model_validate(values | changes)


def test_qmd_runs_no_code_and_uses_quarto_citations():
    text = render_qmd(
        artifact(
            "Approved [S1]. Both agree [S1], [S2] and [S1][S3].\n\n---\n\n"
            "![Debt]( F1 )\n\nSee [S2].",
            notes=("Coverage is a *sample*.",),
        )
    )
    header, body = text.split("\n---\n", 1)
    assert header.startswith('---\ntitle: "Library: news"\ndate: 2026-01-02\n')
    # Cells never run, and raw HTML or LaTeX cannot pass through to an export.
    assert "execute:\n  enabled: false" in header
    assert "from: markdown-raw_html-raw_tex-raw_attribute" in header
    assert "bibliography: references.json" in header
    assert "Approved [@S1]. Both agree [@S1; @S2] and [@S1; @S3]." in body
    assert "![Debt](figures/F1.png)" in body and "See [@S2]." in body
    # A line of dashes in the text cannot open a second YAML block.
    assert "\n---\n" not in body and "\n***\n" in body
    assert "## Notes\n\n- Coverage is a \\*sample\\*." in body
    assert body.rstrip().endswith("## References\n\n::: {#refs}\n:::")
    plain = render_qmd(artifact("No sources."), references=False)
    assert "bibliography" not in plain and "## References" not in plain
    assert "## Notes" not in plain


@pytest.mark.parametrize(
    ("markdown", "problem"),
    [
        ("", "no text"),
        ("x" * 1001, "longer than 1000"),
        ("---\nfilters: [evil.lua]\n---\nText", "YAML header"),
        ("Text\n\n```{python}\nimport os\n```", "code cells"),
        ("Text\n\n   ~~~ {r}\n1\n~~~", "code cells"),
        ("Total is `{python} 1 + 1`.", "inline code that runs"),
        ("{{< include /etc/passwd >}}", "shortcodes"),
        ("`<script>x</script>`{=html}", "raw markup"),
        ("Claim [S1] and [S7].", "unknown: S7"),
        ("![Debt](F2)", "only images"),
        ("![x](https://example.com/p.png)", "only images"),
        ("![x](/home/user/.ssh/key.png)", "only images"),
    ],
)
def test_text_that_could_run_code_or_cite_nothing_is_refused(markdown, problem):
    found = artifact_problem(
        "Title", markdown, evidence_ids=["S1"], figure_ids=["F1"], max_chars=1000
    )
    assert found is not None and problem in found


def test_plain_cited_markdown_is_accepted():
    text = "## Summary\n\nApproved [S1].\n\n```python\nprint('shown, not run')\n```\n\n![Debt](F1)"
    check = {"evidence_ids": ["S1"], "figure_ids": ["F1"], "max_chars": 1000}
    assert artifact_problem("Title", text, **check) is None
    assert "title" in str(artifact_problem("  ", text, **check))


def test_references_become_a_csl_bibliography():
    entry = csl_reference(reference())
    assert entry == {
        "id": "S1",
        "type": "webpage",
        "title": "New [library] # Injected heading",
        "URL": "https://example.com/a_(b)",
        "container-title": "example.com",
        "accessed": {"date-parts": [[2026, 1, 2]]},
        "author": [{"literal": "Ana Writer"}],
        "issued": {"date-parts": [[2026, 1, 2]]},
        "note": "feed summary. Only the feed summary was retrieved.",
    }
    bare = csl_reference(reference(author=None, published_at=None, limitations=()))
    assert "author" not in bare and "issued" not in bare
    assert bare["note"] == "feed summary."


def test_saving_writes_the_document_its_references_and_its_figures(tmp_path):
    folder = tmp_path / "nested" / "out"
    kept = artifact_from_answer("Check the\nlibrary news", result(), now=WHEN)
    assert kept.id == "A1" and kept.title == "Check the library news"
    assert kept.notes == ("Only the feed summary was retrieved.",)
    extra = [reference("S9", title="Never cited")]
    (path,) = save_artifacts(
        folder, [kept], [*result().references, *extra], [figure(), figure("F2")]
    )
    assert path == folder / "A1-check-the-library-news.qmd"
    assert artifact_filename(artifact(title="???")) == "A1.qmd"
    text = path.read_text(encoding="utf-8")
    assert "approved** [@S1]" in text and "![Debt](figures/F1.png)" in text
    # Only what the artifact cites or places is written; a figure cites its data.
    listed = json.loads((folder / "references.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in listed] == ["S1", "S2"]
    assert sorted(p.name for p in (folder / "figures").iterdir()) == [
        "F1.json",
        "F1.png",
    ]
    assert (folder / "figures" / "F1.png").read_bytes().startswith(b"\x89PNG")
    recipe = (folder / "figures" / "F1.json").read_text(encoding="utf-8")
    assert Figure.model_validate_json(recipe) == figure()

    # Saving a revision replaces the files, including after a new title.
    revised = kept.model_copy(
        update={"title": "Renamed", "markdown": "Short.", "version": 2}
    )
    (again,) = save_artifacts(folder, [revised], [], [])
    assert again.name == "A1-renamed.qmd" and not path.exists()
    assert "bibliography" not in again.read_text(encoding="utf-8")
    assert [p.name for p in folder.glob("*.qmd")] == ["A1-renamed.qmd"]


def test_saving_does_not_write_through_a_link(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("keep", encoding="utf-8")
    (tmp_path / "A1-library-news.qmd").symlink_to(target)
    save_artifacts(tmp_path, [artifact()], [reference()], [])
    assert target.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "A1-library-news.qmd").is_symlink()


def test_new_folders_are_never_reused(tmp_path, monkeypatch):
    first = new_artifact_folder(tmp_path, "Check: the NEWS!", now=WHEN)
    second = new_artifact_folder(tmp_path, "Check: the NEWS!", now=WHEN)
    assert first.name == "20260102-030405-check-the-news"
    assert second.name == "20260102-030405-check-the-news-2"
    assert new_artifact_folder(tmp_path, "???", now=WHEN).name == "20260102-030405"
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(InputError, match="artifacts directory"):
        new_artifact_folder(blocker / "inside", "task")
    with pytest.raises(InputError, match="artifacts directory"):
        save_artifacts(blocker / "inside", [artifact()], [], [])
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    default = new_artifact_folder(None, "task", now=WHEN)
    if sys.platform.startswith("linux"):
        assert default.parent == tmp_path / "data" / "sourcesift" / "artifacts"


def test_artifacts_directory_is_relative_to_the_config_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[artifacts]\ndirectory = "out"\n', encoding="utf-8")
    assert load_settings(config).artifacts.directory == tmp_path / "out"
    assert Settings().artifacts.directory is None


def test_cli_artifact_flag_saves_and_keeps_stdout_clean(monkeypatch, capsys, tmp_path):
    settings = Settings(artifacts={"directory": tmp_path})
    asked = {}

    def run_sync(self, request, **options):
        asked.update(options)
        return result()

    monkeypatch.setattr(cli.SourceSift, "run_sync", run_sync)
    monkeypatch.setattr(cli, "load_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sys, "argv", ["ssift", "ask", "Library news", "--artifact"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))
    cli.main()
    out = capsys.readouterr()
    # The flag also lets the model write the document itself.
    assert asked["artifacts"] is True
    (folder,) = tmp_path.iterdir()
    assert folder.name.endswith("-library-news")
    saved = folder / "A1-library-news.qmd"
    assert "approved** [@S1]" in saved.read_text(encoding="utf-8")
    assert (folder / "figures" / "F1.png").is_file()
    assert f"artifact saved to {saved}" in out.err
    assert "artifact saved" not in out.out and out.out.startswith("The library")
    assert "Figures:\n- F1: Debt (line chart) [S2]" in out.out

    # A document the model wrote is saved as written, not replaced by the answer.
    written = artifact("## Findings\n\nApproved [S1].", id="A1", title="Findings")
    monkeypatch.setattr(
        cli.SourceSift, "run_sync", lambda *a, **k: result(artifacts=(written,))
    )
    cli.main()
    out = capsys.readouterr()
    assert "Artifacts:\n- A1: Findings" in out.out
    assert sum(1 for _ in tmp_path.glob("*/A1-findings.qmd")) == 1


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto is not installed")
def test_quarto_renders_a_saved_artifact_without_running_anything(tmp_path):
    hostile = artifact(
        "Approved [S1].\n\n<script>document.title='x'</script>\n\n"
        "```python\nopen('RAN', 'w')\n```\n\n![Debt](F1)"
    )
    (path,) = save_artifacts(tmp_path, [hostile], result().references, [figure()])
    done = subprocess.run(
        ["quarto", "render", path.name, "--to", "html"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode()
    html = path.with_suffix(".html").read_text(encoding="utf-8")
    # The reference list is built from the bibliography; a title is only text.
    assert "Injected Heading" in html and "<h1>Injected" not in html
    assert "<script>document.title" not in html and "&lt;script&gt;" in html
    assert not (tmp_path / "RAN").exists()


def test_kept_answer_takes_its_own_heading_as_the_title():
    kept = artifact_from_answer(
        "Chart the debt.",
        result(answer="### Debt over the **past** year\n\nIt rose [S1]."),
    )
    assert (kept.title, kept.markdown) == ("Debt over the past year", "It rose [S1].")
    # Without a heading, or with nothing under it, the request names the artifact.
    plain = artifact_from_answer("Chart the debt.", result(answer="It rose [S1]."))
    assert (plain.title, plain.markdown) == ("Chart the debt.", "It rose [S1].")
    bare = artifact_from_answer("Chart the debt.", result(answer="## Only a heading"))
    assert (bare.title, bare.markdown) == ("Chart the debt.", "## Only a heading")
