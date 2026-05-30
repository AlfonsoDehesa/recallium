# Configuration

Recollectium uses a JSON config file plus XDG-style directories for data, cache, logs, and runtime files. Most users can install and run Recollectium without editing config manually. Use this page when you want to inspect paths, change the service port, move the database, or understand every setting.

## Config location

Default config path:

```text
~/.config/recollectium/config.json
```

On systems that set `XDG_CONFIG_HOME`, the config lives at:

```text
$XDG_CONFIG_HOME/recollectium/config.json
```

Print the resolved path without creating a file:

```bash
recollectium config --path
```

Print built-in defaults without creating a file:

```bash
recollectium config --defaults
```

Print effective config:

```bash
recollectium config
```

The effective config is the built-in defaults merged with any values in your config file.

## Defaults

```json
{
  "version": 1,
  "cli_output": "human_readable",
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

## Settings

| Setting | Type | Default | Options | What it does |
|---|---|---|---|---|
| `version` | integer | `1` | `1` | Config schema version. Recollectium uses this to validate the config format. Do not change it unless a future migration says to. |
| `cli_output` | string | `human_readable` | `human_readable`, `json` | Output format for CLI command results and non-argparse failures. Use `human_readable` for terminal-friendly summaries and errors. Human-readable output uses Rich-backed ANSI color only when the target stream is a TTY; pipes and captured output remain plain text. Use `json` for scripts and adapters. |
| `database.path` | string path | `recollectium.db` | relative or absolute path | SQLite database file. Relative paths resolve under the data directory. Absolute paths are used as written. |
| `embedding.provider` | string | `builtin-fastembed` | currently `builtin-fastembed` | Embedding provider. v1 supports the built-in local FastEmbed provider. |
| `embedding.model` | string | `jinaai/jina-embeddings-v2-small-en` | currently the built-in model | Embedding model name. Other models are planned for future releases, but v1 validates the built-in profile. |
| `service.host` | string | `127.0.0.1` | host or IP address | Bind host for API or managed MCP service. Keep this on localhost unless you have private networking and external access controls. |
| `service.port` | integer | `8765` | TCP port | Port used by the API or managed MCP service. Change this if the default port is already in use. |
| `logging.level` | string | `info` | `debug`, `info`, `warning`, `error` | Minimum log level. Use `debug` when troubleshooting. |
| `logging.format` | string | `json` | `json` | Log output format. v1 uses structured JSON logs. |
| `logging.max_bytes` | integer | `10485760` | positive integer | Maximum size of the active log file before rotation. Default is 10 MiB. |
| `logging.backup_count` | integer | `5` | non-negative integer | Number of rotated log files to keep. |
| `directories.data` | string path or null | `null` | path or `null` | Data directory override. Stores the default SQLite database and other durable data. Null means use XDG defaults. |
| `directories.cache` | string path or null | `null` | path or `null` | Cache directory override. Used for cached runtime assets. Null means use XDG defaults. |
| `directories.logs` | string path or null | `null` | path or `null` | Logs directory override. Null means use XDG state defaults. |
| `directories.runtime` | string path or null | `null` | path or `null` | Runtime directory override for PID and discovery files. Null means use `XDG_RUNTIME_DIR` when available, otherwise a fallback under data. |
| `workspace.uid_normalization` | string | `normalize` | `normalize`, `exact` | Controls workspace UID cleanup. `normalize` lowercases and slugifies workspace candidates. `exact` keeps caller-provided UIDs as-is after validation. |

## XDG paths

When `directories.*` is null, Recollectium uses XDG-style paths:

- Config: `$XDG_CONFIG_HOME/recollectium/`, fallback `~/.config/recollectium/`
- Data: `$XDG_DATA_HOME/recollectium/`, fallback `~/.local/share/recollectium/`
- Cache: `$XDG_CACHE_HOME/recollectium/`, fallback `~/.cache/recollectium/`
- Logs: `$XDG_STATE_HOME/recollectium/logs/`, fallback `~/.local/state/recollectium/logs/`
- Runtime: `$XDG_RUNTIME_DIR/recollectium/`, fallback inside the data directory

## Config commands

```bash
recollectium config
recollectium config --path
recollectium config --defaults
recollectium config --validate
recollectium config get service.port
recollectium config set service.port 9090
recollectium config unset service.port
recollectium config init --force
recollectium config edit
recollectium config reset
recollectium config doctor
```

### `recollectium config`

Prints the effective config as human-readable text by default. Pass `--json` when you need formatted JSON. This is the best first command when you want to know which values Recollectium is actually using.

### `recollectium config --path`

Prints the config file path that Recollectium would use. It does not create the file.

### `recollectium config --defaults`

Prints the built-in defaults. It does not read or create your config file.

### `recollectium config --validate`

Validates the active config and exits:

- `0` when valid.
- `1` when an explicit config file is missing.
- `2` when the config exists but is invalid.

### `recollectium config get KEY`

Prints one effective value. Keys use dot notation.

Example:

```bash
recollectium config get service.port
```

### `recollectium config set KEY VALUE`

Writes one config value. The value is parsed as JSON when possible, so numbers, booleans, null, and quoted strings work as expected.

Examples:

```bash
recollectium config set service.port 9090
recollectium config set logging.level '"debug"'
recollectium config set cli_output json
recollectium config set directories.data '"/data/recollectium"'
```

### `recollectium config unset KEY`

Removes an explicit key from your config file. The built-in default then applies again.

Example:

```bash
recollectium config unset service.port
```

### `recollectium config init [--force]`

Creates a starter config file with all defaults. If the file already exists, use `--force` to overwrite it.

### `recollectium config edit`

Opens the config file in `$EDITOR`. If the file does not exist, Recollectium creates it first with defaults.

### `recollectium config reset`

Replaces the config file with a fresh copy of defaults. Use this when you want to discard local config edits.

### `recollectium config doctor`

Checks that the config is valid and that resolved data, cache, logs, runtime, and database parent directories exist, are directories, and are writable.

## CLI overrides

Global CLI options override config values for one invocation only:

```bash
recollectium --db /tmp/recollectium.db list
recollectium --config /tmp/config.json config
recollectium --log-level debug search-user "preferences about wording"
recollectium --json list
recollectium --json service discover
```

Use config for durable settings. Use CLI overrides for tests, temporary databases, debugging, output-format changes, or one-off operations. `--json` and `--human-readable` are mutually exclusive and can appear before or after the command. They override `cli_output` for one invocation only, including non-argparse failure output. If a command needs the literal value `--json` or `--human-readable`, put it after `--` so it is treated as a value instead of an output flag. `completion --source`, completion candidate generation, `serve`, and `mcp-stdio` keep their protocol output regardless of `cli_output`.
