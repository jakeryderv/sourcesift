# SourceSift

SourceSift is a Python SDK and CLI with a planned source-aware research flow for
“check news” and “check tech.” It will select registered sources using their
links, metadata, descriptions, and optional user context.

Phase 1 implements single model requests with supplied text/Markdown context,
configuration, and composable output. Source selection, URL retrieval, and verified
current-news research are planned for Phase 2.

Start with the [CLI guide](cli.md), [Python SDK](sdk.md), and
[configuration reference](configuration.md).

- [Use cases](use-cases.md) describe the intended users and behavior.
- [Design](design.md) describes the proposed architecture and interfaces.
- [Roadmap](roadmap.md) tracks implementation phases and completion criteria.
- [API reference](reference/index.md) documents only the code that exists today.

See the [repository README](https://github.com/jakeryderv/sourcesift#readme) for
installation, development commands, and the release workflow.

API reference content is generated from source docstrings during the documentation
build. The maintained Markdown pages remain in this repository; archived course
documents are excluded from the generated site.
