
# SourceSift — Development Roadmap

**Goal:** Incrementally build a Python-first, plugin-driven content discovery agent, prioritizing a usable CLI, ephemeral agent interactions, and extensibility before persistence or advanced infrastructure.

## Guiding Principles

- **Python-first:** Implement the core, API/SDK, and CLI entirely in Python initially.
- **Working software first:** Each phase should deliver independently usable functionality.
- **Stateless by default:** Avoid databases and persistent application state early.
- **CLI-first:** Prioritize terminal usability, scripting, stdin/stdout, and composability.
- **Plugin-driven:** Build functionality around shared interfaces for built-in and third-party capabilities.
- **Fixed agent foundation:** Use PydanticAI + OpenRouter throughout.
- **Incremental complexity:** Introduce Rust, persistence, and advanced orchestration only when justified.

---

## Phase 1 — Core Agent & CLI

**Goal:** Establish a minimal, functional agent accessible through Python and the `ssift` command.

### Implementation

- [ ] Initialize the Python library using `uv init --lib`.
- [ ] Establish basic project structure and configuration.
- [ ] Integrate PydanticAI with OpenRouter.
- [ ] Implement a minimal Python agent API/SDK.
- [ ] Implement Cyclopts CLI and PyPI entry point.
- [ ] Support ephemeral, single-turn prompts.
- [ ] Support reading prompts and context from files or stdin.
- [ ] Print responses to stdout, with diagnostics/errors on stderr.
- [ ] Support plain-text and Markdown output.
- [ ] Add basic tests.

### Example Usage

```bash
ssift ask "Explain the latest developments in AI"

ssift ask "Summarize this document" --file report.md

cat report.md | ssift ask "Summarize this"

ssift ask "Summarize this" < report.md

ssift ask "Summarize this" --file report.md > summary.md
```

These commands represent the intended CLI behavior, not implemented functionality.

### Deliverable

A functional, stateless Python agent with an importable API/SDK and a composable CLI.

**Milestone:** A user can provide a prompt and optional context, receive an agent response, and pipe or redirect that response to other programs.

---

## Phase 2 — Source Discovery & Retrieval

**Goal:** Enable agents to retrieve and use information from external sources.

### Implementation

- [ ] Implement HTTP retrieval using HTTPX.
- [ ] Support direct article URLs.
- [ ] Implement article text extraction using Trafilatura.
- [ ] Support RSS/Atom parsing using feedparser.
- [ ] Add website feed discovery.
- [ ] Normalize extracted content and metadata.
- [ ] Expose retrieval functionality as agent tools.
- [ ] Support source-aware prompts with references to retrieved content.
- [ ] Handle retrieval failures, timeouts, and unavailable content.

### Example Usage

```bash
ssift ask "Summarize this article" --url https://example.com/article

ssift ask "What are the recent developments in AI?" \
    --source https://example.com/feed.xml

ssift ask "Compare these sources" \
    --url https://example.com/article1 \
    --url https://example.org/article2
```

### Deliverable

An agent capable of retrieving, interpreting, and responding using external articles, websites, and feeds.

**Milestone:** SourceSift can answer questions grounded in explicitly supplied sources without requiring local storage.

---

## Phase 3 — Plugin Architecture & Public SDK

**Goal:** Make application capabilities extensible through a unified plugin system.

### Implementation

- [ ] Define public plugin interfaces and registration contracts.
- [ ] Implement a central plugin registry.
- [ ] Organize built-in functionality through plugin interfaces.
- [ ] Support source and extractor plugins.
- [ ] Support agent tool plugins.
- [ ] Define workflow extension interfaces.
- [ ] Support third-party plugin discovery using Python package entry points.
- [ ] Expose plugin functionality through the Python SDK.
- [ ] Add basic plugin inspection through the CLI.
- [ ] Create an example third-party plugin.

### Plugin Capabilities

| Capability | Purpose |
|---|---|
| Source | Discover content from external sources |
| Extractor | Extract and normalize source content |
| Tool | Provide callable functionality to agents |
| Workflow | Coordinate operations and agent execution |
| Ranker | Customize relevance scoring and filtering |
| Command | Extend CLI functionality |

Not every capability needs a complete implementation in this phase. Establish interfaces as concrete use cases emerge.

### Example Usage

```bash
ssift plugin list

ssift ask "Find relevant articles" --source https://example.com
```

Python SDK example:

```python
from sourcesift import Agent

agent = Agent()

# Plugins register additional tools and capabilities.
agent.run("Find articles about AI")
```

### Deliverable

A plugin-driven Python SDK where built-in and third-party functionality use the same extension interfaces.

**Milestone:** A developer can create and install a custom source or tool plugin without modifying SourceSift's core.

---

## Phase 4 — Interactive Agent & TUI

**Goal:** Extend ephemeral single-turn execution into interactive, multi-turn agent sessions.

### Implementation

- [ ] Implement reusable conversational session management in Python.
- [ ] Maintain message history and context within a running session.
- [ ] Support iterative tool calling and agent interactions.
- [ ] Implement basic context/window management.
- [ ] Support streaming responses.
- [ ] Add an interactive CLI conversation mode.
- [ ] Expose session operations through the Python SDK.
- [ ] Establish a frontend-independent interface for future TUI integration.
- [ ] Implement a terminal UI.

### TUI Options

- **Python-first:** Prototype using Textual, potentially replacing the frontend with Rust later.
- **Rust-first:** Build directly with Ratatui, using subprocess/IPC to communicate with the Python session runtime.

