"""Typed data sources and widgets through the real agent loop, offline."""

import json
from contextlib import asynccontextmanager

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from sourcesift import (
    AgentSettings,
    Chart,
    ConfigurationError,
    Record,
    Result,
    Settings,
    SourceResult,
    SourceSift,
    SourcesSettings,
    Stats,
    StatView,
    cli,
    source,
    widget,
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


def test_model_chooses_a_widget_and_the_application_draws_it(monkeypatch, capsys):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            sent = payload(messages)
            treasury = next(s for s in sent["catalog"] if s["id"] == "us-treasury")
            assert treasury["returns"] == ["TimeSeries", "Stats", "Table"]
            assert set(treasury["params"]["properties"]) == {"dataset", "days"}
            assert "params" not in next(s for s in sent["catalog"] if s["id"] == "npr")
            assert [w["id"] for w in sent["widgets"]] == [
                "line-chart",
                "table",
                "stats",
                "map",
            ]
            assert sent["widgets"][0]["accepts"] == "TimeSeries"
            assert "log_scale" in sent["widgets"][0]["options"]["properties"]
            assert "show(evidence_id, widget, options)" in info.instructions
            return tools(QUERY)
        if step == 2:
            return tools(
                (
                    "show",
                    {
                        "evidence_id": "S1",
                        "widget": "line-chart",
                        "options": {"title": "Debt"},
                    },
                ),
                ("show", {"evidence_id": "S1", "widget": "stats"}),
            )
        return ModelResponse(parts=[TextPart("Debt is $38.0 trillion. [S1]")])

    app = configure(monkeypatch, respond)
    result = app.run_sync("chart the national debt")
    chart, figures = result.blocks
    assert chart.widget == "line-chart" and isinstance(chart.view, Chart)
    assert chart.view.title == "Debt" and chart.evidence_ids == ("S1",)
    assert [p.value for p in chart.view.series[0].points] == [
        38000000000100.5,
        38000000000300.5,
    ]
    assert isinstance(figures.view, StatView) and figures.view.items[0].change == 200.0
    assert result.references[0].id == "S1" and result.http_requests == 1
    assert not any("visual" in note for note in result.limitations)
    # The whole result, visuals included, survives a JSON round trip.
    assert Result.model_validate(result.model_dump(mode="json")) == result
    text = cli.render_result(result, "plain")
    assert "Visuals:\n- line-chart: Debt [S1]\n- stats: US public debt as of" in text


def test_uncited_visual_is_omitted_and_noted(monkeypatch):
    step = 0
    rates = {"source_id": "us-treasury", "params": {"dataset": "interest-rates"}}

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return tools(QUERY, ("query_source", rates))
        if step == 2:
            return tools(("show", {"evidence_id": "S2", "widget": "table"}))
        return ModelResponse(parts=[TextPart("Debt is $38.0 trillion. [S1]")])

    result = configure(monkeypatch, respond).run_sync("debt and rates")
    # The answer never cites the table's evidence, so nothing backs the visual.
    assert result.blocks == () and [r.id for r in result.references] == ["S1"]
    assert (
        "A visual was omitted because the answer did not cite its evidence."
        in result.limitations
    )


@pytest.mark.asyncio
async def test_follow_up_shows_earlier_data_without_a_new_request(monkeypatch):
    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return tools(QUERY)
        if step == 2:
            return ModelResponse(parts=[TextPart("Debt is $38.0 trillion. [S1]")])
        if step == 3:
            return tools(("show", {"evidence_id": "S1", "widget": "stats"}))
        return ModelResponse(parts=[TextPart("Shown as figures. [S1]")])

    session = configure(monkeypatch, respond).session()
    first = await session.run("what is the national debt")
    assert first.blocks == () and first.http_requests == 1
    second = await session.run("show that as figures")
    (block,) = second.blocks
    assert isinstance(block.view, StatView) and second.http_requests == 0
    session.reset()
    assert session._state.datasets == {}


def test_extensions_register_sources_and_widgets_in_python(monkeypatch):
    class Params(BaseModel):  # a plain pydantic model is enough
        metric: str

    @source(
        id="my-metrics",
        name="My Metrics",
        website="https://x.test/",
        description="Team metrics.",
        params=Params,
        returns=(Stats,),
    )
    async def my_metrics(params, context):
        fetched = await context.get("https://x.test/api")
        data = Stats(name=params.metric, items=({"label": "Open", "value": 7},))
        return SourceResult(
            [Record("Metrics", fetched.url, "Open: 7", fetched)], (data,)
        )

    @widget(id="big-number", description="One figure.", accepts=Stats)
    def big_number(data, options):
        return StatView(title=data.name.upper(), items=data.items[:1])

    step = 0

    async def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            sent = payload(messages)
            assert sent["catalog"][-1]["id"] == "my-metrics"
            assert sent["widgets"][-1]["id"] == "big-number"
            return tools(
                (
                    "query_source",
                    {"source_id": "my-metrics", "params": {"metric": "bugs"}},
                )
            )
        if step == 2:
            return tools(("show", {"evidence_id": "S1", "widget": "big-number"}))
        return ModelResponse(parts=[TextPart("Seven open. [S1]")])

    app = configure(monkeypatch, respond)
    app.register(my_metrics)
    app.register(big_number)
    (block,) = app.run_sync("how many bugs").blocks
    assert block.source_id == "my-metrics" and block.view.title == "BUGS"
    assert block.params == {"metric": "bugs"}

    for item in (my_metrics, big_number):
        with pytest.raises(ConfigurationError, match="unique"):
            app.register(item)
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
