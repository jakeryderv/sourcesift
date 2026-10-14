# SourceSift — Use Cases & Product Philosophy

## 1. Purpose

SourceSift is a source-centric, plugin-driven information agent that discovers, retrieves, and evaluates information from configurable sources.

Its purpose is to help users stay informed, investigate topics, and discover relevant information without manually searching through numerous websites, feeds, or publications.

SourceSift combines:

- A curated collection of useful information sources.
- Metadata-driven source discovery and selection.
- Agent-powered research, analysis, and synthesis.
- User-defined context, interests, and preferences.
- An extensible Python SDK and plugin ecosystem.
- A composable command-line interface.

**Core philosophy:** Bring relevant information to the user from appropriate sources, rather than requiring the user to find and search each source individually.

## 2. Product Principles

### Sources First

Sources are first-class components of the system.

Each source describes what information it provides, which subjects and regions it covers, and how its content can be accessed.

SourceSift should understand source capabilities well enough to select appropriate sources for a given request.

### Plugin-Driven

Built-in functionality and third-party extensions use the same plugin interfaces.

Users can extend or customize:

- Sources and content providers.
- Extraction and retrieval methods.
- Agent tools and capabilities.
- Research and processing workflows.
- Relevance and ranking behavior.
- CLI functionality.

The plugin system extends SourceSift's capabilities without requiring replacement of its PydanticAI/OpenRouter foundation.

### Context-Driven Relevance

Relevance is defined primarily through explicit user-provided context rather than automatically learned preferences.

Users can describe their interests, occupation, industries, locations, priorities, and other relevant information.

This context guides source selection, evaluation, and response generation.

### Stateless by Default

SourceSift should provide useful results without requiring persistent storage or an application database.

Each request can retrieve current information, evaluate it, and return a response.

Caching, search indexes, historical tracking, and persistent sessions are optional future enhancements.

### Composable and Programmable

SourceSift should work through both its Python SDK and CLI.

CLI commands should support stdin/stdout, file inputs, Markdown output, and Unix piping/redirection.

## 3. Source Model

### Source Metadata

Each registered source can provide descriptive metadata for discovery, filtering, and agent selection.

| Metadata | Purpose | Examples |
|---|---|---|
| Name / ID | Identify the source | `example-news` |
| Description | Explain the source's purpose | General news coverage |
| Type | Describe its integration | RSS, website, API |
| Categories | Classify subject coverage | News, technology, finance |
| Industries | Identify specialized coverage | Marketing, healthcare, energy |
| Geography | Describe geographic coverage | Local, US national, global |
| Location | Identify geographic relevance | Oklahoma, Tulsa, United States |
| Language | Describe supported languages | English |
| Capabilities | Describe available operations | Latest articles, search, retrieval |
| Requirements | Describe access needs | Public, API key, authentication |

Metadata is descriptive and extensible, rather than a rigid classification system.

Sources may belong to multiple categories, industries, or geographic regions.

### Source vs. Article Metadata

Source metadata describes the source's general coverage and capabilities.

Article metadata describes an individual piece of content, such as its title, publication date, author, topic, and geographic relevance.

A source's categories should not automatically determine the categories of every article it publishes.

### Source Selection

SourceSift should use the user's prompt, configured context, and available source metadata to identify appropriate sources.

Selection may involve:

1. Understanding the information being requested.
2. Identifying relevant topics, industries, and geography.
3. Selecting appropriate available sources.
4. Retrieving and evaluating relevant content.
5. Producing a grounded response with source references.

Users should also be able to explicitly select or restrict sources.

## 4. Built-In Sources

SourceSift should ship with a curated collection of source definitions and integrations.

Built-in sources are configurable, optional, and implemented through the same interfaces available to third-party plugins.

### General News

Provide broad coverage of current events.

- **Local:** City, regional, and state coverage.
- **National:** United States news and current events.
- **Global:** International developments.

### Specialized Sources

Support focused information discovery across subjects and industries.

Initial categories may include:

- Technology and artificial intelligence.
- Business and economics.
- Finance and investing.
- Marketing and advertising.
- Science and research.
- Healthcare.
- Government and public policy.
- Other user-defined categories.

