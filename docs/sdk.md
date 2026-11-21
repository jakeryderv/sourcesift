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
`selected_sources`, `window`, and `http_requests`. Citation `[S1]` corresponds to a
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

## Data sources and widgets

!!! warning "New interface"
    `sourcesift.extend` is new and may change before it is opened to installed
    plugins. Extensions are trusted Python running in your process: unlike the
    model, they can do anything your program can.

A data source is an async function with typed parameters. It returns evidence for
the model to cite and, optionally, the same data as one or more `Table` values. A
widget is a function from a table and typed options to a view: a `Figure` (any
[Plotly](https://plotly.com/javascript/) figure, as plain `data` and `layout`), a
`TableView`, or a `StatView`. Neither refers to the other, so any widget can show
any source's table whose columns fit its options.

```python
from pydantic import BaseModel, Field
from sourcesift import (
    Figure,
    Record,
    SourceResult,
    SourceSift,
    Table,
    source,
    widget,
)


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


class GaugeOptions(BaseModel):
    column: str = Field(description="Numeric column to show.")


@widget(
    id="gauge",
    description="The latest value of one column as a dial.",
    options=GaugeOptions,
)
def gauge(table, options):
    if table.kind(options.column) != "number":
        raise ValueError(f"Column {options.column!r} is not numeric.")
    value = table.values(options.column)[-1]
    return Figure(
        title=table.name,
        data=[{"type": "indicator", "mode": "gauge+number", "value": value}],
    )


app = SourceSift()
app.register(repo_stats)
app.register(gauge)
result = app.run_sync("How many open issues does example/project have? Chart it.")
for block in result.blocks:
    print(block.widget, block.view.title, block.evidence_ids)
```

- With no widget of your own, the built-in `chart`, `table`, `stats`, and `map`
  widgets already work on any table a source returns.
- A column's kind (`text`, `number`, `time`) is worked out from its values. Declare
  `kind="time"` for ISO 8601 dates or date-times, and give a `unit` where one
  applies; charts use it for axis labels.
- A widget raises `ValueError` with a short message when its options do not fit
  the table. The message goes to the model, which can correct its request.
- A figure carries structure only. The page applies its own colours and fonts.
- `context.get(url)` is the only network access a source is given. It applies the
  same address checks, robots rules, size limits, and request budget as feeds.
  `context.now`, `context.since`, and `context.limit` carry the clock, the start of
  the date window, and the per-source item limit.
- Field descriptions on the parameter and option models are what the model sees.
- `api_hosts=("api.example.com",)` on `@source` skips the
  [robots check](research.md#robots-rules-and-public-apis) for those hosts only.
  Use it for a documented public API whose terms allow programmatic use.
- Raise `sourcesift.retrieval.urls.RetrievalError` for a failure the user should
  see as a note.
- A `Block` holds the view, the options the model chose, and the table it was
  drawn from.

Loading extension files from configuration and discovering installed plugins are
planned; see the [design](design.md#11-proposal-web-app-typed-data-and-display-blocks).

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

## Reports

```python
from sourcesift import SourceSift, render_report, save_report

app = SourceSift()
prompt = "Check tech and AI this week"
result = app.run_sync(prompt)
text = render_report(prompt, result)  # Markdown string
path = save_report(prompt, result, app.settings.reports.directory)
```

`render_report` returns the request, answer, visuals, references, and notes as
Markdown. Tables and headline figures are written out; a chart or map is replaced
by the rows it was drawn from unless you supply a picture of it.
`save_report(..., images={0: png_bytes})` saves a PNG for the visual at that
position in `result.blocks` beside the report and links it. `save_report` writes
a new file, never replacing an existing one, and returns the path. A `None` directory means the per-user default described in
[configuration](configuration.md#reports).

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

Sessions are independent objects, kept in memory by default. `app.session(save=True)`
writes the conversation to a file after each completed turn, `session.saved_path`
reports where, and `app.session(resume=True)` continues the most recently saved
one; see [saving conversations](chat.md#save-and-continue-a-conversation). `session.turns` returns completed
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
there is no automatic summarization, persistence, or resume. See [chat](chat.md).
