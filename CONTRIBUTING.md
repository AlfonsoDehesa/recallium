# Contributing to Recollectium

Thanks for helping improve Recollectium. This guide is the contributor contract for the repo: how to request features, report bugs, submit pull requests, and prepare releases.

Use the available GitHub templates. They keep review focused and make sure maintainers get the information they need in one place.

## 1. Submit a feature request

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

## 2. Submit a bug report

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

## 3. Submit a PR

Pull requests should be scoped, verified, documented, and easy to review. Keep each PR focused on one feature, fix, or docs change.

Use the pull request template. Do not delete template sections just because the PR is small. If a section does not apply, mark it as not applicable and say why.

### Development setup

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

### Branches and commits

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

Each commit should be one logical, verified change. Do not save all work for one large end-of-branch commit when the work can be split into clean slices.

Good commit messages:

```text
docs: clarify local service security model
fix(logging): propagate log level to service restart
feat: expose workspace alias removal through mcp
```

Avoid vague messages such as `updates`, `fix stuff`, or `address feedback`.

### PR format

Open a PR when there is a concrete change to review. Draft PRs are fine for early feedback. Keep follow-up work on the same PR until review is done.

Every PR should answer:

- What changed?
- Why did it change?
- How was it verified?
- Which docs were updated?
- What is the status of every required quality gate?
- Are there any risks, compatibility notes, migration notes, or follow-up items?

Use this structure in the PR body or in a final PR comment before review:

```markdown
## Summary

One or two sentences describing the change.

## Changes

- Changed X to do Y.
- Updated docs for Z.

## Documentation

- [ ] `README.md` updated, or not applicable because ...
- [ ] GitHub Wiki updated, or not applicable because ...
- [ ] `docs/local-service-api.md` updated, or not applicable because ...
- [ ] `docs/local-service-openapi.json` updated, or not applicable because ...
- [ ] `docs/opencode-adapter-contract.md` updated, or not applicable because ...
- [ ] `SECURITY.md` updated, or not applicable because ...
- [ ] `ROADMAP.md` updated, or not applicable because ...
- [ ] `CONTRIBUTING.md` updated, or not applicable because ...
- [ ] `CHANGELOG.md` updated under `✨ Features`, `🐛 Fixes`, or `🧹 Chores`, or not applicable because ...

## Database migrations

- [ ] This PR does not change the SQLite schema.
- [ ] If it changes the SQLite schema, the migration plan is documented below.

## Verification

- [ ] `git diff --check` passed.
- [ ] `uv run ruff format --check .` passed, or not applicable because ...
- [ ] `uv run ruff check .` passed.
- [ ] `uv run pyright` passed.
- [ ] `uv run pytest` passed, or not applicable because ...
- [ ] `uv run pytest --cov=src/recollectium --cov-report=term-missing` passed, or accepted coverage misses are documented.
- [ ] CI passed, or is pending at ...

## Risks and follow-up

- Risk: ...
- Follow-up: ...
```

For docs-only PRs, still list every gate as passed, skipped with a reason, or not applicable. Do not make the reviewer infer that a gate was skipped.

### PR submittal gates

Before marking a PR ready for review, complete the gates that match the changed surface. Record every gate in the PR template.

#### Required for every PR

- The branch is based on current `main`.
- The PR is scoped to one feature, fix, or docs change.
- `git diff --check` passes.
- The PR template is complete.
- Docs are updated or marked not applicable with a reason for each canonical doc.
- `CHANGELOG.md` is updated for release-notable work, or the PR explains why no changelog entry is needed.
- CI is passing or the PR clearly states which check is still pending or failing.
- Secrets, tokens, credentials, private memory contents, and sensitive local paths are not included.

#### Required for code changes

Run the full gate before review unless the PR explains why a gate is not applicable:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=src/recollectium --cov-report=term-missing
```

Coverage should stay at 100 percent for changed or added code. If 100 percent is not feasible, list the exact uncovered lines in the PR and explain why the gap is acceptable.

Do not suppress warnings, loosen rules, or delete tests to make checks pass.

#### Required for docs-only changes

Run at least:

```bash
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

