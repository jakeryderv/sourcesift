# Python SDK

SourceSift analyzes supplied text and researches registered sources through OpenRouter.
Use a tool-capable model for research. Each request has independent retrieval state.

Set `OPENROUTER_API_KEY` securely in your environment and choose a model, for example
`SOURCESIFT_MODEL=openai/gpt-6.1-sol` and `SOURCESIFT_REASONING_EFFORT=medium`.
See [configuration](configuration.md) for TOML and context options.

```python
from sourcesift import SourceSift

app = SourceSift()
result = app.run_sync("Summarize the project", files=["project.md"])
print(result.answer)
print(result.limitations)
print(result.usage)
```

In an async application or notebook, use `await app.run(...)`. `run_sync()` rejects
calls inside an active event loop. Each call is independent; previous documents
and messages are not retained. The SDK reads stdin only when a binary stream is
explicitly passed via `stdin=`.

## In-memory context and settings

```python
from sourcesift import ContextDocument, Request, SourceSift, load_settings

settings = load_settings(overrides={"agent": {"model": "openai/gpt-6.1-sol"}})
app = SourceSift(settings)
request = Request(
    prompt="Summarize the project in one paragraph",
    context=(ContextDocument(name="project", text="The project studies rainfall."),),
    output_format="plain",
)
result = app.run_sync(request)
```

Passing a resolved `Settings` object bypasses environment and config loading.
Alternatively use `SourceSift(config_path="settings.toml", model="provider/model")`.
Do not combine resolved settings with config/model overrides.

`Result` contains `answer`, `limitations`, configured `model`, and `usage` (model
requests and reported input/output tokens). Research also supplies `references`,
`figures`, `artifacts`, `selected_sources`, `window`, and `http_requests`. Citation `[S1]` corresponds to a
`Reference` with ID `S1`. References contain actual URLs, publisher hostnames,
registered source IDs when available, feed-summary/article kind, publication/update
and retrieval timestamps, and extraction limitations. Only cited evidence appears
in `references`; selected sources may include sources that failed.

```python
result = app.run_sync("Check tech and AI for this project", files=["project.md"])
print(result.answer)
for reference in result.references:
    print(reference.id, reference.title, reference.url, reference.kind)
```

A supplied-text answer that uses no retrieval retains the no-retrieval limitation.
Citations identify retrieved evidence; the model still determines whether a claim
is supported. See [research](research.md) for safeguards and evaluation boundaries.

## Source definitions

```python
from sourcesift import Source, SourceSift

app = SourceSift()
app.register_source(
    Source(
        id="example-publication",
        name="Example Publication",
        website="https://example.com/",
        feeds=("https://example.com/feed.xml",),  # replace with a real public feed
        description="Research and developments in my field.",
        topics=("research",),
        geography="United States",
    )
)
print(app.registry.list())
```

