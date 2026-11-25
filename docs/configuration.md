# Configuration and context

The SDK and research runtime use one settings model for Python and the CLI.

## Location and precedence

The optional default file is `config.toml` in the platform's per-user `sourcesift`
configuration directory: `$XDG_CONFIG_HOME/sourcesift/` (normally
`~/.config/sourcesift/`) on Linux, `~/Library/Application Support/sourcesift/` on
macOS, and `%LOCALAPPDATA%\sourcesift\` on Windows. Use `SOURCESIFT_CONFIG` or an
explicit config path to select a different file. An explicitly selected file must
exist. Project directories and `.env` files are not searched automatically.

Settings resolve from defaults, then TOML, supported environment variables, and
explicit CLI/SDK overrides. An explicit config path overrides `SOURCESIFT_CONFIG`;
only that selected file is loaded. Unknown settings are rejected.

```toml
[agent]
model = "openai/gpt-6.1-sol"
reasoning_effort = "medium"

[context]
instructions_file = "context.md" # optional personal priorities and response preferences
files = ["project.md"]          # optional background documents

[limits]
max_input_bytes = 131072
max_context_files = 16
timeout_seconds = 120
max_output_tokens = 8192
```

No model is chosen implicitly; a request without one fails with a message saying
how to set it. `SOURCESIFT_MODEL` overrides `[agent].model`.
`SOURCESIFT_REASONING_EFFORT` overrides `[agent].reasoning_effort`. Effort is optional;
omitting it uses the provider default. Accepted values are `none`, `minimal`, `low`,
`medium`, `high`, and `xhigh`; support depends on the selected model. The example
uses GPT-6.1 Sol at medium effort. Output token budgets can include reasoning tokens,
so increase the cap if the model exhausts it before producing an answer.
Set `OPENROUTER_API_KEY` in the process environment; credentials are not accepted
in TOML. SDK callers may pass a credential explicitly. Secrets are omitted from
settings representations and serialization. Neither credentials nor document text
are logged by SourceSift.

## Context inputs

Configured `files` are optional background information. `instructions_file` is an
explicitly selected personal guidance file: interests, priorities, and response
preferences, subordinate to the current task and grounding rules. It is not
automatically discovered from `AGENTS.md` or a project directory. The prompt determines the
current task. Context order is personal guidance, configured background files, SDK-supplied documents,
explicit file inputs, and piped stdin. Configured paths are relative to the TOML
file; explicit paths are relative to the working directory. `~` expands to the
user's home directory. Files must be regular UTF-8 text or Markdown files; PDF,
images, and other binary formats are not supported.

The input budget counts UTF-8 bytes in the prompt, document labels, and document
text together. Files and stdin are read with bounded sizes. Over-limit inputs are
rejected rather than truncated. The context count includes guidance, background files, SDK
documents, explicit files, and a supplied stdin stream. Empty stdin adds no document.
The configuration must be a regular file and has a 64 KiB limit.

The total timeout covers model calls and retrieval within one run. The output
cap applies to each model response. Input bytes are not model tokens: a model may
have a smaller context window. Context and retrieved evidence are sent to the
selected model through OpenRouter. Local configuration does not mean offline inference.

## Artifacts

```toml
[artifacts]
directory = "artifacts" # relative to this TOML file; `~` expands
```

`ssift ask --artifact` saves each run's [artifact files](research.md#artifact-files)
in a new folder here. Without this setting they go to `artifacts/` in the
platform's per-user `sourcesift` data directory:
`$XDG_DATA_HOME/sourcesift/artifacts/` (normally
`~/.local/share/sourcesift/artifacts/`) on Linux, `~/Library/Application
Support/sourcesift/artifacts/` on macOS, and
`%LOCALAPPDATA%\sourcesift\artifacts\` on Windows. The directory is created
when the first artifact is saved. Artifacts of a saved web conversation are kept
with that conversation instead.

## Saved conversations

```toml
[sessions]
save = false           # true also saves SDK sessions that do not ask for it
directory = "sessions" # relative to this TOML file; `~` expands
```

`ssift web` saves every conversation unless started with `--no-save`. SDK
sessions are kept in memory unless `save` is true here or `save=True` is passed.
Saved conversations go to `sessions/` in the same per-user data directory as
artifacts unless `directory` is set. Each conversation is a folder named by its
start time:

```text
sessions/20261125-194036-873c0947/
  conversation.json   prompts, answers, evidence, figures, artifacts
  meta.json           title and counts, for the conversation list
  artifacts/          the conversation's artifact files
