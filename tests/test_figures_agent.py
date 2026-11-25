"""Data sources, figures, and artifacts through the real agent loop, offline."""

import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from sourcesift import (
    AgentSettings,
    ConfigurationError,
    InputError,
    Record,
    Result,
    Settings,
    SourceResult,
    SourceSift,
    SourcesSettings,
    Table,
    cli,
    render_png,
    source,
)
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page

DEBT = {
    "data": [
        {"record_date": "2026-10-14", "tot_pub_debt_out_amt": "38000000000300.50"},
        {"record_date": "2026-10-13", "tot_pub_debt_out_amt": "38000000000100.50"},
    ]
}


def configure(monkeypatch, respond, settings=None):
    @asynccontextmanager
    async def model(settings):
        yield FunctionModel(respond)

    async def get(self, url):
        assert url.startswith(
            ("https://api.fiscaldata.treasury.gov/", "https://x.test/")
        )
        self.requests += 1
        return Page(url, url, json.dumps(DEBT).encode(), "application/json")

    monkeypatch.setattr(runtime, "_openrouter_model", model)
    monkeypatch.setattr(Fetcher, "get", get)
    return SourceSift(
        settings
        or Settings(agent=AgentSettings(model="example/test", api_key="test-key"))
    )


def payload(messages):
    prompts = [
        part.content
        for message in messages
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    return json.loads(prompts[-1])


def tools(*calls):
    return ModelResponse(
        parts=[
            ToolCallPart(name, args, f"call-{i}")
            for i, (name, args) in enumerate(calls)
        ]
    )


QUERY = ("query_source", {"source_id": "us-treasury", "params": {"dataset": "debt"}})


CHART = (
    "make_figure",
    {
        "evidence_id": "S1",
        "kind": "line",
        "x": "Date",
        "y": ["Total public debt outstanding"],
        "title": "Debt",
    },
)


def test_model_names_columns_and_the_application_draws_the_figure(monkeypatch, capsys):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            sent = payload(messages)
            treasury = next(s for s in sent["catalog"] if s["id"] == "us-treasury")
            assert set(treasury["params"]["properties"]) == {"dataset", "days"}
            assert "params" not in next(s for s in sent["catalog"] if s["id"] == "npr")
            assert sent["figures"] == [] and "widgets" not in sent
            names = {tool.name for tool in info.function_tools}
            # One-off requests get no document tool unless it is asked for.
            assert names == {
                "research",
                "query_source",
                "make_figure",
                "read_table",
                "read_article",
            }
            assert "make_figure(evidence_id, kind, x, y, ...)" in info.instructions
            assert "write_artifact" not in info.instructions
            return tools(QUERY)
        if step == 2:
            return tools(CHART)
        if step == 3:
            # A figure that was never made cannot be placed.
            return ModelResponse(parts=[TextPart("Debt [S1].\n\n![Debt](F7)")])
        return ModelResponse(parts=[TextPart("Debt is $38.0 trillion.\n\n![Debt](F1)")])

    app = configure(monkeypatch, respond)
    result = app.run_sync("chart the national debt")
    assert step == 4
    (chart,) = result.figures
    assert chart.id == "F1" and chart.title == "Debt" and chart.kind == "line"
    assert chart.evidence_ids == ("S1",) and chart.source_id == "us-treasury"
    assert chart.table.rows[0][0] == "2026-10-13"
    assert render_png(chart).startswith(b"\x89PNG")
    # Placing the figure cites the evidence its rows came with.
    assert result.references[0].id == "S1" and result.http_requests == 1
    assert result.artifacts == ()
    # The whole result, figures included, survives a JSON round trip.
    assert Result.model_validate(result.model_dump(mode="json")) == result
    text = cli.render_result(result, "plain")
    assert "Figures:\n- F1: Debt (line chart) [S1]" in text


@pytest.mark.asyncio
async def test_rows_are_summarized_for_a_chart_and_read_for_a_table(monkeypatch):
    replies = []

    def call(name, args):
        # Each call needs its own ID to be its own step.
        return ModelResponse(parts=[ToolCallPart(name, args, f"call-{len(replies)}")])

    async def respond(messages, info):
        last = messages[-1].parts[0]
        if last.part_kind == "tool-return":
            replies.append(last.content)
        if len(replies) == 0:
            return call(*QUERY)
        if len(replies) == 1:
            monthly = CHART[1] | {"kind": "bar", "period": "month", "title": "Monthly"}
            return call("make_figure", monthly)
        if len(replies) == 2:
            return call("read_table", {"evidence_id": "S1", "period": "month"})
        if len(replies) == 3:
            return call("read_table", {"evidence_id": "S1", "period": "decade"})
        return ModelResponse(parts=[TextPart("Month-end debt [S1].\n\n![Monthly](F1)")])

    session = configure(monkeypatch, respond).session()
    result = await session.run("chart month-end debt and list the values")
    (chart,) = result.figures
    # One bar per month, drawn from the last record in it and dated as recorded.
    assert chart.table.name.endswith("(last per month)")
    assert chart.table.rows == (("2026-10-14", 38000000000300.5),)
    read = replies[2]
    assert read["total_rows"] == 1 and read["cite"] == "[S1]"
    assert read["rows"][0][0] == "2026-10-14" and len(read["columns"]) > 1
    assert "period must be one of" in replies[3]["error"]
    assert [(step.tool, step.state, step.summary) for step in result.steps][2:] == [
        ("read_table", "done", "1 row"),
        (
            "read_table",
            "failed",
            "period must be one of: day, week, month, quarter, year.",
        ),
    ]

    # A later turn is told which tables it still holds, so it need not query again.
    async def follow_up(messages, info):
        kept = payload(messages)["chartable"]
        assert kept[0]["evidence_id"] == "S1" and kept[0]["tables"][0]["rows"] == 2
        return ModelResponse(parts=[TextPart("Still [S1].")])

    monkeypatch.setattr(
        runtime, "_openrouter_model", asynccontextmanager(_yield(follow_up))
    )
    assert (await session.run("and again?")).http_requests == 0


def _yield(respond):
    async def model(settings):
        yield FunctionModel(respond)

    return model


def test_shape_selects_summarizes_and_ranks_rows():
    from sourcesift import Column
    from sourcesift.data import shape

    table = Table(
        name="Sales",
        columns=(
            Column(name="Day", kind="time"),
            Column(name="Units"),
            Column(name="Region"),
        ),
        rows=(
            ("2026-02-02", 9, "east"),
            ("2026-01-05", 1, "east"),
            ("2026-01-30", 2, "east"),
            ("2026-01-30", 4, "west"),
            ("2026-03-02", None, "east"),
        ),
    )
    assert shape(table) is table
    monthly = shape(table, columns=("Day", "Units"), period="month", combine="sum")
    assert monthly.name == "Sales (sum per month)"
    assert monthly.rows == (
        ("2026-01-01", 7.0),
        ("2026-02-01", 9.0),
        ("2026-03-01", None),
    )
    # A text column splits each period. First and last keep a recorded row
    # whole, skipping one with no number in it.
    split = shape(table, period="quarter", combine="last", since="2026-01-10")
    assert split.rows == (("2026-02-02", 9, "east"), ("2026-01-30", 4, "west"))
    assert shape(table, columns=("Region", "Units"), top=2).rows == (
        ("east", 9),
        ("west", 4),
    )
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        ({"period": "hour"}, "period must be"),
        ({"combine": "median"}, "combine must be"),
        ({"columns": ("Units",), "period": "month"}, "time column"),
        ({"columns": ("Region",), "top": 1}, "number column"),
        ({"since": "next week"}, "ISO date"),
        ({"since": "2030-01-01"}, "No rows"),
        ({"columns": ("Missing",)}, "no column"),
        ({"top": -1}, "negative"),
    )
    for options, problem in cases:
        with pytest.raises(ValueError, match=problem):
            shape(table, **options)


