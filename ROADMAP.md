# Roadmap

## Phase 1 (v0.1.x): Installable core infrastructure

Recallium Core is fully installable, runnable, and ready for integration.

- Python 3.12+, `uv` for environment and dependency management.
- Config file with auto-creation, validation, and CLI overrides.
- Structured JSON logging with rotation and configurable levels.
- Service lifecycle commands with PID files and graceful shutdown.
- Smart embeddings via built-in FastEmbed.
- Database migrations with versioned runner.
- CLI for memory operations, embedding status, and service management.
- Local FastAPI + uvicorn HTTP service with OpenAPI docs.

In progress:

- One-command bootstrap installer (cross-platform, zero dependencies).
- Packaging and distribution.
- Workspace UID registry and OpenCode adapter discovery.
- CLI polish, shell completion, `--version` flag, and consistent errors.
- PowerShell dynamic shell completion for Windows users.
- Install guide, API docs, and local access control documentation.

## Phase 1.5 (v0.1.x follow-up): Cross-platform polish

Recallium keeps Phase 1 focused while capturing polish work that should happen
before Windows is treated as fully first-class.

- PowerShell shell completion for Windows users.
- PowerShell install and uninstall integration for managed completion blocks.
- Completion docs for PowerShell alongside bash, zsh, and fish.

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
