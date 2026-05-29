# CLI Reference

Global form:

```bash
recollectium [--config CONFIG_PATH] [--db DB_PATH] [--log-level debug|info|warning|error] COMMAND ...
```

## Global options

- `--config CONFIG_PATH`: use a custom config file.
- `--db DB_PATH`: override `database.path` for this invocation.
- `--log-level`: override configured log level for this invocation.
- `--version`: print installed version.

## init

```bash
recollectium init [--db DB_PATH]
```

Creates the config file, XDG directories, database, migrations, and model cache.

## add

```bash
recollectium add --space user --type preference --content "..."
recollectium add --space workspace --workspace-uid my-project --type decision --content "..."
```

Options include `--metadata`, `--source`, `--confidence`, and `--sensitivity`.

## search-user

```bash
recollectium search-user [--type TYPE] [--limit LIMIT] [--include-archived] "query"
```

Searches active user memories semantically.

## search-workspace

```bash
recollectium search-workspace [--type TYPE] --workspace-uid UID [--limit LIMIT] [--include-archived] "query"
```

Searches active memories for one workspace UID.

## list

```bash
recollectium list [--space SPACE] [--type TYPE] [--status STATUS] [--workspace-uid UID] [--include-archived] [--limit LIMIT]
```

Lists memories as JSON.

## get

```bash
recollectium get MEMORY_ID
```

Retrieves one memory by ID.

## update

```bash
recollectium update MEMORY_ID [--type TYPE] [--content CONTENT] [--metadata JSON_OR_PATH] [--source SOURCE] [--confidence SCORE] [--sensitivity LABEL]
```

Updates editable memory fields. Updating content regenerates the embedding.

## archive

```bash
recollectium archive MEMORY_ID
```

Archives a memory. Archived memories are hidden from default list and search results.

## workspace

```bash
recollectium workspace list [--include-archived] [--include-aliases]
recollectium workspace resolve UID
recollectium workspace rename OLD_UID NEW_UID
recollectium workspace alias add CANONICAL_UID ALIAS_UID [--migrate-existing]
recollectium workspace alias list [--workspace UID]
recollectium workspace alias remove ALIAS_UID
```

## config

```bash
recollectium config
recollectium config --path
recollectium config --defaults
recollectium config --validate
recollectium config get KEY
recollectium config set KEY VALUE
recollectium config unset KEY
recollectium config init [--force]
recollectium config doctor
recollectium config edit
recollectium config reset
```

## service

```bash
recollectium service start api
recollectium service start mcp
recollectium service stop
recollectium service status
recollectium service discover
recollectium service restart [--type api|mcp]
```

## serve

```bash
recollectium serve [--host HOST] [--port PORT]
```

Runs the local HTTP API service in the foreground. Default host is `127.0.0.1`, default port is `8765`.

## mcp-stdio

```bash
recollectium mcp-stdio
```

Runs an MCP server over stdin/stdout. Intended for MCP clients that spawn Recollectium as a child process.

## embedding commands

```bash
recollectium embedding-status
recollectium embedding-jobs [--job-id JOB_ID] [--state STATE] [--limit LIMIT]
```

## lifecycle commands

```bash
recollectium completion [--source | --install] [--yes] [bash|zsh|fish|powershell]
recollectium upgrade [--check] [--dry-run] [--force]
recollectium uninstall [--purge] [--yes-delete-all-recollectium-data] [--dry-run]
```