If the docs change wiki navigation or anchors, verify the wiki sidebar and links that changed.

#### Required for CLI, API, MCP, and service changes

Surface parity matters. If functionality is reachable through one primary surface, confirm whether it belongs in the others. Before release, every functionality reachable through the CLI must also be reachable through the API and the MCP server unless there is a documented reason not to expose it.

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

If a PR changes local service API endpoints, request schemas, response schemas, error shapes, capability names, version behavior, workspace UID rules, or local access/security assumptions, update both `docs/local-service-api.md` and `docs/local-service-openapi.json`.

If a PR changes service discovery, remote Core addressing, health/version/capability validation, workspace UID selection, adapter-facing operations, local auto-start, or plugin error handling expectations, update `docs/opencode-adapter-contract.md` and the matching wiki page.

#### Required for logging changes

Structured logging is a release gate. Before marking a PR ready, confirm that changed major features, endpoints, and code paths are logged where useful. Changed failure paths should emit appropriate structured events.

Logs must:

- Preserve stdout JSON contracts.
- Avoid memory content, metadata payloads, credentials, tokens, secrets, and other sensitive data.
- Avoid noisy events that make logs harder to use.

If a PR changes logging config, log path behavior, service logs, CLI log-level handling, structured log events, or failure paths, update the Wiki Logs page in the same change.

### Documentation update rules

Docs are part of the product. If a PR changes user-facing behavior, update the matching docs in the same PR.

Canonical docs:

- `README.md`: public front door, install overview, status, quick start, local access/security summary, and links to deeper docs.
- GitHub Wiki: long-form user and integrator manual. Keep wiki changes aligned with the same PR whenever behavior, docs, configuration, CLI, API, MCP, service lifecycle, logs, install, uninstall, security guidance, or adapter contracts change.
- `docs/local-service-api.md`: human-readable local API reference.
- `docs/local-service-openapi.json`: machine-readable local API contract served by the service.
- `docs/opencode-adapter-contract.md`: canonical adapter/plugin contract for OpenCode and related integrations.
- `SECURITY.md`: supported versions, vulnerability reporting, local access assumptions, and security posture.
- `ROADMAP.md`: current progress, release blockers, completed work, and upcoming version targets.
- `CONTRIBUTING.md`: contributor, PR, quality gate, and release procedure contract.
- `CHANGELOG.md`: human-readable release notes for published versions. The release workflow uses this file as the curated part of the GitHub Release body.

### Changelog usage

Recollectium keeps a human-written `CHANGELOG.md` and uses GitHub's generated release notes as automation on top of that. GitHub can collect merged PRs automatically, but it cannot reliably decide which changes matter to users or how to phrase them. The changelog is the curated summary; generated release notes are supporting detail.

Use a changelog entry for release-notable work:

- New user-visible behavior, commands, endpoints, config, install behavior, docs surfaces, or integrations.
- Bug fixes that change behavior, remove user-visible failure modes, or clarify confusing docs.
- Release chores that matter to users or operators, such as CI coverage, packaging, release automation, dependency policy, or documentation structure.

Skip a changelog entry for changes that are not useful in release notes, such as typo-only fixes, internal test refactors, PR template cleanup, or follow-up edits that are already covered by a broader entry. If you skip it, write the reason in the PR's `CHANGELOG.md` checkbox.

Every release section must use this exact shape:

```markdown
## Unreleased

### ✨ Features

- Added ...

### 🐛 Fixes

- Fixed ...

### 🧹 Chores

- Updated ...
```

Use `## Unreleased` while work is accumulating. In the release-prep PR, rename or copy the unreleased notes to the target version heading, such as `## v1.0.0`, then restore a fresh empty `## Unreleased` section above it.

Keep entries short and user-facing. Start each bullet with a past-tense verb such as `Added`, `Fixed`, `Updated`, `Documented`, or `Removed`. Do not paste commit hashes, PR numbers, or internal implementation noise into the changelog unless they help users understand the release.

