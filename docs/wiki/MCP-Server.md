# MCP Server

MCP lets AI clients call Recollectium through a standard tool interface. Use it when an assistant or agent supports Model Context Protocol and should call memory tools directly inside the client.

## What MCP is for

MCP is best when an agent should see Recollectium operations as native tools, such as "search user memory", "add workspace memory", or "resolve workspace".

Use MCP when:

- your client supports MCP tools;
- you want the agent to call Recollectium without composing CLI commands;
- you want one durable Core database shared by multiple agent surfaces;
- you want user and workspace memory rules enforced by Recollectium Core.

If you are building an adapter, script, dashboard, or service that talks over HTTP, use the API instead.

## Run the MCP server

Recollectium supports two MCP runtime styles.

### Stdio mode

```bash
recollectium mcp-stdio
```

Use stdio mode when the MCP client starts local servers as child processes. The server reads and writes through stdin/stdout. No PID file is created. The server runs for the lifetime of the client connection.

Useful global options:

```bash
recollectium --config /path/to/config.json mcp-stdio
recollectium --db /path/to/recollectium.db mcp-stdio
recollectium --log-level debug mcp-stdio
```

### Managed HTTP mode

```bash
recollectium service start mcp
recollectium service status
recollectium service discover
recollectium service stop
```

Managed mode starts a background MCP service using the configured host and port. It writes PID and discovery files so local adapters can find it.

Use managed mode when a client or adapter expects a long-running local service instead of spawning a stdio child process.

## Example client setup

For clients that accept a command plus arguments, configure a local stdio MCP server with:

```text
command: recollectium
args: ["mcp-stdio"]
```

Claude Code supports adding a local stdio MCP server from the command line:

```bash
claude mcp add --transport stdio recollectium -- recollectium mcp-stdio
```

Claude Desktop and other JSON-configured MCP clients commonly use an `mcpServers` block:

```json
{
  "mcpServers": {
    "recollectium": {
      "command": "recollectium",
      "args": ["mcp-stdio"]
    }
  }
}
```

OpenCode exposes an `mcp` configuration section. A local Recollectium entry follows the same command/args shape:

```json
{
  "mcp": {
    "recollectium": {
      "type": "local",
      "command": ["recollectium", "mcp-stdio"],
      "enabled": true
    }
  }
}
```

Exact config file locations and names vary by client. Use the client's MCP docs as the source of truth, then point the client at `recollectium mcp-stdio`.

If running from a source checkout during development, use:

```bash
uv --directory /path/to/recollectium run recollectium mcp-stdio
```

## Discovery and compatibility

Stdio clients usually manage the MCP process themselves, so discovery is just the command configuration above.

Managed MCP mode can be discovered with:

```bash
recollectium service discover
```

Clients and adapters should still treat Recollectium Core as the source of truth for memory rules. Workspace aliases, workspace UID normalization, memory bucket validation, and archive behavior all live in Core.

## Response format

MCP tools return JSON strings, not native Python objects.

Successful memory-returning tools return either a memory object or a list of search/list results. Errors return:

```json
{"error": "message"}
```

## Memory rules

- Workspace search requires `workspace_uid`.
- Adding workspace memories requires `space="workspace"` and `workspace_uid`.
- Adding user memories requires `space="user"` and must not include `workspace_uid`.
- Workspace filters on list are optional.

Violations return an error JSON object.

## Operations

All MCP tools return JSON strings. On Recollectium errors, tools return a JSON object containing an `error` field.

### `search_user_memory(query, type=None, limit=10)`

Searches user-space memories by semantic similarity.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. |
| `type` | No | all user types | Optional user memory bucket filter. Usually omit this first. |
| `limit` | No | `10` | Maximum number of ranked results. |

Returns: JSON list of search results. Each result has `memory`, `score`, and `rank`.

### `search_workspace_memory(query, workspace_uid, type=None, limit=10)`