**Preferred approach:** Keep the conversational runtime in Python regardless of frontend implementation. Choose the TUI language based on development needs.

### Example Usage

```bash
ssift chat

ssift tui
```

### Deliverable

An interactive agent supporting multi-turn conversations, tool execution, source retrieval, and optional TUI interaction.

**Milestone:** A user can have a continuous, contextual conversation with SourceSift without requiring persistent storage.

---

## Phase 5 — Content Discovery & Agent Workflows

**Goal:** Expand from prompted retrieval to structured discovery, evaluation, and recommendations.

### Implementation

- [ ] Implement source ingestion workflows.
- [ ] Discover and process multiple articles from configured sources.
- [ ] Add article normalization and deduplication.
- [ ] Define structured article evaluation schemas.
- [ ] Evaluate relevance using PydanticAI.
- [ ] Categorize and rank retrieved articles.
- [ ] Support configurable, in-memory user interests and preferences.
- [ ] Generate personalized article recommendations.
- [ ] Add workflow plugins for custom processing pipelines.
- [ ] Establish evaluation tests for recommendation quality.

### Example Usage

```bash
ssift run discover --source https://example.com/feed.xml

ssift ask "Find articles relevant to AI and robotics" \
    --source https://example.com/feed.xml
```

### Deliverable

A configurable content discovery and recommendation agent operating without a persistent database.

**Milestone:** SourceSift can process multiple sources, evaluate articles, and produce personalized recommendations.

---

## Phase 6 — Persistence, Search & Personalization

**Goal:** Introduce durable application state once the core workflows and interfaces are established.

### Implementation

- [ ] Integrate SQLite for local persistence.
- [ ] Store configured sources and article metadata.
- [ ] Persist extracted articles, evaluations, and recommendations.
- [ ] Add deduplication across ingestion runs.
- [ ] Implement full-text search using SQLite FTS5.
- [ ] Persist user profiles, interests, and preferences.
- [ ] Support article feedback and recommendation history.
- [ ] Optionally persist conversational sessions.
- [ ] Add database migrations and maintenance commands.
- [ ] Keep storage interfaces separate from agent and plugin logic.

### Example Usage

```bash
ssift source add https://example.com/feed.xml

ssift ingest

ssift search "AI regulation"

ssift history
```

### Deliverable

A local-first content discovery application with durable storage, searchable history, and user personalization.

**Milestone:** SourceSift can accumulate knowledge across runs without requiring a server or external database.

---

## Phase 7 — Rust Integration & Optimization

**Goal:** Introduce native Rust functionality where it provides measurable benefits.

### Implementation

- [ ] Profile Python performance and identify bottlenecks.
- [ ] Add a Rust workspace if needed.
- [ ] Implement optimized native modules using PyO3.
- [ ] Integrate Rust extensions through Maturin.
- [ ] Preserve stable Python API/SDK interfaces.
- [ ] Build platform-specific wheels.
- [ ] Develop or refine the Ratatui frontend if selected.
- [ ] Test native components across supported platforms.

### Deliverable

An optionally Rust-accelerated SourceSift with the same public Python API.

**Milestone:** Native implementations improve performance or usability without introducing Rust-specific requirements for plugin developers.

---

## Phase 8 — Packaging, Release & Ecosystem

**Goal:** Prepare SourceSift for broader installation, reuse, and extension.

### Implementation

- [ ] Finalize public SDK contracts and documentation.
- [ ] Document plugin development and supported capabilities.
- [ ] Establish package versioning and compatibility policies.
- [ ] Configure CI for testing and release builds.
- [ ] Package compiled Rust components where applicable.
- [ ] Test `pip`, `uv`, and `uvx` installation workflows.
- [ ] Publish SourceSift to PyPI.
- [ ] Provide example plugins and workflows.
- [ ] Document CLI usage and configuration.
- [ ] Establish a contribution process.

### Installation

```bash
uv tool install sourcesift

ssift --help
```

### Deliverable

A documented, installable Python application and SDK with a usable CLI and extensible plugin ecosystem.

---

## Scope & Priorities

| Priority | Focus | Phases |
|---|---|---|
| P0 | Functional Python agent, SDK, and CLI | 1 |
| P1 | Source retrieval and grounded responses | 2 |
| P1 | Plugin architecture and extensibility | 3 |
| P1 | Interactive agent and TUI | 4 |
| P1 | Content discovery and recommendations | 5 |
| P2 | Persistent storage and search | 6 |
| P2 | Rust optimization | 7 |
| P2 | Production packaging and ecosystem | 8 |

## Deferred Features

- Email account and newsletter integrations.
- General-purpose web crawling and browser automation.
- Web application and HTTP server.
- Complex multi-agent orchestration.
- Vector databases and semantic search.
- Automatic long-term preference learning.
- Advanced plugin dependency management and sandboxing.
- Cloud infrastructure and hosted services.

## Initial Development Target

The first meaningful release should support:

```bash
ssift ask "Summarize this document" --file document.md > summary.md
```

Followed by source-aware retrieval:

```bash
ssift ask "Summarize recent articles" \
    --source https://example.com/feed.xml \
    > briefing.md
```

The goal is to establish a **composable, stateless agent with a reusable Python SDK and CLI**, then grow it into an interactive, plugin-driven discovery system.

**Core progression:**

`Python Agent + CLI → Sources & Retrieval → Plugins → Interactive Agent / TUI → Discovery Workflows → Persistence → Rust Optimization → Release`

