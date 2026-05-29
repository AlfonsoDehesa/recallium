# Contributing to Recollectium

Thanks for helping improve Recollectium. This guide is the contributor contract for the repo: how to report bugs, request features, submit pull requests, and prepare releases.

Use the available GitHub templates. They keep review focused and make sure the information maintainers need is not scattered across comments.

## 3 ways to contribute

### 1. Report a bug

Use the Bug report issue template. Before opening a new issue, check open and closed issues to see whether the problem has already been reported.

A good bug report has three parts: what happened, what you expected, and how to reproduce it.

Include:

- The exact command you ran.
- The full error output. Do not summarize or trim it.
- Recollectium logs, if possible.
- The output of `recollectium --version`.
- Your OS and Python version, from `python --version`.
- The exact reproduction steps, in order.
- Any config, database path, or memory data involved, if it is safe to share.

Do not paste secrets, tokens, credentials, private memory contents, or sensitive local paths into public issues. If sensitive data is required to explain the problem, redact it or ask a maintainer how to share it safely.

### 2. Add a feature request

Use the Feature request issue template. Describe the problem you are trying to solve, not just the solution you want.

A short user story helps:

```text
I want to do X so that Y.
```

Include:

- The use case.
- The current workaround, if any.
- The surface you expect to use: CLI, Python API, local HTTP API, MCP, configuration, service lifecycle, logging, install, uninstall, adapter/plugin integration, or docs.
- Any compatibility constraints you already know about.

Feature requests do not need a full implementation design. They should make the user need clear enough that maintainers can decide whether it belongs in Core, an adapter, the wiki, or a later roadmap phase.

### 3. Submit a PR

Pull requests should be scoped, verified, documented, and easy to review. Keep each PR focused on one feature, fix, or docs change.

Use the pull request template. Do not delete template sections just because the PR is small. If a section does not apply, mark it as not applicable and say why.

Every PR should answer:

- What changed?
- Why did it change?
- How was it verified?
- Which docs were updated?
- What is the status of every required quality gate?
- Are there any risks, compatibility notes, migration notes, or follow-up items?

#### Development setup

Requirements:

- Python 3.12 or later.
- `uv`.
- Git.

Everything else is managed by uv.

```bash
git clone https://github.com/AlfonsoDehesa/recollectium.git
cd recollectium
uv sync --group dev
```

This creates the project virtual environment, installs Recollectium in editable mode, and installs developer tools such as pytest, ruff, pyright, and coverage.

Verify the environment:

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv run recollectium --help
```

Always run project commands through `uv run` while developing from a source checkout so tools use the managed environment instead of a global Python install.

#### Branches

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

#### Commits

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

#### Opening a PR

Open a PR when there is a concrete change to review. Draft PRs are fine for early feedback. Keep follow-up work on the same PR until review is done.

The PR template includes required sections and a quality gate checklist. Fill it out before marking the PR ready for review.

The PR description should include:

- Summary: one or two sentences describing the change.
- Changes: the important files or surfaces changed and what was done.
- Roadmap status: whether the PR implements a `ROADMAP.md` item and whether `ROADMAP.md` was updated.
- Database migration status: whether the SQLite schema changed, and if so the migration module, existing-row behavior, lazy-migration safety notes, backfill or re-embedding plan, and upgrade tests.
- Quality gates: every relevant command and whether it passed, failed, or was not applicable.
- Policy compliance: pytest success rate, feature coverage, codebase coverage, ruff status, and pyright status.
- Documentation status: which docs changed, or why docs did not need to change.
- Risks and follow-up: compatibility concerns, known limitations, deferred work, or manual release steps.

Use this structure in the PR body or in a final PR comment before review:

```markdown
## Summary

One or two sentences describing the change.

## Changes

- Changed X to do Y.
- Updated docs for Z.

## Documentation

- [ ] README updated or not applicable because ...
- [ ] Wiki updated or not applicable because ...
- [ ] API/OpenAPI docs updated or not applicable because ...
- [ ] SECURITY.md updated or not applicable because ...
- [ ] ROADMAP.md updated or not applicable because ...

## Verification

- [ ] `git diff --check` passed
- [ ] `uv run ruff format --check .` passed, or not applicable because ...
- [ ] `uv run ruff check .` passed
- [ ] `uv run pyright` passed
- [ ] `uv run pytest` passed, or not applicable because ...
- [ ] `uv run pytest --cov=src/recollectium --cov-report=term-missing` passed, or accepted coverage misses are documented
- [ ] CI passed

## Risks and follow-up

