# Contributing to Recallium

There are two ways to contribute: open an issue or submit a pull request.

## Creating an issue

Before you open any issue, check the open and closed issues to make sure
it has not already been reported. Pick the template that fits and fill it
out. We read every issue.

### Reporting a bug

A bug report has three parts: what happened, what you expected, and how
to reproduce it.

**What happened:**

- Paste the exact command you ran.
- Paste the full error output. Do not summarize or trim.
- Include the output of `recallium --version`.

**What you expected:**

- Tell us what you thought would happen instead. One or two sentences.

**How to reproduce:**

- List the exact steps, in order, that make the problem happen every time.
- Include your OS and Python version (`python --version`).
- If it involves a config file, database, or specific memory data,
  describe it or attach it if safe.

### Suggesting a feature

Tell us what problem you are trying to solve, not just the solution you
want. A short user story helps: "I want to do X so that Y."

## Submitting a pull request

### Repo policy

We use ruff for formatting and linting, pyright for type checks, and
pytest for tests. We target 100 percent coverage on changed code.

Do not submit a PR if any of these fail:

- `uv run ruff format .`
- `uv run ruff check .`
- `uv run pyright`
- `uv run pytest`
- `uv run pytest --cov=src/recallium --cov-report=term-missing`

If coverage is not 100 percent, explain the uncovered lines in the PR
description. Do not suppress warnings or loosen the ruleset to make checks
pass.

Everything below covers the conventions and workflow for PRs.

### AI development

AI-assisted development is allowed as long as it follows every convention
in this document. The same quality gates, commit standards, and review
process apply regardless of how the code was written.

Do not commit your AI tooling configuration to the repo. The `.gitignore`
already excludes common editor and agent directories (`.opencode/`,
`.cursor/`, `.claude/`, `.aider*`, etc.). If your tool writes project
config, keep it local. The repo is for Recallium, not for your development
environment.

### Development setup

You need Python 3.12 or later and `uv`. Everything else is managed by uv.

```bash
git clone https://github.com/AlfonsoDehesa/recallium.git
cd recallium
uv sync --group dev
```

That creates the project venv, installs Recallium in editable mode, and
pulls in dev tooling (pytest, ruff, pyright, coverage).

Verify it works:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

You can run `uv run recallium --help` to try the CLI directly.

### Branch workflow

All work starts from `main` on a feature branch. Never commit directly
to `main` or push to it.

```bash
git checkout main
git pull --ff-only
git checkout -b my-feature
```

Make your changes on that branch. Each commit should be one logical,
verified change, not a pile of unrelated edits.

### Pull request lifecycle

You can open a PR whenever you are ready. If you prefer to finish
everything locally and open a complete PR, that is fine. If you want
feedback early, open a draft and push follow-up commits as you go.

When you open a PR, a template auto-fills the description with a quality
gates checklist. Fill it out before marking the PR ready for review.

Every PR must pass the quality gates before merge:

- `uv run ruff format .`: code style
- `uv run ruff check .`: linting
- `uv run pyright`: type checking
- `uv run pytest`: full test suite
- `uv run pytest --cov=src/recallium --cov-report=term-missing`: coverage

Aim for 100 percent coverage on changed code. If that is not feasible,
explain the uncovered lines in the PR description.

### Commit style

Keep messages short and descriptive. Use the conventional prefix if it
helps, but clarity matters more than format:

```
fix(logging): propagate --log-level to serve and restart
```

Not:

```
addressed issue with logging flag propagation across service lifecycle
commands and updated related test fixtures accordingly
```

### Review policy

PRs are reviewed by a codebase administrator and merged to `main` once
they pass. When you are ready for your PR to be reviewed, mark it as
such. Use the GitHub ready-for-review button, or leave a comment asking
for a review.

Replies and follow-up commits happen on the same PR until the review is
done.

## For administrators

### After merge

Delete the feature branch. The merge commit on `main` is the record.

Do not tag or release directly from a feature branch. Releases happen
from `main` only.

### Changelog

`CHANGELOG.md` at the repo root holds human-readable release notes.
When you bump the version for a release, add a section at the top:

```markdown
## v0.2.0

Added cross-platform bootstrap installer. `curl | sh` on Linux and macOS,
`irm | iex` on Windows. CI now runs on all three platforms.
```

The release workflow combines this with an auto-generated list of merged
PRs.

### Releases

Releases are created automatically when a version tag is pushed.

1. Open a PR that does exactly two things:
   - Bumps `version` in `pyproject.toml`.
   - Adds the release section to `CHANGELOG.md`.
2. Merge the PR.
3. Tag and push:

   ```bash
   git checkout main
   git pull --ff-only
   git tag v0.2.0
   git push origin v0.2.0
   ```

The `.github/workflows/release.yml` workflow builds the wheel and sdist,
combines changelog notes with the merged PR list, and creates a GitHub
Release with both artifacts attached.

### CI

CI runs on every push and PR. The matrix covers:

- `uv run ruff check .` and `uv run pyright`
- Full pytest suite with coverage
- Cross-platform bootstrap install smoke test on Linux, macOS, and Windows

CI is defined in `.github/workflows/`. If you change how Recallium builds
or installs, update CI in the same PR.

## Questions

Open an issue. The repo is the source of truth for everything.
