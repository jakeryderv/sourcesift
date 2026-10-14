# SourceSift

SourceSift provides a Python SDK and CLI for requests with explicit document and
personal context. Source-aware research and personalized discovery are in development. Requests such as “check news” or “check tech” will guide source
selection using registered links, metadata, descriptions, and optional user context.
The first curated collection will cover US national news, technology, AI, business,
marketing, and finance.

**Phase 1 is implemented:** single requests through PydanticAI and OpenRouter,
optional text/Markdown context, TOML configuration, and shell-friendly output.
Source selection, URL retrieval, and verified current-news research arrive in
Phase 2. The SDK is an early API and may evolve before 1.0.

## Project Documentation

[Read the documentation](https://jakevanslyke.com/sourcesift/).

The Markdown documents directly under `docs/` are the maintained project reference:

- [Use cases and product scope](docs/use-cases.md): who SourceSift serves and how it
  should behave.
- [Design](docs/design.md): architecture, proposed interfaces, and technical decisions.
- [Roadmap](docs/roadmap.md): implementation order, progress, and completion criteria.
- [CLI guide](docs/cli.md), [Python SDK](docs/sdk.md), and
  [configuration](docs/configuration.md): current usage and defaults.
- [API reference](docs/reference/index.md): source-based reference rendered by MkDocs.

Documents in `docs/capstone/` are archived course material for reference. The
maintained documents describe the current direction.

## Installation

Requires Python 3.11 or newer.

```sh
pip install sourcesift
```

Set `OPENROUTER_API_KEY` securely in your environment, then select a model:

```sh
export SOURCESIFT_MODEL=openai/gpt-6.1-sol
export SOURCESIFT_REASONING_EFFORT=medium
ssift ask "Summarize this document" --file report.md
cat report.md | ssift ask "Summarize this" > summary.md
```

```python
from sourcesift import SourceSift

app = SourceSift()
result = app.run_sync("Summarize this document", files=["report.md"])
print(result.answer)
# Inside an async application: result = await app.run(...)
```

Context is sent to the selected model through OpenRouter. No model is selected
implicitly and no external sources are retrieved in Phase 1. See the
[configuration guide](docs/configuration.md) for background context, limits, and
settings precedence.

## Development

Use [uv](https://docs.astral.sh/uv/) and
[actionlint 1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12).
With Go installed, `go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`
installs the workflow linter; ensure its binary is on `PATH`.

```sh
uv sync --locked
uv run --locked pre-commit install
uv run --locked python scripts/check.py
```

Install hooks once per clone. Commits run Ruff's safe lint fixes and formatting on
staged Python files, followed by project-wide type checking targeting Python 3.11.
If Ruff changes a file, review and stage the fixes before committing again. Pushes
run the offline test suite and version/lockfile consistency checks. All Python tools
use the versions in `uv.lock`. Archived files under `docs/capstone/` are excluded
from hooks.

Run either hook stage manually with:

```sh
uv run --locked pre-commit run --all-files
uv run --locked pre-commit run --all-files --hook-stage pre-push
```

The check command runs formatting, linting, type checks, hook configuration
validation, offline tests, release-metadata consistency checks, a strict docs build,
and workflow linting.
CI runs static checks once and tests on Python 3.11–3.14, then builds and validates
wheel/sdist distributions and installs both in fresh environments. Superseded PR
runs are canceled; main and publishing runs remain independent. CI still enforces
checks even if local hooks were not installed or were skipped.

Mark tests requiring external services or API credentials with
`@pytest.mark.network`. Hooks and normal CI exclude them; run them explicitly with
`SOURCESIFT_LIVE_TEST=1 uv run --locked python -m pytest -m network` after setting
`OPENROUTER_API_KEY`, `SOURCESIFT_MODEL`, and optionally `SOURCESIFT_REASONING_EFFORT`.
This opt-in check sends a small synthetic document to the model and incurs normal
provider charges. Tests never load `.env` automatically.

Run distribution validation locally with:

```sh
uv build --no-sources
uv run --locked twine check --strict dist/*
```

Tests cover configuration, input boundaries, SDK execution, CLI composition,
provider transport, and release guardrails. Ordinary tests disable live model calls. Package runtime versions should be read through `importlib.metadata`
instead of maintaining another hard-coded version in Python source.

### Documentation preview

Documentation dependencies live in a separate `docs` dependency group:

```sh
uv run --locked --group docs mkdocs serve
uv run --locked --group docs mkdocs build --strict
```

MkDocs builds the maintained Markdown pages and mkdocstrings renders API reference
content from Google-style docstrings and type annotations. The generated HTML lives
in ignored `site/`; the reference directives in `docs/reference/` are not expanded
API Markdown when viewed on GitHub. Add public API members to the reference as they
are implemented. Archived `docs/capstone/` files are excluded from the site.

CI builds the docs once and uploads a `documentation-site` artifact for preview.
After a successful push CI run on the current `main` commit, **Deploy docs** publishes
that same artifact to [GitHub Pages](https://jakevanslyke.com/sourcesift/). PR builds
remain downloadable previews. The public site tracks development on `main`,
independently of PyPI releases. To retry a deployment, rerun **Deploy docs** for the
current main commit; if its artifacts have expired, rerun that commit's push CI run.

### Coverage and property tests

```sh
uv run --locked python -m pytest -q -m 'not network' --cov --cov-report=html --cov-report=xml
uv run --locked coverage report --include='src/sourcesift/*' --fail-under=90
uv run --locked coverage report --include='scripts/*'
```

Branch coverage runs on Python 3.14 in CI; the other Python jobs run ordinary tests.
The `coverage-reports` artifact contains HTML and XML reports. Open `htmlcov/index.html`
locally for line and branch details. Application and tooling summaries are reported
separately. CI requires at least 90% application coverage, including branches;
tooling coverage remains informational. Offline agent tests use deterministic models
and a mock HTTP transport, and do not establish live model answer quality.

Hypothesis tests run with the ordinary offline suite. Initial properties check that
only release PRs can change versions and that releases increase through development,
alpha, beta, release-candidate, final, and post-release versions. CI uses a reproducible
200-example profile per property; local runs use Hypothesis defaults and retain
failure examples in ignored `.hypothesis/`. Application properties also check exact UTF-8 byte boundaries. Retain explicit
examples and mocked-provider tests alongside properties.

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
Automation refreshes `uv.lock`. GitHub requires **Approve workflows** on bot-created
or bot-updated PRs before their normal CI can run. Wait for **Prepare release** to
finish, approve workflows on the release PR, and require its `CI` check to pass.
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
release automation explicitly dispatches publication. The release PR's workflow
approval is separate from approving a PR review and does not publish anything.
Manually dispatched checks do not clear GitHub's bot-PR workflow approval gate.
A `workflow_run` completion for that PR does not trigger another release-preparation
loop. See [GitHub's token-trigger rules](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs).

### Recovery

- If release preparation fails, fix the cause and rerun **Prepare release** on
  `main`. It requires a successful push CI run on the current main commit.
- If a release PR changes during CI, wait for preparation to finish, then approve
  its latest pending workflow run and wait for CI again.
- If publishing fails, inspect the failed job and PyPI state before retrying. Rerun
  failed jobs to reuse the checked artifacts. Never move a published tag or change
  the contents of an already published version.
- If publication was never dispatched, run **Publish to PyPI** on the existing tag
  and supply that same tag as its input. A published GitHub Release must exist.

## License

Copyright 2026 Jake Van Slyke. Licensed under [Apache 2.0](LICENSE).
