# Changelog

Recollectium v1.0.0 is here! 🎉

This first release turns the idea into a real local-first memory system for agents: private by default, useful from the CLI, scriptable through the API, and ready for MCP workflows. It includes the core memory engine, semantic search, workspace identity, service discovery, install and upgrade flows, shell completion, docs, tests, and the release machinery needed to keep it moving. The exciting part is what this unlocks: a durable memory layer for agents without asking users to hand their context to someone else's cloud. This is the foundation, and now the fun part starts: building adapters, workflows, and better agent experiences on top of it. 🚀

## Unreleased

### ✨ Features

- Added the local-first Recollectium Core memory engine with SQLite-backed storage for private, durable memory on a user's own machine.
- Added user and workspace memory scopes with canonical memory buckets, type filters, metadata, and archive-aware retrieval.
- Added memory add, search, list, get, update, and archive operations across the CLI, Python API, local HTTP API, and MCP surfaces.
- Added FastEmbed semantic search with the `jinaai/jina-embeddings-v2-small-en` model, chunk-aware ranking, background re-embedding jobs, and embedding and job status reporting.
- Added SQLite migrations plus predictable config, data, cache, log, and runtime directories across supported platforms.
- Added a CLI with JSON output for automation and Rich-backed human-readable output for interactive terminals.
- Added a Python API, local FastAPI HTTP service, MCP stdio server, and managed MCP service for integrating local memory into tools.
- Added FastAPI endpoints for health, version, capabilities, memories, embeddings, workspaces, and service metadata.
- Added MCP tools for memory operations, workspace management, embedding status, embedding jobs, and service discovery.
- Added managed service lifecycle commands with start, stop, status, restart, discovery metadata, and local endpoint reporting.
- Added workspace UID normalization, listing, rename, resolve, and alias support for stable workspace identity across moved or renamed projects.
- Added an OpenCode adapter readiness contract with discovery, health, capability, workspace, remote Core, and split-machine deployment guidance.
- Added install-time initialization and model-readiness checks plus bootstrap installers for Linux, macOS, and Windows.
- Added upgrade checks, dry-run upgrade planning, and package upgrade flows that preserved running service state.
- Added safe uninstall commands that preserved user data by default and required an explicit purge for data removal.
- Added shell completion generation for bash, zsh, fish, and PowerShell, including completion support for configuration keys.
- Added structured JSON logging with rotation plus lifecycle and failure events for install, service, CLI, API, MCP, embedding, and uninstall paths.
- Added an optional seeded development memory database with config toggles and `recollectium dev reset` for repeatable local testing.

### 🐛 Fixes

- Fixed validation for memory payloads, workspace identifiers, non-finite floats, bucket filters, and mixed workspace identity inputs.
- Fixed CLI stdout JSON contracts so automation output stayed clean while non-argparse failures emitted structured JSON on stderr.
- Hardened service lifecycle handling for stale or corrupt PID files, daemon cleanup, process ownership checks, crash detection, and discovery-file cleanup.
- Improved install and model-readiness failure handling with clearer offline, model download, and recovery guidance.
- Fixed MCP parity gaps for metadata, filters, embedding tools, workspace operations, and JSON metadata parsing failures.
- Fixed workspace alias handling and same-UID rename behavior so workspace identity updates were predictable and non-destructive.
- Fixed uninstall and completion cleanup behavior across supported shells and platforms.
- Clarified local service, API, security, and documentation wording where earlier guidance could imply unsupported authentication, exposure, or deployment guarantees.

### 🧹 Chores

- Adopted the AGPL-3.0-only license for the public release.
- Standardized the project on Python 3.12 or later with a uv-managed contributor and release workflow.
- Added contributor workflow documentation, issue templates, release checklist guidance, changelog conventions, and release automation.
- Added changelog validation and release workflow enforcement for curated release notes.
- Refreshed the README, SECURITY, ROADMAP, CONTRIBUTING, local service API docs, OpenAPI contract, OpenCode adapter contract, and GitHub Wiki documentation.
- Expanded CI and test coverage for core memory behavior, service lifecycle, MCP, install, uninstall, completion, and release-critical paths.
- Documented the v1 local-first unauthenticated security model with localhost defaults and private-network guidance.
- Retired repo-hosted wiki source pages in favor of the published GitHub Wiki as the canonical long-form documentation.
