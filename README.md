# SourceSift

SourceSift is a planned Python agent for source-aware research and personalized
content discovery. Requests such as “check news” or “check tech” will guide source
selection using registered links, metadata, descriptions, and optional user context.
The first curated collection will cover US national news, technology, AI, business,
marketing, and finance.

Version **0.0.1 is an initial scaffold**. Source selection, retrieval, research,
and the planned `ssift` CLI are not implemented yet. The current package only
exposes the scaffold's `hello()` function; no stable API is promised.

## Project Documentation

The Markdown documents directly under `docs/` are the maintained project reference:

- [Use cases and product scope](docs/use-cases.md): who SourceSift serves and how it
  should behave.
- [Design](docs/design.md): architecture, proposed interfaces, and technical decisions.
- [Roadmap](docs/roadmap.md): implementation order, progress, and completion criteria.

Documents in `docs/capstone/` are archived course material for reference. The
maintained documents describe the current direction.

## Installation

Requires Python 3.11 or newer.

```sh
pip install sourcesift
```

```python
from sourcesift import hello

print(hello())  # Hello from sourcesift!
```

## Development

Use [uv](https://docs.astral.sh/uv/) to install the locked development environment
and run checks:

```sh
uv sync --locked
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build --no-sources
uv run --locked twine check --strict dist/*
```

GitHub Actions checks Python 3.11–3.14 and verifies that the wheel and source
distribution install and import in fresh environments. Add behavioral tests as
features are implemented.

## Releases

The version in `pyproject.toml` is the source of truth. For each release:

1. Update that version (for example, `uv version 0.0.2 --no-sync`), then run the
   development checks above.
2. Commit and push to `main`; wait for CI to pass.
3. Create and publish a GitHub Release with the matching tag, such as `v0.0.2`,
   targeting that commit and describing the changes. Use GitHub's prerelease
   option for versions with an alpha, beta, or release-candidate suffix.

`.github/workflows/publish.yml` validates the tag against the package version,
reruns CI on the release commit, and publishes the checked distributions through
PyPI Trusted Publishing. Its publishing job uses the GitHub environment `pypi`;
no PyPI API token is needed.

## License

Copyright 2026 Jake Van Slyke. Licensed under [Apache 2.0](LICENSE).
