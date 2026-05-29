# Contributing to Recollectium

Thanks for helping improve Recollectium. This guide is the contributor contract for the repo: how to report issues, set up a development environment, open pull requests, keep docs current, and prepare releases.

## Start here

There are three main ways to contribute:

- Open an issue for a bug, question, or feature request.
- Submit a pull request from a feature branch.
- Improve docs, examples, or release checklists when behavior changes.

Recollectium uses `uv` for Python environment management, ruff for formatting and linting, pyright for type checks, and pytest for tests. We target 100 percent coverage on changed code.

## Ways to contribute

### Report a bug

Before opening an issue, check open and closed issues to see whether it has already been reported. Pick the template that fits and fill it out.

A good bug report has three parts: what happened, what you expected, and how to reproduce it.

Include:

- The exact command you ran.
- The full error output. Do not summarize or trim it.
- The output of `recollectium --version`.
- Your OS and Python version, from `python --version`.
- The exact reproduction steps, in order.
- Any config, database path, or memory data involved, if it is safe to share.

Do not paste secrets, tokens, credentials, private memory contents, or sensitive local paths into public issues.

### Suggest a feature

Describe the problem you are trying to solve, not just the solution you want. A short user story helps:

```text
I want to do X so that Y.
```

If the feature affects CLI commands, the local API, MCP tools, configuration, service behavior, logging, install behavior, uninstall behavior, or adapter/plugin behavior, mention the surface you expect to use.

### Submit a pull request

Pull requests should be scoped, verified, and easy to review. Keep each PR focused on one feature, fix, or docs change.

Every PR should answer:

- What changed?
- Why did it change?
- How was it verified?
- Which docs were updated?
- Are there any risks or follow-up items?

## Development setup

### Requirements

You need:

- Python 3.12 or later.
- `uv`.
- Git.

Everything else is managed by uv.

### Clone and install

```bash
git clone https://github.com/AlfonsoDehesa/recollectium.git
cd recollectium
uv sync --group dev
```

This creates the project virtual environment, installs Recollectium in editable mode, and installs developer tools such as pytest, ruff, pyright, and coverage.

### Verify your environment

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv run recollectium --help
```

Always run project commands through `uv run` so tools use the managed environment instead of a global Python install.

## Pull request workflow

### Branches

All work starts from `main` on a feature branch. Never commit directly to `main` and never push directly to `main`.

```bash
git checkout main
git pull --ff-only origin main
git checkout -b docs/my-change
```

Use descriptive branch names:

- `docs/<topic>` for documentation.
- `fix/<topic>` for bug fixes.
- `feat/<topic>` for new features.
- `chore/<topic>` for maintenance.

### Commits

Each commit should be one logical, verified change. Do not save all work for one large end-of-branch commit when the work can be split into clean slices.

Good examples:

```text
docs: clarify local service security model
fix(logging): propagate log level to service restart
feat: expose workspace alias removal through mcp
```

Avoid vague messages:

```text
updates
fix stuff
address feedback
```

### Opening a PR

Open a PR when there is a concrete change to review. Draft PRs are fine for early feedback. Keep follow-up work on the same PR until the review is done.

The PR template includes a quality gate checklist. Fill it out before marking the PR ready for review.

### Review and follow-up commits

PRs are reviewed by a codebase administrator and merged to `main` once they pass. When you are ready for review, mark the PR ready or leave a comment asking for review.

Replies and follow-up commits happen on the same PR. Do not open a new PR for review fixes unless the maintainer asks for one.

## Quality gates

### Required commands

Run these before marking a PR ready when code changes are involved:

| Command | Purpose |
|---|---|
| `uv run ruff format .` | Format Python code. |
| `uv run ruff check .` | Lint Python code. |
| `uv run pyright` | Type check `src` and `tests`. |
| `uv run pytest` | Run the full test suite. |
| `uv run pytest --cov=src/recollectium --cov-report=term-missing` | Run coverage and show missing lines. |

For docs-only PRs, run at least:

```bash
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

The final release sweep still runs the full gate.

### Coverage expectations

Aim for 100 percent coverage on changed or added code. If 100 percent is not feasible, explain the exact uncovered lines in the PR description and why the gap is acceptable.

