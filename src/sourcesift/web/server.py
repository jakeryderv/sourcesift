"""HTTP API and static page for one local user.

The server is meant for the loopback address only. Any page open in the same
browser can send requests to it, so every request must carry the expected Host
header (which defeats DNS rebinding), and every API request must also carry the
per-launch token and, when the browser sends one, a matching Origin.
"""

import asyncio
import base64
import json
import logging
import secrets
from collections.abc import AsyncIterator, Iterable
from html import escape
from importlib.resources import files
from typing import Any

from markdown_it import MarkdownIt
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from sourcesift.artifacts import new_artifact_folder, save_artifacts
from sourcesift.core.application import SourceSift
from sourcesift.core.session import Session
from sourcesift.data import Figure
from sourcesift.errors import InputError, SourceSiftError
from sourcesift.figures import render_png
from sourcesift.models import Result, SessionEvent
from sourcesift.sources import Source

MAX_SESSIONS = 8
MAX_BODY_BYTES = 1_048_576
_HEADERS = {
    "Cache-Control": "no-store",
    # No inline script, no framing by other pages, and no remote content at all.
    # Figures arrive inside the page's own HTML; rendered tables set cell alignment.
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
# Raw HTML in a model's text is never rendered, and the only images are figures.
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def _image(renderer: Any, tokens: Any, index: int, options: Any, env: Any) -> str:
    """Draw a placed figure; any other image becomes its description as text."""
    token = tokens[index]
    target = str(token.attrs.get("src", "")).strip()
    figure = (env or {}).get("figures", {}).get(target)
    label = escape(token.content)
    if figure is None:
        return f'<span class="missing-figure">{label or escape(target)}</span>'
    data = base64.b64encode(render_png(figure)).decode()
    return (
        f'<img class="figure" data-figure="{escape(figure.id)}" '
        f'alt="{escape(figure.title)}" src="data:image/png;base64,{data}">'
    )


_MARKDOWN.add_render_rule("image", _image)


def render_markdown(text: str, figures: Iterable[Figure] = ()) -> str:
    """Model Markdown as HTML: raw HTML escaped, and only known figures drawn."""
    return _MARKDOWN.render(text, {"figures": {item.id: item for item in figures}})


class Guard:
    """Reject requests that did not come from this launch's own page."""

    def __init__(self, app: ASGIApp, *, hosts: frozenset[str], token: str) -> None:
        self.app = app
        self.hosts = hosts
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        host = request.headers.get("host", "")
        problem = None
        if host not in self.hosts:
            problem = "Unexpected host."
        elif request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            supplied = request.headers.get("authorization", "")
            if origin is not None and origin != f"http://{host}":
                problem = "Unexpected origin."
            elif not secrets.compare_digest(
                supplied.encode(), f"Bearer {self.token}".encode()
            ):
                problem = "Open the link printed by ssift web."
            elif int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
                problem = "Request is too large."
        if problem is not None:
            await JSONResponse({"error": problem}, 403, _HEADERS)(scope, receive, send)
            return

        async def with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    *((k.lower().encode(), v.encode()) for k, v in _HEADERS.items()),
                ]
            await send(message)

        await self.app(scope, receive, with_headers)


def _turn(prompt: str, result: Result) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "result": result.model_dump(mode="json"),
        "answer_html": render_markdown(result.answer, result.figures),
    }


def source_kind(source: Source) -> str:
    """How a source is read, in the words the catalog documentation uses."""
    if "query" in source.capabilities:
        return "live data"
    return "feed and articles" if "article" in source.capabilities else "feed only"


def _sources(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "id": source.id,
            "name": source.name,
            "kind": source_kind(source),
            "description": source.description,
            "topics": source.topics,
            "geography": source.geography,
            "enabled": enabled,
        }
        for source, enabled in session.sources
    ]


