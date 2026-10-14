# Command line

Install SourceSift, set `OPENROUTER_API_KEY` securely in your environment, and choose
an OpenRouter model. For example:

```sh
export SOURCESIFT_MODEL=openai/gpt-6.1-sol
export SOURCESIFT_REASONING_EFFORT=medium
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

The prompt is required. Put `--` before a prompt that starts with a dash.
Configured background, explicit files, and piped stdin can be combined; see
[configuration and limits](configuration.md). Stdin is read only when redirected,
so an ordinary terminal call never prompts for additional input. Files and stdin
are context for the task, not replacements for the prompt.

Answers and disclosed limitations go to stdout. Errors go to stderr. There are no
progress messages in the answer stream, and output is buffered until the request
succeeds. Use shell redirection to save output. Plain rendering removes Markdown
styling and may reflow text; use Markdown when preserving source formatting matters.

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
Do not put API keys in prompts, files, CLI flags, or committed configuration.

Phase 1 analyzes supplied text. It cannot fetch URLs, select news sources, or
verify current reporting. Every result includes a note about that limitation.
