"""The local web server: access rules, streamed turns, sources, and artifacts."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from sourcesift import AgentSettings, ArtifactsSettings, Settings, SourceSift, cli
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
            args = json.dumps(
                {"evidence_id": "S1", "kind": "bar", "x": "Story", "y": ["Points"]}
            )
            yield {
                0: DeltaToolCall(name="make_figure", json_args=args, tool_call_id="c2")
            }
        else:
            yield "**First** leads. [S1]\n\n![Points](F1)\n\n"
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
            artifacts=ArtifactsSettings(directory=str(tmp_path)),
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
    for path in ("/app.js", "/dom.js", "/app.css"):
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


def test_turn_streams_progress_then_a_result_with_a_figure(served):
    client, fetched = served
    session = client.post("/api/sessions", json={}, headers=AUTH).json()
    assert session["model"] == "example/test" and session["turns"] == []
    assert len(session["sources"]) == 32
    assert {"id", "name", "kind", "description", "enabled"} <= set(
        session["sources"][0]
    )
    base = f"/api/sessions/{session['id']}"

    assert client.post(f"{base}/artifacts", json={}, headers=AUTH).status_code == 400
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
        ("make_figure", "running"),
        ("make_figure", "done"),
    ]
    assert steps[0]["title"] == "Getting data from Hacker News"
    assert steps[1]["summary"] == "2 new items" and "[S1] First" in steps[1]["lines"]
    assert steps[2]["title"] == "Drawing a bar chart"
    assert steps[3]["summary"] == "Hacker News front page"
    # Drafts arrive already rendered, growing as the model writes.
    drafts = [event["html"] for event in stream if event["event"] == "draft"]
    assert "<strong>First</strong>" in drafts[0] and len(drafts[-1]) > len(drafts[0])
    turn = stream[-1]["turn"]
    assert turn["prompt"] == "front page"
    (figure,) = turn["result"]["figures"]
    assert figure["id"] == "F1" and figure["source_id"] == "hacker-news"
    assert figure["table"]["name"] == "Hacker News front page"
    assert figure["table"]["rows"][0][:2] == ["First", 10.0]
    # Markdown is rendered; raw HTML is escaped and only the figure is an image.
    html = turn["answer_html"]
    assert "<strong>First</strong>" in html and "<script>" not in html
    assert "&lt;script&gt;" in html and html.count("<img") == 1
    assert 'data-figure="F1"' in html and 'src="data:image/png;base64,iVBOR' in html
    assert (
        "http://t/p.png" not in html and '<span class="missing-figure">i</span>' in html
    )
    # While the answer is being written the figure is not yet part of the page.
    assert "<img" not in drafts[-1]
    assert len(fetched) == 1

    # The conversation survives a page reload, and an answer can be kept.
    again = client.get(base, headers=AUTH).json()
    assert again["id"] == session["id"] and len(again["turns"]) == 1
    assert [s["state"] for s in turn["result"]["steps"]] == ["done", "done"]
    assert (
        client.post(f"{base}/artifacts", json={"turn": 5}, headers=AUTH).status_code
        == 400
    )
    saved = client.post(f"{base}/artifacts", json={"turn": 0}, headers=AUTH).json()
    assert saved["id"] == "A1" and saved["title"] == "front page"
    path = Path(saved["path"])
    text = path.read_text(encoding="utf-8")
    assert "**First** leads. [@S1]" in text and "![Points](figures/F1.png)" in text
    assert (path.parent / "figures" / "F1.png").is_file()
    assert (path.parent / "references.json").is_file()
    large = client.post(f"{base}/turns", content=b"x" * 1_100_000, headers=AUTH)
    assert large.status_code == 403


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
        assert stream[-1]["turn"]["result"]["figures"] == []
    other = client.post("/api/sessions", json={}, headers=AUTH).json()
    assert all(source["enabled"] for source in other["sources"])


def test_the_page_loads_nothing_from_other_hosts(served):
    client, _ = served
    policy = client.get("/").headers["content-security-policy"]
    assert "script-src 'self';" in policy and "connect-src 'self';" in policy
    assert "img-src 'self' data: blob:;" in policy and "https://" not in policy
    assert client.get("/api/radar", headers=AUTH).status_code == 404
    assert client.get("/vendor/plotly.min.js").status_code == 404


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
