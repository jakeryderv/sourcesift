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

The application provides a Python SDK, a Cyclopts CLI, and a local web app. One-off
requests run without an application database or saved conversation history. Configuration and
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
| Interactive interface | Local web app (Starlette) |
| Figures / export | Matplotlib / optional Quarto |
| Native optimization | Optional Rust, after profiling |

## 2. Architecture and Request Flow

```text
User request + optional context
              │
              ▼
CLI / web app / Python SDK
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
└── Structured result → answer, references, figures, artifacts, limitations
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
references, figures, artifacts, selected source IDs, the research window, and
HTTP request count.
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

`ssift web` serves the interactive interface over the shared session runtime; see
[section 11](#11-web-app-figures-and-artifacts). A bare `ssift` shows help. Plugin
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

The web server calls `Session.run()` and forwards UI-independent
status/step/draft/reset events to the page. Drafts remain provisional until
citation validation completes; the page replaces them with the final `Result`, or
discards them on error/cancellation. The core imports no web or UI types.
Personal guidance is explicitly selected through `[context].instructions_file`;
other files and web content stay research material. Context is loaded once per
session; reset reloads it atomically. Per-turn attachments are read and
validated at submission, then passed as ordinary `Request.context` documents to
the same session runtime. See the [web app guide](web.md) for the user-facing contract.

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
| Web app | Starlette, uvicorn, markdown-it-py |
| Figures / artifact export | Matplotlib / Quarto (optional) |
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
Conversations are saved as files (section 11); automatic preference learning is a
separate addition.

Rust native modules should follow measured bottlenecks,
remain behind Python interfaces, and include a platform-wheel distribution plan.

Email integrations, general crawling, browser automation, semantic/vector search,
complex multi-agent orchestration, and hosted services remain deferred. The local
web application is described in [section 11](#11-web-app-figures-and-artifacts). Product scope is maintained in [use-cases.md](use-cases.md); sequencing
and completion criteria belong in [roadmap.md](roadmap.md).

## 11. Web App, Figures, and Artifacts

This section records the design built in November 2026. It replaced the Textual
chat, Markdown reports, and Plotly widgets with fewer parts that share one core.

### Interfaces

There are three ways in, and every one calls the same `SourceSift` and `Session`
objects:

| Interface | Role | State |
|---|---|---|
| Python SDK | The core; everything else is built on it | Whatever the caller keeps |
| `ssift ask` | One request from a script or pipe | None |
| `ssift web` | The interactive interface | Saved conversations |

There is no terminal chat. A second interactive interface had to repeat every
feature of the first (sources, evidence, saving, visuals), and the two drifted.
The rule for new work: a capability goes into the core first, and an interface
only presents it.

### What a turn can produce

```text
query_source ──► evidence [S1]  +  tables
                                     │
make_figure(evidence, kind, x, y) ──►│──► Figure F1 (recipe + rows)
                                          │
answer text  ──── cites [S1], places ![…](F1)
write_artifact(title, markdown) ──► Artifact A1, cites and places the same way
```

- **Evidence** is what was retrieved. Only evidence can be cited.
- **A table** is plain rows and columns a live data source returns beside its
  text. Its columns are described to the model; its values are not something the
  model can change.
- **A figure** is a recipe (kind, columns, title) plus the table it is drawn
  from. Python draws it with Matplotlib as a PNG. One drawing routine serves the
  web page, saved artifacts, and SDK callers, so a figure looks the same
  everywhere and needs no browser.
- **An artifact** is a Markdown document with a title, kept across turns and
  revised by ID.

`Result` carries `answer`, `references`, `figures`, and `artifacts`. Figures and
artifacts replaced `Result.blocks`.

### Why the model gets no file or code tool

The model's only way to produce a document is `write_artifact(title, markdown)`.
The application validates the text and writes every file. This keeps three
properties:

1. **Numbers come from sources.** A chart is drawn from retrieved rows by fixed
   code. The model cannot supply plotted values or plotting code.
2. **Exports run nothing.** Artifacts are saved as Quarto (`.qmd`) files, a
   format that can execute code cells. The application rejects cells, inline
   code, shortcodes, and raw blocks on the way in, and writes a header that
   turns execution and raw HTML/LaTeX off. Both must fail for retrieved or
   model-written text to run during an export.
3. **Citations are checked.** An artifact citing an unknown evidence ID, or
   placing an image that is not a figure from this conversation, is refused and
   the model is told why.

### Why Quarto, and why optional

Quarto turns one Markdown file into HTML, PDF, Word, and slides, and formats
citations from a bibliography. SourceSift writes `[S1]` as `[@S1]` and the
references as CSL JSON, so the reference list is Quarto's work rather than
ours. Quarto is a separate program of several hundred megabytes, so it is never
required: without it an artifact is still a readable Markdown file, the web page
renders artifacts itself with the same Markdown renderer as answers, and only
the export actions are hidden.

### Storage

Files, not a database:

```text
<data dir>/sessions/<ID>/conversation.json   history, evidence, figures, artifacts
<data dir>/sessions/<ID>/meta.json           title and counts for listing
<data dir>/sessions/<ID>/artifacts/          .qmd files, references.json, figures/
<data dir>/artifacts/<time>-<title>/         artifacts saved by `ssift ask --artifact`
```

`conversation.json` is the record; the `artifacts/` folder is written from it
after each change and can be regenerated. The web app saves by default because a
conversation list is only useful if conversations persist; `ssift ask` saves
nothing unless asked.

### The web app

A Starlette server on the loopback address serves a page with three parts: the
conversation list, the chat, and a side pane for an artifact, the evidence, or
the sources. Markdown is rendered on the server with raw HTML disabled, and
figures are embedded as images, so the page never parses model text as HTML and
loads nothing from another host. Access rules are in the
[web app guide](web.md#access-and-privacy).

### Dropped, and what would bring it back

| Dropped | Reason | Would return as |
|---|---|---|
| Interactive Plotly charts | A second renderer in the browser, and no export path | An optional interactive view built from the same figure recipe |
| Maps and the radar layer | Needed outside tile services and could not be exported | A figure kind drawn in Python, if a use appears |
| `table` and `stats` widgets | Markdown tables written by the model cover them | A table embed that copies rows from a source table, if models mistranscribe values |
| Widgets as an extension point | One figure tool is enough so far | A plugin interface, with Phase 5 |

### Open questions

- Whether artifacts need a table embed that copies source rows, so that numbers
  in a written table get the same guarantee as numbers in a chart.
- Loading data source files from configuration and installed plugins into
  `ssift web`.
- Uploading files in the page, and choosing the model there.