def test_a_figure_the_answer_forgot_is_placed_after_it(monkeypatch):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return tools(QUERY)
        if step == 2:
            return tools(CHART)
        return ModelResponse(parts=[TextPart("Debt is $38.0 trillion. [S1]")])

    result = configure(monkeypatch, respond).run_sync("chart the debt")
    assert result.answer == "Debt is $38.0 trillion. [S1]\n\n![Debt](F1)"
    assert [figure.id for figure in result.figures] == ["F1"]


@pytest.mark.asyncio
async def test_follow_up_charts_earlier_data_and_places_earlier_figures(monkeypatch):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return tools(QUERY)
        if step == 2:
            return ModelResponse(parts=[TextPart("Debt is $38.0 trillion. [S1]")])
        if step == 3:
            assert "write_artifact" in {tool.name for tool in info.function_tools}
            return tools(CHART)
        if step == 4:
            return ModelResponse(parts=[TextPart("Here it is.\n\n![Debt](F1)")])
        assert payload(messages)["figures"] == [{"id": "F1", "title": "Debt"}]
        return ModelResponse(parts=[TextPart("Again: ![Debt](F1)")])

    session = configure(monkeypatch, respond).session()
    first = await session.run("what is the national debt")
    assert first.figures == () and first.http_requests == 1
    second = await session.run("chart that")
    assert [f.id for f in second.figures] == ["F1"] and second.http_requests == 0
    third = await session.run("show the chart again")
    assert third.figures == second.figures == session.figures
    assert [r.id for r in third.references] == ["S1"]
    session.reset()
    assert session._state.datasets == {} and session.figures == ()


