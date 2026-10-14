
# SourceSift — Design Document

**Python-first, plugin-driven, Rust-accelerated personalized content discovery agent.**

## 1. Overview

SourceSift discovers, extracts, evaluates, and ranks content from configurable sources based on user interests and preferences.

The application provides a reusable Python SDK, extensible plugin ecosystem, and command-line interface, with optional native Rust components and a future terminal UI.

### Project Information

| Property | Decision |
|---|---|
| Repository / Package | `sourcesift` |
| CLI Command | `ssift` |
| Primary Language | Python |
| Secondary Language | Rust (optional) |
| Package Manager | uv (`uv init --lib`) |
| Distribution | PyPI |
| Agent Framework | PydanticAI |
| Model Provider | OpenRouter |
| CLI Framework | Cyclopts |
| Storage | SQLite + FTS5 |
| Architecture | Plugin-first, local-first |

## 2. Architecture

```text
Interfaces
├── Python CLI (Cyclopts)
└── Rust TUI (Ratatui, later)
          │
          ▼
Python Core / API / SDK
├── Application lifecycle & configuration
├── Plugin registry & discovery
├── Workflow orchestration
├── Agent integration
└── Public SDK interfaces
          │
          ├── Fixed Agent Foundation
          │   └── PydanticAI
          │       └── OpenRouter
          │
          ├── Plugin Capabilities
          │   ├── Sources
          │   ├── Extractors
          │   ├── Tools
          │   ├── Workflows
          │   ├── Rankers
          │   └── CLI Commands
          │
          ├── Storage
          │   └── SQLite + FTS5
          │
          └── Rust Native Modules (optional)
              └── PyO3 / Maturin
```

The Python core coordinates the application. Interfaces and plugins interact through public SDK contracts rather than directly depending on internal implementations.

## 3. Core Design

### Fixed Foundation

The following components remain concrete rather than interchangeable:

- **Python Core:** Application lifecycle, configuration, orchestration, and plugin management.
- **PydanticAI:** Agent execution, tool calling, structured outputs, and context management.
- **OpenRouter:** Model provider, with configurable model selection.
- **Cyclopts:** Python CLI framework.
- **SQLite + FTS5:** Local persistence and full-text search.

### Plugin-Driven Capabilities

Application functionality is exposed through standardized plugin interfaces.

Built-in and third-party plugins use the same contracts.

| Capability | Responsibility |
|---|---|
| Source | Discover content from feeds, websites, or external services |
| Extractor | Retrieve and normalize article content |
| Tool | Expose callable functionality to PydanticAI agents |
| Workflow | Coordinate processing, evaluation, and other operations |
| Ranker | Implement relevance scoring and ranking strategies |
| Command | Extend the `ssift` CLI |

A plugin may register multiple capabilities.

### Plugin System

- Python-based plugin interfaces and registration.
- Built-in functionality implemented through the same interfaces.
- Third-party plugin discovery via Python package entry points.
- Plugins managed through a central registry.
- SourceSift adapts registered tools to PydanticAI internally.
- Public plugin contracts remain independent of PydanticAI internals.

Example third-party package:

```toml
[project.entry-points."sourcesift.plugins"]
reddit = "sourcesift_reddit:RedditPlugin"
```

Advanced dependency management, sandboxing, permissions, and hot reloading are deferred.

## 4. Content Processing Pipeline

```text
Configured Sources
(RSS / Atom, websites, article URLs)
          │
          ▼
Discovery & Ingestion
          │
          ▼
Article Extraction
(Normalize, deduplicate, extract metadata)
          │
          ▼
Agent Evaluation
(PydanticAI + OpenRouter)
├── Evaluate relevance
├── Categorize content
├── Rank importance
└── Retrieve additional context when needed
          │
          ▼
Storage & Indexing
(SQLite + FTS5)
          │
          ▼
SDK / CLI
(Browse, search, configure, provide feedback)
```

Deterministic operations use standard Python workflows. Agent execution is reserved for tasks requiring model judgment, reasoning, or conditional tool usage.

### Initial Source Support

- RSS/Atom feeds.
- Automatic feed discovery from website URLs.
- Direct article URLs.
- Basic website article discovery where supported.

General-purpose crawling, email integrations, authentication-heavy sources, and browser automation are deferred.

## 5. Technology Stack

| Component | Technology |
|---|---|
| Core / SDK | Python, Pydantic |
| Agent Runtime | PydanticAI |
| Model Provider | OpenRouter |
| Workflow Orchestration | Python (`async`/`await`) |
| CLI | Cyclopts |
| Configuration | pydantic-settings |
| RSS/Atom Parsing | feedparser |
| Source Discovery | Trafilatura |
| HTTP Requests | HTTPX |
| Article Extraction | Trafilatura |
| Storage | SQLite |
| Search | SQLite FTS5 |
| Plugin Discovery | `importlib.metadata` |
| Testing | pytest |
| Rust Bindings | PyO3 + Maturin (optional) |
| TUI | Rust + Ratatui (later) |
| Build / Distribution | uv + PyPI |

## 6. Repository Structure