Sources may overlap across categories and geographic scopes.

### Source Quality

Prefer authoritative, reputable, and regularly maintained sources.

Distinguish primary reporting and official publications from commentary, aggregation, and secondary reporting.

Source metadata should support provenance and transparency without implying that any source is universally reliable.

Built-in source availability depends on working public feeds, APIs, or accessible website content.

## 5. User Context & Configuration

### User Context

Users explicitly provide information that helps SourceSift determine relevance.

Examples include:

- Professional background and industry.
- Topics and interests.
- Geographic location and preferred coverage.
- Organizations, companies, or technologies of interest.
- Research goals and priorities.
- Preferred response style or level of detail.

Context should be optional and controlled by the user.

### Configuration Philosophy

Configuration should be declarative, portable, and accessible through the Python SDK.

Potential configuration mechanisms:

- **TOML:** Human-readable application configuration.
- **Markdown:** Longer-form user context and preferences.
- **Python:** Programmatic configuration and customization.
- **Environment variables:** API keys and environment-specific settings.

A configuration file may reference external Markdown context files.

The same underlying configuration models should be available programmatically through the Python SDK.

### Illustrative Configuration

```toml
[agent]
model = "anthropic/claude-sonnet-4.6"

[context]
files = ["context.md"]

[sources]
categories = ["news", "technology", "finance"]
regions = ["us", "global"]
```

Example `context.md`:

```markdown
# User Context

## Background
I work in technology and artificial intelligence.

## Interests
- AI research and applications
- Robotics
- Technology industry developments
- Business and economics

## Geographic Focus
- Oklahoma and surrounding region
- United States
- Important global developments

## Priorities
Focus on significant developments, practical implications,
and information relevant to my interests.
```

These examples describe proposed configuration interfaces.

### Configuration Behavior

- Built-in defaults provide useful out-of-the-box behavior.
- Users can enable, disable, or configure sources.
- Custom sources and plugins can extend the defaults.
- CLI arguments can override relevant settings for individual requests.
- Python API users can construct and modify configuration programmatically.
- Markdown context files are loaded as task context, not executed as code.

Python configuration should be optional rather than necessary for ordinary use.

## 6. Primary Use Cases

### UC-01 — General News Discovery

**User story:** As a user, I want to ask about recent news so I can understand important developments without manually visiting multiple publications.

Example:

```bash
ssift ask "What are the major news stories today?"
```

Expected behavior:

- Select relevant general news sources.
- Retrieve recent reporting.
- Identify significant developments.
- Summarize findings with source references.
- Distinguish reporting from interpretation.

### UC-02 — Topic-Based Research

**User story:** As a user, I want to investigate a topic using relevant sources rather than manually searching for articles.

Example:

```bash
ssift ask "Any recent news about AI in healthcare?"
```

Expected behavior:

- Identify relevant subjects and categories.
- Select appropriate technology and healthcare sources.
- Retrieve recent information.
- Explain significant findings and developments.
- Provide links to supporting sources.

### UC-03 — Geographic News

**User story:** As a user, I want to discover news relevant to a particular location or geographic scope.

Example:

```bash
ssift ask "What's happening in Oklahoma this week?"
```

Expected behavior:

- Recognize geographic intent.
- Prefer sources covering the requested location.
- Retrieve geographically relevant reporting.
- Summarize local or regional developments.

Geographic context may come from the prompt or explicit configuration.

### UC-04 — Personalized Relevance

**User story:** As a user, I want SourceSift to incorporate my interests and professional context when identifying important information.

Example:

```bash
ssift ask "What recent developments should I know about?"
```

Expected behavior:

- Load configured user context.
- Identify relevant categories and sources.
- Evaluate information against the user's interests.
- Prioritize meaningful developments.
- Explain why selected information is relevant.

Relevance is derived from explicit context rather than requiring a persistent preference-learning system.

### UC-05 — Document-Guided Research

**User story:** As a user, I want SourceSift to use a document as context for finding related information.

Example:

```bash
ssift ask "Find recent developments related to this project" \
    --file project.md \
    > research.md
```

