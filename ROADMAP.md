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

Remaining release blockers:

### Workspace UID contract

Release goal: Core has a stable workspace identity contract that works across
machines, mounts, paths, and adapters with zero registration, zero dotfiles,
and zero model involvement.

- [ ] Document the contract: a workspace UID is any non-empty string the caller
  chooses. Core stores and retrieves memories by that string as-is after
  normalization. No registration, no dotfiles, no git dependency.
- [ ] Add `workspace.uid_normalization` config key with two modes:
  `normalize` (default) and `exact`. In `normalize` mode, every workspace UID
  is lowercased, non-alphanumeric characters replaced with a single dash,
  consecutive dashes collapsed, and leading/trailing dashes stripped. In
  `exact` mode, the UID is passed through unchanged.
- [ ] Apply normalization at the storage boundary before every write and
  lookup so all adapters, CLI calls, and API requests benefit automatically.
- [ ] Add `recallium workspace current` CLI command that returns the
  normalized directory basename of the current working directory.
- [ ] Add `recallium workspace list` CLI command that shows all distinct
  workspace UIDs from the database (no separate registry file).
- [ ] Document the adapter contract: the adapter resolves the workspace UID
  from the actual directory the model is working in (not from a session stash
  or explicit declaration). Follow the file path, derive the basename, and
  use that as the UID. The adapter injects the resolved UID into every memory
  call; the model never picks or types the UID.
- [ ] Add tests for normalization across common collision patterns, exact
  mode passthrough, `workspace current` in nested and root directories, and
  `workspace list` with mixed UIDs.

### Install-time initialization and model readiness

Release goal: bootstrap install leaves Recallium ready to use by default, and
embedding-using commands always run against the configured model.

- [ ] Keep the normal package install flow first.
- [ ] During bootstrap install, automatically run init if no config file exists.
- [ ] If a config file already exists, skip init and preserve the existing config.
- [ ] After install and any needed init, automatically prepare the configured
  FastEmbed model with no extra user action.
- [ ] If the configured model is missing, download or warm it before install
  finishes.
- [ ] If the configured model differs from the currently prepared Recallium model,
  download or warm the new configured model and switch to it only after it is
  ready.
- [ ] Delete and replace old Recallium-managed model state only when it is safe and
  clearly owned by Recallium.
- [ ] Keep `recallium init` available as an explicit user command.
- [ ] Keep model preparation available through explicit user-facing commands where
  appropriate.
- [ ] On service startup, verify the configured model is ready before the service
  finishes starting.
- [ ] Before any CLI command that needs embeddings completes, verify the configured
  model is ready.
- [ ] On any surface that needs embeddings, if the configured model is not ready,
  prepare it, then resume and finish the original command, API request, or
  service operation.
- [ ] Do not check or report model mismatch for commands that do not need
  embeddings.
- [ ] Add a code comment at the central model-readiness wrapper explaining that
  future commands that need embeddings must use this flow.
- [ ] Ensure the model-readiness flow works with embedding profile migration and
  re-embedding jobs when the configured model changes.
- [ ] Extend the model download UX work to include progress or status for model
  migration and re-embedding triggered by model changes.
- [ ] Add tests for absent config install, existing config install, missing model,
  changed model, service startup readiness, embedding CLI readiness,
  non-embedding commands skipping model checks, and migration progress/status.

### FastEmbed model download and migration UX

Release goal: first-run model setup and configured-model migration are
understandable and recoverable instead of feeling like Recallium silently hung or
failed.

- [ ] Make `recallium init` clearly explain that it may download the built-in
  FastEmbed model on first run.
- [ ] Surface clear progress or status messaging around model cache warmup where
  practical without breaking JSON output contracts.
- [ ] Surface clear progress or status messaging for embedding migration and
  re-embedding when the configured model changes.
- [ ] Provide actionable offline guidance when the model cannot be fetched.
- [ ] Preserve machine-readable CLI output for automation.
- [ ] Document first-run model cache behavior and configured-model migration behavior
  in README install guidance.
- [ ] Add tests for success, timeout, unavailable provider, unavailable model,
  migration progress/status, and user-facing error text.

### Structure around memory types

Release goal: Recallium ships with a defined, documented set of memory types so
agents, adapters, and users share a common vocabulary instead of guessing at
freeform strings.

- [ ] Define a stable set of supported memory types: preference, fact, note,
  decision, task_context, summary, and reflection.
- [ ] Validate memory type against the supported set during add and update.
- [ ] Reject unknown memory types with a clear error that lists the allowed
  values.
- [ ] Add known-type completion for `--type` in the CLI (both argcomplete and
  PowerShell).
- [ ] Document supported memory types and their intended usage in README, CLI
  help, and API docs.
- [ ] Keep the schema and endpoints forward-compatible with Phase 2 intent-native
  naming (`remember`, `recall`, `link`, `forget`).
- [ ] Add tests for valid types, unknown types, and type completion across both
  completion engines.

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
