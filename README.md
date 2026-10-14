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

Use [uv](https://docs.astral.sh/uv/) and
[actionlint 1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12).
With Go installed, `go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`
installs the workflow linter; ensure its binary is on `PATH`.

```sh
uv sync --locked
uv run --locked python scripts/check.py
```

The check command runs formatting, linting, type checks, tests, release-metadata
consistency checks, and workflow linting. CI runs the same Python checks on
Python 3.11–3.14, then builds and validates wheel/sdist distributions and installs
both in fresh environments. Run distribution validation locally with:

```sh
uv build --no-sources
uv run --locked twine check --strict dist/*
```

Tests currently cover release guardrails. Add application tests alongside Phase 1
features. Package runtime versions should be read through `importlib.metadata`
instead of maintaining another hard-coded version in Python source.

## GitHub Workflow

1. Create a branch for a focused change and open a PR against `main`.
2. Use a Conventional Commit title, for example `feat(cli): add ask command`,
   `fix(config): resolve relative paths`, or `docs: clarify source selection`.
3. Wait for the required `CI` check and resolve review conversations.
4. Squash merge. The PR title becomes the squash commit title used for release notes.

The main-branch rules require a PR and current passing checks, block force pushes
and deletion, and require no additional approving reviewer for this solo project.
Merged branches are deleted automatically. Release tags matching `v*` are protected
against updates and deletion. The `pypi` environment accepts release tags only.

## Versions, Changelog, and Releases

`pyproject.toml` is the package version source of truth. Release Please maintains a
release PR that updates it, the release manifest, and [CHANGELOG.md](CHANGELOG.md).
Automation refreshes `uv.lock` and starts CI on the resulting PR commit.
Ordinary feature PRs leave those version numbers unchanged.

- `fix:` and other releasable fixes produce patch releases.
- `feat:` produces a minor release; the first usable SDK/CLI is targeted at `0.1.0`.
- Breaking changes use `!` or a `BREAKING CHANGE:` footer. Before `1.0`, these bump
  the minor version; at and after `1.0`, they bump the major version.
- Documentation changes can contribute to a patch release. Maintenance-only changes
  do not normally create a release on their own.
- Review generated notes for accuracy, especially compatibility and migration details.

Merging an ordinary PR updates the pending release PR. **Merging the release PR
is the release decision:** after CI passes on that merged main commit, Release
Please creates the matching tag and GitHub Release. Automation then dispatches
`.github/workflows/publish.yml` on that tag to validate and publish through the
`pypi` Trusted Publisher. No personal access token or PyPI API token is required.

The built-in GitHub token does not trigger ordinary release-event workflows, so
release automation explicitly dispatches publication. It also dispatches release-PR
CI after refreshing the lockfile, avoiding a manual approval dependency for the
bot-generated PR's normal workflow event. A `workflow_run` completion for that PR
does not trigger another release-preparation loop.

### Recovery

- If release preparation fails, fix the cause and rerun **Prepare release** on
  `main`. It requires a successful push CI run on the current main commit.
- If a release PR changes during CI, rerun preparation to check its latest commit.
- If publishing fails, inspect the failed job and PyPI state before retrying. Rerun
  failed jobs to reuse the checked artifacts. Never move a published tag or change
  the contents of an already published version.
- If publication was never dispatched, run **Publish to PyPI** on the existing tag
  and supply that same tag as its input. A published GitHub Release must exist.

## License

Copyright 2026 Jake Van Slyke. Licensed under [Apache 2.0](LICENSE).
