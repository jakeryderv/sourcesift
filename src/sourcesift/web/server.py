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
import re
import secrets
import time
from collections.abc import AsyncIterator, Iterable
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

from sourcesift.core.application import SourceSift
from sourcesift.core.session import Session
from sourcesift.errors import InputError, SourceSiftError
from sourcesift.models import Result, SessionEvent
from sourcesift.reports import save_report
from sourcesift.retrieval.http import Fetcher
from sourcesift.retrieval.urls import RetrievalError
from sourcesift.tui_panels import source_kind

MAX_SESSIONS = 8
MAX_BODY_BYTES = 1_048_576
# Saving a report may carry a picture of each chart drawn in the page.
MAX_REPORT_BYTES = 24_000_000
# Radar imagery comes from one fixed service. This server looks up the current
# frame; the browser then loads map and radar tiles itself.
RADAR_INDEX = "https://api.rainviewer.com/public/weather-maps.json"
RADAR_TILES = "https://tilecache.rainviewer.com{path}/256/{{z}}/{{x}}/{{y}}/2/1_1.png"
RADAR_SECONDS = 300
_MAPS = "https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com"
_RADAR = "https://tilecache.rainviewer.com"
_HEADERS = {
    "Cache-Control": "no-store",
    # No inline script, no framing by other pages, and no remote content except
    # map and radar tiles from the hosts named here. The chart library sets
    # element styles and runs its map renderer in a worker made from a blob.
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; worker-src blob:; child-src blob:; "
    f"img-src 'self' data: blob: {_MAPS} {_RADAR}; "
    f"connect-src 'self' {_MAPS} {_RADAR}; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
# Raw HTML and images in a model's answer are never rendered.
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")


def render_markdown(text: str) -> str:
    """Answer Markdown as HTML with raw HTML escaped and images left as text."""
    return _MARKDOWN.render(text)


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
            elif int(request.headers.get("content-length") or 0) > (
                MAX_REPORT_BYTES
                if request.url.path.endswith("/report")
                else MAX_BODY_BYTES
            ):
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
        "answer_html": render_markdown(result.answer),
    }


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
        self.radar: tuple[float, str] | None = None

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
                html = render_markdown("".join(draft))
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

    async def report(self, request: Request) -> Response:
        session = self._session(request)
        if not session.turns:
            raise InputError("Nothing to save yet; ask a question first.")
        body = await self._body(request)
        index = body.get("turn", len(session.turns) - 1)
        if not isinstance(index, int) or not 0 <= index < len(session.turns):
            raise InputError("There is no such answer to save.")
        prompt, result = session.turns[index]
        # The page may send a PNG of each chart it drew, keyed by its position.
        sent = body.get("images", {})
        images: dict[int, bytes] = {}
        prefix = "data:image/png;base64,"
        try:
            for key, value in sent.items():
                if not value.startswith(prefix):
                    raise ValueError
                images[int(key)] = base64.b64decode(
                    value.removeprefix(prefix), validate=True
                )
        except (AttributeError, TypeError, ValueError):
            raise InputError("The chart images could not be read.") from None
        path = save_report(
            prompt, result, session.settings.reports.directory, images=images
        )
        pictures = [
            name
            for key in sorted(images)
            if (path.parent / (name := f"{path.stem}-{key + 1}.png")).is_file()
        ]
        return JSONResponse({"path": str(path), "images": pictures})

    async def radar_tiles(self, request: Request) -> Response:
        """Where the newest radar frame's tiles are, looked up every few minutes."""
        if self.radar is None or time.monotonic() - self.radar[0] > RADAR_SECONDS:
            try:
                async with Fetcher(self.core.settings.limits) as fetcher:
                    page = await fetcher.get(RADAR_INDEX, robots=False)
                path = str(json.loads(page.body)["radar"]["past"][-1]["path"])
            except (RetrievalError, ValueError, LookupError, TypeError):
                path = ""
            if not re.fullmatch(r"/v2/radar/[A-Za-z0-9_]{1,40}", path):
                raise InputError("Radar imagery is unavailable right now.")
            self.radar = (time.monotonic(), path)
        return JSONResponse({"tiles": RADAR_TILES.format(path=self.radar[1])})


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
            Route("/api/sessions/{id}/report", api.report, methods=["POST"]),
            Route("/api/radar", api.radar_tiles),
            Mount("/", StaticFiles(directory=str(static), html=True)),
        ],
        middleware=[Middleware(Guard, hosts=frozenset(hosts), token=token)],
        exception_handlers={SourceSiftError: _input_error},
    )
