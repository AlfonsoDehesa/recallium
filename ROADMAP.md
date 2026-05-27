# Roadmap

## Phase 1 (v0.1.x): Release-ready core

Recallium Core is installable, runnable, documented, and ready for the first
public release. The local service, CLI, API, bootstrap installers, service
lifecycle, shell completion for Unix shells, uninstall behavior, and service
discovery are already in place.

Remaining release blockers:

- Packaging and distribution readiness: verify wheel and source distribution
  builds, verify `pip`, `pipx`, and `uv tool` installs, and confirm the release
  workflow can publish from a version tag.
- Workspace UID registry: define and implement the stable workspace identifier
  contract Core expects adapters to use.
- OpenCode adapter readiness handoff: ensure Core exposes and documents the
  service discovery, workspace UID, API, and capability contracts needed by the
  future adapter.
- PowerShell dynamic shell completion for Windows users, including config-key
  completion parity with argcomplete.
- Final release sweep: run the full pre-release checklist in `CONTRIBUTING.md`,
  refresh README, API docs, local access notes, roadmap, changelog, version, and
  quality gates.

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
