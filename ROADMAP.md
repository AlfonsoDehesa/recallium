# Roadmap

## v1.0.0: Core release

Recollectium Core is at v1.0.0. The release includes the local memory core, CLI, Python API, local HTTP API, MCP stdio, managed MCP service, local embeddings, service lifecycle, install, upgrade, uninstall, logging, shell completion, workspace UID management, configuration, and adapter discovery contract.

Completed in v1.0.0:

- [x] Core local memory MVP with user and workspace memory CRUD, search, update, archive, and list operations.
- [x] Local FastAPI service API with health, version, capabilities, memory, and embedding endpoints.
- [x] Smart local embeddings with built-in FastEmbed using `jinaai/jina-embeddings-v2-small-en`.
- [x] Background re-embedding worker with embedding job tracking.
- [x] Versioned SQLite schema migrations with an internal migration runner.
- [x] Config file system and predictable data, cache, log, and runtime directories.
- [x] Service lifecycle and service type support for API and MCP services.
- [x] Structured logging, lifecycle events, crash detection, and CLI log-level handling.
- [x] Python 3.12 compatibility.
- [x] Repository policy docs, contribution workflow, issue templates, and release checklist.
- [x] AGPL-3.0 license selection.
- [x] Cross-platform bootstrap install flow for Linux, macOS, and Windows.
- [x] Safe uninstall surface with default data preservation and explicit purge.
- [x] Bash, zsh, fish, and PowerShell shell completion support.
- [x] Local service discovery for adapters through `recollectium service discover` and `service-discovery.json`.
- [x] Workspace UID contract: normalization, listing, rename, aliasing, and CLI/API/MCP parity.
- [x] Install-time init and model readiness checks for CLI, service startup, and bootstrap install flows.
- [x] Canonical memory buckets and optional read filters across CLI, API, MCP, docs, and completion.
- [x] OpenCode adapter readiness handoff through documented service discovery, health, version, capabilities, workspace UID behavior, and adapter contract docs.
- [x] Package upgrade flow through `recollectium upgrade` with dry-run/check modes and service-state preservation.
- [x] CLI failure contracts: non-argparse failures emit structured JSON on stderr and stdout JSON contracts stay clean.
- [x] Local access and security documentation through `SECURITY.md`, README/API/adapter warnings, and private-network guidance.
- [x] Public docs and wiki release pass for README, CONTRIBUTING, SECURITY, ROADMAP, API docs, adapter docs, and GitHub Wiki pages.
- [x] Configurable CLI output with human-readable terminal output by default and JSON mode for automation.
- [x] TTY-aware CLI color for human-readable output while pipes, captured output, and JSON mode stay uncolored.

## Phase 1.5 (post-1.0.0 follow-up): Post-release polish

Phase 1.5 is limited to follow-up work that happens after the 1.0.0 release path is proven.

### Windows hardening after real user testing

- [ ] Harden the Windows installer based on actual user-reported install failures.
- [ ] Harden Windows service, PATH, shell, and profile behavior discovered during real usage.
- [ ] Harden Windows smoke tests based on failures that appear after 1.0.0.

### PyPI publication

- [ ] Verify `pyproject.toml` package metadata: name, version, license, Python version, dependencies, and CLI entry point.
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

Release goal: OpenCode can use Recollectium Core through a thin plugin or adapter that consumes the Core service contract instead of reimplementing memory logic.

- [ ] Build the OpenCode plugin or adapter.
- [ ] Consume Core service discovery from the plugin.
- [ ] Support explicit remote Core base-URL configuration for private-network split-machine Core instances and validate those endpoints with health, version, and capabilities.
- [ ] If local autodiscovery reports the service is not running, attempt to start the local API service before guiding the user.
- [ ] Consume Core workspace UID behavior from the plugin.
- [ ] Expose Recollectium-backed tools inside OpenCode.
- [ ] Add plugin-facing documentation and troubleshooting guides.

## Phase 2 (v1.x): Product intelligence

Recollectium fulfills its product promise as a personal intelligence engine after the 1.0.0 release line is stable.

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

This roadmap is kept in sync with the internal product spec. If a PR completes something listed here, that same PR must update this file, move the feature into the completed v1.0.0 section when applicable, mark the completed checklist item, and leave the remaining roadmap accurate.
