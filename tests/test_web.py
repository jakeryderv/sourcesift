"""The local web server: access rules, streamed turns, sources, and artifacts."""

import io
import json
import sys
import zipfile
from contextlib import asynccontextmanager

import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from starlette.testclient import TestClient

from sourcesift import AgentSettings, ArtifactsSettings, Settings, SourceSift, cli
from sourcesift import export as export_module
from sourcesift.agents import runtime
from sourcesift.core.config import SessionsSettings
from sourcesift.errors import InputError
from sourcesift.export import export_artifact, export_formats
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
            artifacts=ArtifactsSettings(directory=str(tmp_path / "artifacts")),
            sessions=SessionsSettings(directory=str(tmp_path / "sessions")),
        )
    )

    def launch(**options):
        app = create_app(core, token=TOKEN, hosts=("testserver",), **options)
        return TestClient(app)

    with launch() as client:
        client.launch, client.root = launch, tmp_path
        yield client, fetched


def ask(client, session, prompt="front page"):
    path = f"/api/sessions/{session['id']}/turns"
    return events(client.post(path, json={"prompt": prompt}, headers=AUTH))


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
    assert len(session["sources"]) == 33
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
    kept = client.post(f"{base}/artifacts", json={"turn": 0}, headers=AUTH).json()
    assert kept["id"] == "A1"
    (artifact,) = kept["artifacts"]
    assert artifact["title"] == "front page" and 'data-figure="F1"' in artifact["html"]
    assert client.get(base, headers=AUTH).json()["artifacts"] == kept["artifacts"]
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


def test_an_artifact_downloads_as_its_file_or_a_zip_with_what_it_needs(served):
    client, _ = served
    session = client.post("/api/sessions", json={}, headers=AUTH).json()
    ask(client, session)
    base = f"/api/sessions/{session['id']}/artifacts"
    client.post(base, json={"turn": 0}, headers=AUTH)
    source = client.get(f"{base}/A1/download?format=qmd", headers=AUTH)
    assert 'filename="A1-front-page.qmd"' in source.headers["content-disposition"]
    assert "**First** leads. [@S1]" in source.text
    assert "![Points](figures/F1.png)" in source.text
    packed = client.get(f"{base}/A1/download", headers=AUTH)
    assert 'filename="A1-front-page.zip"' in packed.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(packed.content)) as bundle:
        assert set(bundle.namelist()) == {
            "A1-front-page.qmd",
            "references.json",
            "references.csl",
            "figures/F1.png",
            "figures/F1.json",
        }
    for path in (f"{base}/A9/download", f"{base}/A1/download?format=exe"):
        assert client.get(path, headers=AUTH).status_code == 400
    assert client.get(f"{base}/A1/download").status_code == 403


def test_saved_conversations_are_listed_reopened_renamed_and_deleted(served):
    first, _ = served
    assert first.get("/api/info", headers=AUTH).json()["saving"] is False
    assert first.get("/api/conversations", headers=AUTH).json()["conversations"] == []
    with first.launch(save=True) as client:
        assert client.get("/api/info", headers=AUTH).json()["saving"] is True
        session = client.post("/api/sessions", json={}, headers=AUTH).json()
        assert session["saved"] is False
        result = ask(client, session)[-1]
        assert result["saved"] is True and result["title"] == "front page"
        base = f"/api/sessions/{session['id']}"
        client.post(f"{base}/artifacts", json={"turn": 0}, headers=AUTH)
        (listed,) = client.get("/api/conversations", headers=AUTH).json()[
            "conversations"
        ]
        assert listed["id"] == session["id"] and listed["artifacts"] == 1
        folder = first.root / "sessions" / session["id"]
        assert (folder / "artifacts" / "A1-front-page.qmd").is_file()

    # A later launch reads it from disk: by ID, or as the latest with --continue.
    with first.launch(save=True, resume=True) as client:
        body = {"conversation": session["id"]}
        opened = client.post("/api/sessions", json=body, headers=AUTH).json()
        assert opened["id"] == session["id"] and len(opened["turns"]) == 1
        assert opened["artifacts"][0]["id"] == "A1"
        renamed = client.patch(base, json={"title": " Hacker  News "}, headers=AUTH)
        assert renamed.json()["title"] == "Hacker News"
        assert client.patch(base, json={"title": 3}, headers=AUTH).status_code == 400
        listed = client.get("/api/conversations", headers=AUTH).json()["conversations"]
        assert listed[0]["title"] == "Hacker News"
        fresh = client.post("/api/sessions", json={}, headers=AUTH).json()
        assert fresh["id"] != session["id"] and fresh["turns"] == []
        assert client.delete(base, headers=AUTH).json() == {"deleted": session["id"]}
        assert not folder.exists()
        assert client.get(base, headers=AUTH).status_code == 400
        missing = {"conversation": "../../etc"}
        assert (
            client.post("/api/sessions", json=missing, headers=AUTH).status_code == 400
        )
        # An unsaved conversation can be dropped too.
        gone = client.delete(f"/api/sessions/{fresh['id']}", headers=AUTH)
        assert gone.status_code == 200

    with first.launch(save=True, resume=True) as client:
        ask(client, client.post("/api/sessions", json={}, headers=AUTH).json())
    with first.launch(save=True, resume=True) as client:
        latest = client.post("/api/sessions", json={"resume": True}, headers=AUTH)
        assert len(latest.json()["turns"]) == 1


def test_export_needs_quarto_and_reports_its_failures(served, monkeypatch, tmp_path):
    client, _ = served
    monkeypatch.setattr(export_module, "quarto_path", lambda: None)
    assert export_formats() == ()
    assert client.get("/api/info", headers=AUTH).json()["export_formats"] == []
    session = client.post("/api/sessions", json={}, headers=AUTH).json()
    ask(client, session)
    base = f"/api/sessions/{session['id']}/artifacts"
    client.post(base, json={"turn": 0}, headers=AUTH)
    refused = client.get(f"{base}/A1/download?format=pdf", headers=AUTH)
    assert refused.status_code == 400 and "Quarto" in refused.json()["error"]

    # A stand-in program: it writes the file it is asked for, or fails.
    program = tmp_path / "quarto"
    program.write_text(
        "#!/bin/sh\n"
        'if [ "$4" = docx ]; then echo "bad input" >&2; exit 1; fi\n'
        'echo rendered > "$6"\n'
    )
    program.chmod(0o755)
    monkeypatch.setattr(export_module, "quarto_path", lambda: str(program))
    formats = client.get("/api/info", headers=AUTH).json()["export_formats"]
    assert {"id": "pdf", "label": "PDF"} in formats and len(formats) == 4
    made = client.get(f"{base}/A1/download?format=slides", headers=AUTH)
    assert 'filename="A1-front-page-slides.html"' in made.headers["content-disposition"]
    assert made.text == "rendered\n"
    failed = client.get(f"{base}/A1/download?format=docx", headers=AUTH)
    assert failed.status_code == 400 and "bad input" in failed.json()["error"]

    source = tmp_path / "A1.qmd"
    source.write_text("text")
    assert export_artifact(source, "pdf").name == "A1.pdf"
    for path, kind in ((source, "exe"), (tmp_path / "none.qmd", "pdf")):
        with pytest.raises(InputError):
            export_artifact(path, kind)
    monkeypatch.setattr(export_module, "quarto_path", lambda: str(tmp_path / "gone"))
    with pytest.raises(InputError, match="could not be started"):
        export_artifact(source, "pdf")
