# SourceSift — Design Document

**Python-first, plugin-driven research with prompt-driven source selection.**

**Status:** Phases 1–3 implement the SDK, CLI, supplied context, registered
sources, bounded retrieval, evidence references, and interactive terminal chat. Executable plugins and later
roadmap capabilities remain planned. Current contracts are documented in the
[SDK](sdk.md), [CLI](cli.md), [research](research.md), and
[configuration](configuration.md) references.

**Related documents:** [Use cases and scope](use-cases.md),
[implementation roadmap](roadmap.md), and [setup and releases](https://github.com/jakeryderv/sourcesift#readme).
The Markdown files directly under `docs/` are the maintained project reference;
`docs/capstone/` contains archived course material.

## 1. Overview

SourceSift discovers, retrieves, evaluates, and synthesizes information from
registered sources based on a user's request and optional personal context.

A user should be able to ask “check news,” “check tech,” or “what developments
matter for my work?” without selecting feeds or learning category-specific flags.
Registered sources carry links, descriptive metadata, and brief descriptions that
the agent uses to decide where to look.

The initial application provides a Python SDK and Cyclopts CLI. Requests run
without an application database or saved conversation history. Configuration and
context files are supported, and each run can maintain in-memory state. In this
design, semantic selection means interpreting the prompt against source metadata;
it does not require embeddings, a vector database, or an exact keyword syntax.

### Project Information

| Property | Decision |
|---|---|
| Repository / package | `sourcesift` |
| CLI command | `ssift` |
| Public application object | `SourceSift` |
| Core, SDK, and plugins | Python |
| Agent runtime | PydanticAI |
| Model provider | OpenRouter, with configurable model selection |
| CLI framework | Cyclopts |
| Development / distribution | uv / PyPI |
| Initial state | Configuration files and per-run memory |
| Future persistence | SQLite + FTS5, when justified |
| Terminal UI | Textual + Rich + asyncio |
| Native optimization | Optional Rust, after profiling |

## 2. Architecture and Request Flow

```text
User request + optional context
              │
              ▼
CLI / Textual chat / Python SDK
              │
              ▼
SourceSift application
├── Configuration and request limits
├── Source definitions and plugin registry
├── PydanticAI agent → OpenRouter
│   ├── Interpret intent and select registered sources
│   ├── Request retrieval through registered tools
│   ├── Decide whether more evidence is needed
│   └── Evaluate and synthesize retrieved information
├── Python retrieval and extraction
│   └── HTTP, feed parsing, normalization, provenance
└── Structured result → answer, references, and limitations
```

The agent may alternate between retrieval and evaluation within a bounded request.
A single user turn can include multiple tool calls. `SourceSift.session()` retains
conversation and evidence across turns; independent `run()` calls remain stateless.

Deterministic operations remain ordinary Python: configuration loading, HTTP
requests, parsing, normalization, deduplication within a run, and output rendering.
The agent handles intent, semantic source selection, relevance, and synthesis.

Storage is an optional future extension to this path. It must not become a
requirement for an ordinary `ssift ask` request. Local execution and configuration
do not imply offline inference: selected context and retrieved content are sent to
the configured model through OpenRouter.

## 3. Source Definitions, Retrieval, and Evidence

### Registered Source Definitions

A source definition describes a publication, feed, website, or service. It carries:

- A stable ID and human-readable name.
- Website, feed, or other access links.
- A brief description of its coverage.
- Descriptive topics, industries, language, and geographic coverage.
- Available retrieval capabilities and any access requirements.

Names, descriptions, and metadata help the agent interpret requests. Labels such
as `tech` and `ai` can overlap; users do not need to reproduce those labels exactly.
Configuration can enable or disable definitions, and plugins or SDK users can add
them. Disabled definitions are excluded before agent selection.

The initial curated coverage is **US national news, technology, AI, business,
marketing, and finance**. Specific publications and endpoints will be selected and
verified during implementation. Local and global news collections are later
expansions. This is a collection's intended coverage, not a claim of comprehensive
news coverage or a requirement that every topical source be US-based.

### Shared Retrieval Adapters

Source definitions are data. Retrieval adapters implement access methods such as
RSS/Atom or website retrieval. Multiple definitions can share an adapter; adding
another ordinary feed should not require a new Python plugin.

Initial retrieval supports RSS/Atom, feed discovery from website URLs, direct
article URLs, and bounded website article discovery where supported. Feed
discovery locates access links; semantic source selection chooses which registered
sources are relevant to the request. These are separate operations.

An adapter exposes only capabilities it actually supports. A source that supplies
recent feed entries is not assumed to provide arbitrary historical search.
General-purpose crawling, open-web search, authenticated account integrations,
and browser automation are outside the initial implementation.

### Semantic Selection and Explicit Requests

The ordinary interface is a prompt:

```bash
ssift ask "Check news"
ssift ask "Check tech and AI for developments relevant to my work"
ssift ask "Check business, marketing, and finance this week"
ssift ask "Summarize this article: https://example.com/article"
```

The agent selects among enabled registered definitions using their links,
metadata, descriptions, and the user's context. It can retrieve articles linked
from selected feeds or pages as evidence, within the run's retrieval limits.

Users can name a publication or supply a link in the prompt. A request to use only
a named source must constrain source selection; if the source cannot be identified
or accessed, explain the limitation instead of silently substituting others.
This is a semantic research instruction. It does not establish a domain-level
network sandbox, and a separate `--source` flag or domain-policy interface is not
part of the initial CLI contract. References identify the actual publications used,
including linked material from another publisher.

### Content Items and Provenance

Content items describe individual retrieved documents, independently of source
coverage metadata. Proposed fields include an item ID, title, requested and final
URL, source ID where known, extracted text, author, publication/update timestamps
when available, retrieval timestamp, and extraction limitations.

A source's category does not automatically classify all its articles. Preserve
unknown dates as unknown, and distinguish when something was published from when
SourceSift fetched it. Deduplicate repeated URLs/content within a request before
presenting recommendations.

## 4. Plugin Contracts

Built-in and third-party capabilities use the same Python contracts. Start with
source definitions, retrieval/extraction, and tools needed by the first research
flow. Extend the contracts as concrete use cases emerge.

| Capability | Responsibility |
|---|---|
| Source | Register source definitions and, when necessary, custom access adapters |
| Extractor | Normalize retrieved content and preserve provenance |
| Tool | Expose a callable capability to the agent |
| Workflow | Coordinate reusable research operations; introduced as needed |
| Ranker | Customize relevance scoring; introduced as needed |
| Command | Extend the CLI; introduced as needed |

A plugin can register multiple capabilities. The application adapts tools to
PydanticAI internally, keeping public contracts independent of framework internals.
Third-party discovery will use Python package entry points:

```toml
[project.entry-points."sourcesift.plugins"]
example = "sourcesift_example:ExamplePlugin"
```

Discovered plugins need clear identities, duplicate-registration errors, and
useful load-failure diagnostics. Installed, enabled plugins execute trusted Python
code in the application process. Advanced sandboxing, permission systems,
dependency management, and hot reloading are deferred.

## 5. Configuration and User Context

Configuration is optional beyond model selection and credentials. Implemented
mechanisms are TOML for application settings, Markdown for personal context,
environment variables for credentials and deployment-specific settings, and Python
objects for SDK callers. Ordinary use should not require executable Python config.

Illustrative TOML, with an example model identifier rather than a promised default:

```toml
[agent]
model = "anthropic/claude-sonnet-4.6"

[context]
files = ["context.md"]
```

Categories remain descriptive source metadata; users can say “check tech” directly.
They do not need to configure topic filters before making a request.

### Resolution Rules

- For the same setting: built-in defaults → TOML → supported environment variables
  → explicit CLI or SDK overrides.
- Resolve context paths declared in TOML relative to that TOML file. Resolve paths
  supplied on the CLI relative to the working directory.
- Treat configured context as background; the current request determines the task.
  Explain material conflicts instead of silently changing the requested scope.
- Load Markdown as text, and avoid logging credentials or personal context by default.
- Load configured context first, then explicit file inputs and piped stdin in a
  documented order. Read stdin only when piped/redirected, so normal terminal calls
  do not wait for input unexpectedly.

The [configuration reference](configuration.md) defines implemented locations,
environment variables, precedence, and limits. The CLI and SDK share these models.

## 6. Public SDK and CLI

`SourceSift` is the public application object. The underlying PydanticAI agent
remains internal. An async core and synchronous convenience method serve both
application and script callers:

```python
from sourcesift import SourceSift

app = SourceSift()
result = app.run_sync("Summarize this document", files=["report.md"])
print(result.answer)

# In an existing async application:
# result = await app.run("Summarize this document", files=["report.md"])
```

The result contains answer text, limitations, model usage, cited evidence
references, selected source IDs, the research window, and HTTP request count.
The CLI renders the same result used by SDK callers.
The API is early and may evolve before 1.0.

`register_source(Source(...))` adds a data definition today. Executable tool
registration and entry-point discovery remain Phase 5 work.

### Research CLI

```bash
ssift ask "Check news"
ssift ask "Check marketing for developments relevant to this project" --file project.md
cat interests.md | ssift ask "Check tech and AI for me" > briefing.md
ssift ask "Compare https://example.com/a and https://example.org/b"
```

Default output is readable Markdown, with a plain-text output option. Primary
results go to stdout; diagnostics and progress go to stderr. Scripts must not need
interactive input. The exit convention is `0` for a usable result (including
clearly disclosed partial coverage), `1` when the request cannot be completed, and
`2` for invalid invocation/configuration. See the [CLI reference](cli.md) for flags and interruption/pipe exit codes.

`ssift` in a terminal, or explicit `ssift chat`, runs a Textual interface over the
shared session runtime. Slash-command completion, an ignore-aware `@` file picker,
and session-only model setup make chat the primary interactive entry point. Plugin
inspection and workflow commands arrive in their roadmap phases. Archive search and ingestion commands depend on future persistence.
The installed entry point is `ssift = "sourcesift.cli:main"`.

### Interactive session contract

`Session` owns completed turns and a private PydanticAI history/evidence snapshot.
Each turn runs against a copy; only a validated successful result commits. Evidence
IDs are monotonic within a session and keep their identity when an article is read
in more detail. Previous evidence is labeled as retained, not newly retrieved.
Per-turn source, HTTP, tool, and model limits restart; session turn and byte limits
bound accumulated history. Reaching them requires a new session, without silent
truncation or model-generated memory summaries.

Textual owns the terminal and event loop. Async workers call `Session.run()` and
consume UI-independent status/draft/reset events. Drafts remain provisional until
citation validation completes; the UI replaces them with the final `Result`, or
discards them on error/cancellation. The core imports no Textual or Rich UI types.
Personal guidance is explicitly selected through `[context].instructions_file`;
other files and web content stay research material. Context is loaded once per
session; reset reloads it atomically. Selected per-turn attachments are read and
validated at submission, with relative path labels, then passed as ordinary
`Request.context` documents to the same session runtime. UI discovery and keyboard
logic remain outside the core. See the [web app guide](web.md) for the user-facing contract.

## 7. Grounding, Failure Handling, and Limits

- Tie factual research claims to retrieved evidence and provide usable references.
  Distinguish source reporting, the agent's interpretation, and uncertainty.
- Resolve “today” and “this week” using a known current time and configured
  time zone (UTC by default), and disclose the window. “Recent” defaults to seven
  rolling days; calendar windows and unknown dates follow the [research contract](research.md).
- If evidence is missing, conflicting, stale, or inaccessible, say so. Never treat
  retrieval time as proof that an undated article is recent.
- Continue through individual source failures when useful evidence remains, and
  disclose incomplete coverage. An unsupported topic/location should produce a
  coverage limitation rather than a claim of comprehensive research.
- Bound model requests/tool calls, sources/articles fetched, input size, HTTP
  response size, retries, concurrency, and total execution time. Numeric defaults
  are documented in the [configuration reference](configuration.md).
- Treat retrieved documents as evidence, not as instructions that can alter the
  task, enable plugins, change configuration, or disclose credentials.

## 8. Technology Stack

| Component | Planned technology |
|---|---|
| Core / SDK / schemas | Python, Pydantic |
| Agent runtime / provider | PydanticAI / OpenRouter |
| Orchestration | Python `async`/`await` |
| CLI / configuration | Cyclopts / pydantic-settings |
| HTTP / RSS and Atom | HTTPX / feedparser |
| Article extraction / feed discovery | Trafilatura / bounded HTML link parsing |
| Plugin discovery | `importlib.metadata` |
| Testing | pytest, with fixtures and separate live evaluations |
| Future persistence / archive search | SQLite / FTS5 |
| Optional native modules | PyO3 + Maturin |
| Terminal UI | Textual + Rich + asyncio |
| Build / distribution | uv / PyPI |

## 9. Proposed Repository Structure

Create modules as functionality arrives. This is a direction, not a list of empty
packages to scaffold immediately.

```text
sourcesift/
├── pyproject.toml
├── README.md                 # Current setup and release instructions
├── docs/
│   ├── use-cases.md           # Product behavior and scope
│   ├── design.md              # Architecture and contracts
│   ├── roadmap.md             # Sequence and progress
│   └── capstone/              # Archived course material
├── src/sourcesift/
│   ├── __init__.py
│   ├── core/                  # Application, configuration, orchestration
│   ├── agents/                # PydanticAI integration
│   ├── sources/               # Definitions and shared retrieval adapters
│   ├── plugins/               # Contracts, registry, built-ins
│   ├── models/                # Requests, content, evidence, results
│   └── cli/                   # Cyclopts commands and rendering
└── tests/                     # Fixtures and behavioral checks as features arrive
```

## 10. Deferred Extensions

SQLite/FTS5 may later support caching, saved research, feedback, and archive search.
Explicit user context already supports personalization without those features.
Persistent conversations and automatic preference learning are separate additions.

The Textual TUI uses the Python session runtime directly, with asyncio workers for
streaming and cancellation. Rust native modules should follow measured bottlenecks,
remain behind Python interfaces, and include a platform-wheel distribution plan.

Email integrations, general crawling, browser automation, semantic/vector search,
complex multi-agent orchestration, and hosted services remain deferred. A local
web application is proposed in [section 11](#11-proposal-web-app-typed-data-and-display-blocks). Product scope is maintained in [use-cases.md](use-cases.md); sequencing
and completion criteria belong in [roadmap.md](roadmap.md).

## 11. Proposal: Web App, Typed Data, and Display Blocks

**Status: steps 1 to 3 of the order of work are implemented, and the data layer
has since been simplified.** Sources now return plain tables instead of several
typed shapes, the built-in widgets build [Plotly](https://plotly.com/javascript/)
figures from named columns, and a visual is a snapshot with no automatic refresh,
so the shapes, `refresh_seconds`, and the refresh and tile routes described below
no longer exist. The [research](research.md#visuals) and [SDK](sdk.md) guides
describe what is built. Step 2 is the [web app](web.md). Built-ins are
registered by `app.register(...)` rather than an extension file. The rest of this
section is the proposal as agreed. It
would make a local web app the main interface, keep `ssift ask`, retire the Textual
chat once the web app covers the same ground, and turn the SDK into the way
SourceSift is extended: typed sources and widgets written in Python.

### Goals

- Answer requests such as “show me the weather in Chicago” or “show the national
  debt this year” with a live visual next to the cited answer.
- Keep every number on screen traceable to retrieved evidence.
- Let new data sources be added without touching the agent loop, and later by
  third-party packages.

Not goals: a hosted service, a general dashboard builder, or letting the model
write code or markup that the page runs.

### Three layers

Sources and widgets never refer to each other. Both are written against a small
shared set of typed data shapes, so any widget can show any source's data of a
shape it accepts.

```text
Source ──produces──► Data shape ◄──accepts── Widget ──renders as──► page primitive
(weather, prices)    (TimeSeries, …)         (line chart, …)        (chart, map, table, stat)
```

**1. Data shapes.** The shared vocabulary, kept deliberately small:

| Shape | Holds |
|---|---|
| `TimeSeries` | Named series of timestamped values with a unit |
| `Table` | Typed columns and rows |
| `Stats` | A few labeled values, each with an optional unit and change |
| `GeoPoints` | Located items with labels and optional values |

A source may also define a shape of its own (a `Forecast`, say) when the generic
ones lose too much; only widgets written for that shape can show it.

**2. Sources.** A typed source declares its parameters and what it returns. One
fetch yields the text the model reads and cites, plus the same data as shapes:

```python
class DebtParams(Contract):
    days: int = Field(default=365, ge=1, le=3650)


@source(
    id="us-treasury-debt",
    name="US public debt",
    description="Total US public debt outstanding by day.",
    params=DebtParams,
    returns=(TimeSeries,),
    refresh_seconds=None,  # static; a number lets the page re-fetch
)
async def debt(params: DebtParams, context: FetchContext) -> SourceResult:
    page = await context.get(TREASURY_URL.format(days=params.days))
    series = parse_debt(page)
    return SourceResult(evidence=[summarize(series, page)], data=[series])
```

`FetchContext` supplies the bounded `get(url)`, the clock, and the date window, so
a source cannot reach the network any other way. Each returned data object is tied
to the citation ID of its evidence. The existing Hacker News and Treasury adapters
become typed sources; feed sources stay as they are.

**3. Widgets.** A widget declares which shape it accepts, the options the model
may set, and how to turn data plus options into one of the page's primitives:

```python
class LineOptions(Contract):
    title: str = Field(default="", max_length=80)
    log_scale: bool = False


@widget(
    id="line-chart",
    description="Values over time.",
    accepts=TimeSeries,
    options=LineOptions,
)
def line_chart(data: TimeSeries, options: LineOptions) -> Chart:
    return Chart(
        title=options.title or data.name, series=data.series, y_log=options.log_scale
    )
```

The page knows four primitives: `chart`, `map`, `table`, and `stat`. A widget is a
Python function from data to primitives, so new widgets need no browser code.
A visual the primitives cannot express would need a new primitive in the page.

### How a visual gets into an answer

The model gets a second tool beside `query_source`:

```text
show(evidence_id="S2", widget="line-chart", options={"title": "US debt, past year"})
```

- The model chooses *which* widget and its options. Options are validated against
  the widget's model, and the widget must accept a shape attached to that evidence.
- The data comes only from what the source returned for that citation. The model
  cannot pass values, so it cannot put an invented number on screen.
- The catalog the model sees lists each source's parameter schema and the shapes
  it returns, and each widget's accepted shape and options.
- `Result.blocks` holds the rendered primitives in the order shown, each with its
  citation ID, alongside `Result.references`.

A block from a source with `refresh_seconds` can be re-fetched by the page through
`app.fetch_data(source_id, params)`. That runs the source and the same widget
again: no model request and no token cost. The server enforces the interval.

### The web app

`ssift web` starts a server on the loopback address and opens the page. The server
is a thin layer over the existing `Session`:

| Route | Purpose |
|---|---|
| `POST /api/sessions` | Start or continue a conversation |
| `POST /api/sessions/{id}/turns` | Run a turn; streams status, draft, then the final result |
| `GET` / `PUT /api/sessions/{id}/sources` | The catalog and which sources are enabled |
| `POST /api/data/{source_id}` | Refresh a block's data without the model |
| `POST /api/sessions/{id}/report` | Save the latest answer as a report |

- The page is static files shipped in the package: chat, citations with an evidence
  side panel, the source picker, and renderers for the four primitives. Chart and map
  libraries are bundled rather than loaded from a CDN.
- It is installed as an optional extra (`sourcesift[web]`) so the CLI stays light.
- Because a local server can be reached by any page in the browser, it binds to
  loopback only, requires a per-launch token, and checks the request origin. Files
  are attached by upload; the page never sends a path for the server to read.

### Extension interface

The SDK's job becomes extending SourceSift, in Python. Sources, widgets, and data
shapes are ordinary typed Python objects, and built-ins are defined exactly the
way a user's would be:

```python
# ~/.config/sourcesift/extensions.py, named by [extensions].files in config.toml
from sourcesift import TimeSeries, source, widget

@source(id="my-metrics", ...)
async def my_metrics(params, context): ...

@widget(id="sparkline", accepts=TimeSeries, ...)
def sparkline(data, options): ...
```

- An extension file is loaded only when the configuration names it; nothing is
  picked up from the working directory. It is trusted Python running in the
  application process, so the guarantee that the model has no file or shell access
  describes the built-ins, not arbitrary extensions.
- Package discovery through the `sourcesift.plugins` entry point (section 4) comes
  after the interface has held still across at least three built-in sources and
  three widgets. Until then it is documented as unstable.
- Deliberately not extensible: the agent loop, the fetcher and its network rules,
  and citation checking.

### Order of work

1. Data shapes, typed sources, widgets, the `show` tool, and `Result.blocks` in
   the core; port Hacker News and Treasury. `ssift ask --json` gains `blocks`.
2. `ssift web` with chat, citations, sources, and the `chart` block, shown with
   Treasury debt over time (no API key, no open access question).
3. Weather, shown with `stat` and `map` widgets, and the Treasury series shown
   with a second widget. Reusing widgets across sources is the test of the design.
4. Stock prices with a live `chart`.
5. Load extension files, then package discovery; rewrite the SDK guide around
   extending.
6. Remove the Textual chat.

### Open questions

- **Robots and public APIs.** Open-Meteo and the US National Weather Service
  disallow all agents on their API hosts. Step 3 needs a decision on exempting
  built-in data sources from the robots check.
- **Stock data.** Free quotes generally require an API key and have usage terms.
  Step 4 needs a provider chosen and a place for user-supplied keys in settings.
- **One tool or one per source.** A single `query_source` keeps the tool list
  fixed; a tool per source gives the model a native schema for each. The proposal
  picks the single tool and should be revisited if models misuse it.
- **How small the shape vocabulary can stay.** Generic shapes make widgets
  reusable but flatten domain detail; a radar map is not a generic `GeoPoints`
  view. The rule above (generic first, a source-specific shape when needed) needs
  testing against weather.
- **Placement.** Blocks are listed after the answer, in the order the model
  showed them. Placing a block inside the prose is possible later.
- **Saved conversations.** Whether blocks are stored with a saved conversation
  or rebuilt on reopen.
