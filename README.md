# Recallium Core MVP

Recallium Core is a local-first Python memory engine for agents.

This MVP provides:

- Local SQLite storage for memories.
- Explicit user and workspace memory scopes.
- Create, search, list, retrieve, update, and archive operations.
- A JSON CLI and Python API for local development.
- Smart local embeddings with built-in FastEmbed using `jinaai/jina-embeddings-v2-small-en`.

## Current boundaries (what this repo does not include yet)

This MVP does not include:

- OpenCode adapter integration.
- Historian summaries.
- Dreamer workflows.
- Cloud sync, multi-user support, or UI.

## Local-first behavior

- Recallium Core runs fully local.
- First-time model cache download may require network access to fetch `jinaai/jina-embeddings-v2-small-en`.
- Data is stored in a local SQLite file.

## Smart embedding behavior

- Recallium uses one production embedding path: built-in local FastEmbed.
- Active profile: `provider=builtin-fastembed`, `model=jinaai/jina-embeddings-v2-small-en`.
- Long memory content is chunked per model profile before embedding.
- On startup and during search, stale profile embeddings are refreshed and tracked as embedding jobs.
- Use CLI and local service status endpoints to inspect profile state and job progress.

## Install

### Recommended: blank machine bootstrap

You do not need Python, pip, pipx, or uv installed first. The bootstrap
installer downloads uv, installs Recallium in an isolated tool environment,
and puts the `recallium` command on PATH.

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recallium/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/AlfonsoDehesa/recallium/main/install.ps1 | iex"
```

Verify the install:

```bash
recallium --version
recallium init
```

`recallium init` creates the config file, data/cache/log/runtime directories,
SQLite database, runs migrations, and downloads the built-in FastEmbed model.
It is safe to run more than once.

### Shell completion

Bootstrap install configures tab completion for bash, zsh, and fish
automatically. After `curl | sh`, open a new shell session and `recallium
<TAB>` works.

To set up completion manually:

```bash
recallium completion --install
```

To see the setup instructions for a specific shell:

```bash
recallium completion bash
recallium completion zsh
recallium completion fish
```

The completion eval line uses a managed comment block so uninstall can
identify and remove it cleanly:

```bash
# >>> recallium completion >>>
eval "$(recallium completion --source bash)"
# <<< recallium completion <<<
```

### Python package managers

If you already have Python 3.12 or newer:

```bash
pip install recallium
```

If you prefer isolated CLI tools:

```bash
pipx install recallium
```

Try without installing permanently:

```bash
uvx recallium --version
```

## Install for development

Recallium Core requires Python 3.12 or newer. Use `uv` for environment and dependency management.

```bash
uv sync --group dev
```

Run the full local quality gate:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

Run the CLI through the managed environment:

```bash
uv run recallium --help
```

## Updating

```bash
recallium update
```

This prints upgrade commands for the bootstrap installer, pip, pipx, and uv
tool installs. Existing memory updates still use `recallium update <memory_id>
...`.

## Uninstalling

```bash
recallium uninstall
```

This prints the package-manager command to remove the installed Recallium CLI.
Safe uninstall preserves local memories and settings by default. Preserved paths
include the config file, SQLite database, data directory, model cache, logs, and
runtime directory, so reinstalling Recallium later reuses the existing config and
database and runs any required migrations without overwriting your memories.
If Recallium installed a managed shell completion block, safe uninstall removes
that shell rc block while preserving your memories.

Package removal commands by install method:

| Install method | Command |
|---|---|
| Bootstrap installer or uv tool | `uv tool uninstall recallium` |
| pipx | `pipx uninstall recallium` |
| pip | `python -m pip uninstall recallium` |
| Source checkout | Remove the checkout or shell path entry manually. |

To preview a full data purge without deleting anything:

```bash
recallium uninstall --purge --dry-run
```

To permanently delete Recallium-owned config, data, cache, logs, and runtime
paths -- **this deletes your memories, and cannot be undone**:

```bash
recallium uninstall --purge
```

For non-interactive purge automation, use the explicit destructive confirmation
flag:

```bash
recallium uninstall --purge --yes-delete-all-recallium-data
```

Purge only removes paths that look Recallium-owned and refuses broad paths such
as your home directory, root directory, or current working directory. If the
configured cache path appears shared with other tools, Recallium skips it and
reports why. If a Recallium service is running, uninstall stops it cleanly before
printing package removal guidance or deleting purge targets; `--dry-run` shows
what would happen without stopping the service or deleting files.

## Data path behavior

- Default database path: `~/.local/share/recallium/recallium.db`
- Override database path in config: set `database.path` in `config.json`
- Override database path in CLI: `recallium --db /tmp/recallium.db ...`
- Override database path in Python: `RecalliumCore(db_path="/tmp/recallium.db")`

## Configuration

Recallium uses a JSON config file located at `~/.config/recallium/config.json`
by default. The file is auto-created with built-in defaults the first time you
run a command that loads the effective config. CLI flags override config values.
Inspection-only commands `recallium config --path` and `recallium config --defaults`
do not create a config file.

### Config file location

| Situation | Path |
|---|---|
| Default (Linux XDG) | `~/.config/recallium/config.json` |
| Custom via `--config` | Any path you specify. Explicit missing paths fail clearly unless a config creation command is used. |

The config directory (`~/.config/recallium/`) and file are created
automatically with restrictive permissions (`0700` for directories, `0600` for
the file).

### All available settings

```json
{
  "version": 1,
  "database": {
    "path": "recallium.db"
  },
  "embedding": {
    "provider": "builtin-fastembed",
    "model": "jinaai/jina-embeddings-v2-small-en"
  },
  "service": {
    "host": "127.0.0.1",
    "port": 8765
  },
  "logging": {
    "level": "info",
    "format": "json",
    "max_bytes": 10485760,
    "backup_count": 5
  },
  "directories": {
    "data": null,
    "cache": null,
    "logs": null,
    "runtime": null
  }
}
```

| Setting | Default | Description |
|---|---|---|
| `version` | `1` | Config schema version for future compatibility. |
| `database.path` | `"recallium.db"` | SQLite database path. Relative paths resolve against the data directory. Absolute paths are used as-is. |
| `embedding.provider` | `"builtin-fastembed"` | Embedding provider. Only `"builtin-fastembed"` is supported in this release. Other values fail validation. |
| `embedding.model` | `"jinaai/jina-embeddings-v2-small-en"` | Embedding model name. Only this model is supported in this release. Other values fail validation. |
| `service.host` | `"127.0.0.1"` | Host interface for the local HTTP service. |
| `service.port` | `8765` | TCP port for the local HTTP service. |
| `logging.level` | `"info"` | Log level for the `recallium.*` logger hierarchy. Allowed values: `debug`, `info`, `warning`, `error`. |
| `logging.format` | `"json"` | Log output format. Only `"json"` is supported in this release. |
| `logging.max_bytes` | `10485760` | Maximum log file size in bytes before rotation (10 MiB). Must be a positive integer. |
| `logging.backup_count` | `5` | Number of rotated log file backups to keep. Must be a positive integer. |
| `directories.data` | `null` (XDG default) | Override the data directory. |
| `directories.cache` | `null` (XDG default) | Override the cache directory. |
| `directories.logs` | `null` (XDG default) | Override the logs directory. |
| `directories.runtime` | `null` (XDG default) | Override the runtime directory. |

When `directories.*` is `null` or unset, Recallium uses standard XDG paths:

- Config: `$XDG_CONFIG_HOME/recallium/` (fallback `~/.config/recallium/`)
- Data: `$XDG_DATA_HOME/recallium/` (fallback `~/.local/share/recallium/`)
- Cache: `$XDG_CACHE_HOME/recallium/` (fallback `~/.cache/recallium/`)
- Logs: `$XDG_STATE_HOME/recallium/logs/` (fallback `~/.local/state/recallium/logs/`)
- Runtime: `$XDG_RUNTIME_DIR/recallium/` (fallback inside data directory)

### Priority order

Values are resolved in this order (highest wins):

1. CLI flags (e.g., `--db`, `--port`, `--host`)
2. Explicit values in `config.json`
3. Built-in defaults

### Using `recallium config`

```bash
# Print effective configuration (defaults merged with your overrides)
recallium config

