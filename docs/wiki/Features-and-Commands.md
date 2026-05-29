# Features and Commands

## Memory operations

| Feature | CLI | API | MCP |
|---|---|---|---|
| Add memory | `add` | `POST /v1/memories` | `add_memory` |
| Search user memory | `search-user` | `POST /v1/memories/search_user` | `search_user_memory` |
| Search workspace memory | `search-workspace` | `POST /v1/memories/search_workspace` | `search_workspace_memory` |
| List memories | `list` | `GET /v1/memories` | `list_memories` |
| Get memory | `get` | `GET /v1/memories/{memory_id}` | `get_memory` |
| Update memory | `update` | `PATCH /v1/memories/{memory_id}` | `update_memory` |
| Archive memory | `archive` | `POST /v1/memories/{memory_id}/archive` | `archive_memory` |

## Workspace operations

| Feature | CLI | API | MCP |
|---|---|---|---|
| List workspaces | `workspace list` | `GET /v1/workspaces` | `list_workspaces` |
| Resolve workspace | `workspace resolve` | `GET /v1/workspaces/resolve` | `resolve_workspace` |
| Rename workspace | `workspace rename` | `POST /v1/workspaces/{uid}/rename` | `rename_workspace` |
| Add alias | `workspace alias add` | `POST /v1/workspaces/{uid}/aliases` | `add_workspace_alias` |
| List aliases | `workspace alias list` | `GET /v1/workspaces/{uid}/aliases` | `list_workspace_aliases` |
| Remove alias | `workspace alias remove` | `DELETE /v1/workspaces/aliases/{alias_uid}` | `remove_workspace_alias` |

## Service and system operations

- `init`: initialize config, database, directories, migrations, and model cache.
- `config`: inspect and edit config.
- `service`: start, stop, restart, status, and discovery for managed services.
- `serve`: run the API service in the foreground for development.
- `mcp-stdio`: run MCP over stdio for clients that spawn a child process.
- `embedding-status`: inspect active local embedding profile.
- `embedding-jobs`: list or fetch embedding jobs.
- `completion`: install or print shell completion.
- `upgrade`: upgrade the package.
- `uninstall`: remove package state or purge all data with confirmation.

## Output contracts

Successful CLI commands that return data print JSON to stdout.

Most non-argparse command failures write structured JSON to stderr and leave stdout empty. Validation and input errors usually exit 2. Runtime, service, database, migration, resource, not-found, and embedding errors usually exit 1.

The intentional exception is `recollectium service discover`: when no managed service is running, it exits 1, writes `status: "not_running"` JSON to stdout, and leaves stderr empty so adapters can read the discovery state.
