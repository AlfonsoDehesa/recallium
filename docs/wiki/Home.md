# Recollectium Wiki

Welcome to the Recollectium manual.

Recollectium is a local-first memory engine for AI agents. It gives agents a durable, inspectable place to store and search facts, preferences, decisions, task context, and project knowledge without locking that memory inside one client.

## What sets Recollectium apart

Recollectium is not just a helper database for one agent. It is a portable memory layer designed around ownership, semantic recall, and agent interoperability.

- **Local-first by default:** memory lives on your machine unless you choose otherwise.
- **User memory matters:** Recollectium treats user preferences, communication style, durable goals, and personal context as first-class memory, not an afterthought behind project-only notes.
- **Semantic search by meaning:** agents can ask for "preferences about wording" and find the right preference memories without needing an exact `type` filter every time.
- **Portable across agents and models:** any tool that can use CLI, Python, HTTP, or MCP can use the same Core.
- **Simple to self-host:** installation is one command, runtime is local, storage is SQLite, and services are managed by Recollectium.
- **Open source and community driven:** Recollectium is built for people who want their memory stack to be inspectable, extensible, and owned by the community.

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
