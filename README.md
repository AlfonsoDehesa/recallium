# Recollectium Core MVP

Recollectium Core is a local-first Python memory engine for agents.

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

- Recollectium Core runs fully local.
- First-time model cache download may require network access to fetch `jinaai/jina-embeddings-v2-small-en`.
- Data is stored in a local SQLite file.

## Local access and security

Recollectium is local-first software. In v1, the API and MCP services are unauthenticated and are not hardened as public network services. The SQLite memory database is not encrypted by Recollectium.

The recommended v1 deployment is to run Recollectium on the same machine as the agent or client and keep services bound to localhost, usually `127.0.0.1`. Binding to a non-local interface, such as `0.0.0.0`, a LAN address, a VPN address, a container bridge, or a public interface, can expose unauthenticated memory operations to anyone who can reach that interface.

Any user, process, or network client with sufficient access to the Recollectium data directory, database file, or unauthenticated service endpoint can read, modify, or delete memories. Because memories influence what agents recall, unauthorized memory changes can also influence agent behavior.

If the agent and Recollectium must run on different machines, expose Recollectium only over private networking with external access controls. For most users, a private overlay network such as Tailscale is the recommended split-machine path. See [SECURITY.md](SECURITY.md) for the full v1 security model.

## Smart embedding behavior

- Recollectium uses one production embedding path: built-in local FastEmbed.
- Active profile: `provider=builtin-fastembed`, `model=jinaai/jina-embeddings-v2-small-en`.
- Long memory content is chunked per model profile before embedding.
- On startup and during search, stale profile embeddings are refreshed and tracked as embedding jobs.
- Use CLI and local service status endpoints to inspect profile state and job progress.

## Install

### Recommended: blank machine bootstrap

You do not need Python, pip, pipx, or uv installed first. The bootstrap
installer downloads uv, installs Recollectium in an isolated tool environment,
runs `recollectium init` (config, database, model), and puts the `recollectium`
command on PATH. The first run downloads the built-in FastEmbed model
(~100 MB, 30-120 seconds).

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.ps1 | iex"
```

Verify the install:

```bash
recollectium --version
```

Bootstrap install runs `recollectium init` automatically. If you installed via
`pip`, `pipx`, or `uv tool`, run init once:

```bash
recollectium init
```

`recollectium init` creates the config file, data/cache/log/runtime directories,
SQLite database, runs migrations, and downloads the built-in FastEmbed model
(~100 MB on first run). It is safe to run more than once.

### Shell completion

Bootstrap install configures tab completion automatically:

- Linux/macOS installs bash, zsh, or fish completion based on `$SHELL`.
  If `$SHELL` is missing or unsupported, it falls back to bash and writes the
  managed block to `~/.bashrc`.
- Windows installs PowerShell completion into `$PROFILE.CurrentUserCurrentHost`.

After bootstrap install, open a new shell session and `recollectium <TAB>` works.
Bootstrap update refreshes the managed completion block instead of appending a
duplicate, and uninstall removes Recollectium-managed completion blocks while
preserving unrelated shell/profile content.

To set up completion manually:

```bash
recollectium completion --install
recollectium completion --install bash
recollectium completion --install zsh
recollectium completion --install fish
```

PowerShell:

```powershell
recollectium completion --install powershell
```

To see the setup instructions for a specific shell:

```bash
recollectium completion bash
recollectium completion zsh
recollectium completion fish
recollectium completion powershell
```

PowerShell completion uses a small `Register-ArgumentCompleter` wrapper that asks
Recollectium for candidates dynamically, so commands, subcommands, flags, and
config keys stay in sync with the installed CLI. The automatic installer targets
`$PROFILE.CurrentUserCurrentHost`. If you want completion in every PowerShell
host, manually add this to `$PROFILE.CurrentUserAllHosts` instead:

```powershell
recollectium completion powershell --source | Invoke-Expression
```

The completion setup uses a managed comment block so update and uninstall can
identify and refresh or remove it cleanly:

```bash
# >>> recollectium completion >>>
eval "$(recollectium completion --source bash)"
# <<< recollectium completion <<<
```

### Python package managers

If you already have Python 3.12 or newer:

```bash
pip install recollectium
```

If you prefer isolated CLI tools:

```bash
pipx install recollectium
```

Try without installing permanently:

```bash
uvx recollectium --version
```

## Install for development

Recollectium Core requires Python 3.12 or newer. Use `uv` for environment and dependency management.

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
uv run recollectium --help
```

