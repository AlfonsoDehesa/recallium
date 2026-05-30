<p align="center">
  <img src="docs/assets/recollectium-banner.png" alt="Recollectium" width="100%">
</p>

# Recollectium

Local-first memory for AI agents.

## About

Recollectium is memory infrastructure for agents that should actually remember. Not vague chat history. Not a black-box profile trapped inside one hosted product. A local, inspectable memory engine you can run, query, migrate, back up, and plug into the tools you already use.

The promise is simple: every new agent session should start with continuity. Your preferences, project decisions, setup notes, hard-won debugging context, and recurring working patterns should not disappear when you change models, switch clients, or open a fresh terminal. Recollectium gives that context a durable home you control.

Core handles the serious parts: SQLite storage, local embeddings, semantic search, migrations, local service APIs, MCP tools, service lifecycle, structured logs, and adapter-facing discovery. Adapters stay thin. They bring the current workspace context, then let Core handle memory correctly and consistently.

OpenCode is the first important adapter target, but Recollectium is bigger than one client. It is the memory layer for a world where people use many agents, many models, and many interfaces, and still want one coherent record of what matters.

## Why another memory engine?

Most agent memory falls into one of a few awkward buckets: no durable memory, memory trapped inside one hosted client, memory that mixes personal preferences with project facts, or memory that is hard to inspect, move, and maintain.

Recollectium is built around these principles:

- **Local-first by default.** No memory leaves your machine unless you allow it. You own the data, the database, and the runtime.
- **Semantic recall.** Human memory does not work by exact string matching. Agent memory should not either. Recollectium uses local embeddings so agents can find the closest useful memories by meaning, not just by keywords.
- **User space as first-class context.** Workspace memory matters, but user memory is often the most valuable signal. An agent that understands your durable preferences, style, goals, and working patterns will work better for you across every project.
- **Easily self-hostable by design.** No paid memory provider, no hosted lock-in, no dependency maze. Install with one command and keep going.
- **Provider agnostic.** Use any AI provider, any model, any agent, closed source or open source. If you switch platforms, your memory comes with you.
- **Multi-platform and multi-surface.** Recollectium works through CLI, Python, local HTTP API, MCP stdio, and managed MCP service mode. It is usable from agents, scripts, plugins, and Python projects.
- **No feature compromise.** Higher-level memory workflows such as dreamer agents, context managers, summarizers, and richer adapter integrations can build on the same Core instead of inventing separate storage.
- **Open source and community driven.** Recollectium is built for people who want inspectable, portable, community-improved agent memory. Your memory, your way.

## Quick start

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.ps1 | iex"
```

For the full setup flow, including first memory, service startup, MCP, API, logs, and troubleshooting, see the [Quick Start](docs/wiki/Quick-Start.md) in the wiki source pages. These pages are ready to publish to the GitHub Wiki once GitHub initializes the wiki git remote.

Common next steps:

- Install details: [Installation](docs/wiki/Installation.md)
- Learn the model: [Concepts](docs/wiki/Concepts.md)
- Configure Recollectium: [Configuration](docs/wiki/Configuration.md)
- Use the CLI: [CLI Reference](docs/wiki/CLI-Reference.md)
- Start services: [Service Management](docs/wiki/Service-Management.md)
- Read logs: [Logs](docs/wiki/Logs.md)
- Connect through MCP: [MCP Server](docs/wiki/MCP-Server.md)
- Call the local API: [API Reference](docs/wiki/API-Reference.md)

## What Recollectium gives you

- Local SQLite memory storage.
- Explicit `user` and `workspace` memory scopes.
- Canonical memory buckets for preferences, facts, decisions, task context, configuration, bug findings, and notes.
- Create, search, list, get, update, and archive memory operations.
- Local FastEmbed embeddings with `jinaai/jina-embeddings-v2-small-en`.
- Background re-embedding jobs and embedding status inspection.
- CLI, Python API, local HTTP API, and MCP surfaces.
- Configurable CLI output, with human-readable text by default and JSON available for automation.
- Managed API and MCP service lifecycle with discovery metadata for adapters.
- Structured JSON logging with rotation.
- Bootstrap install, package upgrade, safe uninstall, and shell completion.

## Documentation

Start with the wiki source pages:

- [Wiki Home](docs/wiki/Home.md)
- [Quick Start](docs/wiki/Quick-Start.md)
- [Installation](docs/wiki/Installation.md)
- [Concepts](docs/wiki/Concepts.md)
- [Configuration](docs/wiki/Configuration.md)
- [Features and Commands](docs/wiki/Features-and-Commands.md)
- [CLI Reference](docs/wiki/CLI-Reference.md)
- [Service Management](docs/wiki/Service-Management.md)
- [Logs](docs/wiki/Logs.md)
- [MCP Server](docs/wiki/MCP-Server.md)
- [API Reference](docs/wiki/API-Reference.md)
- [Adapter and Plugin Integration](docs/wiki/Adapter-and-Plugin-Integration.md)
- [Verified Supported Plugins](docs/wiki/Verified-Supported-Plugins.md)
- [Troubleshooting](docs/wiki/Troubleshooting.md)
- [FAQ](docs/wiki/FAQ.md)

Repo docs that act as canonical contracts:

- [Local service API](docs/local-service-api.md)
- [OpenAPI JSON](docs/local-service-openapi.json)
- [OpenCode adapter contract](docs/opencode-adapter-contract.md)
- [Security policy](SECURITY.md)
- [Contributing guide](CONTRIBUTING.md)
- [Roadmap](ROADMAP.md)

## Local-first security model

Recollectium v1 services are local-first and unauthenticated. The recommended deployment is to run Recollectium on the same machine as the agent or client and keep services bound to localhost, usually `127.0.0.1`.

Binding the API or MCP service to a non-local interface can expose memory operations to anyone who can reach that interface. If you need split-machine access, use private networking with external access controls. For most users, Tailscale is the friendliest path.

Read [SECURITY.md](SECURITY.md) before changing service host settings or exposing Recollectium outside the local machine.

## Project status

Recollectium Core is in final v1.0 release preparation. Core is implemented; remaining release work is public wiki/docs polish and the final release sweep. OpenCode plugin implementation is planned after v1.

See [ROADMAP.md](ROADMAP.md) for the current release plan.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, quality gates, documentation rules, release checklist, and PR process.

Please do not publish sensitive vulnerability details in public issues. See [SECURITY.md](SECURITY.md) for security reporting guidance.

## License

Recollectium is licensed under the [GNU Affero General Public License v3.0](LICENSE).
