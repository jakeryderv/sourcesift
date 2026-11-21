"""The local web server: access rules, streamed turns, sources, reports, radar."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from sourcesift import AgentSettings, ReportsSettings, Settings, SourceSift, cli
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page
from sourcesift.web.server import create_app, render_markdown

TOKEN = "launch-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
HITS = {
    "hits": [
        {"objectID": "1", "title": "First", "points": 10, "num_comments": 2},
        {"objectID": "2", "title": "Second", "points": 5, "num_comments": 1},
    ]
}


@pytest.fixture
def served(monkeypatch, tmp_path):
    """A client for one launch, a scripted model, and a counter of data requests."""
    fetched = []

    async def respond(messages, info):
        calls = sum(isinstance(m, ModelResponse) for m in messages)
        if calls == 0:
            args = json.dumps({"source_id": "hacker-news", "params": {}})
            yield {
                0: DeltaToolCall(name="query_source", json_args=args, tool_call_id="c1")
            }
        elif calls == 1:
            args = json.dumps({"evidence_id": "S1", "widget": "table"})
            yield {0: DeltaToolCall(name="show", json_args=args, tool_call_id="c2")}
        else:
            yield "**First** leads. [S1]\n\n"
            yield "<script>x</script> ![i](http://t/p.png)"

    @asynccontextmanager
    async def model(settings):
        yield FunctionModel(stream_function=respond)

    async def get(self, url):
        fetched.append(url)
        self.requests += 1
        return Page(url, url, json.dumps(HITS).encode(), "application/json")

    monkeypatch.setattr(runtime, "_openrouter_model", model)
    monkeypatch.setattr(Fetcher, "get", get)
    core = SourceSift(
        Settings(
            agent=AgentSettings(model="example/test", api_key="test-key"),
            reports=ReportsSettings(directory=str(tmp_path)),
        )
    )
    app = create_app(core, token=TOKEN, hosts=("testserver",))
    with TestClient(app) as client:
        yield client, fetched


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_only_this_launchs_page_can_use_the_api(served):
    client, _ = served
    page = client.get("/")
    assert page.status_code == 200 and "<title>SourceSift</title>" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    for path in ("/app.js", "/figure.js", "/app.css"):
        assert client.get(path).status_code == 200
    # Another site's name resolving to this machine is refused, even for the page.
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/sessions", json={}).status_code == 403
    wrong = {"Authorization": "Bearer nope"}
    assert client.post("/api/sessions", json={}, headers=wrong).status_code == 403
    cross = AUTH | {"Origin": "https://evil.example"}
    assert client.post("/api/sessions", json={}, headers=cross).status_code == 403
    same = AUTH | {"Origin": "http://testserver"}
    assert client.post("/api/sessions", json={}, headers=same).status_code == 200
    big = client.post("/api/sessions", content=b"x" * 1_100_000, headers=AUTH)
    assert big.status_code == 403
    assert client.post("/api/sessions", content=b"[1]", headers=AUTH).status_code == 400
    assert client.get("/api/sessions/unknown", headers=AUTH).status_code == 400


def test_turn_streams_progress_then_a_result_with_visuals(served):
    client, fetched = served
    session = client.post("/api/sessions", json={}, headers=AUTH).json()
    assert session["model"] == "example/test" and session["turns"] == []
    assert len(session["sources"]) == 32
    assert {"id", "name", "kind", "description", "enabled"} <= set(
        session["sources"][0]
    )
    base = f"/api/sessions/{session['id']}"

    assert client.post(f"{base}/report", json={}, headers=AUTH).status_code == 400
    assert (
        client.post(f"{base}/turns", json={"prompt": 3}, headers=AUTH).status_code
        == 400
    )
    stream = events(
        client.post(f"{base}/turns", json={"prompt": "front page"}, headers=AUTH)
    )
    kinds = [event["event"] for event in stream]
    assert kinds[0] == "status" and kinds[-1] == "result" and "draft" in kinds
    # Each tool call is reported when it starts and when it finishes.
    steps = [event["step"] for event in stream if event["event"] == "step"]
    assert [(s["tool"], s["state"]) for s in steps] == [
        ("query_source", "running"),
        ("query_source", "done"),
        ("show", "running"),
        ("show", "done"),
    ]
    assert steps[0]["title"] == "Getting data from Hacker News"
    assert steps[1]["summary"] == "2 new items" and "[S1] First" in steps[1]["lines"]
    assert steps[3]["summary"] == "Hacker News front page"
    # Drafts arrive already rendered, growing as the model writes.
    drafts = [event["html"] for event in stream if event["event"] == "draft"]
    assert "<strong>First</strong>" in drafts[0] and len(drafts[-1]) > len(drafts[0])
    turn = stream[-1]["turn"]
    assert turn["prompt"] == "front page"
    (block,) = turn["result"]["blocks"]
    assert block["widget"] == "table" and block["source_id"] == "hacker-news"
    assert block["table"]["name"] == "Hacker News front page"
    assert block["view"]["rows"][0][:2] == ["First", 10.0]
    # Markdown is rendered; raw HTML is escaped and images are not loaded.
    html = turn["answer_html"]
    assert "<strong>First</strong>" in html and "<script>" not in html
    assert "&lt;script&gt;" in html and "<img" not in html
    assert len(fetched) == 1

    # The conversation survives a page reload and can be saved as a report.
    again = client.get(base, headers=AUTH).json()
    assert again["id"] == session["id"] and len(again["turns"]) == 1
    assert [s["state"] for s in turn["result"]["steps"]] == ["done", "done"]
    assert (
        client.post(f"{base}/report", json={"turn": 5}, headers=AUTH).status_code == 400
    )
    saved = client.post(f"{base}/report", json={"turn": 0}, headers=AUTH).json()["path"]
    assert "front page" in Path(saved).read_text(encoding="utf-8")


def test_sources_can_be_limited_for_one_conversation(served):
    client, _ = served
    session = client.post("/api/sessions", json={}, headers=AUTH).json()
    base = f"/api/sessions/{session['id']}/sources"
    changed = client.put(base, json={"enabled": ["npr"]}, headers=AUTH).json()
    assert [s["id"] for s in changed["sources"] if s["enabled"]] == ["npr"]
    assert client.get(base, headers=AUTH).json() == changed
    assert (
        client.put(base, json={"enabled": ["missing"]}, headers=AUTH).status_code == 400
    )
    assert client.put(base, json={"enabled": "npr"}, headers=AUTH).status_code == 400
    # With Hacker News switched off, the model's query finds no source.
    stream = events(
        client.post(
            f"/api/sessions/{session['id']}/turns", json={"prompt": "hn"}, headers=AUTH
        )
    )
    assert stream[-1]["event"] in {"result", "error"}
    if stream[-1]["event"] == "result":
        assert stream[-1]["turn"]["result"]["blocks"] == []
    other = client.post("/api/sessions", json={}, headers=AUTH).json()
    assert all(source["enabled"] for source in other["sources"])


def test_radar_address_is_looked_up_by_the_server_and_cached(monkeypatch, served):
    client, _ = served
    seen = []
    frames = {"radar": {"past": [{"path": "/v2/radar/old"}, {"path": "/v2/radar/ab1"}]}}

    async def get(self, url, *, robots=True):
        seen.append(url)
        assert robots is False
        return Page(url, url, json.dumps(frames).encode(), "application/json")

    monkeypatch.setattr(Fetcher, "get", get)
    assert client.get("/api/radar").status_code == 403
    # The newest frame, as a tile address the map fills in itself.
    expected = "https://tilecache.rainviewer.com/v2/radar/ab1/256/{z}/{x}/{y}/2/1_1.png"
    assert client.get("/api/radar", headers=AUTH).json() == {"tiles": expected}
    assert client.get("/api/radar", headers=AUTH).json() == {"tiles": expected}
    assert seen == ["https://api.rainviewer.com/public/weather-maps.json"]

    # The page may load map and radar tiles from the named hosts and nowhere else.
    policy = client.get("/").headers["content-security-policy"]
    assert "script-src 'self';" in policy and "worker-src blob:" in policy
    assert "https://tilecache.rainviewer.com" in policy
    assert "https://*.basemaps.cartocdn.com" in policy
    for path in ("/figure.js", "/dom.js", "/vendor/plotly.min.js"):
        assert client.get(path).status_code == 200
    assert client.get("/map.js").status_code == 404


def test_radar_failure_is_reported_not_guessed(monkeypatch, served):
    client, _ = served

    async def get(self, url, *, robots=True):
        body = {"radar": {"past": [{"path": "https://evil.test/x"}]}}
        return Page(url, url, json.dumps(body).encode(), "application/json")

    monkeypatch.setattr(Fetcher, "get", get)
    reply = client.get("/api/radar", headers=AUTH)
    assert reply.status_code == 400 and "unavailable" in reply.json()["error"]


def test_markdown_tables_render_and_links_keep_safe_schemes():
    html = render_markdown(
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n[x](javascript:alert(1)) [y](https://e.com)"
    )
    assert "<table>" in html and 'href="https://e.com"' in html
    assert "javascript:" not in html.replace("[x](javascript:alert(1))", "")


def test_web_command_reports_a_busy_port(monkeypatch, capsys):
    import socket

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        with pytest.raises(SystemExit) as stopped:
            port = str(taken.getsockname()[1])
            monkeypatch.setattr(
                sys, "argv", ["ssift", "web", "--port", port, "--no-browser"]
            )
            cli.main()
    assert stopped.value.code != 0
    assert "is not available" in capsys.readouterr().err