## Upgrading Recollectium

```bash
recollectium upgrade
```

`recollectium upgrade` checks the installed version against the latest GitHub
release and applies an upgrade through the detected install method. It supports
bootstrap installs, `pip`, `pipx`, `uv tool`, and source checkouts. User
configuration, data, and memory databases are preserved; only the package files
and managed service process state are touched. If a managed
API or MCP service was running before the upgrade, Recollectium stops it and
restarts that same service type after the package update succeeds.

Use non-mutating modes for automation and previews:

```bash
recollectium upgrade --check
recollectium upgrade --dry-run
```

If install-method detection is ambiguous, pass an explicit method:

```bash
recollectium upgrade --install-method pip
recollectium upgrade --install-method pipx
recollectium upgrade --install-method uv_tool
recollectium upgrade --install-method source
```

Package upgrades use `recollectium upgrade`. Memory record edits use
`recollectium update <memory_id> ...`.

## Uninstalling

```bash
recollectium uninstall
```

This removes managed service state and Recollectium-managed shell completion
blocks. For bootstrap installs, uninstall also starts a safe background handoff to
run `uv tool uninstall recollectium` after cleanup. Safe uninstall preserves local
memories and settings by default. Preserved paths include the config file, SQLite
database, data directory, model cache, logs, and runtime directory, so reinstalling
Recollectium later reuses the existing config and database and runs any required
migrations without overwriting your memories.

Package removal commands by install method:

| Install method | Command |
|---|---|
| Bootstrap installer or uv tool | `uv tool uninstall recollectium` |
| pipx | `pipx uninstall recollectium` |
| pip | `python -m pip uninstall recollectium` |
| Source checkout | Remove the checkout or shell path entry manually. |

To preview a full data purge without deleting anything:

```bash
recollectium uninstall --purge --dry-run
```

To permanently delete Recollectium-owned config, data, cache, logs, and runtime
paths -- **this deletes your memories, and cannot be undone**:

```bash
recollectium uninstall --purge
```

For non-interactive purge automation, use the explicit destructive confirmation
flag:

```bash
recollectium uninstall --purge --yes-delete-all-recollectium-data
```

Purge only removes paths that look Recollectium-owned and refuses broad paths such
as your home directory, root directory, or current working directory. If the
configured cache path appears shared with other tools, Recollectium skips it and
reports why. If a Recollectium service is running, uninstall stops it cleanly before
printing package removal guidance or deleting purge targets; `--dry-run` shows
what would happen without stopping the service or deleting files.

## Data path behavior

- Default database path: `~/.local/share/recollectium/recollectium.db`
- Override database path in config: set `database.path` in `config.json`
- Override database path in CLI: `recollectium --db /tmp/recollectium.db ...`
- Override database path in Python: `RecollectiumCore(db_path="/tmp/recollectium.db")`

## Configuration

Recollectium uses a JSON config file located at `~/.config/recollectium/config.json`
by default. The file is auto-created with built-in defaults the first time you
run a command that loads the effective config. CLI flags override config values.
Inspection-only commands `recollectium config --path` and `recollectium config --defaults`
do not create a config file.

### Config file location

| Situation | Path |
|---|---|
| Default (Linux XDG) | `~/.config/recollectium/config.json` |
| Custom via `--config` | Any path you specify. Explicit missing paths fail clearly unless a config creation command is used. |

The config directory (`~/.config/recollectium/`) and file are created
automatically with restrictive permissions (`0700` for directories, `0600` for
the file).

### All available settings

```json
{
  "version": 1,
  "database": {
    "path": "recollectium.db"
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
  },
  "workspace": {
    "uid_normalization": "normalize"
  }
}
```