Do not suppress warnings, loosen rules, or delete tests to make checks pass.

### Structured logging gate

Structured logging is a release gate. Before marking a PR ready, confirm that changed major features, endpoints, and code paths are logged where useful. Changed failure paths should emit appropriate structured events.

Logs must:

- Preserve stdout JSON contracts.
- Avoid memory content, metadata payloads, credentials, tokens, secrets, and other sensitive data.
- Avoid noisy events that make logs harder to use.

If a PR changes logging config, log path behavior, service logs, CLI log-level handling, structured log events, or failure paths, update the Wiki Logs page in the same change.

### CLI, API, MCP, and docs parity

Surface parity matters. If functionality is reachable through one primary surface, confirm whether it belongs in the others.

Before release, every functionality reachable through the CLI must also be reachable through the API and the MCP server unless there is a documented reason not to expose it. No surface should silently lag behind the others.

When adding, removing, or changing CLI commands or flags, update CLI help text and docs in the same PR. Every CLI command should have:

- A short top-level command description.
- Clear command-level `--help` output.
- Help text for every flag and positional argument.
- Any important constraints, defaults, formats, or side effects.

Useful help checks:

```bash
uv run recollectium --help
uv run recollectium add --help
uv run recollectium search-user --help
uv run recollectium search-workspace --help
uv run recollectium list --help
uv run recollectium get --help
uv run recollectium update --help
uv run recollectium archive --help
uv run recollectium config --help
uv run recollectium service --help
uv run recollectium mcp-stdio --help
```

## Documentation requirements

Docs are part of the product. If a PR changes user-facing behavior, update the matching docs in the same PR.

### README and wiki

`README.md` is the public front door. Keep it focused and link to deeper docs.

The GitHub Wiki is the long-form user and integrator manual. Update it when a PR changes any of these:

- Installation, upgrade, uninstall, or shell completion.
- Configuration keys, defaults, validation, or CLI overrides.
- CLI commands, flags, arguments, output contracts, or exit behavior.
- API endpoints, request schemas, response schemas, errors, versioning, or capabilities.
- MCP modes, tools, arguments, options, or client configuration.
- Service lifecycle, service discovery, runtime files, PID files, or service logs.
- Logging config, log locations, log rotation, or structured log events.
- Local access/security guidance.
- Adapter/plugin discovery, remote Core addressing, compatibility validation, or workspace UID behavior.
- Memory scopes, memory buckets, workspace aliases, embeddings, or background jobs.

The wiki must stay aligned with README, `docs/local-service-api.md`, `docs/local-service-openapi.json`, `docs/opencode-adapter-contract.md`, `SECURITY.md`, and `ROADMAP.md`.

### API and OpenAPI docs

When adding, removing, or changing local service API endpoints, request schemas, response schemas, error shapes, capability names, version behavior, workspace UID rules, or local access/security assumptions, update both:

- `docs/local-service-api.md`
- `docs/local-service-openapi.json`

Every documented API operation should include:

- Purpose and side effects.
- Required and optional inputs.
- Request and response schemas.
- Error codes and common failure cases.
- Example requests and responses.
- Version and capability discovery behavior when relevant.
- Workspace UID rules when relevant.
- Local access and security assumptions when relevant.

If the service exposes machine-readable API documentation, keep the served contract and repository documentation consistent.

### Adapter/plugin contract docs

`docs/opencode-adapter-contract.md` is the canonical adapter/plugin contract for the OpenCode adapter path and related integrations.

Update it when a PR changes:

- Service discovery.
- Remote Core addressing.
- Health, version, or capability validation.
- Workspace UID selection, normalization, aliases, or rename behavior.
- Adapter-facing memory operations.
- Local auto-start expectations.
- Error handling expectations for plugins.

If this contract changes, update the Wiki Adapter and Plugin Integration page in the same PR.

### SECURITY.md and local access warnings

Update `SECURITY.md` and linked local-access warnings when a PR changes:

- Service host or port behavior.
- API or MCP service exposure.
- Remote Core deployment guidance.
- Discovery or compatibility validation wording.
- Authentication, authorization, TLS, API keys, or other security posture.
- Data path, database, or filesystem access assumptions.