- Risk: ...
- Follow-up: ...
```

For docs-only PRs, still list every gate. Do not make the reviewer infer that a gate was skipped.

#### Review and follow-up commits

PRs are reviewed by a codebase administrator and merged to `main` once they pass. When you are ready for review, mark the PR ready or leave a comment asking for review.

Replies and follow-up commits happen on the same PR. Do not open a new PR for review fixes unless the maintainer asks for one.

When review feedback is in:

1. Read every comment before making changes.
2. Group related fixes into focused commits.
3. Update tests and docs with the fix, not afterward.
4. Run the right quality gate for the scope of the change.
5. Push the branch.
6. Reply to the review with what changed and which checks passed.

A review is not resolved just because a commit was pushed. The final PR state should make it easy for the reviewer to see that each requested change was handled.

A good final PR comment includes:

```markdown
Addressed review feedback in `<commit>`.

What changed:
- ...

Verification:
- `git diff --check`: passed
- `uv run ruff check .`: passed
- `uv run pyright`: passed
- `uv run pytest`: passed or not run because ...
- CI: passed or pending

Remaining:
- None, or the exact remaining blocker.
```

#### Required quality gates

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

#### Coverage expectations

Aim for 100 percent coverage on changed or added code. If 100 percent is not feasible, explain the exact uncovered lines in the PR description and why the gap is acceptable.

Do not suppress warnings, loosen rules, or delete tests to make checks pass.

#### Structured logging gate

Structured logging is a release gate. Before marking a PR ready, confirm that changed major features, endpoints, and code paths are logged where useful. Changed failure paths should emit appropriate structured events.

Logs must:

- Preserve stdout JSON contracts.
- Avoid memory content, metadata payloads, credentials, tokens, secrets, and other sensitive data.
- Avoid noisy events that make logs harder to use.

If a PR changes logging config, log path behavior, service logs, CLI log-level handling, structured log events, or failure paths, update the Wiki Logs page in the same change.

#### CLI, API, MCP, and docs parity

Surface parity matters. If functionality is reachable through one primary surface, confirm whether it belongs in the others.

Before release, every functionality reachable through the CLI must also be reachable through the API and the MCP server unless there is a documented reason not to expose it. No surface should silently lag behind the others.

When adding, removing, or changing CLI commands or flags, update CLI help text and docs in the same PR. Every CLI command should have:

- A short top-level command description.
- Clear command-level `--help` output.
- Help text for every flag and positional argument.
- Any important constraints, defaults, formats, or side effects.

Useful help checks for the full command inventory:

```bash
uv run recollectium --help
uv run recollectium init --help
uv run recollectium add --help
uv run recollectium search-user --help
uv run recollectium search-workspace --help
uv run recollectium list --help
uv run recollectium get --help
uv run recollectium update --help
uv run recollectium archive --help
uv run recollectium workspace --help
uv run recollectium config --help
uv run recollectium service --help
uv run recollectium serve --help
uv run recollectium db-status --help
uv run recollectium embedding-status --help
uv run recollectium embedding-jobs --help
uv run recollectium mcp-stdio --help
uv run recollectium completion --help
uv run recollectium upgrade --help
uv run recollectium uninstall --help
```

#### Documentation requirements

Docs are part of the product. If a PR changes user-facing behavior, update the matching docs in the same PR.

`README.md` is the public front door. Keep it focused and link to deeper docs.

`docs/wiki/` contains the long-form user and integrator manual source pages. Publish those pages to the GitHub Wiki when the GitHub wiki remote is initialized. Update them when a PR changes any of these:

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

The wiki source pages and published GitHub Wiki must stay aligned with README, `docs/local-service-api.md`, `docs/local-service-openapi.json`, `docs/opencode-adapter-contract.md`, `SECURITY.md`, and `ROADMAP.md`.

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

Update `SECURITY.md` and linked local-access warnings when a PR changes:

- Service host or port behavior.
- API or MCP service exposure.
- Remote Core deployment guidance.
- Discovery or compatibility validation wording.
- Authentication, authorization, TLS, API keys, or other security posture.
- Data path, database, or filesystem access assumptions.

Recollectium v1 services are unauthenticated and localhost-first. Docs must keep that clear.

When a PR implements a release blocker or roadmap item, update `ROADMAP.md` in the same PR. Move completed work into the `Completed` section, mark the item complete, and keep the remaining roadmap accurate. Do not leave completed work expanded under remaining blockers.

#### Schema migrations

A SQLite schema change includes new tables, columns, indexes, constraints, or data-shape changes to existing rows.

Recollectium uses an internal migration runner under `src/recollectium/migrations/versions/`. Do not assume Alembic is required for ordinary Phase 1 migrations.

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

Embedding migration is not the same as database migration. Provider, model, profile, or vector changes belong to the re-embedding path. Table, column, index, and data-shape changes belong to SQLite schema migrations.

#### AI-assisted development

AI-assisted development is allowed as long as it follows every convention in this document. The same quality gates, commit standards, docs requirements, and review process apply regardless of how the code was written.

Do not commit AI tooling configuration to the repo. The `.gitignore` excludes common editor and agent directories such as `.opencode/`, `.cursor/`, `.claude/`, and `.aider*`. If a tool writes project config, keep it local. The repo is for Recollectium, not for your development environment.

## For admins

This section is for maintainers and release managers.

### Merge policy

Delete the feature branch after merge. The merge commit on `main` is the record.

Do not tag or release directly from a feature branch. Releases happen from `main` only.

### CI

CI runs on every push and PR. The matrix covers:

- `uv run ruff check .`
- `uv run pyright`
- Full pytest suite with coverage.
- Cross-platform bootstrap install smoke tests on Linux, macOS, and Windows.

CI is defined in `.github/workflows/`. If you change how Recollectium builds, installs, upgrades, uninstalls, runs services, or validates completions, update CI in the same PR.

### Changelog

`CHANGELOG.md` at the repo root holds human-readable release notes. When you bump the version for a release, add a section at the top:

```markdown
## v1.0.0

