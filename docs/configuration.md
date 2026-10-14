# Configuration and context

Phase 1 uses one settings model for Python and the CLI. The SDK/CLI execution
interfaces are being implemented; configuration and context loading are available.

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
model = "provider/model-id" # Replace with an available OpenRouter model ID.

[context]
files = ["context.md"]

[limits]
max_input_bytes = 131072
max_context_files = 16
timeout_seconds = 60
max_output_tokens = 2048
```

No model is chosen implicitly. `SOURCESIFT_MODEL` overrides `[agent].model`.
Set `OPENROUTER_API_KEY` in the process environment; credentials are not accepted
in TOML. SDK callers may pass a credential explicitly. Secrets are omitted from
settings representations and serialization. Neither credentials nor document text
are logged by SourceSift.

## Context inputs

Configured files are optional background information. The prompt determines the
current task. Context order is configured background files, SDK-supplied documents,
explicit file inputs, and piped stdin. Configured paths are relative to the TOML
file; explicit paths are relative to the working directory. `~` expands to the
user's home directory. Files must be regular UTF-8 text or Markdown files; PDF,
images, and other binary formats are not supported.

The input budget counts UTF-8 bytes in the prompt, document labels, and document
text together. Files and stdin are read with bounded sizes. Over-limit inputs are
rejected rather than truncated. The context count includes background files, SDK
documents, explicit files, and a supplied stdin stream. Empty stdin adds no document.
The configuration file itself has a 64 KiB limit.

The model timeout and output cap apply to model execution. Input bytes are not
model tokens: a model may have a smaller context window. Phase 1 makes one model
request, with automatic provider and output retries disabled. All supplied text
is sent to the selected model through OpenRouter. Local configuration does not
mean offline inference.