Recollectium v1 services are unauthenticated and localhost-first. Docs must keep that clear.

### ROADMAP.md

When a PR implements a release blocker or roadmap item, update `ROADMAP.md` in the same PR.

Move completed work into the `Completed` section, mark the item complete, and keep the remaining roadmap accurate. Do not leave completed work expanded under remaining blockers.

## Schema migrations

### What counts as a schema change

A SQLite schema change includes new tables, columns, indexes, constraints, or data-shape changes to existing rows.

Recollectium uses an internal migration runner under `src/recollectium/migrations/versions/`. Do not assume Alembic is required for ordinary Phase 1 migrations.

### Required migration plan

If a PR changes the SQLite schema, include a migration plan in the PR. The plan must state:

- The migration module under `src/recollectium/migrations/versions/`.
- The exact schema change.
- How existing rows are populated, defaulted, nullable, or intentionally unknown.
- Whether any new field is semantically required and how legacy rows satisfy it.
- Whether backfill is synchronous in the migration or deferred to a background job.
- Whether the migration is safe to apply lazily on database open.
- Running-service compatibility expectations.
- Downgrade or forward-only behavior when a database is newer than the installed package.
- Tests proving upgrade behavior from the previous schema version.

Semantically required fields must not rely on application code silently inventing values for legacy rows unless that fallback is explicitly documented and tested.

### Embedding migration is separate

Embedding migration is not the same as database migration. Provider, model, profile, or vector changes belong to the re-embedding path. Table, column, index, and data-shape changes belong to SQLite schema migrations.

## AI-assisted development

AI-assisted development is allowed as long as it follows every convention in this document. The same quality gates, commit standards, docs requirements, and review process apply regardless of how the code was written.

Do not commit AI tooling configuration to the repo. The `.gitignore` excludes common editor and agent directories such as `.opencode/`, `.cursor/`, `.claude/`, and `.aider*`. If a tool writes project config, keep it local. The repo is for Recollectium, not for your development environment.

## For maintainers

### After merge

Delete the feature branch after merge. The merge commit on `main` is the record.

Do not tag or release directly from a feature branch. Releases happen from `main` only.

### Changelog

`CHANGELOG.md` at the repo root holds human-readable release notes. When you bump the version for a release, add a section at the top:

```markdown
## v1.0.0

Prepared the first stable Recollectium Core release with install, service, API, MCP, docs, and release checklist updates.
```

The release workflow combines changelog notes with an auto-generated list of merged PRs.

### Release process

Releases are created automatically when a version tag is pushed.

1. Run the pre-release checklist below and confirm every item.
2. Open a PR that does exactly two things:
   - Bumps `version` in `pyproject.toml`.
   - Adds the release section to `CHANGELOG.md`.
3. Merge the PR.
4. Tag and push from `main`:

   ```bash
   git checkout main
   git pull --ff-only origin main
   git tag v1.0.0
   git push origin v1.0.0
   ```

The `.github/workflows/release.yml` workflow combines changelog notes with the merged PR list and creates a GitHub Release.

### CI

CI runs on every push and PR. The matrix covers:

- `uv run ruff check .`
- `uv run pyright`
- Full pytest suite with coverage.
- Cross-platform bootstrap install smoke tests on Linux, macOS, and Windows.

CI is defined in `.github/workflows/`. If you change how Recollectium builds, installs, upgrades, uninstalls, runs services, or validates completions, update CI in the same PR.

## Pre-release checklist

Before cutting a release, run through this checklist. Every item must be confirmed before the version-bump PR is opened.

### Surface parity

- [ ] Every functionality reachable through the CLI is also reachable through the API and the MCP server. No surface is missing an operation the others expose.
- [ ] `recollectium config` get/set/unset covers every configurable key in `config.json`.

### Documentation

