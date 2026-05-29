# Quick Start

This page gets Recollectium installed, initialized, and doing useful work quickly.

## 1. Install

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.ps1 | iex"
```

The bootstrap installer installs uv if needed, installs Recollectium as an isolated tool, runs initialization, and installs shell completion where safe.

## 2. Verify

```bash
recollectium --version
recollectium --help
```

If you installed with `pip`, `pipx`, or `uv tool`, run initialization once:

```bash
recollectium init
```

The first initialization downloads the local FastEmbed model cache. Expect roughly 100 MB and 30 to 120 seconds depending on network and machine speed.

## 3. Add a user memory

```bash
recollectium add   --space user   --type preference   --content "I prefer concise technical answers."
```

## 4. Search user memory

```bash
recollectium search-user "concise answers"
```

Searches default to all user buckets. Add `--type preference` only when you deliberately want to narrow recall.

## 5. Add a workspace memory

```bash
recollectium add   --space workspace   --workspace-uid recollectium   --type decision   --content "Use SQLite for local memory persistence."
```

## 6. Search workspace memory

```bash
recollectium search-workspace   "local persistence"   --workspace-uid recollectium
```

## 7. Start the local API service

```bash
recollectium service start api
recollectium service status
recollectium service discover
```

The default endpoint is `http://127.0.0.1:8765`.

## 8. Stop the service

```bash
recollectium service stop
```

## Where to go next

- Learn the model: [Concepts](Concepts.md)
- Configure paths and service settings: [Configuration](Configuration.md)
- Use every command: [CLI Reference](CLI-Reference.md)
- Run API or MCP services: [Service Management](Service-Management.md)
- Connect an MCP client: [MCP Server](MCP-Server.md)
- Call the local HTTP API: [API Reference](API-Reference.md)
