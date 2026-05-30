# Features and Commands

This page gives a practical map of what Recollectium can do across CLI, API, and MCP. For exhaustive command examples, see [CLI Reference](CLI-Reference.md). For endpoint payloads, see [API Reference](API-Reference.md). For MCP tool contracts, see [MCP Server](MCP-Server.md).

## Memory operations

| Feature | CLI | Main options | API | MCP | What it does |
|---|---|---|---|---|---|
| Add memory | `add` | `--space`, `--type`, `--content`, `--workspace-uid`, `--metadata`, `--source`, `--confidence`, `--sensitivity` | `POST /v1/memories` | `add_memory` | Stores a user or workspace memory and embeds its content for semantic search. |
| Search user memory | `search-user` | `query`, `--type`, `--limit`, `--include-archived` | `POST /v1/memories/search_user` | `search_user_memory` | Searches global user memories by meaning. Usually search without `--type` first. |
| Search workspace memory | `search-workspace` | `query`, `--workspace-uid`, `--type`, `--limit`, `--include-archived` | `POST /v1/memories/search_workspace` | `search_workspace_memory` | Searches memories for one workspace UID by meaning. |
| List memories | `list` | `--space`, `--type`, `--status`, `--workspace-uid`, `--include-archived`, `--limit` | `GET /v1/memories` | `list_memories` | Lists memories directly for inspection, audits, and finding IDs. |
| Get memory | `get MEMORY_ID` | `MEMORY_ID` | `GET /v1/memories/{memory_id}` | `get_memory` | Fetches one memory by ID. |
| Update memory | `update MEMORY_ID` | `--type`, `--content`, `--metadata`, `--source`, `--confidence`, `--sensitivity` | `PATCH /v1/memories/{memory_id}` | `update_memory` | Updates editable fields. Changing content regenerates the embedding. |
| Archive memory | `archive MEMORY_ID` | `MEMORY_ID` | `POST /v1/memories/{memory_id}/archive` | `archive_memory` | Hides a memory from default list and search results without hard-deleting it. |

## Workspace operations

| Feature | CLI | Main options | API | MCP | What it does |
|---|---|---|---|---|---|
| List workspaces | `workspace list` | `--include-archived`, `--include-aliases` | `GET /v1/workspaces` | `list_workspaces` | Lists known workspace UIDs, optionally with aliases. |
| Resolve workspace | `workspace resolve UID` | `UID` | `GET /v1/workspaces/resolve?uid=...` | `resolve_workspace` | Normalizes a workspace candidate and resolves aliases to the canonical UID. |
| Rename workspace | `workspace rename OLD_UID NEW_UID` | `OLD_UID`, `NEW_UID` | `POST /v1/workspaces/{uid}/rename` | `rename_workspace` | Migrates all workspace memories, including archived memories, to a new UID. |
| Add alias | `workspace alias add` | `CANONICAL_UID`, `ALIAS_UID`, `--migrate-existing` | `POST /v1/workspaces/{uid}/aliases` | `add_workspace_alias` | Makes an old or alternate UID resolve to a canonical UID. |
| List aliases | `workspace alias list` | `--workspace UID` | `GET /v1/workspaces/{uid}/aliases` | `list_workspace_aliases` | Lists alias mappings, optionally filtered by canonical workspace. |
| Remove alias | `workspace alias remove ALIAS_UID` | `ALIAS_UID` | `DELETE /v1/workspaces/aliases/{alias_uid}` | `remove_workspace_alias` | Removes an alias mapping. It does not delete memories. |

## Service and system operations

| Feature | CLI | Options | What it does |
|---|---|---|---|
| Initialize | `init` | `--db` | Creates config, directories, database, migrations, and model cache. |
| Config inspect/edit | `config` | `--path`, `--defaults`, `--validate`, `get`, `set`, `unset`, `init --force`, `doctor`, `edit`, `reset` | Reads, validates, creates, edits, or resets configuration. |
| Database status | `db-status` | global `--db` | Shows current and pending schema migrations. |
| Start service | `service start api`, `service start mcp` | service type: `api` or `mcp` | Starts a managed background service and writes discovery metadata. |
| Stop service | `service stop` | none | Stops the running managed service. |
| Service status | `service status` | none | Shows whether a managed service is running. |
| Service discovery | `service discover` | none | Prints adapter-friendly endpoint, version, capability, PID, and path metadata. |
| Restart service | `service restart` | `--type api`, `--type mcp` | Restarts the running or last-known service. Use `--type` if no service type can be inferred. |
| Foreground API | `serve` | `--host`, `--port` | Runs the API service in the foreground for debugging or development. |
| MCP stdio | `mcp-stdio` | global `--db`, `--config`, `--log-level` | Runs MCP over stdin/stdout for clients that spawn tools as child processes. |
| Embedding status | `embedding-status` | none | Shows active model profile, runtime, readiness, and recent jobs. |
| Embedding jobs | `embedding-jobs` | `--job-id`, `--state`, `--limit` | Lists or fetches embedding jobs used for readiness and re-embedding. |
| Shell completion | `completion` | `SHELL`, `--source`, `--install`, `--yes` | Prints or installs shell completion for bash, zsh, fish, or PowerShell. |
| Upgrade | `upgrade` | `--check`, `--dry-run`, `--force`, `--install-method`, `--repo`, `--allow-main`, `--timeout` | Checks and applies package upgrades through the detected install method. |
| Uninstall | `uninstall` | `--purge`, `--yes-delete-all-recollectium-data`, `--dry-run` | Prints safe uninstall instructions. With `--purge`, deletes Recollectium-owned local data after confirmation. |

## Global flags

These can be used before most commands:

| Flag | What it does |
|---|---|
| `--config CONFIG_PATH` | Uses a specific config file for one invocation. |
| `--db DB_PATH` | Uses a specific SQLite database path for one invocation. |
| `--log-level debug|info|warning|error` | Overrides logging level for one invocation. |
| `--version` | Prints the installed version. |

## Memory type buckets

User memory types:

- `fact`
- `preference`
- `personal_fact`
- `social_context`
- `goal`
- `communication_style`
- `note`

Workspace memory types:

- `fact`
- `decision`
- `task_context`
- `configuration`
- `bug_finding`
- `note`

## Output contracts

CLI commands that return command data print human-readable summaries to stdout by default. Set `cli_output` to `json` in config, or pass `--json`, for scripts and adapters. Pass `--human-readable` to force terminal-friendly summaries for one invocation. `--json` and `--human-readable` are mutually exclusive and can appear before or after the command.

Protocol commands keep their machine contract regardless of `cli_output`: `completion --source`, completion candidate generation, `serve`, and `mcp-stdio` do not switch to human text.

Non-argparse command failures follow the same output format on stderr. In JSON mode they write a structured JSON object; in human-readable mode they write a readable message with status, detail, hint, and other fields. Validation and input errors usually exit `2`. Runtime, service, database, migration, resource, not-found, and embedding errors usually exit `1`.

The intentional exception is `recollectium service discover`: when no managed service is running, it exits `1`, writes `status: "not_running"` output to stdout, and leaves stderr empty so adapters can read the discovery state. Use `--json` for adapter discovery calls if a user config may prefer human-readable output.