Register before starting requests. Definitions are immutable; registration replaces
the application's registry for future runs. IDs, names, and aliases must be unique.
An omitted feed enables discovery of declared RSS/Atom links from `website`.
`capabilities=("feed",)` disables article follow-ups through that source.
Additions and disabled IDs can also be configured in TOML. A
[live data source](research.md#live-data-sources) is code, not configuration; see
below.

## Data sources

!!! warning "New interface"
    `sourcesift.source` is new and may change before it is opened to installed
    plugins. A data source is trusted Python running in your process: unlike the
    model, it can do anything your program can.

A data source is an async function with typed parameters. It returns evidence for
the model to cite and, optionally, the same data as one or more `Table` values.
The model can then draw a [figure](research.md#figures) from any of those tables.

```python
from pydantic import BaseModel, Field
from sourcesift import Record, SourceResult, SourceSift, Table, render_png, source


class RepoParams(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$", description="owner/name")


@source(
    id="repo-stats",
    name="Repository stats",
    website="https://example.com/",
    description="Open issue and pull request counts by week for one repository.",
    params=RepoParams,
)
async def repo_stats(params, context):
    page = await context.get(f"https://example.com/api/{params.repo}")
    weeks = parse(page.body)  # your parsing: [("2026-11-02", 41, 7), ...]
    table = Table(
        name=f"Open work in {params.repo}",
        columns=[
            {"name": "Week", "kind": "time"},
            {"name": "Issues"},
            {"name": "Pull requests"},
        ],
        rows=weeks,
    )
    text = f"{params.repo} has {weeks[-1][1]} open issues."
    return SourceResult([Record(params.repo, page.url, text, page)], [table])


app = SourceSift()
app.register(repo_stats)
result = app.run_sync("How many open issues does example/project have? Chart it.")
for figure in result.figures:
    print(figure.id, figure.kind, figure.title, figure.evidence_ids)
    open(f"{figure.id}.png", "wb").write(render_png(figure))
```

- A column's kind (`text`, `number`, `time`) is worked out from its values. Declare
  `kind="time"` for ISO 8601 dates or date-times, and give a `unit` where one
  applies; charts use it for axis labels.
- A `Figure` holds the recipe the model chose (kind and columns) and the table it
  is drawn from. `render_png(figure)` returns the picture as PNG bytes.
- `context.get(url)` is the only network access a source is given. It applies the
  same address checks, robots rules, size limits, and request budget as feeds.
  `context.now`, `context.since`, and `context.limit` carry the clock, the start of
  the date window, and the per-source item limit.
- Field descriptions on the parameter model are what the model sees.
- `api_hosts=("api.example.com",)` on `@source` skips the
  [robots check](research.md#robots-rules-and-public-apis) for those hosts only.
  Use it for a documented public API whose terms allow programmatic use.
- Raise `sourcesift.retrieval.urls.RetrievalError` for a failure the user should
  see as a note.

Loading source files from configuration and discovering installed plugins are
planned.

Catch `ConfigurationError` or `InputError` to correct local input, and `ModelError`
for timeout, provider, or unusable-output failures. All derive from
`SourceSiftError`. Async cancellation propagates normally. SourceSift does not
retry failed provider requests. A `ModelError` message carries the HTTP status and
OpenRouter's short error message but never the raw response body; that is available
as `error.detail` with the API key redacted, and the status as `error.status_code`.
Treat `detail` as untrusted text that can echo request content. One
citation-validation repair is allowed within the model-request budget. Individual
retrieval failures appear as limitations; an entirely unsuccessful research run
returns an explicit inability to verify current information.

## Artifacts

```python
from sourcesift import SourceSift, artifact_from_answer, render_qmd, save_artifacts

app = SourceSift()
prompt = "Write a briefing on tech and AI this week"
result = app.run_sync(prompt, artifacts=True)
artifacts = result.artifacts or (artifact_from_answer(prompt, result),)
print(render_qmd(artifacts[0]))  # the Quarto document as a string
paths = save_artifacts("briefing", artifacts, result.references, result.figures)
```

`artifacts=True` gives the model the [`write_artifact`](research.md#artifacts)
tool for this request; `Result.artifacts` holds what it wrote. An `Artifact` has
an `id` (`A1`), `title`, `markdown` with `[S1]` citations and placed figures,
`notes`, a `version`, and `updated_at`. `artifact_from_answer` turns a finished
answer into one.

`save_artifacts(directory, artifacts, references, figures)` writes the
[artifact files](research.md#artifact-files) into that folder, replacing the
files of an earlier call, and returns the `.qmd` paths.
`sourcesift.export.export_artifact(path, "pdf")` renders a saved file to `html`,
`pdf`, `docx`, or `slides` when Quarto is installed, and raises `InputError`
when it is not; `export_formats()` reports what is available.

## Interactive sessions

```python
from sourcesift import SourceSift

app = SourceSift()
session = app.session(files=["project.md"])
# Inside an async function:
first = await session.run("Check tech and AI")
second = await session.run("Read the second article in more detail")
print(second.answer, second.references)
session.reset()  # clears history and reloads configured/initial context files
```

`session.sources` lists every catalog source with whether the conversation may use
it, and `session.enable_sources(["npr", "hacker-news"])` limits later turns to
those IDs until `reset()`.

`Result.steps` lists what the agent did in plain language, one step per tool
call with its outcome. During a session turn the same steps arrive as `step`
events, once when a step starts and once when it finishes.

In a session the model can always write artifacts. `session.artifacts` and
`session.figures` hold everything made so far, `session.keep_answer()` turns the
latest answer into an artifact (pass a turn index for an earlier one), and
`session.save_artifacts(directory)` writes them all as files.

Sessions are independent objects, kept in memory by default. `app.session(save=True)`
saves the conversation in its own folder after each completed turn, with its
artifacts as files in `session.artifacts_path`; `session.id` names it and
`session.saved_path` reports where it is. `app.conversations()` lists saved
conversations, newest first, as `ConversationInfo` values (`id`, `title`,
`updated_at`, `turns`, `artifacts`). `app.session(resume="<id>")` reopens one
and `app.session(resume=True)` the most recent. `session.rename("…")` sets the
title and `app.delete_conversation("<id>")` removes the folder. See
[saved conversations](web.md#saved-conversations). `session.turns` returns completed
prompt/result pairs and `session.context` shows the context snapshot. Settings and
source registration are snapshotted at creation; create a new session to change them.
Additional `files=` or `Request.context` on a turn become part of its history.

An optional synchronous `on_event` callback receives `SessionEvent` values:
`status` reports progress, `draft` appends provisional text, and `reset` clears the
previous draft (including citation-repair attempts). Keep callbacks short and
nonblocking; the returned `Result` is authoritative. Passing a callback enables
model streaming. Cancellation uses ordinary asyncio task cancellation and propagates
`CancelledError`. Errors/cancellation preserve prior turns, and concurrent calls
on the same session raise `InputError`. Reset while busy also raises `InputError`.

Limits on turns and serialized context require an explicit new session when full;
there is no automatic summarization.
