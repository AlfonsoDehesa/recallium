# Configuration

## Config location

Default config path:

```text
~/.config/recollectium/config.json
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

## Defaults

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

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `version` | `1` | Config schema version. |
| `database.path` | `recollectium.db` | SQLite database path. Relative paths resolve under the data directory. |
| `embedding.provider` | `builtin-fastembed` | Built-in local FastEmbed provider. |
| `embedding.model` | `jinaai/jina-embeddings-v2-small-en` | Built-in model used for local embeddings. |
| `service.host` | `127.0.0.1` | API or MCP service bind host. Keep localhost unless protected externally. |
| `service.port` | `8765` | API or MCP service port. |
| `logging.level` | `info` | `debug`, `info`, `warning`, or `error`. |
| `logging.format` | `json` | Structured JSON logs. |
| `logging.max_bytes` | `10485760` | Log rotation size. |
| `logging.backup_count` | `5` | Rotated log backups to keep. |
| `directories.data` | `null` | Data directory override. |
| `directories.cache` | `null` | Cache directory override. |
| `directories.logs` | `null` | Logs directory override. |
| `directories.runtime` | `null` | Runtime directory override. |
| `workspace.uid_normalization` | `normalize` | Normalize or keep exact workspace UID candidates. |

## XDG paths

When `directories.*` is null, Recollectium uses XDG-style paths:

- Config: `$XDG_CONFIG_HOME/recollectium/`, fallback `~/.config/recollectium/`
- Data: `$XDG_DATA_HOME/recollectium/`, fallback `~/.local/share/recollectium/`
- Cache: `$XDG_CACHE_HOME/recollectium/`, fallback `~/.cache/recollectium/`
- Logs: `$XDG_STATE_HOME/recollectium/logs/`, fallback `~/.local/state/recollectium/logs/`
- Runtime: `$XDG_RUNTIME_DIR/recollectium/`, fallback inside the data directory

## Config commands

```bash
recollectium config get service.port
recollectium config set service.port 9090
recollectium config unset service.port
recollectium config init --force
recollectium config edit
recollectium config reset
recollectium config doctor
recollectium config --validate
```

## CLI overrides

Global flags override config for the current invocation:

```bash
recollectium --config /path/to/config.json --db /tmp/recollectium.db --log-level debug list
recollectium serve --host 127.0.0.1 --port 8765
```

Do not bind services to non-local interfaces unless private networking and access controls protect the endpoint.