# Print built-in defaults only
# Does not create a config file
recallium config --defaults

# Show where the config file lives
# Does not create a config file
recallium config --path

# Validate the config file (exit 0 on success, 1 on error)
recallium config --validate

# Run config and directory health checks
recallium config doctor

# Get a single value by dot-notation key
recallium config get service.port

# Set a value (creates the file if needed, preserves existing keys)
recallium config set service.port 9090

# Remove a key so the built-in default takes effect
recallium config unset service.host

# Create or overwrite the starter config with all defaults
recallium config init --force

# Open the config file in your editor ($EDITOR)
# Creates the file with defaults first if it does not exist
recallium config edit

# Reset the config file to built-in defaults
# Creates the file if it does not exist
recallium config reset
```

### CLI flag overrides

| CLI flag | Overrides config key | Applies to |
|---|---|---|
| `--db <path>` | `database.path` | All commands |
| `--host <host>` | `service.host` | `serve` command |
| `--port <port>` | `service.port` | `serve` command |
| `--log-level <level>` | `logging.level` | Current invocation only; does not modify config |
| `--config <path>` | — | Loads config from a custom path |


## Service Management

Recallium can run as a long-running service accessible over HTTP. Use the `recallium service` commands to manage the service lifecycle.

Two service types are available:

- **API** (`recallium service start api`): REST API server with all memory operations, embedding status, and health checks. Mounted at the configured `service.host` and `service.port`.
- **MCP** (`recallium service start mcp`): MCP (Model Context Protocol) HTTP server with memory tools for AI assistant integration. Uses SSE transport at the configured address.

  MCP tools exposed:

  - `add_memory` -- create a new memory
  - `get_memory` -- retrieve a single memory by ID
  - `update_memory` -- update a memory's content
  - `archive_memory` -- archive a memory by ID
  - `list_memories` -- list memories, optionally filtered
  - `search_user_memory` -- semantic search across user-space memories
  - `search_workspace_memory` -- semantic search within a workspace

Only one service can run at a time. The service manager uses a PID file to track the running process and prevent conflicts.

### Starting a service

```bash
# Start the REST API server
recallium service start api