| Setting | Default | Description |
|---|---|---|
| `version` | `1` | Config schema version for future compatibility. |
| `database.path` | `"recollectium.db"` | SQLite database path. Relative paths resolve against the data directory. Absolute paths are used as-is. |
| `embedding.provider` | `"builtin-fastembed"` | Embedding provider. Only `"builtin-fastembed"` is supported in this release. Other values fail validation. |
| `embedding.model` | `"jinaai/jina-embeddings-v2-small-en"` | Embedding model name. Only this model is supported in this release. Other values fail validation. |
| `service.host` | `"127.0.0.1"` | Host interface for the local HTTP service. Keep the default localhost bind unless you understand that v1 services are unauthenticated and non-local binds can expose memory contents. See [SECURITY.md](SECURITY.md). |
| `service.port` | `8765` | TCP port for the local HTTP service. |
| `logging.level` | `"info"` | Log level for the `recollectium.*` logger hierarchy. Allowed values: `debug`, `info`, `warning`, `error`. |
| `logging.format` | `"json"` | Log output format. Only `"json"` is supported in this release. |
| `logging.max_bytes` | `10485760` | Maximum log file size in bytes before rotation (10 MiB). Must be a positive integer. |
| `logging.backup_count` | `5` | Number of rotated log file backups to keep. Must be a positive integer. |
| `directories.data` | `null` (XDG default) | Override the data directory. |
| `directories.cache` | `null` (XDG default) | Override the cache directory. |
| `directories.logs` | `null` (XDG default) | Override the logs directory. |
| `directories.runtime` | `null` (XDG default) | Override the runtime directory. |
| `workspace.uid_normalization` | `"normalize"` | Workspace UID normalization mode. `"normalize"` (default) lowercases and slugifies UIDs so `Recollectium Core` and `recollectium-core` resolve to the same workspace. `"exact"` stores and looks up UIDs exactly as provided. |

When `directories.*` is `null` or unset, Recollectium uses standard XDG paths:

- Config: `$XDG_CONFIG_HOME/recollectium/` (fallback `~/.config/recollectium/`)
- Data: `$XDG_DATA_HOME/recollectium/` (fallback `~/.local/share/recollectium/`)
- Cache: `$XDG_CACHE_HOME/recollectium/` (fallback `~/.cache/recollectium/`)
- Logs: `$XDG_STATE_HOME/recollectium/logs/` (fallback `~/.local/state/recollectium/logs/`)
- Runtime: `$XDG_RUNTIME_DIR/recollectium/` (fallback inside data directory)

### Priority order

Values are resolved in this order (highest wins):

1. CLI flags (e.g., `--db`, `--port`, `--host`)
2. Explicit values in `config.json`
3. Built-in defaults

### Using `recollectium config`

```bash
# Print effective configuration (defaults merged with your overrides)
recollectium config

# Print built-in defaults only
# Does not create a config file
recollectium config --defaults

# Show where the config file lives
# Does not create a config file
recollectium config --path

# Validate the config file (exit 0 on success, 1 on error)
recollectium config --validate

# Run config and directory health checks
recollectium config doctor

# Get a single value by dot-notation key
recollectium config get service.port

# Set a value (creates the file if needed, preserves existing keys)
recollectium config set service.port 9090

# Remove a key so the built-in default takes effect
recollectium config unset service.host

# Create or overwrite the starter config with all defaults
recollectium config init --force

# Open the config file in your editor ($EDITOR)
# Creates the file with defaults first if it does not exist
recollectium config edit

# Reset the config file to built-in defaults
# Creates the file if it does not exist
recollectium config reset
```

### CLI flag overrides

| CLI flag | Overrides config key | Applies to |
|---|---|---|
| `--db <path>` | `database.path` | All commands |
| `--host <host>` | `service.host` | `serve` command. Non-local binds are risky unless protected by external private networking and access controls. |
| `--port <port>` | `service.port` | `serve` command |
| `--log-level <level>` | `logging.level` | Current invocation only; does not modify config |
| `--config <path>` | — | Loads config from a custom path |


## Service Management

Recollectium can run as a long-running service accessible over HTTP. Use the `recollectium service` commands to manage the service lifecycle.

The v1 API and MCP services are unauthenticated and should stay bound to localhost unless you protect access with private networking or equivalent external controls. See [SECURITY.md](SECURITY.md) before changing the service host or exposing Recollectium outside the local machine.

Two service types are available:

- **API** (`recollectium service start api`): REST API server with all memory operations, embedding status, and health checks. Mounted at the configured `service.host` and `service.port`.
- **MCP** (`recollectium service start mcp`): MCP (Model Context Protocol) HTTP server with memory tools for AI assistant integration. Uses SSE transport at the configured address.

  MCP tools exposed:

  - `add_memory` -- create a new memory
  - `get_memory` -- retrieve a single memory by ID
  - `update_memory` -- update a memory's content
  - `archive_memory` -- archive a memory by ID
  - `list_memories` -- list memories, optionally filtered
  - `search_user_memory` -- semantic search across user-space memories
  - `search_workspace_memory` -- semantic search within a workspace
  - `list_workspaces` -- list known workspace UIDs, optionally with aliases
  - `rename_workspace` -- migrate a workspace UID to a new UID
  - `resolve_workspace` -- normalize and resolve a workspace UID candidate
  - `add_workspace_alias` -- add an alias for a canonical workspace UID
  - `list_workspace_aliases` -- list aliases for a workspace
  - `remove_workspace_alias` -- remove an alias mapping