Expected behavior:

- Read the supplied document.
- Identify relevant subjects, organizations, and terminology.
- Select appropriate information sources.
- Retrieve related information.
- Produce a grounded response.
- Write the response to stdout.

### UC-06 — Explicit Source Research

**User story:** As a user, I want to restrict research to particular sources when necessary.

Example:

```bash
ssift ask "Summarize recent developments" \
    --source https://example.com/feed.xml
```

Expected behavior:

- Use the requested source.
- Retrieve relevant accessible content.
- Analyze the content.
- Provide references to retrieved material.

### UC-07 — Extending SourceSift

**User story:** As a developer, I want to introduce custom sources and capabilities without modifying the application's core.

Example:

```python
from sourcesift import SourceSift

app = SourceSift()

app.register_source(CustomSource())
app.register_tool(CustomTool())
```

Expected behavior:

- Accept implementations matching public SDK contracts.
- Register source metadata and capabilities.
- Make custom sources available for selection.
- Expose compatible tools to the agent.
- Preserve the fixed agent runtime and provider foundation.

The example API is illustrative.

### UC-08 — CLI Automation

**User story:** As a user, I want SourceSift to work within shell scripts and command-line workflows.

Example:

```bash
cat topic.md | ssift ask "Find recent related news" > news.md
```

Expected behavior:

- Accept standard input.
- Return useful Markdown or plain-text output.
- Write primary results to stdout.
- Write diagnostics and progress information to stderr.
- Use meaningful exit codes.
- Avoid requiring an interactive session.

## 7. Agent Responsibilities

The agent should focus on operations requiring contextual judgment.

Examples:

- Understanding user research intent.
- Selecting sources based on metadata and context.
- Deciding whether additional retrieval is necessary.
- Evaluating relevance.
- Synthesizing information from multiple sources.
- Identifying uncertainty and conflicting information.

Deterministic tasks should remain ordinary Python operations, including HTTP requests, parsing, normalization, configuration loading, and output formatting.

The initial foundation remains:

- **PydanticAI:** Agent runtime, tools, structured outputs.
- **OpenRouter:** Model inference and selection.
- **SourceSift:** Source registry, plugins, workflows, context, and SDK.

## 8. Persistence Philosophy

Persistent storage is not a prerequisite for SourceSift's primary use cases.

The initial design should support:

- Ephemeral prompts and responses.
- Source retrieval on demand.
- User-defined configuration and context files.
- In-memory source registries and session state.
- Direct terminal output and file redirection.

Potential future enhancements include:

- HTTP response and article caching.
- Source metadata caching.
- Historical article indexing.
- Persistent conversational sessions.
- Scheduled monitoring and change detection.
- Searchable local archives.

These features should be added when specific use cases justify them.

## 9. Initial Product Boundaries

### Included

- Curated, configurable built-in sources.
- RSS/Atom and direct website/article retrieval.
- Source metadata and category-based selection.
- Python SDK and plugin interfaces.
- PydanticAI + OpenRouter.
- Cyclopts CLI.
- User-defined context through configuration and Markdown.
- Stateless research and source-grounded responses.
- stdin/stdout and file-based workflows.

### Deferred

- Email/newsletter account integrations.
- Persistent article database and historical indexing.
- Automatic user preference learning.
- General-purpose crawling and browser automation.
- Cloud services and background scheduling.
- Advanced plugin permissions and sandboxing.
- Native Rust optimization.
- Rust TUI.
- Web application and HTTP server.

## 10. Success Criteria

SourceSift should be considered successful when users can:

1. Install the package and use `ssift` without extensive setup.
2. Ask open-ended questions about current information.
3. Retrieve relevant content from built-in or custom sources.
4. Narrow research by subject, industry, geography, or source.
5. Provide personal context through simple configuration or Markdown.
6. Receive grounded, useful responses with source references.
7. Pipe inputs and outputs through ordinary terminal workflows.
8. Extend the application through Python plugins and SDK interfaces.

The primary measure of success is whether SourceSift consistently discovers and presents relevant, trustworthy information with minimal user effort.

