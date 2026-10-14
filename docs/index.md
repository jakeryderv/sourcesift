# SourceSift

SourceSift is a planned Python-first research agent for requests such as
“check news” and “check tech.” It will select registered sources using their
links, metadata, descriptions, and optional user context.

The current package is an initial scaffold. It exposes only `hello()`; the SDK,
source retrieval, and `ssift` CLI described in the planning documents are not
implemented yet.

- [Use cases](use-cases.md) describe the intended users and behavior.
- [Design](design.md) describes the proposed architecture and interfaces.
- [Roadmap](roadmap.md) tracks implementation phases and completion criteria.
- [API reference](reference/index.md) documents only the code that exists today.

See the [repository README](https://github.com/jakeryderv/sourcesift#readme) for
installation, development commands, and the release workflow.

API reference content is generated from source docstrings during the documentation
build. The maintained Markdown pages remain in this repository; archived course
documents are excluded from the generated site.
