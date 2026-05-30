# Recollectium Wiki

Welcome to the Recollectium manual.

Recollectium is a local-first memory engine for AI agents. It stores and searches facts, preferences, decisions, task context, and project knowledge without tying that memory to one client.

## What sets Recollectium apart

Recollectium is a portable memory layer for local ownership, semantic recall, and interoperability across agents.

- Memory lives on your machine unless you choose otherwise.
- User preferences, communication style, durable goals, and personal context can be stored separately from project notes.
- Semantic search lets agents find relevant memories without exact keyword or type matches.
- Tools that can use CLI, Python, HTTP, or MCP can share the same Core.
- Installation is one command, storage is SQLite, and services are managed by Recollectium.
- The project is open source, inspectable, and portable.

## Start here

- [Quick Start](Quick-Start.md): install, initialize, add memories, search, and start services.
- [Installation](Installation.md): one-command install, package-manager installs, development install, upgrade, and uninstall.
- [Concepts](Concepts.md): user memory, workspace memory, semantic recall, aliases, and embeddings.
- [CLI Reference](CLI-Reference.md): all commands and flags.
- [API Reference](API-Reference.md): local HTTP API calls, parameters, responses, and errors.
- [MCP Server](MCP-Server.md): MCP modes and tool contracts.
- [Troubleshooting](Troubleshooting.md): common install, PATH, config, service, API, and MCP fixes.

## Repo docs that stay canonical

Some documents are contracts for implementers and should be treated as canonical:

- [Local service API](../local-service-api.md)
- [OpenAPI JSON](../local-service-openapi.json)
- [OpenCode adapter contract](../opencode-adapter-contract.md)
- [Security policy](../../SECURITY.md)
- [Contributing guide](../../CONTRIBUTING.md)
