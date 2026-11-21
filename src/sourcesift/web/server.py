"""HTTP API and static page for one local user.

The server is meant for the loopback address only. Any page open in the same
browser can send requests to it, so every request must carry the expected Host
header (which defeats DNS rebinding), and every API request must also carry the
per-launch token and, when the browser sends one, a matching Origin.
"""

import asyncio
import json
import logging
import re
import secrets
import time
from collections.abc import AsyncIterator, Iterable
from importlib.resources import files
from typing import Any

from markdown_it import MarkdownIt
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from sourcesift.core.application import SourceSift
from sourcesift.core.session import Session
from sourcesift.data import Block
from sourcesift.errors import InputError, SourceSiftError
from sourcesift.models import Result, SessionEvent
from sourcesift.reports import save_report
from sourcesift.retrieval.http import Fetcher
from sourcesift.retrieval.urls import RetrievalError
from sourcesift.tui_panels import source_kind

MAX_SESSIONS = 8
MAX_BODY_BYTES = 1_048_576
# Map imagery comes from two fixed services, fetched by this server so the page
# itself contacts nothing else. Both ask for attribution, which the page shows.
BASE_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
RADAR_INDEX = "https://api.rainviewer.com/public/weather-maps.json"
RADAR_TILES = "https://tilecache.rainviewer.com{path}/256/{z}/{x}/{y}/2/1_1.png"
RADAR_MAX_ZOOM = 7
RADAR_SECONDS = 300
BASE_SECONDS = 86400
MAX_TILES = 600
_HEADERS = {
    "Cache-Control": "no-store",
    # No inline script or style, no remote content, and no framing by other pages.
    # Map tiles are fetched with the token and shown from blob: URLs.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; "
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
        # Refresh key -> (monotonic time, block), to enforce each source's interval.
        self.refreshed: dict[str, tuple[float, dict[str, Any]]] = {}
        self.tiles: dict[tuple[str, int, int, int], tuple[float, bytes]] = {}
        self.radar: tuple[float, str] | None = None
        # The map tile service asks clients to keep to two connections.
        self.tile_gate = asyncio.Semaphore(2)

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
        index = (await self._body(request)).get("turn", len(session.turns) - 1)
        if not isinstance(index, int) or not 0 <= index < len(session.turns):
            raise InputError("There is no such answer to save.")
        prompt, result = session.turns[index]
        path = save_report(prompt, result, session.settings.reports.directory)
        return JSONResponse({"path": str(path)})

    async def refresh(self, request: Request) -> Response:
        try:
            block = Block.model_validate((await self._body(request)).get("block"))
        except ValidationError:
            raise InputError("That is not a visual this server produced.") from None
        data_source = self.core.toolkit.sources.get(block.source_id)
        interval = data_source.refresh_seconds if data_source else None
        if interval is None:
            raise InputError("This visual does not update.")
        key = json.dumps(
            [block.source_id, block.widget, block.params, block.options, block.window],
            sort_keys=True,
        )
        cached = self.refreshed.get(key)
        if cached is not None and time.monotonic() - cached[0] < interval:
            return JSONResponse(cached[1])
        fresh = await self.core.refresh(block)
        payload = {
            "block": fresh.model_dump(mode="json"),
            "refreshed_at": time.time(),
        }
        if len(self.refreshed) >= 64:
            self.refreshed.pop(next(iter(self.refreshed)))
        self.refreshed[key] = (time.monotonic(), payload)
        return JSONResponse(payload)

    async def _fetch(self, url: str) -> tuple[bytes, str]:
        try:
            async with self.tile_gate, Fetcher(self.core.settings.limits) as fetcher:
                page = await fetcher.get(url, robots=False)
        except RetrievalError:
            raise InputError("Map imagery is unavailable right now.") from None
        return page.body, page.content_type

    async def _radar_path(self) -> str:
        """The newest radar frame, looked up at most every few minutes."""
        if self.radar is None or time.monotonic() - self.radar[0] > RADAR_SECONDS:
            body, _ = await self._fetch(RADAR_INDEX)
            try:
                frames = json.loads(body)["radar"]["past"]
                path = str(frames[-1]["path"])
            except (ValueError, LookupError, TypeError):
                path = ""
            if not re.fullmatch(r"/v2/radar/[A-Za-z0-9_]{1,40}", path):
                raise InputError("Radar imagery is unavailable right now.")
            self.radar = (time.monotonic(), path)
        return self.radar[1]

    async def tile(self, request: Request) -> Response:
        layer = request.path_params["layer"]
        z, x, y = (request.path_params[key] for key in ("z", "x", "y"))
        limit = RADAR_MAX_ZOOM if layer == "radar" else 12
        if layer not in {"base", "radar"} or not (
            0 <= z <= limit and 0 <= x < 2**z and 0 <= y < 2**z
        ):
            raise InputError("There is no such map tile.")
        key = (layer, z, x, y)
        keep = RADAR_SECONDS if layer == "radar" else BASE_SECONDS
        cached = self.tiles.get(key)
        if cached is None or time.monotonic() - cached[0] > keep:
            if layer == "radar":
                url = RADAR_TILES.format(path=await self._radar_path(), z=z, x=x, y=y)
            else:
                url = BASE_TILES.format(z=z, x=x, y=y)
            body, kind = await self._fetch(url)
            if not body.startswith(b"\x89PNG") or not kind.startswith("image/png"):
                raise InputError("Map imagery is unavailable right now.")
            while len(self.tiles) >= MAX_TILES:
                self.tiles.pop(next(iter(self.tiles)))
            cached = self.tiles[key] = (time.monotonic(), body)
        return Response(cached[1], media_type="image/png")


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
            Route("/api/blocks/refresh", api.refresh, methods=["POST"]),
            Route("/api/tiles/{layer}/{z:int}/{x:int}/{y:int}", api.tile),
            Mount("/", StaticFiles(directory=str(static), html=True)),
        ],
        middleware=[Middleware(Guard, hosts=frozenset(hosts), token=token)],
        exception_handlers={SourceSiftError: _input_error},
    )