Prepared the first stable Recollectium Core release with install, service, API, MCP, docs, and release checklist updates.
```

The release workflow combines changelog notes with an auto-generated list of merged PRs.

### Release flow

Releases are created automatically when a version tag is pushed. Maintainers should do the release from a clean `main` checkout after the release-prep PR is merged.

1. Run the pre-release checklist below and confirm every item.
2. Open a release-prep PR that does exactly these things:
   - Bumps `version` in `pyproject.toml`.
   - Adds the release section to `CHANGELOG.md`.
   - Updates docs only if the checklist uncovered a docs gap.
3. Use the PR template and list the status of every gate in the release-prep PR.
4. Wait for CI and review to pass.
5. Merge the release-prep PR.
6. Tag and push from `main`:

   ```bash
   git checkout main
   git pull --ff-only origin main
   git status --short
   git tag v1.0.0
   git push origin v1.0.0
   ```

The `.github/workflows/release.yml` workflow combines changelog notes with the merged PR list and creates a GitHub Release.

After the release workflow completes:

- Confirm the GitHub Release exists and includes the changelog section.
- Confirm package install paths work from the published artifact once available.
- Confirm README and wiki links resolve.
- If the GitHub Wiki has been initialized, sync `docs/wiki/` to the wiki repository.

### Pre-release checklist

Before cutting a release, run through this checklist. Every item must be confirmed before the version-bump PR is opened.

#### Surface parity

- [ ] Every functionality reachable through the CLI is also reachable through the API and the MCP server. No surface is missing an operation the others expose.
- [ ] `recollectium config` get/set/unset covers every configurable key in `config.json`.

#### Documentation

- [ ] API docs (`docs/local-service-api.md` and `docs/local-service-openapi.json`) match the running service. The OpenAPI spec is served by the service and matches the repo copy.
- [ ] MCP tools are documented and the docs match every tool the server exposes.
- [ ] Every CLI command, subcommand, flag, and positional argument has help text. No undocumented paths. Run `recollectium --help` for every subcommand and confirm nothing is missing.
- [ ] README is current: install, project status, quick start routing, local access/security, and links to wiki and repo docs.
- [ ] `docs/wiki/` source pages and the published GitHub Wiki are current and in sync with the README and repo docs:
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

#### Database migrations

- [ ] If the release changes the SQLite schema, migration plans are shipped and tested for each schema change.

#### Shell completion

- [ ] Every CLI command and flag is reachable through argcomplete. Run `recollectium <TAB>` through every subcommand and confirm completions work.
- [ ] `recollectium config get/set/unset <TAB>` completes config keys.
- [ ] PowerShell dynamic completion works through `Register-ArgumentCompleter`. Run `recollectium <TAB>` in PowerShell through every subcommand and confirm completions work.
- [ ] `recollectium config get/set/unset <TAB>` completes config keys in PowerShell too.

#### Install and update

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

#### Cross-environment

- [ ] All CLI commands work on Linux, macOS, and Windows.
- [ ] All commands work with Python 3.12 and the latest Python release.
- [ ] The service starts, responds to health checks, and stops cleanly on all supported platforms.

#### Quality gates

- [ ] `uv run ruff format .` is clean.
- [ ] `uv run ruff check .` is clean.
- [ ] `uv run pyright` reports zero errors and zero warnings.
- [ ] `uv run pytest` passes.
- [ ] `uv run pytest --cov=src/recollectium --cov-report=term-missing` reports 100 percent coverage, or accepted misses are documented.

#### Release metadata

- [ ] `version` in `pyproject.toml` is bumped to the target version.
- [ ] `CHANGELOG.md` has an entry for this release under the new version header.
- [ ] The changelog entry summarizes user-facing changes clearly. No internal-only commit noise.

## Questions

Open an issue using the available template. The repo and wiki are the source of truth for public project docs.
