# Roadmap

## Phase 1 (v1.0.0): Release-ready core

Recollectium Core is installable, runnable, documented, and ready for the first
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
- [x] Uninstall cleanup for Recollectium-managed shell completion blocks.
- [x] Local service discovery for adapters through `recollectium service discover` and `service-discovery.json`.
- [x] Workspace UID contract: normalization, listing, rename, and CLI/API/MCP parity.
- [x] Install-time init and model readiness: central `_ensure_model_ready()` wrapper with state file tracking, service startup gate, CLI embedding gate, bootstrap install auto-init, offline error guidance.
- [x] Canonical memory buckets and optional read filters: small canonical user/workspace bucket sets, scope-aware write validation, exact-match optional read filters, CLI/API/MCP/docs alignment, and completion coverage.
- [x] OpenCode adapter readiness handoff: documented service discovery, health/version/capabilities validation, workspace UID resolution, adapter workflow, and adapter contract docs.
- [x] Workspace UID aliasing across Core, CLI, API, MCP, docs, and adapter contract: direct aliases, alias resolution for workspace operations, conflict-safe migration with `--migrate-existing`, and rename alias preservation.
- [x] Package upgrade flow through `recollectium upgrade`: latest-release checks, pip/pipx/uv/bootstrap/source install methods, dry-run/check modes, service-state preservation, docs, unit tests, and install-smoke CI coverage.
- [x] CLI error-formatting audit: non-argparse failures return structured JSON on stderr with standardized exit codes, stdout JSON contracts stay clean, and representative failure paths are covered by tests.
- [x] CI uninstall-flow coverage across bootstrap install-smoke jobs: default uninstall preservation, explicit purge, managed Unix completion cleanup, package-manager guidance assertions, and final `uv tool uninstall recollectium` cleanup.
- [x] Local access and security documentation audit: canonical `SECURITY.md`, README/API/adapter warnings, release checklist coverage, and private-network guidance for split-machine deployments.
- [x] PowerShell completion lifecycle: dynamic `Register-ArgumentCompleter` wrapper, install/update/uninstall managed profile blocks, bootstrap metadata, and tests.
- [x] Public docs and wiki release pass: focused README with banner and wiki routing, reorganized CONTRIBUTING.md, clarified SECURITY.md, wiki source pages for every release surface, and release checklist coverage for wiki maintenance.
- [x] Configurable CLI output: `cli_output` defaults to human-readable rendering for terminal use, JSON remains available for automation, and `--json` / `--human-readable` override the config per invocation.
- [x] TTY-aware CLI color: human-readable CLI output uses Rich-backed ANSI color on TTY streams while pipes, captured output, and JSON mode stay uncolored.

Remaining release blockers:

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
- [ ] Verify `pip install recollectium` from the published package.
- [ ] Verify `pipx install recollectium` from the published package.
- [ ] Verify `uv tool install recollectium` from the published package.
- [ ] Confirm `recollectium --version` works after each install method.
- [ ] Confirm `recollectium init` works after each install method.
- [ ] Confirm bootstrap installers can install the published package or release tag.

### OpenCode plugin work

Release goal: OpenCode can use Recollectium Core through a thin plugin or adapter
that consumes the Core service contract instead of reimplementing memory logic.

- [ ] Build the OpenCode plugin or adapter.
- [ ] Consume Core service discovery from the plugin.
- [ ] Support explicit remote Core base-URL configuration for private-network
  split-machine Core instances and validate those endpoints with health, version,
  and capabilities.
- [ ] If local autodiscovery reports the service is not running, attempt to start
  the local API service before guiding the user.
- [ ] Consume Core workspace UID behavior from the plugin.
- [ ] Expose Recollectium-backed tools inside OpenCode.
- [ ] Add plugin-facing documentation and troubleshooting guides.

## Phase 2 (v1.x): Product intelligence

Recollectium fulfills its product promise as a personal intelligence engine after the first 1.0 release line is stable.

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
