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
- A long-running service or daemon.
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

## Install for development

Recallium Core requires Python 3.14 or newer. Use `uv` for environment and dependency management.

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
    "level": "info"
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
| `logging.level` | `"info"` | Service log level. Allowed values: `debug`, `info`, `warning`, `error`. |
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

# Get a single value by dot-notation key
recallium config get service.port

# Set a value (creates the file if needed, preserves existing keys)
recallium config set service.port 9090

# Remove a key so the built-in default takes effect
recallium config unset service.host

# Create or overwrite the starter config with all defaults
recallium config init --force
```

### CLI flag overrides

| CLI flag | Overrides config key | Applies to |
|---|---|---|
| `--db <path>` | `database.path` | All commands |
| `--host <host>` | `service.host` | `serve` command |
| `--port <port>` | `service.port` | `serve` command |
| `--config <path>` | — | Loads config from a custom path |


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
