# Roadmap

## Phase 1 (v0.1.x): Release-ready core

Recallium Core is installable, runnable, documented, and ready for the first
public release. The local service, CLI, API, bootstrap installers, service
lifecycle, shell completion for Unix shells, uninstall behavior, and service
discovery are already in place.

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

### PowerShell dynamic shell completion

Release goal: Windows users get dynamic Tab completion in PowerShell with parity
for the important Recallium CLI paths.

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

## Phase 1.5 (v0.1.x follow-up): Post-release polish

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
