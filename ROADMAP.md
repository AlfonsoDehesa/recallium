# Roadmap

## Phase 1 (v1.0.0): Release-ready core

Recallium Core is installable, runnable, documented, and ready for the first
public release. The local service, CLI, API, bootstrap installers, service
lifecycle, shell completion for Unix shells, uninstall behavior, and service
discovery are already in place.

Completed:

- Core local memory MVP with user and workspace memory CRUD, search, update, archive, and list operations.
- Local FastAPI service API with health, version, capabilities, memory, and embedding endpoints.
- Smart local embeddings with built-in FastEmbed using `jinaai/jina-embeddings-v2-small-en`.
- Background re-embedding worker with embedding job tracking.
- Full test coverage push across the implemented core surface.
- Versioned SQLite schema migrations with an internal migration runner.
- Config file system and predictable data, cache, log, and runtime directories.
- Service lifecycle and service type support for API and MCP services.
- Structured logging, lifecycle events, crash detection, and CLI log-level handling.
- Python 3.12 compatibility.
- Repository policy docs, contribution workflow, issue templates, and release checklist.
- AGPL-3.0 license selection.
- Cross-platform bootstrap install flow for Linux, macOS, and Windows.
- Safe uninstall surface with default data preservation and explicit purge.
- Bash, zsh, and fish shell completion through argcomplete.
- Uninstall cleanup for Recallium-managed shell completion blocks.
- Local service discovery for adapters through `recallium service discover` and `service-discovery.json`.

Remaining release blockers:

### Packaging and distribution readiness

Release goal: strangers can install Recallium without cloning the repository.

- Verify `pyproject.toml` package metadata: name, version, license, Python
  version, dependencies, and CLI entry point.
- Build a wheel and source distribution.
- Install from the local wheel.
- Install from the source distribution.
- Verify `pip install recallium` from the intended package index or local
  release artifact.
- Verify `pipx install recallium` from the intended package index or local
  release artifact.
- Verify `uv tool install recallium` from the intended package index or local
  release artifact.
- Confirm `recallium --version` works after each install method.
- Confirm `recallium init` works after each install method.
- Confirm the GitHub release workflow can publish from a version tag.
- Confirm `CHANGELOG.md` and `pyproject.toml` version match.

### Workspace UID registry

Release goal: Core has a stable workspace identity contract that adapters can
use without treating filesystem paths as canonical memory buckets.

- Decide where workspace IDs live.
- Decide whether Core creates workspace IDs, reads them, or both.
- Define the workspace UID file format if the ID is stored on disk.
- Ensure the same repository maps to the same workspace UID across sessions.
- Ensure moving a folder does not accidentally create a different memory bucket.
- Add CLI or API support if needed to inspect or register a workspace.
- Document how adapters should get or create the workspace UID.
- Add tests for creating, reading, validating, and reusing workspace IDs.

### FastEmbed model download UX

Release goal: first-run model setup is understandable and recoverable instead
of feeling like Recallium silently hung or failed.

- Make `recallium init` clearly explain that it may download the built-in
  FastEmbed model on first run.
- Surface clear progress or status messaging around model cache warmup where
  practical without breaking JSON output contracts.
- Provide actionable offline guidance when the model cannot be fetched.
- Preserve machine-readable CLI output for automation.
- Document the first-run model cache behavior in README install guidance.
- Add tests for success, timeout, unavailable provider, unavailable model, and
  user-facing error text.

### OpenCode adapter readiness handoff

Release goal: Core is ready for the future OpenCode adapter even though the
adapter itself is not part of this repository.

- Document exactly how the adapter discovers the running service.
- Document how the adapter checks service health, version, and capabilities.
- Document how the adapter gets or creates the workspace UID.
- Confirm the API has everything the adapter needs for user and workspace
  memory operations.
- Confirm capability names are stable enough for adapter compatibility checks.
- Confirm errors are clear when the service is not running or incompatible.
- Write an adapter workflow doc: install Core, start service, discover service,
  validate service, then use memory endpoints.
- Add an adapter contract section to the service or API docs if needed.

### Rich dynamic PowerShell shell completion

Release goal: Windows users get rich dynamic Tab completion in PowerShell with
parity for the important Recallium CLI paths.

- Add PowerShell as a supported completion target.
- Generate a `Register-ArgumentCompleter` script.
- Make PowerShell call Recallium dynamically during Tab completion.
- Complete top-level commands.
- Complete subcommands.
- Complete command flags.
- Complete config keys for `recallium config get/set/unset`.
- Add install support so the completion block can be added to the PowerShell
  profile.
- Add uninstall support so Recallium can remove the managed completion block.
- Add tests for generated PowerShell script output.
- Add docs for manual and automatic PowerShell setup.

### CLI error-formatting audit

Release goal: users and automation get predictable command failures across the
whole CLI.

- Audit every CLI command for consistent exit codes.
- Audit stderr messages so validation, not-found, config, service, embedding,
  and install errors are clear and actionable.
- Preserve stdout JSON contracts for successful machine-readable commands.
- Confirm commands that are meant for automation return structured JSON where
  appropriate.
- Add or update tests for representative error paths across the CLI.

### Local access and security documentation audit

Release goal: users understand the local-only security model before exposing the
service outside localhost.

- Document that the Phase 1 local service is unauthenticated.
- Document that binding to non-local interfaces can expose memory contents.
- Confirm README, service API docs, and config docs explain host and port risks.
- Confirm install and service docs recommend local-only defaults.
- Add release checklist coverage for local access and security assumptions.

### Final release sweep

Release goal: no embarrassing loose ends before tagging.

- Run the full release checklist in `CONTRIBUTING.md`.
- Confirm all CLI help text is accurate.
- Confirm README is current.
- Confirm API docs match the running service.
- Confirm OpenAPI JSON matches FastAPI output.
- Confirm config docs list every config key.
- Confirm install docs match actual installer behavior.
- Confirm uninstall docs are accurate.
- Confirm roadmap reflects what is done and what is next.
- Run `uv run ruff format .`.
- Run `uv run ruff check .`.
- Run `uv run pyright`.
- Run `uv run pytest`.
- Run coverage and keep it at 100 percent or explicitly document accepted misses.
- Bump version.
- Add changelog entry.
- Open the release PR.
- Merge the release PR.
- Tag main.
- Push the tag.
- Confirm GitHub Release is created.

## Phase 1.5 (post-1.0.0 follow-up): Post-release polish

Phase 1.5 is for useful polish that should not block the first public release.
It should improve cross-platform feel and adapter ergonomics after the core
release path is proven.

- PowerShell completion install and uninstall refinements beyond the Phase 1
  dynamic completion baseline.
- Windows installer polish discovered during real user testing.
- Cross-platform release smoke-test hardening beyond the minimum release gate.
- Adapter-facing documentation examples and troubleshooting guides.
- Small CLI usability improvements that do not change the core contract.

## Phase 2 (v0.2.x): Product intelligence

Recallium fulfills its product promise as a personal intelligence engine.

- Daily memory maintenance (dreamer reviews and improves the memory set).
- User reflection summaries for conversation topics.
- Historian conversation summaries at regular turn intervals.
- Nightly and workspace memory summaries injected into conversations.
- Raw message storage with retention policies.
- Storage compaction with policy-driven behavior.
- Importance scoring with decay and access boosting.
- Intent-native naming (`remember`, `recall`, `link`, `forget`).
- Entity tagging for faceted filtering.

## Keeping this up to date

This roadmap is kept in sync with the internal product spec. If you
complete something listed here, update it.
