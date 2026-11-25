# SourceSift

SourceSift is a research assistant with a local web app, a Python SDK, and a CLI for “check news,” “check tech,” and research
with explicit context. The model selects from registered source descriptions;
Python retrieves and normalizes evidence, preserves provenance, and supplies
references for the answer.

Phases 1 and 2 implement supplied-text analysis and bounded research across 31
sources covering US national and world news, technology, AI, science, health,
business, marketing, finance, and US policy and government.
See [research and sources](research.md) for the catalog, freshness rules, and limits.
Conversations run in `ssift web`, a local [web page](web.md); `ssift ask` answers one request from a script or pipe.
Plugin discovery and richer recommendations remain later work.

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
