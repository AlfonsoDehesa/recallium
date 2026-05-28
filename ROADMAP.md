# Roadmap

## Phase 1 (v1.0.0): Release-ready core

Recallium Core is installable, runnable, documented, and ready for the first
public release. The local service, CLI, API, bootstrap installers, service
lifecycle, shell completion for Unix shells, uninstall behavior, and service
discovery are already in place.

Completed:

- [x] Core local memory MVP with user and workspace memory CRUD, search, update, archive, and list operations.
- [x] Local FastAPI service API with health, version, capabilities, memory, and embedding endpoints.
- [x] Smart local embeddings with built-in FastEmbed using `jinaai/jina-embeddings-v2-small-en`.
- [x] Background re-embedding worker with embedding job tracking.
- [x] Full test coverage push across the implemented core surface.
- [x] Versioned SQLite schema migrations with an internal migration runner.
- [x] Config file system and predictable data, cache, log, and runtime directories.
- [x] Service lifecycle and service type support for API and MCP services.
- [x] Structured logging, lifecycle events, crash detection, and CLI log-level handling.
- [x] Python 3.12 compatibility.
- [x] Repository policy docs, contribution workflow, issue templates, and release checklist.
- [x] AGPL-3.0 license selection.
- [x] Cross-platform bootstrap install flow for Linux, macOS, and Windows.
- [x] Safe uninstall surface with default data preservation and explicit purge.
- [x] Bash, zsh, and fish shell completion through argcomplete.
- [x] Uninstall cleanup for Recallium-managed shell completion blocks.
- [x] Local service discovery for adapters through `recallium service discover` and `service-discovery.json`.
- [x] Workspace UID contract: normalization, listing, rename, and CLI/API/MCP parity.
- [x] Install-time init and model readiness: central `_ensure_model_ready()` wrapper with state file tracking, service startup gate, CLI embedding gate, bootstrap install auto-init, offline error guidance.
- [x] Canonical memory buckets and optional read filters: small canonical user/workspace bucket sets, scope-aware write validation, exact-match optional read filters, CLI/API/MCP/docs alignment, and completion coverage.

Remaining release blockers:


### OpenCode adapter readiness handoff

Release goal: Core is ready for the future OpenCode adapter even though the
adapter itself is not part of this repository.

- [ ] Document exactly how the adapter discovers the running service.
- [ ] Document how the adapter checks service health, version, and capabilities.
- [ ] Document how the adapter gets or creates the workspace UID.
- [ ] Confirm the API has everything the adapter needs for user and workspace
  memory operations.
- [ ] Confirm capability names are stable enough for adapter compatibility checks.
- [ ] Confirm errors are clear when the service is not running or incompatible.
- [ ] Write an adapter workflow doc: install Core, start service, discover service,
  validate service, then use memory endpoints.
- [ ] Add an adapter contract section to the service or API docs if needed.

### Rich dynamic PowerShell shell completion

Release goal: Windows users get rich dynamic Tab completion in PowerShell with
parity for the important Recallium CLI paths.

- [ ] Add PowerShell as a supported completion target.
- [ ] Generate a `Register-ArgumentCompleter` script.
- [ ] Make PowerShell call Recallium dynamically during Tab completion.
- [ ] Complete top-level commands.
- [ ] Complete subcommands.
- [ ] Complete command flags.
- [ ] Complete config keys for `recallium config get/set/unset`.
- [ ] Add install support so the managed completion block can be added to the
  correct PowerShell profile.
- [ ] Add uninstall support so Recallium can remove the managed PowerShell
  completion block.
- [ ] Ensure bootstrap install records the PowerShell completion profile edit in
  install metadata where appropriate.
- [ ] Support both Windows PowerShell and PowerShell 7 where practical, or document
  the supported shell version clearly.
- [ ] Add tests for generated PowerShell script output.
- [ ] Add tests for PowerShell profile install, duplicate detection, uninstall
  cleanup, and dry-run uninstall behavior.
- [ ] Add docs for manual and automatic PowerShell setup.
- [ ] Add CI or smoke coverage for the PowerShell completion install path where
  practical.

### CLI error-formatting audit

Release goal: users and automation get predictable command failures across the
whole CLI.

- [ ] Audit every CLI command for consistent exit codes.
- [ ] Audit stderr messages so validation, not-found, config, service, embedding,
  and install errors are clear and actionable.
- [ ] Preserve stdout JSON contracts for successful machine-readable commands.
- [ ] Confirm commands that are meant for automation return structured JSON where
  appropriate.
- [ ] Add or update tests for representative error paths across the CLI.

### Local access and security documentation audit

Release goal: users understand the local-only security model before exposing the
service outside localhost.

- [ ] Document that the Phase 1 local service is unauthenticated.
- [ ] Document that binding to non-local interfaces can expose memory contents.
- [ ] Confirm README, service API docs, and config docs explain host and port risks.
- [ ] Confirm install and service docs recommend local-only defaults.
- [ ] Add release checklist coverage for local access and security assumptions.

### Update flow

Release goal: `recallium update` can check for, download, and apply updates
without requiring manual reinstall steps.

