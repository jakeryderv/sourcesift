# Python SDK

SourceSift can analyze supplied UTF-8 text and Markdown through OpenRouter. External
source selection, URL retrieval, and verified news research arrive in Phase 2.

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

`Result` contains `answer`, `limitations`, the configured `model`, and `usage`
(requests, input tokens, output tokens as reported by the runtime). Phase 1 always
reports that no external sources were retrieved. Model-generated answers are not
proof that current facts have been verified. Retrieval references will be added
with the evidence contracts in Phase 2.

Catch `ConfigurationError` or `InputError` to correct local input, and `ModelError`
for timeout, provider, or unusable-output failures. All derive from
`SourceSiftError`. Async cancellation propagates normally. SourceSift does not
retry model requests automatically or print provider response bodies in errors.