Only one service can run at a time. The service manager uses a PID file to track the running process and prevent conflicts.

### Starting a service

```bash
# Start the REST API server
recollectium service start api

# Start the MCP HTTP server
recollectium service start mcp

# Use a custom database path
recollectium --db /tmp/custom.db service start api
```

Output on success:

```json
{"endpoint": "http://127.0.0.1:8765", "pid": 12345, "status": "started", "type": "api"}
```

### Checking service status

```bash
recollectium service status
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

### Discovering a service for adapters

Local adapters and plugins should use the machine-readable discovery command instead of hardcoding the default endpoint or parsing service logs:

```bash
recollectium service discover
```

When a managed service is running, discovery exits `0` and prints JSON with the service type, PID, endpoint, API prefix, health URL, version URL, capabilities URL, Recollectium version, config path, runtime directory, PID file, and discovery file path. `recollectium service start api` and `recollectium service start mcp` also write the same running metadata to `{runtime_dir}/service-discovery.json`.

When no managed service is running, discovery exits `1`, prints `status="not_running"`, and includes the next step to start the API service. The command does not create a config file just to inspect discovery state. If PID or discovery metadata is stale, discovery removes the stale Recollectium-owned files and reports what was cleaned.

Adapters should autodiscover Recollectium after the host application loads the
plugin when the adapter and Core run on the same machine. Users should not need
to manually configure host, port, PID file, runtime path, or service type for
that local path. Private-network split-machine Core instances are different: the user points
the plugin at the Core base URL in plugin config. Before using the service,
adapters must validate the target endpoint by calling health, version, and
capabilities, whether those URLs came from local discovery or from the configured
remote base URL. See `docs/opencode-adapter-contract.md` for the full adapter
contract.

Binding Recollectium to a non-local interface can expose memory contents because the Phase 1 local API is unauthenticated. See [SECURITY.md](SECURITY.md) for the full v1 security model.

### Stopping a service

```bash
recollectium service stop
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
recollectium service restart

# Restarts using the type from a stale PID file
recollectium service restart --type api

# Specify a type when no trace of a previous service exists
recollectium service restart --type mcp
```

Output:

```json
{"endpoint": "http://127.0.0.1:8765", "pid": 12346, "status": "restarted", "type": "api"}
```

### MCP stdio mode

The `mcp-stdio` command runs an MCP server over stdin/stdout. This mode is designed for AI assistant clients that spawn Recollectium as a child process, such as Claude Desktop.

```bash
recollectium mcp-stdio
```

No PID file is created for stdio mode. The process runs as long as the client is connected.

#### Claude Desktop configuration

Add this to your Claude Desktop `claude_desktop_config.json` to use Recollectium as an MCP server:

```json
{
  "mcpServers": {
    "recollectium": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/recollectium",
        "run", "recollectium", "mcp-stdio"
      ]
    }
  }
}
```

Adjust the `--directory` path to point at your Recollectium Core checkout.

### PID file and runtime directory

The service manager writes a PID file to the runtime directory (default `$XDG_RUNTIME_DIR/recollectium/service.pid`). The file contains JSON with the process ID, service type, and Linux process start-time metadata used to avoid acting on a reused PID:

```json
{"pid": 12345, "process_start_time": 1234567, "type": "api"}
```

The runtime directory can be overridden in config by setting `directories.runtime`.
Daemon stdout and stderr are redirected to `service-api.log` or `service-mcp.log` in the configured logs directory.

### Error handling

- Starting any service while another service is running produces a clear error: `ServiceConflictError: a mcp service is already running (PID 12345). Stop it before starting an api service.`
- Use `recollectium service restart` to restart a running service.
- Stale PID files from crashed processes or PID reuse are cleaned automatically.

## CLI examples

Add a user memory:

```bash
recollectium --db /tmp/recollectium.db add \
  --space user \
  --type preference \
  --content "I prefer concise technical answers."
```

Search user memories:

```bash
recollectium --db /tmp/recollectium.db search-user "concise answers"
```

Searches default to all buckets in the selected scope. Add `--type` when you want to narrow the search to a specific bucket, for example `fact` or `preference`.

Add a workspace memory:

```bash
recollectium --db /tmp/recollectium.db add \
  --space workspace \
  --workspace-uid 7f3b0a5e-example-workspace \
  --type decision \
  --content "Use SQLite for local memory persistence."
