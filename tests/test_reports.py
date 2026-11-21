"""Reports are application-written renderings of a validated result."""

import io
import sys
from datetime import UTC, datetime

import pytest
from textual.widgets import Static, TextArea

from sourcesift import (
    InputError,
    Reference,
    Result,
    Settings,
    cli,
    load_settings,
    render_report,
    save_report,
)
from sourcesift.core.session import Session
from sourcesift.sources import SourceRegistry
from sourcesift.tui import ChatApp

WHEN = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def result(**changes):
    values = {
        "answer": "The library was **approved** [S1].",
        "model": "example/test",
        "limitations": ("Only the feed summary was retrieved.",),
        "references": (
            Reference(
                id="S1",
                title="New [library]\n# Injected heading",
                url="https://example.com/a_(b)",
                requested_url="https://example.com/feed",
                retrieved_from="https://example.com/feed",
                publisher="example.com",
                published_at=WHEN,
                retrieved_at=WHEN,
                kind="feed_summary",
                limitations=("Only the feed summary was retrieved.",),
            ),
        ),
        "selected_sources": ("example",),
    }
    return Result.model_validate(values | changes)


def test_report_contains_request_answer_references_and_notes():
    text = render_report("Check the\nlibrary news", result(), generated_at=WHEN)
    assert text.startswith("# Check the library news\n")
    assert "- Generated: 2026-01-02 03:04 UTC" in text
    assert "- Model: example/test" in text and "- Sources read: example" in text
    assert "> Check the\n> library news" in text
    assert "## Answer\n\nThe library was **approved** [S1]." in text
    assert "<https://example.com/a_(b)>" in text
    assert "Published: 2026-01-02 03:04 UTC; updated: unknown" in text
    assert "## Notes\n\n- Only the feed summary was retrieved." in text
    # Retrieved titles cannot add headings or links to the document.
    assert "\n# Injected" not in text
    assert "New \\[library\\] \\# Injected heading" in text


TABLE = {
    "name": "Debt",
    "columns": [{"name": "Date", "kind": "time"}, {"name": "Total", "unit": "USD"}],
    "rows": [["2026-10-13", 38000000000100.5], ["2026-10-14", 38000000000300.5]],
}
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def block(widget, view, table=TABLE):
    return {
        "widget": widget,
        "evidence_ids": ["S1"],
        "source_id": "us-treasury",
        "options": {},
        "table": table,
        "view": view,
    }


def with_visuals(**changes):
    figure = {"type": "figure", "title": "Debt [chart]", "data": [{"type": "scatter"}]}
    items = [
        {"label": "Total", "value": 38000000000300.5, "unit": "USD", "change": 200.0},
        {"label": "Sky", "value": "Clear"},
        {"label": "Humidity", "value": 65, "unit": "%"},
    ]
    return result(
        blocks=(
            block("chart", figure),
            block("stats", {"type": "stat", "title": "Latest", "items": items}),
            block(
                "table",
                {"type": "table", "title": "Rows"}
                | {key: TABLE[key] for key in ("columns", "rows")},
            ),
        ),
        **changes,
    )


def test_report_writes_visuals_as_tables_lists_and_images():
    text = render_report("Chart the debt", with_visuals(), generated_at=WHEN)
    # Visuals follow the answer and come before the references.
    assert (
        text.index("## Answer") < text.index("## Visuals") < text.index("## References")
    )
    table = (
        "| Date | Total (USD) |\n| --- | ---: |\n"
        "| 2026-10-13 | 38,000,000,000,100.5 |\n| 2026-10-14 | 38,000,000,000,300.5 |"
    )
    # Without a picture, a chart is replaced by the rows it was drawn from.
    assert (
        "### Debt \\[chart\\]\n\n*The chart is not included in this report. It was "
        f"drawn from these rows.*\n\n{table}\n\nData from [S1]." in text
    )
    assert (
        "### Latest\n\n- **Total:** $38,000,000,000,300.5 (change: $200)\n"
        "- **Sky:** Clear\n- **Humidity:** 65%\n\nData from [S1]." in text
    )
    assert f"### Rows\n\n{table}\n\nData from [S1]." in text

    pictured = render_report(
        "Chart the debt", with_visuals(), generated_at=WHEN, images={0: "r-1.png"}
    )
    assert "![Debt \\[chart\\]](r-1.png)\n\nData from [S1]." in pictured
    assert "not included" not in pictured

    long = TABLE | {"rows": [[f"2026-01-{d:02}", d] for d in range(1, 32)] * 2}
    figure = {"type": "figure", "title": "", "data": [{"type": "bar"}]}
    many = render_report("x", result(blocks=(block("chart", figure, long),)))
    assert "### Visual\n\n" in many and "the first 30 of 62 rows below" in many
    assert many.count("| 2026-01-") == 30