Searches workspace memories by semantic similarity.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. |
| `workspace_uid` | Yes | none | Workspace UID to search. Aliases resolve through Core. |
| `type` | No | all workspace types | Optional workspace memory bucket filter. |
| `limit` | No | `10` | Maximum number of ranked results. |

Returns: JSON list of search results.

### `add_memory(space, type, content, workspace_uid=None)`

Adds a memory and stores an embedding for semantic search.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `space` | Yes | `user` or `workspace`. |
| `type` | Yes | Memory bucket. User and workspace spaces have different valid buckets. |
| `content` | Yes | Text to store and embed. |
| `workspace_uid` | Required for workspace, forbidden for user | Workspace UID for workspace memories. |

Returns: created memory object as JSON.

### `get_memory(id)`

Fetches one memory by ID.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `id` | Yes | Memory ID. |

Returns: memory object as JSON.

### `update_memory(id, type=None, content=None)`

Updates a memory's type and/or content. Updating content regenerates the embedding.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `id` | Yes | Memory ID. |
| `type` | No | Replacement memory bucket. |
| `content` | No | Replacement memory text. |

Returns: updated memory object as JSON.

### `archive_memory(id)`

Archives a memory. Archived memories are hidden from default search and list results.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `id` | Yes | Memory ID to archive. |

Returns: archived memory object as JSON.

### `list_memories(space=None, type=None, workspace_uid=None, limit=None)`

Lists memories for inspection.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `space` | No | all spaces | Optional `user` or `workspace` filter. |
| `type` | No | all types | Optional memory type filter. |
| `workspace_uid` | No | all workspaces | Optional workspace filter. |
| `limit` | No | no explicit limit | Maximum number of memories to return. |

Returns: JSON list of memory objects.

### `list_workspaces(include_archived=False, include_aliases=False)`

Lists workspace UIDs known to Core.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `include_archived` | No | `false` | Includes workspaces that only appear on archived memories. |
| `include_aliases` | No | `false` | Returns workspace objects with nested alias arrays. |

Returns: JSON list of workspace UIDs or workspace objects.

### `resolve_workspace(uid)`

Normalizes a workspace UID candidate and resolves aliases.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `uid` | Yes | Workspace UID candidate. |

Returns: JSON object with `input_uid`, `normalized_uid`, `canonical_uid`, and `resolved_by_alias`.

### `add_workspace_alias(canonical_uid, alias_uid, migrate_existing=False)`

Creates an alias for a canonical workspace UID.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `canonical_uid` | Yes | none | Workspace UID that should own the memories. |
| `alias_uid` | Yes | none | Old or alternate UID that should resolve to the canonical UID. |
| `migrate_existing` | No | `false` | Moves existing memories under the alias UID to the canonical UID in the same transaction. |

Returns: JSON object containing the alias and migrated memory count.

### `list_workspace_aliases(canonical_uid=None)`

Lists workspace alias mappings.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `canonical_uid` | No | all canonical UIDs | Optional filter. |

Returns: JSON list of alias mappings.

### `remove_workspace_alias(alias_uid)`

Removes an alias mapping.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `alias_uid` | Yes | Alias UID to remove. |

Returns: removed alias mapping as JSON.

### `rename_workspace(old_uid, new_uid)`

Renames a workspace and migrates all workspace memories from the old UID to the new UID.

Parameters:

| Parameter | Required | What it does |
|---|---:|---|
| `old_uid` | Yes | Current workspace UID. |
| `new_uid` | Yes | New workspace UID. |

Returns: JSON object with old UID, new UID, memory count, and alias update count.


## Errors

MCP tools surface Core errors as JSON instead of raising client-specific exceptions. Common causes include missing required parameters, invalid memory buckets, missing workspace UIDs for workspace operations, missing memory IDs, and embedding provider readiness failures.

## Security reminder

MCP service mode is unauthenticated in v1. Do not expose it publicly. Keep it on localhost unless private networking and external access controls protect it.
