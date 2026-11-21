# Command line

Install SourceSift, set `OPENROUTER_API_KEY` securely in your environment, and choose
an OpenRouter model. For example:

```sh
export SOURCESIFT_MODEL=openai/gpt-6.1-sol
export SOURCESIFT_REASONING_EFFORT=medium
ssift ask "Check news"
ssift ask "Check only Ars Technica for recent AI developments"
ssift ask "Check marketing for my project" --file project.md
ssift ask "Summarize this document" --file report.md
cat report.md | ssift ask "Summarize this" > summary.md
ssift ask "Summarize this" < report.md
```

For a development checkout, prefix commands with `uv run --locked`.
`python -m sourcesift` is equivalent to `ssift`. See `ssift --help`,
`ssift ask --help`, and `ssift --version`.

## Options

| Option | Meaning |
|---|---|
| `--file`, `-f` | UTF-8 text/Markdown file; repeat for additional files |
| `--config` | Explicit TOML configuration file |
| `--model` | OpenRouter model ID overriding environment/config |
| `--reasoning-effort` | Optional model-supported reasoning effort |
| `--format markdown` | Markdown answer, the default |
| `--format plain` | Plain-text answer without terminal styling |
| `--json` | One JSON object: answer, references, notes, usage, and retrieval details |
| `--debug` | On a model failure, also print the raw provider response to stderr |

The prompt is required. Put `--` before a prompt that starts with a dash.
Configured background, explicit files, and piped stdin can be combined; see
[configuration and limits](configuration.md). Stdin is read only when redirected,
so an ordinary terminal call never prompts for additional input. Files and stdin
are context for the task, not replacements for the prompt.

Answers, cited references, date windows, and disclosed limitations go to stdout. Errors go to stderr. There are no
progress messages in the answer stream, and output is buffered until the request
succeeds. Use shell redirection to save output. Plain rendering removes Markdown
styling and may reflow text; use Markdown when preserving source formatting matters.

## JSON output

`--json` prints the same `Result` the [SDK](sdk.md) returns as a single JSON object,
so other programs can use the references without parsing text:

```sh
ssift ask "Check news" --json | jq '.references[] | {id, title, url}'
```

| Field | Content |
|---|---|
| `answer` | The answer text, with `[S1]`-style citation IDs |
| `references` | Cited evidence: `id`, `title`, `url`, `publisher`, dates, `kind`, and per-item `limitations` |
| `limitations` | Notes about coverage, freshness, and retrieval gaps |
| `selected_sources`, `window` | The catalog sources read and the date window applied |
| `usage`, `model`, `http_requests` | Model token counts, model ID, and the number of HTTP requests made |

`--format` still controls how the model writes `answer`. Errors are reported on
stderr with the usual exit codes, and stdout stays empty.

## Exit codes and troubleshooting

| Code | Meaning | Action |
|---|---|---|
| `0` | Usable answer, possibly with disclosed limitations | Read any notes in the answer |
| `1` | Model/provider/timeout failure | Check access, credits, limits, and service availability |
| `2` | Invalid invocation, configuration, credentials, or input | Correct the reported input; inspect `--help` |
| `130` | Interrupted with Ctrl-C | Retry if desired |
| `141` | Downstream pipe closed | Normal when the consuming command exits early |

Missing `OPENROUTER_API_KEY` or model selection is diagnosed before inference.
Provider authentication failures and rate limits fail without automatic retries.
A model failure reports the HTTP status and OpenRouter's own short error message,
for example `(HTTP 404: No endpoints found for …)`. The raw provider response is
left out because it can echo request content; add `--debug` to print it to stderr
with the API key redacted. `ssift chat --debug` shows it in the failed turn.
Do not put API keys in prompts, files, CLI flags, or committed configuration.

Research uses the [registered source catalog](research.md); there are no topic or
source flags. Direct public HTML URLs can be supplied in the prompt, for example
`ssift ask "Summarize this article: https://example.com/article"` with a real URL.
Publisher restrictions, missing dates, and partial coverage appear as notes.
An unsuccessful retrieval returns an inability to verify information (exit `0`),
with no invented current-news briefing. A model failure still exits `1`.

The default total timeout is 60 seconds. For longer research requests, increase
`[limits].timeout_seconds` in configuration; the live evaluation uses 180 seconds.

## Interactive terminal chat

Run `ssift chat`, optionally with `--config`, `--model`, `--reasoning-effort`, and
repeatable `--file/-f`. It requires terminal stdin and stdout; use `ask` for pipes.
A bare `ssift` opens chat when stdin and stdout are terminals; otherwise it shows
help. `ssift --help` always shows help. Missing model/key settings open an in-app
setup panel. See [interactive chat](chat.md) for fuzzy slash commands, `@` file
attachments, personal context, cancellation, and session limits.