class Api:
    """Route handlers and the state of one launch."""

    def __init__(
        self,
        core: SourceSift,
        *,
        files: Iterable[str] = (),
        save: bool | None = None,
        resume: bool = False,
    ) -> None:
        self.core = core
        self.files = tuple(files)
        self.save = save
        self.resume = resume
        self.sessions: dict[str, Session] = {}

    async def _body(self, request: Request) -> dict[str, Any]:
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise InputError("The request body must be a JSON object.")
        return body

    def _session(self, request: Request) -> Session:
        session = self.sessions.get(request.path_params["id"])
        if session is None:
            raise InputError("This conversation is no longer open; start a new one.")
        return session

    async def create_session(self, request: Request) -> Response:
        body = await self._body(request)
        # Only the first conversation of a launch continues a saved one.
        resume = self.resume and bool(body.get("resume")) and not self.sessions
        session = self.core.session(files=self.files, save=self.save, resume=resume)
        while len(self.sessions) >= MAX_SESSIONS:
            self.sessions.pop(next(iter(self.sessions)))
        key = secrets.token_urlsafe(12)
        self.sessions[key] = session
        return JSONResponse(self._describe(key, session))

    def _describe(self, key: str, session: Session) -> dict[str, Any]:
        return {
            "id": key,
            "model": session.settings.agent.model,
            "turns": [_turn(prompt, result) for prompt, result in session.turns],
            "sources": _sources(session),
        }

    async def get_session(self, request: Request) -> Response:
        session = self._session(request)
        return JSONResponse(self._describe(request.path_params["id"], session))

    async def run_turn(self, request: Request) -> Response:
        session = self._session(request)
        prompt = (await self._body(request)).get("prompt")
        if not isinstance(prompt, str):
            raise InputError("Provide a nonempty prompt.")
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        draft: list[str] = []

        def on_event(event: SessionEvent) -> None:
            if event.kind == "draft":
                # Send the whole draft rendered, so the page never parses Markdown.
                draft.append(event.text)
                html = render_markdown("".join(draft), session.figures)
                queue.put_nowait({"event": "draft", "html": html})
            elif event.kind == "reset":
                draft.clear()
                queue.put_nowait({"event": "reset"})
            elif event.kind == "step" and event.step is not None:
                queue.put_nowait({"event": "step", "step": event.step.model_dump()})
            else:
                queue.put_nowait({"event": "status", "text": event.text})

        async def work() -> None:
            try:
                result = await session.run(prompt, on_event=on_event)
                queue.put_nowait({"event": "result", "turn": _turn(prompt, result)})
            except SourceSiftError as exc:
                queue.put_nowait({"event": "error", "message": str(exc)})
            except Exception:
                # The page must still hear that the turn ended; details stay local.
                logging.getLogger(__name__).exception("A turn failed unexpectedly.")
                message = "The server hit an unexpected error; see its terminal."
                queue.put_nowait({"event": "error", "message": message})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(work())

        async def stream() -> AsyncIterator[str]:
            try:
                while (item := await queue.get()) is not None:
                    yield json.dumps(item, ensure_ascii=False) + "\n"
            finally:
                # A closed connection cancels the turn; a finished one is unaffected.
                task.cancel()

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def get_sources(self, request: Request) -> Response:
        return JSONResponse({"sources": _sources(self._session(request))})

    async def put_sources(self, request: Request) -> Response:
        session = self._session(request)
        enabled = (await self._body(request)).get("enabled")
        if not isinstance(enabled, list) or not all(
            isinstance(i, str) for i in enabled
        ):
            raise InputError("enabled must be a list of source IDs.")
        session.enable_sources(enabled)
        return JSONResponse({"sources": _sources(session)})

    async def keep_answer(self, request: Request) -> Response:
        """Keep an answer as an artifact and save it to the artifacts directory."""
        session = self._session(request)
        if not session.turns:
            raise InputError("Nothing to keep yet; ask a question first.")
        index = (await self._body(request)).get("turn", len(session.turns) - 1)
        if not isinstance(index, int) or not 0 <= index < len(session.turns):
            raise InputError("There is no such answer to keep.")
        artifact = session.keep_answer(index)
        folder = new_artifact_folder(
            session.settings.artifacts.directory, artifact.title
        )
        (path,) = save_artifacts(folder, [artifact], session.evidence, session.figures)
        return JSONResponse(
            {"id": artifact.id, "title": artifact.title, "path": str(path)}
        )


async def _input_error(request: Request, exc: Exception) -> Response:
    return JSONResponse({"error": str(exc)}, 400)


def create_app(
    core: SourceSift,
    *,
    token: str,
    hosts: Iterable[str],
    files_: Iterable[str] = (),
    save: bool | None = None,
    resume: bool = False,
) -> Starlette:
    """Build the ASGI application for one launch."""
    api = Api(core, files=files_, save=save, resume=resume)
    static = files("sourcesift.web") / "static"
    return Starlette(
        routes=[
            Route("/api/sessions", api.create_session, methods=["POST"]),
            Route("/api/sessions/{id}", api.get_session, methods=["GET"]),
            Route("/api/sessions/{id}/turns", api.run_turn, methods=["POST"]),
            Route("/api/sessions/{id}/sources", api.get_sources, methods=["GET"]),
            Route("/api/sessions/{id}/sources", api.put_sources, methods=["PUT"]),
            Route("/api/sessions/{id}/artifacts", api.keep_answer, methods=["POST"]),
            Mount("/", StaticFiles(directory=str(static), html=True)),
        ],
        middleware=[Middleware(Guard, hosts=frozenset(hosts), token=token)],
        exception_handlers={SourceSiftError: _input_error},
    )