REPORT = "## Debt\n\nDebt reached $38.0 trillion [S1].\n\n![Debt](F1)"


@pytest.mark.asyncio
async def test_model_writes_and_revises_an_artifact(monkeypatch, tmp_path):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            assert "call write_artifact(title," in info.instructions
            return tools(QUERY)
        if step == 2:
            return tools(CHART)
        if step == 3:
            # Text that would run code is refused and the model is told why.
            bad = {"title": "Debt", "markdown": "```{python}\n1\n```"}
            return tools(("write_artifact", bad))
        if step == 4:
            refused = messages[-1].parts[0].content
            assert "cannot contain code cells" in refused["error"]
            return tools(
                ("write_artifact", {"title": " Debt  report ", "markdown": REPORT})
            )
        if step == 5:
            # The artifact carries the citations, so the answer need not repeat them.
            return ModelResponse(parts=[TextPart("I wrote a report on the debt.")])
        if step == 6:
            sent = payload(messages)["artifacts"]
            assert sent == [{"id": "A1", "title": "Debt report", "version": 1}]
            missing = {"title": "x", "markdown": "y", "artifact_id": "A9"}
            return tools(("write_artifact", missing))
        if step == 7:
            assert "There is no artifact A9" in messages[-1].parts[0].content["error"]
            revised = {
                "title": "Debt brief",
                "markdown": "Short [S1].",
                "artifact_id": "A1",
            }
            return tools(("write_artifact", revised))
        return ModelResponse(parts=[TextPart("Shortened it.")])

    settings = Settings(
        agent=AgentSettings(model="example/test", api_key="test-key"),
        artifacts={"directory": tmp_path / "artifacts"},
        sessions={"directory": tmp_path / "sessions"},
    )
    session = configure(monkeypatch, respond, settings).session(save=True)
    first = await session.run("write a report on the national debt")
    (written,) = first.artifacts
    assert written.id == "A1" and written.title == "Debt report"
    assert written.markdown == REPORT and written.version == 1
    # The application's coverage notes for the turn travel with the document.
    assert written.notes == first.limitations and written.notes
    # The result's references and figures cover the artifact as well as the answer.
    assert [r.id for r in first.references] == ["S1"]
    assert [f.id for f in first.figures] == ["F1"]
    assert first.answer == "I wrote a report on the debt."
    assert first.steps[-1].title == "Writing an artifact"
    assert first.steps[-1].lines == ("Debt report",)
    assert (first.steps[-1].state, first.steps[-1].summary) == ("done", "Debt report")

    second = await session.run("make it shorter")
    (revised,) = second.artifacts
    assert revised.id == "A1" and revised.version == 2
    assert revised.title == "Debt brief" and session.artifacts == (revised,)
    assert second.steps[-1].title == "Revising an artifact"

    # An answer can be kept as a second artifact, and everything saves together.
    kept = session.keep_answer(0)
    assert kept.id == "A2" and kept.markdown == first.answer
    with pytest.raises(InputError, match="no such answer"):
        session.keep_answer(5)
    paths = session.save_artifacts(tmp_path / "out")
    assert [path.name for path in paths] == [
        "A1-debt-brief.qmd",
        "A2-write-a-report-on-the-national-debt.qmd",
    ]
    assert "Short [@S1]." in paths[0].read_text(encoding="utf-8")
    assert (tmp_path / "out" / "references.json").is_file()
    # A saved conversation keeps its artifacts as files in its own folder.
    assert session.save_artifacts()[0].parent == session.artifacts_path
    assert session.artifacts_path is not None
    assert sorted(p.name for p in session.artifacts_path.glob("*.qmd")) == [
        "A1-debt-brief.qmd",
        "A2-write-a-report-on-the-national-debt.qmd",
    ]
    unsaved = configure(monkeypatch, respond, settings).session()
    unsaved._state.artifacts = dict(session._state.artifacts)
    assert unsaved.save_artifacts()[0].parent.parent == tmp_path / "artifacts"

    # A continued conversation keeps its artifacts and figures.
    resumed = SourceSift(settings).session(resume=True)
    assert resumed.artifacts == session.artifacts
    assert resumed.figures == session.figures
    resumed.reset()
    assert resumed.artifacts == ()
    with pytest.raises(InputError, match="no artifact to save"):
        resumed.save_artifacts()