The changelog shape is enforced by `tests/test_changelog.py`, which requires every release section to contain exactly these subsections in order: `✨ Features`, `🐛 Fixes`, and `🧹 Chores`.

Update `ROADMAP.md` in the same PR when a change implements a release blocker or roadmap item. Move completed work into the `Completed` section, mark the item complete, and keep the remaining roadmap accurate. Do not leave completed work expanded under remaining blockers.

Recollectium v1 services are unauthenticated and localhost-first. If a PR changes service host or port behavior, API or MCP service exposure, remote Core deployment guidance, discovery wording, auth/TLS/API key posture, data paths, database access, or filesystem assumptions, update `SECURITY.md` and linked local-access warnings.

### Schema migrations

A SQLite schema change includes new tables, columns, indexes, constraints, or data-shape changes to existing rows.

Recollectium uses an internal migration runner under `src/recollectium/migrations/versions/`. Do not assume Alembic is required for current SQLite schema migrations.

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

### Review and follow-up commits

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

### AI-assisted development

AI-assisted development is allowed as long as it follows every convention in this document. The same quality gates, commit standards, docs requirements, and review process apply regardless of how the code was written.

Do not commit AI tooling configuration to the repo. The `.gitignore` excludes common editor and agent directories such as `.opencode/`, `.cursor/`, `.claude/`, and `.aider*`. If a tool writes project config, keep it local. The repo is for Recollectium, not for your development environment.

## 4. For admins

This section is for maintainers and release managers.

### Merge policy

Delete the feature branch after merge. The merge commit on `main` is the record.

Do not tag or release directly from a feature branch. Releases happen from `main` only.

Before merging a PR, confirm:

- The PR is reviewed and approved.
- Required CI checks are green.
- The PR template is complete.
- Required docs and release notes are updated or explicitly not applicable.
- Any release-blocker work is reflected in `ROADMAP.md`.

### CI ownership

CI runs on every push and PR. The matrix covers lint, type checking, tests, coverage, and cross-platform bootstrap install smoke tests on Linux, macOS, and Windows.

CI is defined in `.github/workflows/`. If a PR changes how Recollectium builds, installs, upgrades, uninstalls, runs services, validates completions, or publishes releases, update CI in the same PR.

### Release procedure

Releases are created automatically when a version tag is pushed. Maintainers should do the tag and release from a clean `main` checkout after the release-prep PR is merged.

The release-prep PR is the single PR for the release sweep. It is a normal PR with a release-specific scope and should contain the Phase A audit, any fixes required by that audit, and the version and changelog preparation for the target release:

- Confirm every item in the release gate below or fix the gap in the release-prep PR.
- Bump `version` in `pyproject.toml`.
- Move the curated `CHANGELOG.md` entries into the target release section.
- Update docs for gaps found during the release gate.

Release steps:

1. Choose the target version and confirm the intended tag, such as `v1.0.0`.
2. Open the release-prep PR against `main` with the normal PR template and list the status of every gate.
3. Complete the release gate below in the release-prep PR. Fix any release-blocking gaps in that same PR.
4. Bump the version and prepare the changelog in the release-prep PR after the audit scope is known.
5. Run the required quality gates in the release-prep PR before merge and record the results in the PR.
6. Wait for review and CI to pass on the release-prep PR.
7. Merge the release-prep PR.
8. Update local `main` and verify the checkout is clean:

   ```bash
   git checkout main
   git pull --ff-only origin main
   git status --short
   ```

9. Confirm CI is green on `main` for the merge commit before tagging. Do not tag if local `main` differs from the reviewed release-prep merge commit.
10. Tag and push the release:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

11. Wait for `.github/workflows/release.yml` to finish. The workflow publishes the matching `CHANGELOG.md` section as the curated release body and lets GitHub append generated release notes for merged PR detail.
12. Complete the post-release checks below.

### Release gate