def test_saved_report_keeps_chart_images_beside_it(tmp_path):
    images = {0: PNG, 1: PNG, 7: PNG, -1: PNG}
    path = save_report(
        "Chart the debt", with_visuals(), tmp_path, generated_at=WHEN, images=images
    )
    # Only a figure gets a picture; other positions are ignored.
    picture = tmp_path / f"{path.stem}-1.png"
    assert picture.read_bytes() == PNG
    assert {p.name for p in tmp_path.iterdir()} == {path.name, picture.name}
    assert f"]({picture.name})" in path.read_text(encoding="utf-8")
    again = save_report(
        "Chart the debt", with_visuals(), tmp_path, generated_at=WHEN, images=images
    )
    assert again.name == f"{path.stem}-2.md"
    assert (tmp_path / f"{path.stem}-2-1.png").is_file()

    # Something that is not a PNG, or is too large, is left out.
    for bad in (b"<svg onload=x>", PNG + b"0" * 4_000_000):
        plain = save_report("other", with_visuals(), tmp_path, images={0: bad})
        assert "not included" in plain.read_text(encoding="utf-8")
        assert not list(tmp_path.glob(f"{plain.stem}-*.png"))


def test_report_omits_empty_sections_and_shortens_long_titles():
    text = render_report(
        "word " * 40, result(references=(), limitations=(), selected_sources=())
    )
    assert "## References" not in text and "## Notes" not in text
    assert "Sources read" not in text
    assert len(text.splitlines()[0]) <= 82 and text.splitlines()[0].endswith("…")


def test_save_creates_directory_and_never_overwrites(tmp_path):
    folder = tmp_path / "nested" / "reports"
    first = save_report("Check: the NEWS!", result(), folder, generated_at=WHEN)
    second = save_report("Check: the NEWS!", result(), folder, generated_at=WHEN)
    assert first.name == "20260102-030405-check-the-news.md"
    assert second.name == "20260102-030405-check-the-news-2.md"
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert save_report("???", result(), folder, generated_at=WHEN).name == (
        "20260102-030405.md"
    )


def test_save_does_not_follow_an_existing_link(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("keep", encoding="utf-8")
    (tmp_path / "20260102-030405-task.md").symlink_to(target)
    path = save_report("task", result(), tmp_path, generated_at=WHEN)
    assert path.name == "20260102-030405-task-2.md"
    assert target.read_text(encoding="utf-8") == "keep"


def test_unwritable_directory_is_an_input_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(InputError, match="reports directory"):
        save_report("task", result(), blocker / "reports")


def test_default_directory_is_per_user(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = save_report("task", result(), generated_at=WHEN)
    if sys.platform.startswith("linux"):
        assert path.parent == tmp_path / "sourcesift" / "reports"


def test_reports_directory_is_relative_to_the_config_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[reports]\ndirectory = "out"\n', encoding="utf-8")
    assert load_settings(config).reports.directory == tmp_path / "out"
    assert Settings().reports.directory is None


def test_cli_report_flag_saves_and_keeps_stdout_clean(monkeypatch, capsys, tmp_path):
    settings = Settings(reports={"directory": tmp_path})
    monkeypatch.setattr(cli.SourceSift, "run_sync", lambda *a, **k: result())
    monkeypatch.setattr(cli, "load_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sys, "argv", ["ssift", "ask", "Library news", "--report"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))
    cli.main()
    out = capsys.readouterr()
    (saved,) = tmp_path.iterdir()
    assert saved.name.endswith("-library-news.md")
    assert "> Library news" in saved.read_text(encoding="utf-8")
    assert f"report saved to {saved}" in out.err
    assert "report saved" not in out.out and out.out.startswith("The library")


@pytest.mark.asyncio
async def test_chat_report_command(tmp_path):
    settings = Settings(
        agent={"model": "example/test", "api_key": "private-key"},
        reports={"directory": tmp_path},
    )
    session = Session(settings, SourceRegistry(()))
    app = ChatApp(session)
    async with app.run_test(size=(100, 24)) as pilot:
        editor = app.query_one("#prompt", TextArea)
        editor.load_text("/report")
        await pilot.press("escape", "enter")
        assert "Nothing to save yet" in str(app.query_one("#status", Static).content)
        assert not list(tmp_path.iterdir())
        session._turns.append(("Library news", result()))
        editor.load_text("/report")
        await pilot.press("escape", "enter")
        (saved,) = tmp_path.iterdir()
        assert "Report saved to" in str(app.query_one("#status", Static).content)
        assert "## References" in saved.read_text(encoding="utf-8")