# Start the MCP HTTP server
recallium service start mcp

# Use a custom database path
recallium --db /tmp/custom.db service start api
```

Output on success:

```json
{"endpoint": "http://127.0.0.1:8765", "pid": 12345, "status": "started", "type": "api"}
```

### Checking service status

```bash
recallium service status
```

When running:

```json
{"endpoint": "http://127.0.0.1:8765", "pid": 12345, "running": true, "type": "api"}
```

When no service is running:

```json
{"running": false}
```

If a stale PID file exists from a previous run that exited unexpectedly, the status output includes the last known service type and PID under `last_service`.

### Stopping a service

```bash
recallium service stop
```

Output:

```json
{"pid": 12345, "status": "stopped"}
```

When no service is running:

```json
{"status": "no_service_running"}
```

Shutdown sends SIGTERM and waits up to 10 seconds for graceful exit. If the process does not exit in time, SIGKILL is sent as a fallback.

### Restarting a service

```bash
# Restarts the currently running service
recallium service restart

# Restarts using the type from a stale PID file
recallium service restart --type api

# Specify a type when no trace of a previous service exists
recallium service restart --type mcp
```

Output:

```json
{"endpoint": "http://127.0.0.1:8765", "pid": 12346, "status": "restarted", "type": "api"}
```

### MCP stdio mode

The `mcp-stdio` command runs an MCP server over stdin/stdout. This mode is designed for AI assistant clients that spawn Recallium as a child process, such as Claude Desktop.

```bash
recallium mcp-stdio
```

No PID file is created for stdio mode. The process runs as long as the client is connected.

#### Claude Desktop configuration

Add this to your Claude Desktop `claude_desktop_config.json` to use Recallium as an MCP server:

```json
{
  "mcpServers": {
    "recallium": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/recallium",
        "run", "recallium", "mcp-stdio"
      ]
    }
  }
}
```

Adjust the `--directory` path to point at your Recallium Core checkout.

### PID file and runtime directory

The service manager writes a PID file to the runtime directory (default `$XDG_RUNTIME_DIR/recallium/service.pid`). The file contains JSON with the process ID, service type, and Linux process start-time metadata used to avoid acting on a reused PID:

```json
{"pid": 12345, "process_start_time": 1234567, "type": "api"}
```

The runtime directory can be overridden in config by setting `directories.runtime`.
Daemon stdout and stderr are redirected to `service-api.log` or `service-mcp.log` in the configured logs directory.

### Error handling

- Starting any service while another service is running produces a clear error: `ServiceConflictError: a mcp service is already running (PID 12345). Stop it before starting an api service.`
- Use `recallium service restart` to restart a running service.
- Stale PID files from crashed processes or PID reuse are cleaned automatically.

## CLI examples

Add a user memory:

```bash
recallium --db /tmp/recallium.db add \
  --space user \
  --type preference \
  --content "I prefer concise technical answers."
```

Search user memories:

```bash
recallium --db /tmp/recallium.db search-user "concise answers"
```

Add a workspace memory:

```bash
recallium --db /tmp/recallium.db add \
  --space workspace \
  --workspace-uid 7f3b0a5e-example-workspace \
  --type decision \
  --content "Use SQLite for local memory persistence."
```

Search workspace memories:

```bash
recallium --db /tmp/recallium.db search-workspace \
  "local persistence" \
  --workspace-uid 7f3b0a5e-example-workspace
```

Workspace memories are keyed by a stable workspace UID. Future adapters, such as
the OpenCode plugin, should create and pass that UID rather than using filesystem
paths as workspace identity.

All successful CLI commands return JSON.

Check embedding profile status:

```bash
recallium --db /tmp/recallium.db embedding-status
```

List embedding jobs:

```bash
recallium --db /tmp/recallium.db embedding-jobs
```

Get one embedding job:

```bash
recallium --db /tmp/recallium.db embedding-jobs --job-id <job-id>
```

## Python API examples

```python
from recallium import RecalliumCore

core = RecalliumCore(db_path="/tmp/recallium.db")

created = core.add_memory(
    space="user",
    type="preference",
    content="I prefer concise technical answers.",
)

results = core.search_user_memories("concise answers", limit=5)

print(created.id)
print(results[0].score if results else None)
```

## Local service status routes

- `GET /v1/embedding/status`
- `GET /v1/embedding/jobs`
- `GET /v1/embedding/jobs/{job_id}`

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the feature plan and version targets.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow. The short
version: open an issue for bugs and feature requests, submit PRs from
feature branches, and keep your commits clean and your tests passing.