```text
sourcesift/
├── pyproject.toml
├── Cargo.toml                 # Optional Rust workspace
├── README.md
├── docs/
│   └── design.md
├── src/
│   └── sourcesift/
│       ├── __init__.py
│       ├── core/              # Lifecycle & orchestration
│       ├── agents/            # PydanticAI integration
│       ├── plugins/
│       │   ├── base.py       # Plugin contracts
│       │   ├── registry.py   # Registration & discovery
│       │   └── builtin/      # Built-in capabilities
│       ├── models/            # Data models & schemas
│       ├── storage/           # SQLite persistence & search
│       ├── cli/               # Cyclopts commands
│       └── _native/           # Rust bindings (optional)
├── rust/                      # Optional / later
│   ├── native/                # PyO3 modules
│   └── tui/                   # Ratatui executable
└── tests/
```

## 7. Public API / SDK

SourceSift exposes reusable Python interfaces for configuring, extending, and running the application.

Illustrative usage:

```python
from sourcesift import Agent, Config, Source

agent = Agent(config=Config())

agent.add_source(Source("https://example.com/feed.xml"))
agent.run()
```

Plugin registration example:

```python
from sourcesift import Plugin

class CustomPlugin(Plugin):
    def setup(self, app):
        app.register_source(CustomSource())
        app.register_tool(CustomTool())
```

These examples describe proposed interfaces, not implemented functionality.

## 8. CLI

The CLI is implemented in Python using Cyclopts and directly uses the SourceSift core/SDK.

### Planned Commands

```bash
ssift source add https://example.com
ssift source list

ssift ingest
ssift search "AI developments"

ssift plugin list
ssift plugin enable example

ssift run daily-briefing
ssift config
```

The plugin system may register additional commands or subcommands through SourceSift-defined interfaces.

### Entry Point

```toml
[project.scripts]
ssift = "sourcesift.cli:main"
```

## 9. Rust Integration

Rust is optional and serves two distinct purposes.

### Native Modules

- Performance-sensitive implementations.
- Exposed to Python through PyO3/Maturin.
- Internal implementations remain hidden behind stable Python interfaces.
- Introduced when beneficial rather than required from the beginning.

### Terminal UI

- Separate Rust frontend using Ratatui.
- Communicates with the Python application through subprocess/IPC.
- Uses the same core functionality as the Python CLI.
- Deferred until the core application is functional.

## 10. Initialization & Distribution

Initialize the project:

```bash
uv init --lib sourcesift
cd sourcesift
```

Install initial dependencies:

```bash
uv add "pydantic-ai-slim[openrouter]"
uv add pydantic-settings cyclopts
uv add httpx feedparser trafilatura
uv add --dev pytest
```

Development:

```bash
uv run ssift --help
```

Future PyPI distribution:

```bash
uv tool install sourcesift
ssift
```

Compiled Rust components, when introduced, will require appropriate platform-specific build and wheel distribution.

## 11. Design Principles

- **Python-first:** Core, SDK, plugins, and CLI use Python.
- **Plugin-first:** Application capabilities are composable and extensible.
- **Fixed agent foundation:** PydanticAI + OpenRouter remain the supported runtime/provider.
- **Shared contracts:** Built-in and third-party plugins use the same interfaces.
- **Source-agnostic:** Content retrieval is not coupled to a specific website or service.
- **Simple orchestration:** Standard Python coordinates workflows; agents handle model-driven decisions.
- **Extensible SDK:** Developers can implement sources, extractors, tools, workflows, rankers, and commands.
- **Rust-accelerated:** Optional native implementations remain behind Python interfaces.
- **Interface-independent:** CLI and future TUI reuse the same application functionality.
- **Local-first:** SQLite persistence without requiring a server.
- **Unified distribution:** PyPI provides the primary installation mechanism.

## 12. Development Priorities

1. **Core Foundation** — Configuration, lifecycle, data models, and plugin registry.
2. **Source Plugins** — RSS/Atom feeds, website discovery, article retrieval and extraction.
3. **Agent Integration** — PydanticAI + OpenRouter, tool registration, structured article evaluation.
4. **Storage & Search** — SQLite persistence, deduplication, preferences, and FTS5.
5. **Workflows** — Source ingestion, article evaluation, recommendations, and search.
6. **Python SDK / CLI** — Public interfaces and Cyclopts commands.
7. **Plugin Ecosystem** — Entry-point discovery, registration, and third-party extension support.
8. **Rust Native Modules (optional)** — Optimized components using PyO3/Maturin.
9. **Rust TUI (later)** — Ratatui frontend.
10. **PyPI Release** — Package, test, and distribute SourceSift.

## 13. Initial Scope

### Included

- Python core, public SDK, and CLI.
- PydanticAI + OpenRouter.
- Plugin registry and built-in plugins.
- RSS/Atom, website, and article URL support.
- Article extraction, categorization, and relevance ranking.
- SQLite storage and full-text search.
- User interests, preferences, and basic feedback.
- Basic third-party plugin support.

### Deferred

- Email/newsletter account integrations.
- General-purpose web crawling and browser automation.
- Advanced preference learning.
- Vector database and semantic search.
- Complex multi-agent orchestration.
- Plugin sandboxing and advanced dependency management.
- Rust acceleration unless justified.
- Rust TUI.
- Web application and HTTP server.