```

Search workspace memories:

```bash
recollectium --db /tmp/recollectium.db search-workspace \
  "local persistence" \
  --workspace-uid 7f3b0a5e-example-workspace
```

Searches default to all buckets in the selected scope. Add `--type` when you want to narrow the workspace search to a bucket such as `decision` or `task_context`.

Workspace memories are keyed by a stable workspace UID. Future adapters, such as
the OpenCode plugin, should instruct the model at prompt level to choose the UID
candidate from the project it is currently working in and making changes to. Use
the project base folder name, not the full path, and do not use the adapter,
agent, sandbox, or temporary execution directory when that differs from the
project under work. If the project or active subfolder is inside a git-managed
tree, prefer the git repository name from the repository root. If there is no
git repo, use the selected project folder name or containing project workspace
folder name. The plugin passes that UID candidate to Core; Core applies
`workspace.uid_normalization` and resolves configured workspace aliases at the
storage boundary. For local autodiscovery,
if the service is not running, the plugin should attempt to start the API service
with `recollectium service start api` before guiding the user. See
`docs/opencode-adapter-contract.md` for the adapter-side workspace UID and
service discovery rules.

List known workspace UIDs:

```bash
recollectium --db /tmp/recollectium.db workspace list
```

List known workspace UIDs with aliases:

```bash
recollectium --db /tmp/recollectium.db workspace list --include-aliases
```

Resolve a UID candidate to its canonical workspace:

```bash
recollectium --db /tmp/recollectium.db workspace resolve recollectium-core
```

Add, list, and remove workspace aliases. Use `--migrate-existing` when the alias
UID already has workspace memories and should be folded into the canonical
workspace in the same transaction:

```bash
recollectium --db /tmp/recollectium.db workspace alias add recollectium recollectium-core --migrate-existing
recollectium --db /tmp/recollectium.db workspace alias list --workspace recollectium
recollectium --db /tmp/recollectium.db workspace alias remove recollectium-core
```

Rename a workspace (migrates all its memories and retargets aliases to a new UID):

```bash
recollectium --db /tmp/recollectium.db workspace rename old-project new-project
```

Successful CLI commands that return machine-readable data write JSON to stdout.
Non-argparse command failures usually write a single structured JSON object to
stderr and leave stdout empty. Error objects always include `status` and
`message`, and may include `detail` and `hint` when extra diagnostic or recovery
guidance is useful. Validation/input/config errors exit with code `2`; runtime,
resource, not-found, service, database, migration, and embedding failures exit
with code `1`. The adapter-facing `recollectium service discover` command is the
intentional exception: when no service is running it exits `1`, writes
`status: "not_running"` JSON to stdout, and leaves stderr empty. Argparse help
and usage errors are the only non-JSON stderr exception so shell discovery and
`--help` workflows stay familiar.

## Memory buckets

Recollectium uses a small canonical bucket set. Write operations choose a bucket, while reads default to all buckets in the selected scope and only narrow with `--type` when needed.

User scope:

| Bucket | Use |
|---|---|
| `fact` | Stable facts about the user |
| `preference` | Stable likes, defaults, and style choices |
| `personal_fact` | Durable facts about the user that are not preferences or relationships |
| `social_context` | People and relationship mappings around the user |
| `goal` | Desired future states or ongoing outcomes |
| `communication_style` | How the user wants the assistant to talk and collaborate |
| `note` | Catch-all user memory when nothing else fits |

Workspace scope:

| Bucket | Use |
|---|---|
| `fact` | Durable truths about the workspace or project |
| `decision` | Chosen directions with rationale |
| `task_context` | Active work state and unfinished branch context |
| `configuration` | Environment and operational setup details |
| `bug_finding` | Diagnosed issues and root causes |
| `note` | Catch-all workspace memory when nothing else fits |

Searches default to all buckets in the selected scope. Add `--type` when you want to narrow the search to a specific bucket.

Check embedding profile status:

```bash
recollectium --db /tmp/recollectium.db embedding-status
```

List embedding jobs:

```bash
recollectium --db /tmp/recollectium.db embedding-jobs
```

Get one embedding job:

```bash
recollectium --db /tmp/recollectium.db embedding-jobs --job-id <job-id>
```

## Python API examples

```python
from recollectium import RecollectiumCore

core = RecollectiumCore(db_path="/tmp/recollectium.db")

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