def test_one_off_request_writes_an_artifact_only_when_asked(monkeypatch):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            assert "write_artifact" in {tool.name for tool in info.function_tools}
            return tools(QUERY)
        if step == 2:
            return tools(("write_artifact", {"title": "Debt", "markdown": "Up [S1]."}))
        return ModelResponse(parts=[TextPart("Done.")])

    result = configure(monkeypatch, respond).run_sync("report", artifacts=True)
    assert [(a.id, a.markdown) for a in result.artifacts] == [("A1", "Up [S1].")]
    assert [r.id for r in result.references] == ["S1"]


def test_extensions_register_sources_in_python(monkeypatch):
    class Params(BaseModel):  # a plain pydantic model is enough
        metric: str

    @source(
        id="my-metrics",
        name="My Metrics",
        website="https://x.test/",
        description="Team metrics.",
        params=Params,
    )
    async def my_metrics(params, context):
        fetched = await context.get("https://x.test/api")
        data = Table(
            name=params.metric,
            columns=({"name": "Team"}, {"name": "Open"}),
            rows=(("web", 7), ("api", 3)),
        )
        return SourceResult(
            [Record("Metrics", fetched.url, "Open: 7", fetched)], (data,)
        )

    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            assert payload(messages)["catalog"][-1]["id"] == "my-metrics"
            return tools(
                (
                    "query_source",
                    {"source_id": "my-metrics", "params": {"metric": "bugs"}},
                )
            )
        if step == 2:
            chart = {"evidence_id": "S1", "kind": "bar", "x": "Team", "y": ["Open"]}
            return tools(("make_figure", chart))
        return ModelResponse(parts=[TextPart("Seven open. [S1]\n\n![bugs](F1)")])

    app = configure(monkeypatch, respond)
    app.register(my_metrics)
    (figure,) = app.run_sync("how many bugs").figures
    assert figure.source_id == "my-metrics" and figure.title == "bugs"
    assert figure.table.rows == (("web", 7), ("api", 3))

    with pytest.raises(ConfigurationError, match="unique"):
        app.register(my_metrics)
    with pytest.raises(ConfigurationError, match="register"):
        app.register_source(my_metrics.source)
    # A live data source cannot be declared in configuration without its code.
    custom = my_metrics.source.model_copy(update={"id": "from-toml", "name": "T"})
    with pytest.raises(ConfigurationError, match="defined in Python"):
        SourceSift(
            Settings(
                agent=AgentSettings(model="example/test", api_key="k"),
                sources=SourcesSettings(custom=(custom,)),
            )
        )
