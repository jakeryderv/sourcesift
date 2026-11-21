"""Plain-language descriptions of what the agent did, for interfaces to show.

The same functions describe a tool call while it runs and afterwards from the
message history, so a live activity list and a finished result agree.
"""

import json
from collections.abc import Iterable
from typing import Any

from pydantic_ai.messages import ModelMessage, ToolCallPart, ToolReturnPart

from sourcesift.models import Step
from sourcesift.retrieval.urls import RetrievalError, hostname
from sourcesift.sources import SourceRegistry


def _short(value: object, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _names(registry: SourceRegistry, ids: Iterable[object]) -> list[str]:
    names = []
    for value in ids:
        source = registry.resolve(str(value))
        names.append(source.name if source else _short(value, 40))
    return names


def _listing(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def call_arguments(part: ToolCallPart) -> dict[str, Any]:
    try:
        arguments = part.args_as_dict()
    except (ValueError, TypeError):
        return {}
    return arguments if isinstance(arguments, dict) else {}


def describe_call(
    tool: str, arguments: dict[str, Any], registry: SourceRegistry
) -> tuple[str, tuple[str, ...]]:
    """A short title and detail lines for a tool call that is starting."""
    lines: list[str] = []
    if tool == "research":
        sources = arguments.get("source_ids") or []
        links = arguments.get("direct_urls") or []
        names = _names(registry, sources if isinstance(sources, list) else [])
        count = len(links) if isinstance(links, list) else 0
        if names:
            title = f"Checking {_listing(names)}"
        elif count:
            title = f"Reading {count} link{'s' if count != 1 else ''}"
        else:
            title = "Looking for sources"
        lines += [f"Source: {name}" for name in names]
        lines += [f"Link: {_short(link)}" for link in (links if count else [])]
        only = arguments.get("only_sources")
        if isinstance(only, list) and only:
            lines.append("Limited to: " + ", ".join(_short(o, 60) for o in only))
        lines.append(f"Date window: {_short(arguments.get('window', 'recent'), 20)}")
    elif tool == "query_source":
        name = _listing(_names(registry, [arguments.get("source_id", "a source")]))
        title = f"Getting data from {name}"
        params = arguments.get("params")
        if isinstance(params, dict):
            lines += [f"{_short(k, 40)}: {_short(v, 80)}" for k, v in params.items()]
    elif tool == "read_article":
        url = str(arguments.get("url", ""))
        try:
            title = f"Reading an article on {hostname(url).removeprefix('www.')}"
        except RetrievalError:
            title = "Reading an article"
        lines.append(_short(url))
    elif tool == "show":
        title = f"Drawing a {_short(arguments.get('widget', 'visual'), 40)}"
        options = arguments.get("options")
        if isinstance(options, dict):
            lines += [f"{_short(k, 40)}: {_short(v, 80)}" for k, v in options.items()]
    else:
        title = f"Running {_short(tool, 40)}"
    return title, tuple(lines)


def describe_result(
    tool: str, content: object, seen: set[str]
) -> tuple[str, str, tuple[str, ...]]:
    """State, a one-line summary, and detail lines for a finished tool call.

    ``seen`` holds evidence IDs and notes already reported in this run, because
    each tool reply repeats everything gathered so far.
    """
    if not isinstance(content, dict):
        return "failed", "No result", (_short(content),)
    if content.get("error"):
        return "failed", _short(content["error"]), ()
    if tool == "show":
        return "done", _short(content.get("title", "")), ()
    lines = []
    fresh = 0
    evidence = content.get("evidence")
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict) or str(item.get("id")) in seen:
            continue
        seen.add(str(item.get("id")))
        fresh += 1
        lines.append(f"[{item.get('id')}] {_short(item.get('title', ''), 120)}")
    notes = content.get("limitations")
    for note in notes if isinstance(notes, list) else []:
        if str(note) not in seen:
            seen.add(str(note))
            lines.append(f"Note: {_short(note, 240)}")
    summary = f"{fresh} new item{'s' if fresh != 1 else ''}" if fresh else "Nothing new"
    return ("done" if fresh else "failed"), summary, tuple(lines[:40])


def steps_from_messages(
    messages: Iterable[ModelMessage], registry: SourceRegistry
) -> tuple[Step, ...]:
    """The steps of one run, rebuilt from its messages."""
    steps: dict[str, Step] = {}
    seen: set[str] = set()
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                title, lines = describe_call(
                    part.tool_name, call_arguments(part), registry
                )
                steps[part.tool_call_id] = Step(
                    id=part.tool_call_id,
                    tool=part.tool_name,
                    state="running",
                    title=title,
                    lines=lines,
                )
            elif isinstance(part, ToolReturnPart) and part.tool_call_id in steps:
                step = steps[part.tool_call_id]
                content = part.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        pass
                state, summary, lines = describe_result(step.tool, content, seen)
                steps[step.id] = step.model_copy(
                    update={
                        "state": state,
                        "summary": summary,
                        "lines": (*step.lines, *lines),
                    }
                )
    return tuple(
        step if step.state != "running" else step.model_copy(update={"state": "failed"})
        for step in steps.values()
    )