Every item in this gate must be confirmed before the release-prep PR is merged.

#### Product and surface readiness

- [ ] Every functionality reachable through the CLI is also reachable through the API and the MCP server, unless a documented exception exists.
- [ ] `recollectium config` get/set/unset covers every configurable key in `config.json`.
- [ ] CLI failure contracts are still valid: non-argparse failures emit structured JSON on stderr, stdout JSON contracts stay unpolluted, and changed failure paths emit structured logs without sensitive payloads.
- [ ] Structured logging remains useful across changed major features, endpoints, code paths, and failure paths.

#### Documentation readiness

- [ ] `README.md` is current.
- [ ] GitHub Wiki is current.
- [ ] `docs/local-service-api.md` matches the running service.
- [ ] `docs/local-service-openapi.json` matches the served OpenAPI contract.
- [ ] `docs/opencode-adapter-contract.md` is current for adapter/plugin discovery, compatibility, remote Core addressing, and workspace UID behavior.
- [ ] `SECURITY.md` accurately states supported versions, local access assumptions, vulnerability reporting, and security posture.
- [ ] `ROADMAP.md` reflects current progress, completed work, release blockers, and upcoming version targets.
- [ ] `CONTRIBUTING.md` reflects the current contributor and release process.
- [ ] `CHANGELOG.md` has a target release section with `✨ Features`, `🐛 Fixes`, and `🧹 Chores` subsections in that order.

#### CLI and completion readiness

- [ ] Every CLI command, subcommand, flag, and positional argument has help text.
- [ ] Argcomplete reaches every CLI command and flag.
- [ ] `recollectium config get/set/unset <TAB>` completes config keys.
- [ ] PowerShell dynamic completion works through `Register-ArgumentCompleter`.
- [ ] PowerShell `recollectium config get/set/unset <TAB>` completes config keys.

#### Install, upgrade, uninstall, and service readiness

- [ ] Bootstrap install works on Linux and macOS.
- [ ] Bootstrap install works on Windows.
- [ ] `pip install recollectium` works from the release candidate artifact.
- [ ] `pipx install recollectium` works from the release candidate artifact.
- [ ] `uv tool install recollectium` works from the release candidate artifact.
- [ ] `recollectium upgrade --check` reports whether a newer release is available without mutating the install.
- [ ] `recollectium upgrade --dry-run` prints the planned upgrade command for each install method without applying changes.
- [ ] `recollectium upgrade` applies package upgrades through bootstrap, pip, pipx, uv tool, and source checkout install methods while preserving running service state.
- [ ] `recollectium uninstall` prints correct package-manager commands for each install method and preserves data by default.
- [ ] `recollectium uninstall --purge` works correctly and safely.
- [ ] The service starts, responds to health checks, and stops cleanly on Linux, macOS, and Windows.

#### Migration readiness

- [ ] If the release changes the SQLite schema, migration plans are shipped and tested for each schema change.
- [ ] Schema migrations are safe for lazy application on database open, or the release notes clearly explain the required operator action.
- [ ] Re-embedding requirements, if any, are documented separately from SQLite schema migrations.

#### Quality readiness

Run the full PR code gate in the release-prep PR before merge:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=src/recollectium --cov-report=term-missing
```

Confirm:

- [ ] Formatting is clean.
- [ ] Ruff reports no lint failures.
- [ ] Pyright reports zero errors and zero warnings.
- [ ] Pytest passes.
- [ ] Coverage is 100 percent, or accepted misses are documented in the release notes.
- [ ] CI is green on the release-prep PR before merge.
- [ ] After merge, local `main` is clean and CI is green for the merge commit before tagging.

### Post-release checks

After the release workflow completes:

- [ ] Confirm the GitHub Release exists and includes the changelog section.
- [ ] Confirm package install paths work from the published artifact once available.
- [ ] Confirm README and wiki links resolve.
- [ ] Confirm the GitHub Wiki is current.

For questions, open an issue using the available template. The repo docs and GitHub Wiki are the source of truth for public project docs.