```

A conversation holds the prompts, answers, retrieved evidence text, and attached
document text, so the folder is readable by your user only. Credentials and
settings are never saved. Files saved by version 0.6 (one `.json` file per
conversation, directly in the directory) are left in place but are not listed or
reopened.

## Sources and freshness

```toml
[sources]
timezone = "America/Chicago" # default UTC; explicit IANA zone, not inferred locally
recent_days = 7
disabled = ["cnbc"]         # registered IDs; misspellings are errors

[[sources.custom]]
id = "example-publication"
name = "Example Publication"
website = "https://example.com/"
feeds = ["https://example.com/feed.xml"] # replace with real public URLs
description = "Research and developments in my field."
topics = ["research"]
geography = "United States"
capabilities = ["feed", "article"]
```

Custom definitions participate in normal semantic selection. Duplicate IDs, names,
or aliases are rejected. Omit `feeds` to discover declared RSS/Atom links on the
website. `disabled` applies before selection; it is not a prompt keyword filter.
See [research](research.md) for exact window and date rules.

## Research budgets

All are `[limits]` settings. Existing input limits above remain unchanged.

| Setting | Default | Meaning |
|---|---:|---|
| `timeout_seconds` | 120 | Total wall-clock timeout for model and retrieval |
| `max_output_tokens` | 8192 | Per-model-response output/reasoning budget |
| `max_model_requests` | 6 | All calls, including tool continuations and citation repair |
| `max_tool_calls` | 8 | Total agent tool calls |
| `max_sources` | 3 | Distinct registered sources attempted |
| `max_items` | 18 | Distinct evidence items retained |
| `max_items_per_source` | 6 | Accepted entries per source, most recent dated first |
| `max_articles` | 6 | Article attempts, including failures |
| `max_figures` | 4 | New [figures](research.md#figures) in one turn |
| `max_artifact_chars` | 40000 | Length of one [artifact](research.md#artifacts) |
| `max_http_requests` | 24 | Requests including robots and redirects |
| `http_timeout_seconds` | 10 | One fetch, including DNS, robots, redirects, and body |
| `max_response_bytes` | 2097152 | Decoded response-body byte limit |
| `max_item_chars` | 10000 | Text per evidence item |
| `max_evidence_chars` | 60000 | Total retained evidence text |

HTTP and provider retries are disabled. Tools execute sequentially. HTTP allows
at most four redirects per fetch; parsing examines at most 200 feed entries and
discovery retains at most four declared feeds. One model retry can repair missing
or unknown citations, within the request limit. Tool/model budget exhaustion is a
model error; HTTP/source/evidence limits produce partial-coverage notes.

For longer research or long artifacts, a 180-second total timeout can help; the
live evaluation uses 180 seconds and 4096 output tokens. Raising limits increases possible latency
and provider cost. The SDK validates upper bounds on every numeric budget.

## Session limits and context reload

`ssift web` and `app.session()` snapshot configured context and initial files at
creation. They keep that text stable until reset. A reset clears completed
history and reloads those files; an unreadable file preserves the previous session.
Change model/source configuration by restarting the server or creating a new application.
One-off `ask` continues to load files for each request.

| Setting under `[limits]` | Default | Meaning |
|---|---:|---|
| `max_session_turns` | 20 | Maximum completed turns before starting fresh |
| `max_session_bytes` | 524288 | Serialized history/evidence budget, also checked with the next request payload |
| `feed_cache_seconds` | 600 | How long a conversation reuses a fetched feed before requesting it again; `0` disables |

All research budgets above apply per turn, including newly collected evidence.
Within one conversation a feed fetched in the last `feed_cache_seconds` is reused
without a new request, and its evidence keeps the original retrieval time. Articles
are always retrieved again. The cache is held in memory and cleared by a reset;
`ssift ask` does not use it.

History and retained evidence are separately bounded by `max_session_bytes`.
Bytes are a conservative application guard, not a tokenizer or a guarantee that
every provider context window fits. Over-limit turns fail without changing completed
history. Sessions are never silently truncated or summarized.