- [ ] `recallium update` checks the installed version against the latest release.
- [ ] Supports pip, pipx, and uv install methods.
- [ ] Bootstrap-installed instances can update through the bootstrap path.
- [ ] Dry-run mode shows what would be updated without applying changes.
- [ ] Clear progress and error messaging for network failures, permission issues,
  and incompatible install methods.
- [ ] Update preserves user config, data, and service state.
- [ ] Add tests for version check, update apply, dry-run, and error paths.

### CI uninstall-flow coverage

Release goal: every bootstrap install-smoke path also proves Recallium can be
uninstalled cleanly.

- [ ] Update CI install-smoke jobs to run the appropriate uninstall flow after the
  install and CLI smoke checks pass.
- [ ] Verify default uninstall preserves Recallium data by default.
- [ ] Verify purge uninstall removes Recallium-managed data only when explicitly
  requested.
- [ ] Verify managed shell completion cleanup runs during uninstall where that shell
  completion was installed.
- [ ] Verify uninstall output gives package-manager guidance without failing the CI
  job for expected package-manager ownership boundaries.
- [ ] Cover Linux, macOS, Windows x86_64, and Windows ARM64 install-smoke jobs where
  practical.

### GitHub Wiki

Release goal: Recallium ships with a public GitHub Wiki that covers every
user-facing surface at release quality, alongside the README.

- [ ] Create and populate the GitHub Wiki with pages for install, config, CLI
  reference, service management, uninstall, memory types, API overview, and
  local access/security.
- [ ] Keep the Wiki in sync with the README and API docs on every PR that
  changes user-facing behavior, docs, or configuration.
- [ ] Add Wiki maintenance to CONTRIBUTING.md, the release checklist, and
  AGENTS.md so agents and contributors keep it current.
- [ ] Confirm the Wiki is current and complete during the final release sweep.

### Final release sweep

Release goal: no embarrassing loose ends before tagging.

- [ ] Run the full release checklist in `CONTRIBUTING.md`.
- [ ] Confirm all CLI help text is accurate.
- [ ] Confirm README is current.
- [ ] Confirm API docs match the running service.
- [ ] Confirm OpenAPI JSON matches FastAPI output.
- [ ] Confirm config docs list every config key.
- [ ] Confirm install docs match actual installer behavior.
- [ ] Confirm uninstall docs are accurate.
- [ ] Confirm roadmap reflects what is done and what is next.
- [ ] Run `uv run ruff format .`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run pyright`.
- [ ] Run `uv run pytest`.
- [ ] Run coverage and keep it at 100 percent or explicitly document accepted misses.
- [ ] Bump version.
- [ ] Add changelog entry.
- [ ] Open the release PR.
- [ ] Merge the release PR.
- [ ] Tag main.
- [ ] Push the tag.
- [ ] Confirm GitHub Release is created.

## Phase 1.5 (post-1.0.0 follow-up): Post-release polish

Phase 1.5 is limited to follow-up work that happens after the 1.0.0 release
path is proven.

### Windows hardening after real user testing

- [ ] Harden the Windows installer based on actual user-reported install failures.
- [ ] Harden Windows service, PATH, shell, and profile behavior discovered during
  real usage.
- [ ] Harden Windows smoke tests based on failures that appear after 1.0.0.

### PyPI publication

- [ ] Verify `pyproject.toml` package metadata: name, version, license, Python
  version, dependencies, and CLI entry point.
- [ ] Confirm `CHANGELOG.md` and `pyproject.toml` version match.
- [ ] Build a wheel and source distribution from the release state.
- [ ] Upload to the intended package index after the release is cut.
- [ ] Verify `pip install recallium` from the published package.
- [ ] Verify `pipx install recallium` from the published package.
- [ ] Verify `uv tool install recallium` from the published package.
- [ ] Confirm `recallium --version` works after each install method.
- [ ] Confirm `recallium init` works after each install method.
- [ ] Confirm bootstrap installers can install the published package or release tag.

### OpenCode plugin work

- [ ] Build the OpenCode plugin or adapter outside the Core release scope.
- [ ] Consume Core service discovery from the plugin.
- [ ] Consume Core workspace UID behavior from the plugin.
- [ ] Expose Recallium-backed tools inside OpenCode.
- [ ] Add plugin-facing documentation and troubleshooting guides.

## Phase 2 (v0.2.x): Product intelligence

Recallium fulfills its product promise as a personal intelligence engine.

- [ ] Daily memory maintenance (dreamer reviews and improves the memory set).
- [ ] User reflection summaries for conversation topics.
- [ ] Historian conversation summaries at regular turn intervals.
- [ ] Nightly and workspace memory summaries injected into conversations.
- [ ] Raw message storage with retention policies.
- [ ] Storage compaction with policy-driven behavior.
- [ ] Importance scoring with decay and access boosting.
- [ ] Intent-native naming (`remember`, `recall`, `link`, `forget`).
- [ ] Entity tagging for faceted filtering.

## Keeping this up to date

This roadmap is kept in sync with the internal product spec. If a PR completes
something listed here, that same PR must update this file, move the feature into
the `Completed` section, mark the completed checklist item, and leave the
remaining roadmap accurate.
