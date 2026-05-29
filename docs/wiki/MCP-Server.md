# MCP Server

## What MCP is for

MCP lets AI clients call Recollectium memory tools through a standard tool interface. Use MCP when the assistant or agent supports Model Context Protocol and should call Recollectium directly instead of shelling out to the CLI.

## Stdio mode

```bash
recollectium mcp-stdio
```

This mode is intended for MCP clients that spawn Recollectium as a child process. No PID file is created. The server runs for the lifetime of the client connection.

## Managed HTTP mode

```bash
recollectium service start mcp
recollectium service status
```

The managed MCP service uses the configured host and port. In v1 it is unauthenticated and should stay on localhost unless protected by private networking and external controls.

## Tools

- `search_user_memory(query, type=None, limit=10)`
- `search_workspace_memory(query, workspace_uid, type=None, limit=10)`
- `add_memory(space, type, content, workspace_uid=None)`
- `get_memory(id)`
- `update_memory(id, type=None, content=None)`
- `archive_memory(id)`
- `list_memories(space=None, type=None, workspace_uid=None, limit=None)`
- `list_workspaces(include_archived=False, include_aliases=False)`
- `resolve_workspace(uid)`
- `add_workspace_alias(canonical_uid, alias_uid, migrate_existing=False)`
- `list_workspace_aliases(canonical_uid=None)`
- `remove_workspace_alias(alias_uid)`
- `rename_workspace(old_uid, new_uid)`

## Return values

MCP tools return JSON strings. On Recollectium errors, tools return a JSON object containing an `error` field.

## Client configuration

For a client that spawns stdio servers, configure the command as `recollectium mcp-stdio`. If running from a source checkout during development, use `uv --directory /path/to/recollectium run recollectium mcp-stdio`.

## Security reminder

MCP service mode is unauthenticated in v1. Do not expose it publicly.