- [ ] API docs (`docs/local-service-api.md` and `docs/local-service-openapi.json`) match the running service. The OpenAPI spec is served by the service and matches the repo copy.
- [ ] MCP tools are documented and the docs match every tool the server exposes.
- [ ] Every CLI command, subcommand, flag, and positional argument has help text. No undocumented paths. Run `recollectium --help` for every subcommand and confirm nothing is missing.
- [ ] README is current: install, project status, quick start routing, local access/security, and links to wiki and repo docs.
- [ ] GitHub Wiki is current and in sync with the README and repo docs:
  - [ ] Home
  - [ ] Quick Start
  - [ ] Installation
  - [ ] Concepts
  - [ ] Configuration
  - [ ] Features and Commands
  - [ ] CLI Reference
  - [ ] Service Management
  - [ ] Logs
  - [ ] MCP Server
  - [ ] API Reference
  - [ ] Adapter and Plugin Integration
  - [ ] Verified Supported Plugins
  - [ ] Troubleshooting
  - [ ] FAQ
  - [ ] About the Author
- [ ] CLI failure contracts are documented and still valid: non-argparse failures emit structured JSON on stderr, stdout JSON contracts stay unpolluted, and changed failure paths emit structured logs without sensitive payloads.
- [ ] Local access/security assumptions are current: `SECURITY.md`, README, API docs, adapter contract, and Wiki state that v1 services are unauthenticated, localhost-first, not hardened as public services, and risky when bound to non-local interfaces without external protection.
- [ ] ROADMAP.md reflects current progress and upcoming version targets.
- [ ] Completed feature work has been moved into the ROADMAP.md `Completed` section in the same PR that implemented it.
- [ ] CONTRIBUTING.md is current.
- [ ] If a PR changes service discovery, remote Core addressing, version or capability validation, or workspace UID behavior, update `docs/opencode-adapter-contract.md`, the API docs, and the Wiki Adapter and Plugin Integration page in the same PR.
- [ ] If a PR changes logging behavior, update the Wiki Logs page in the same PR.

### Database migrations

- [ ] If the release changes the SQLite schema, migration plans are shipped and tested for each schema change.

### Shell completion

- [ ] Every CLI command and flag is reachable through argcomplete. Run `recollectium <TAB>` through every subcommand and confirm completions work.
- [ ] `recollectium config get/set/unset <TAB>` completes config keys.
- [ ] PowerShell dynamic completion works through `Register-ArgumentCompleter`. Run `recollectium <TAB>` in PowerShell through every subcommand and confirm completions work.
- [ ] `recollectium config get/set/unset <TAB>` completes config keys in PowerShell too.

### Install and update

- [ ] Bootstrap install works on Linux and macOS: `curl -LsSf <install.sh URL> | sh` succeeds, `recollectium --version` prints the correct version, and `recollectium init` completes.
- [ ] Bootstrap install works on Windows: `irm <install.ps1 URL> | iex` succeeds end-to-end.
- [ ] `pip install recollectium` works from test PyPI or a local wheel.
- [ ] `pipx install recollectium` works from test PyPI or a local wheel.
- [ ] `uv tool install recollectium` works from test PyPI or a local wheel.
- [ ] `recollectium upgrade --check` reports whether a newer release is available without mutating the install.
- [ ] `recollectium upgrade` applies package upgrades through bootstrap, pip, pipx, uv tool, and source checkout install methods while preserving running service state.
- [ ] `recollectium upgrade --dry-run` prints the planned upgrade command for each install method without applying changes.
- [ ] `recollectium uninstall` prints correct package-manager commands for each install method and preserves data by default.
- [ ] `recollectium uninstall --purge` works correctly and safely.

### Cross-environment

- [ ] All CLI commands work on Linux, macOS, and Windows.
- [ ] All commands work with Python 3.12 and the latest Python release.
- [ ] The service starts, responds to health checks, and stops cleanly on all supported platforms.

### Quality gates

- [ ] `uv run ruff format .` is clean.
- [ ] `uv run ruff check .` is clean.
- [ ] `uv run pyright` reports zero errors and zero warnings.
- [ ] `uv run pytest` passes.
- [ ] `uv run pytest --cov=src/recollectium --cov-report=term-missing` reports 100 percent coverage, or accepted misses are documented.

### Release metadata

- [ ] `version` in `pyproject.toml` is bumped to the target version.
- [ ] `CHANGELOG.md` has an entry for this release under the new version header.
- [ ] The changelog entry summarizes user-facing changes clearly. No internal-only commit noise.

## Questions

Open an issue. The repo and wiki are the source of truth for public project docs.
