# MCP Server

This page is the user-readable reference for Recollectium's Model Context Protocol surface. It keeps the full MCP tool detail, but groups it around the same questions as the API reference: what MCP is for, how to run it, how clients discover or configure it, what the response format looks like, and which operations are available.

MCP and API expose the same core memory operations where the transport makes sense. MCP also has extra stdio guidance because many MCP clients start tool servers as child processes instead of connecting to a long-running HTTP service.

## What MCP is for

Use MCP when an assistant or agent client supports Model Context Protocol and should see Recollectium as native tools.

MCP is best for:

- AI clients that can load local MCP tool servers;
- agents that should call memory tools without composing CLI commands;
- clients that want Recollectium operations to appear as tool calls such as `search_user_memory`, `add_memory`, or `resolve_workspace`;
- one durable Core database shared by multiple agent clients and surfaces;
- integrations that want Recollectium Core to enforce user memory, workspace memory, memory bucket, archive, and workspace alias rules.

Common stdio MCP clients include Claude Code, Claude Desktop, Cursor, and OpenCode. Common HTTP MCP clients or tools include MCP Inspector, OpenAI Agents SDK, and remote MCP gateways.

If you are building an adapter, web UI, script, service integration, test harness, or anything that talks HTTP directly, use the API instead. If your client supports MCP tools and the integration is agent-facing, MCP is usually the nicer path.

## Run the MCP server

Recollectium supports two MCP runtime styles: stdio mode and managed HTTP mode.

### Stdio mode

Use stdio mode when the MCP client starts local servers as child processes.

```bash
recollectium mcp-stdio
```

In stdio mode:

- the MCP client launches `recollectium mcp-stdio`;
- Recollectium reads MCP messages from stdin and writes MCP messages to stdout;
- no HTTP port is opened;
- no PID file or discovery file is created;
- the server runs for the lifetime of the client connection;
- the client is responsible for starting and stopping the process.

Useful global options:

```bash
recollectium --config /path/to/config.json mcp-stdio
recollectium --db /path/to/recollectium.db mcp-stdio
recollectium --log-level debug mcp-stdio
```

Use `--config` when a client should use a specific Recollectium config file. Use `--db` when a client should use a specific SQLite database. Use `--log-level debug` while troubleshooting client startup, tool registration, or embedding readiness.

If running from a source checkout during development, use the source checkout as the command context:

```bash
uv --directory /path/to/recollectium run recollectium mcp-stdio
```

Prefer the installed `recollectium` command for normal user setup after bootstrap or package install. Reserve `uv --directory ... run recollectium ...` for source checkout development.

### Managed HTTP mode

Use managed HTTP mode when a client or adapter expects a long-running local MCP service instead of spawning a stdio child process.

```bash
recollectium service start mcp
recollectium service status
recollectium service discover
recollectium service stop
```

Managed mode starts a background MCP service using the configured host and port. It writes PID and discovery files so local adapters can find it.

Default local behavior follows Recollectium's local service configuration. Keep managed MCP bound to localhost unless private networking and external access controls protect it.

## Discovery and compatibility

Stdio clients usually manage the MCP process themselves, so discovery is the configured command plus arguments. In that path, the client starts Recollectium and receives the available MCP tools during MCP initialization.

Managed MCP mode can be discovered with:

```bash
recollectium service discover
```

The command exits `0` when a managed service is running, exits `1` when no service is running, and exits `2` when config or discovery metadata is invalid. It prints JSON on stdout and does not create a config file just to inspect discovery state.

Running managed MCP response shape:

```json
{
  "status": "running",
  "service": {
    "type": "mcp",
    "pid": 12345,
    "process_start_time": 123456789,
    "endpoint": "http://127.0.0.1:8765",
    "api_prefix": "/v1",
    "health_url": "http://127.0.0.1:8765/v1/health",
    "version_url": "http://127.0.0.1:8765/v1/version",
    "capabilities_url": "http://127.0.0.1:8765/v1/capabilities"
  },
  "versions": {
    "service_api_version": "1",
    "recollectium_version": "0.x.y"
  },
  "paths": {
    "config": "/home/user/.config/recollectium/config.json",
    "runtime_dir": "/run/user/1000/recollectium",
    "pid_file": "/run/user/1000/recollectium/service.pid",
    "discovery_file": "/run/user/1000/recollectium/service-discovery.json"
  }
}
```

Not-running response shape:

```json
{
  "status": "not_running",
  "service": null,
  "versions": {
    "service_api_version": "1",
    "recollectium_version": "0.x.y"
  },
  "paths": {
    "config": "/home/user/.config/recollectium/config.json",
    "runtime_dir": "/run/user/1000/recollectium",
    "pid_file": "/run/user/1000/recollectium/service.pid",
    "discovery_file": "/run/user/1000/recollectium/service-discovery.json"
  },
  "next_step": "Run `recollectium service start api` to start the local API service."
}
```

`recollectium service start api` and `recollectium service start mcp` write the running response to `{runtime_dir}/service-discovery.json` after process ownership is verified. `recollectium service stop`, `recollectium service status`, and `recollectium service discover` remove stale Recollectium-owned PID and discovery files when they prove the managed process is gone.

Clients and adapters should still treat Recollectium Core as the source of truth for memory rules. Workspace aliases, workspace UID normalization, memory bucket validation, archive behavior, and embedding readiness all live in Core.

For same-machine stdio clients, compatibility is normally handled by the MCP initialization flow and the available tool list. For managed MCP or adapter flows, validate the service before enabling Recollectium-backed tools when the client supports that validation. This confirms compatibility, not authentication or authorization:

1. For local discovery, use the returned `health_url`, `version_url`, and `capabilities_url` when the managed service exposes them. For remote Core config, derive `/v1/health`, `/v1/version`, and `/v1/capabilities` from the configured base URL.
2. Call the health endpoint and require an ok response.
3. Call the version endpoint and verify compatible `service_api_version`.
4. Call the capabilities endpoint and verify every required capability is present.

Adapters should autodiscover Recollectium after the host application loads the plugin when the adapter and Core run on the same machine. Users should not need to manually configure host, port, PID file, runtime path, or service type for that local path. If local autodiscovery reports `not_running`, the plugin should attempt the right local startup path and then rerun discovery before guiding the user. For an HTTP API adapter, that startup path is `recollectium service start api`. For a managed MCP adapter, it is `recollectium service start mcp`. For a stdio MCP client, the client should spawn `recollectium mcp-stdio` directly.

Private-network split-machine Core instances are different: the user points the plugin at the Core base URL in plugin config, and the adapter validates that configured endpoint by calling `/v1/health`, `/v1/version`, and `/v1/capabilities` when using the HTTP API path. Host-level plugin registration remains outside Recollectium Core. See [OpenCode adapter contract](../opencode-adapter-contract.md) for the adapter contract and workspace UID rules.

## Response format

MCP tools return JSON strings, not native Python objects.

Successful memory-returning tools return either a JSON object or a JSON list, depending on the tool. For example, `get_memory` returns one memory object:

```json
{
  "id": "8f6d...",
  "space": "user",
  "workspace_uid": null,
  "type": "fact",
  "content": "Alfonso likes tea",
  "metadata": {},
  "status": "active",
  "source": null,
  "confidence": null,
  "sensitivity": null,
  "created_at": "2026-05-18T12:34:56+00:00",
  "updated_at": "2026-05-18T12:34:56+00:00",
  "last_accessed_at": null
}
```

Search tools return a JSON list of ranked results:

```json
[
  {
    "memory": {
      "id": "8f6d...",
      "space": "user",
      "workspace_uid": null,
      "type": "fact",
      "content": "Alfonso likes tea",
      "metadata": {},
      "status": "active",
      "source": null,
      "confidence": null,
      "sensitivity": null,
      "created_at": "2026-05-18T12:34:56+00:00",
      "updated_at": "2026-05-18T12:34:56+00:00",
      "last_accessed_at": null
    },
    "score": 0.91,
    "rank": 1
  }
]
```

Recollectium errors return a JSON object with an `error` field:

```json
{"error": "workspace_uid is required for workspace search"}
```

Unlike the HTTP API, MCP tool errors do not currently use the `{"error":{"code":...,"message":...,"details":...}}` envelope. The MCP surface serializes the Core error message into `{"error":"..."}` so clients can display the failure inside the tool result.

## Memory rules

- Workspace search requires `workspace_uid`.
- Adding workspace memories requires `space="workspace"` and `workspace_uid`.
- Adding user memories requires `space="user"` and must not include `workspace_uid`.
- Memory buckets are scope-aware. User and workspace memories have different valid buckets.
- Workspace filters on list are optional.
- Archived memories are hidden from default search and list behavior.
- Workspace UID candidates are normalized by Core.
- Workspace aliases resolve through Core.

Violations return an error JSON object.

## Operations

All MCP tools return JSON strings. On Recollectium errors, tools return a JSON object containing an `error` field.

### Health, version, and capabilities

MCP does not currently expose standalone `health`, `version`, or `capabilities` tools.

For stdio clients, basic compatibility comes from MCP initialization and the tool list returned by the server. If the client can connect and sees the Recollectium tools documented below, the stdio server is running.

For managed MCP services, use service discovery and validation around the managed service process:

```bash
recollectium service discover
```

When a client or adapter also uses the HTTP validation path, call the discovered `/v1/health`, `/v1/version`, and `/v1/capabilities` URLs before enabling Recollectium-backed tools.

### Memory operations

#### `search_user_memory(query, type=None, limit=10)`

Purpose: semantic search in user-space memories only.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. Must be non-empty. |
| `type` | No | all user types | Optional user memory bucket filter. Usually omit this first. |
| `limit` | No | `10` | Maximum number of ranked results. |

Side effects: none.

Returns: JSON list of search results. Each result has `memory`, `score`, and `rank`.

Example tool arguments:

```json
{
  "query": "editor preferences",
  "type": "preference",
  "limit": 5
}
```

Example result:

```json
[
  {
    "memory": {
      "id": "8f6d...",
      "space": "user",
      "workspace_uid": null,
      "type": "preference",
      "content": "Alfonso prefers concise responses",
      "metadata": {},
      "status": "active",
      "source": null,
      "confidence": null,
      "sensitivity": null,
      "created_at": "2026-05-18T12:34:56+00:00",
      "updated_at": "2026-05-18T12:34:56+00:00",
      "last_accessed_at": null
    },
    "score": 0.91,
    "rank": 1
  }
]
```

#### `search_workspace_memory(query, workspace_uid, type=None, limit=10)`

Purpose: semantic search in one workspace UID only.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. Must be non-empty. |
| `workspace_uid` | Yes | none | Workspace UID to search. Aliases resolve through Core. |
| `type` | No | all workspace types | Optional workspace memory bucket filter. |
| `limit` | No | `10` | Maximum number of ranked results. |

Side effects: none.

Returns: JSON list of search results.

Example tool arguments:

```json
{
  "query": "sqlite migration decision",
  "workspace_uid": "recollectium",
  "type": "decision",
  "limit": 5
}
```

Example result:

```json
[
  {
    "memory": {
      "id": "d22a...",
      "space": "workspace",
      "workspace_uid": "recollectium",
      "type": "decision",
      "content": "Use sqlite for the local memory database",
      "metadata": {},
      "status": "active",
      "source": null,
      "confidence": null,
      "sensitivity": null,
      "created_at": "2026-05-18T12:34:56+00:00",
      "updated_at": "2026-05-18T12:34:56+00:00",
      "last_accessed_at": null
    },
    "score": 0.88,
    "rank": 1
  }
]
```

#### `add_memory(space, type, content, workspace_uid=None)`

Purpose: create one memory and store an embedding for semantic search.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `space` | Yes | none | `user` or `workspace`. |
| `type` | Yes | none | Memory bucket. User and workspace spaces have different valid buckets. |
| `content` | Yes | none | Text to store and embed. Must be non-empty. |
| `workspace_uid` | Required for workspace, forbidden for user | `null` | Workspace UID for workspace memories. |

Side effects:

- Inserts memory into SQLite storage.
- Generates and stores an embedding for `content`.

Returns: created memory object as JSON.

Example tool arguments:

```json
{
  "space": "workspace",
  "type": "decision",
  "content": "Use sqlite for the local memory database",
  "workspace_uid": "recollectium"
}
```

Example result:

```json
{
  "id": "d22a...",
  "space": "workspace",
  "workspace_uid": "recollectium",
  "type": "decision",
  "content": "Use sqlite for the local memory database",
  "metadata": {},
  "status": "active",
  "source": null,
  "confidence": null,
  "sensitivity": null,
  "created_at": "2026-05-18T12:34:56+00:00",
  "updated_at": "2026-05-18T12:34:56+00:00",
  "last_accessed_at": null
}
```

#### `get_memory(id)`

Purpose: fetch one memory by ID.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `id` | Yes | none | Memory ID. |

Side effects:

- Updates `last_accessed_at` when possible.

Returns: memory object as JSON.

Example tool arguments:

```json
{
  "id": "8f6d..."
}
```

Example result:

```json
{
  "id": "8f6d...",
  "space": "user",
  "workspace_uid": null,
  "type": "fact",
  "content": "Alfonso likes tea",
  "metadata": {},
  "status": "active",
  "source": null,
  "confidence": null,
  "sensitivity": null,
  "created_at": "2026-05-18T12:34:56+00:00",
  "updated_at": "2026-05-18T12:34:56+00:00",
  "last_accessed_at": "2026-05-18T12:36:10+00:00"
}
```

#### `update_memory(id, type=None, content=None)`

Purpose: update one existing memory's type and/or content.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `id` | Yes | none | Memory ID. |
| `type` | No | unchanged | Replacement memory bucket. |
| `content` | No | unchanged | Replacement memory text. |

Side effects:

- Updates memory fields.
- If `content` changes, the embedding is regenerated.

Returns: updated memory object as JSON.

Example tool arguments:

```json
{
  "id": "8f6d...",
  "content": "Alfonso likes green tea"
}
```

Example result:

```json
{
  "id": "8f6d...",
  "space": "user",
  "workspace_uid": null,
  "type": "fact",
  "content": "Alfonso likes green tea",
  "metadata": {},
  "status": "active",
  "source": null,
  "confidence": null,
  "sensitivity": null,
  "created_at": "2026-05-18T12:34:56+00:00",
  "updated_at": "2026-05-18T12:35:20+00:00",
  "last_accessed_at": null
}
```

#### `archive_memory(id)`

Purpose: mark a memory archived.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `id` | Yes | none | Memory ID to archive. |

Side effects:

- Sets memory status to archived.
- Archived memories are excluded from default search and list results.

Returns: archived memory object as JSON.

Example tool arguments:

```json
{
  "id": "8f6d..."
}
```

Example result:

```json
{
  "id": "8f6d...",
  "space": "user",
  "workspace_uid": null,
  "type": "fact",
  "content": "Alfonso likes green tea",
  "metadata": {},
  "status": "archived",
  "source": null,
  "confidence": null,
  "sensitivity": null,
  "created_at": "2026-05-18T12:34:56+00:00",
  "updated_at": "2026-05-18T12:35:45+00:00",
  "last_accessed_at": null
}
```

#### `list_memories(space=None, type=None, workspace_uid=None, limit=None)`

Purpose: list memories for inspection with optional filters.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `space` | No | all spaces | Optional `user` or `workspace` filter. |
| `type` | No | all types | Optional memory type filter. |
| `workspace_uid` | No | all workspaces | Optional workspace filter. |
| `limit` | No | no explicit limit | Maximum number of memories to return. |

Side effects: none.

Returns: JSON list of memory objects.

Example tool arguments:

```json
{
  "space": "workspace",
  "workspace_uid": "recollectium",
  "limit": 20
}
```

Example result:

```json
[
  {
    "id": "d22a...",
    "space": "workspace",
    "workspace_uid": "recollectium",
    "type": "decision",
    "content": "Use sqlite for the local memory database",
    "metadata": {},
    "status": "active",
    "source": null,
    "confidence": null,
    "sensitivity": null,
    "created_at": "2026-05-18T12:34:56+00:00",
    "updated_at": "2026-05-18T12:34:56+00:00",
    "last_accessed_at": null
  }
]
```

### Memory response shape

Memory-returning MCP tools serialize the same memory object shape as Core:

```json
{
  "id": "string",
  "space": "user|workspace",
  "workspace_uid": "string|null",
  "type": "string",
  "content": "string",
  "metadata": {},
  "status": "active|archived",
  "source": "string|null",
  "confidence": 0.0,
  "sensitivity": "string|null",
  "created_at": "ISO-8601 string",
  "updated_at": "ISO-8601 string",
  "last_accessed_at": "ISO-8601 string|null"
}
```

Search tools return a list of:

```json
{
  "memory": {"id": "..."},
  "score": 0.91,
  "rank": 1
}
```

### Embedding operations

MCP does not currently expose standalone embedding status or embedding job tools.

Memory tools still use embeddings through Core:

- `add_memory` embeds the stored content.
- `update_memory` regenerates the embedding when content changes.
- `search_user_memory` and `search_workspace_memory` use semantic search.
- Core handles provider readiness, model availability, stale-profile checks, and re-embedding errors.

For embedding status, recent jobs, or one job by ID, use the API endpoints documented in [API Reference](API-Reference.md) or the matching CLI commands:

```bash
recollectium embedding-status
recollectium embedding-jobs --limit 10
```

### Workspace operations

#### `list_workspaces(include_archived=False, include_aliases=False)`

Purpose: list distinct workspace UIDs known to Core.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `include_archived` | No | `false` | Includes workspaces that only appear on archived memories. |
| `include_aliases` | No | `false` | Returns workspace objects with nested alias arrays instead of UID strings. |

Side effects: none.

Returns: JSON list of workspace UIDs or workspace objects.

Example tool arguments:

```json
{
  "include_archived": false,
  "include_aliases": true
}
```

Example result:

```json
[
  {"workspace_uid": "recollectium", "aliases": ["recollectium-core"]},
  {"workspace_uid": "generalist-ai", "aliases": []}
]
```

#### `resolve_workspace(uid)`

Purpose: normalize a workspace UID candidate and resolve it to the canonical UID if it is an alias.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `uid` | Yes | none | Workspace UID candidate. |

Side effects: none.

Returns: JSON object with `input_uid`, `normalized_uid`, `canonical_uid`, and `resolved_by_alias`.

Example tool arguments:

```json
{
  "uid": "Recollectium Core"
}
```

Example result:

```json
{
  "input_uid": "Recollectium Core",
  "normalized_uid": "recollectium-core",
  "canonical_uid": "recollectium",
  "resolved_by_alias": true
}
```

#### `add_workspace_alias(canonical_uid, alias_uid, migrate_existing=False)`

Purpose: add an alias for a canonical workspace UID.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `canonical_uid` | Yes | none | Workspace UID that should own the memories. |
| `alias_uid` | Yes | none | Old or alternate UID that should resolve to the canonical UID. |
| `migrate_existing` | No | `false` | Moves existing memories under the alias UID to the canonical UID in the same transaction. |

Side effects:

- Creates an alias mapping.
- If `migrate_existing=true`, moves existing alias-owned memories into the canonical workspace in the same transaction.

Returns: JSON object containing the alias and migrated memory count.

Example tool arguments:

```json
{
  "canonical_uid": "recollectium",
  "alias_uid": "recollectium-core",
  "migrate_existing": false
}
```

Example result:

```json
{
  "alias": {
    "alias_uid": "recollectium-core",
    "canonical_uid": "recollectium",
    "created_at": "2026-05-28T00:00:00Z",
    "updated_at": "2026-05-28T00:00:00Z"
  },
  "migrated_memories": 0
}
```

Example error when existing memories already use the alias UID:

```json
{
  "error": "workspace alias conflicts with existing workspace memories: recollectium-core. Use --migrate-existing to move those memories to recollectium and keep recollectium-core as an alias."
}
```

#### `list_workspace_aliases(canonical_uid=None)`

Purpose: list workspace alias mappings.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `canonical_uid` | No | all canonical UIDs | Optional canonical workspace UID filter. |

Side effects: none.

Returns: JSON list of alias mappings.

Example tool arguments:

```json
{
  "canonical_uid": "recollectium"
}
```

Example result:

```json
[
  {
    "alias_uid": "recollectium-core",
    "canonical_uid": "recollectium",
    "created_at": "2026-05-28T00:00:00Z",
    "updated_at": "2026-05-28T00:00:00Z"
  }
]
```

#### `remove_workspace_alias(alias_uid)`

Purpose: remove an alias mapping by alias UID.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `alias_uid` | Yes | none | Alias UID to remove. |

Side effects:

- Removes the alias mapping.
- Does not move memories.

Returns: removed alias mapping as JSON.

Example tool arguments:

```json
{
  "alias_uid": "recollectium-core"
}
```

Example result:

```json
{
  "alias_uid": "recollectium-core",
  "canonical_uid": "recollectium",
  "created_at": "2026-05-28T00:00:00Z",
  "updated_at": "2026-05-28T00:00:00Z"
}
```

#### `rename_workspace(old_uid, new_uid)`

Purpose: rename a workspace and migrate all workspace memories from the old UID to the new UID.

Parameters:

| Parameter | Required | Default | What it does |
|---|---:|---|---|
| `old_uid` | Yes | none | Current workspace UID. |
| `new_uid` | Yes | none | New workspace UID. |

Side effects:

- Migrates all workspace memories from `old_uid` to `new_uid`, including archived memories.
- Updates workspace alias mappings that point at the old UID.
- Normalizes both UIDs according to `workspace.uid_normalization` before the operation.

Returns: JSON object with old UID, new UID, memory count, and alias update count.

Example tool arguments:

```json
{
  "old_uid": "recollectium-core",
  "new_uid": "recollectium"
}
```

Example result:

```json
{
  "old_uid": "recollectium-core",
  "new_uid": "recollectium",
  "memories_updated": 42,
  "aliases_updated": 3
}
```

Example error when the workspace does not exist:

```json
{
  "error": "no workspace memories found for uid: nonexistent"
}
```

## Errors

MCP tools surface Core errors as JSON instead of raising client-specific exceptions. The current MCP error shape is:

```json
{"error": "message"}
```

Common causes include:

- missing required parameters;
- invalid memory buckets for the selected scope;
- missing `workspace_uid` for workspace search or workspace memory creation;
- providing `workspace_uid` for a user memory;
- missing memory IDs;
- unsupported or empty workspace UID candidates after normalization;
- workspace alias conflicts;
- embedding provider readiness failures;
- embedding model cache or load failures;
- embedding generation failures;
- re-embedding jobs already in progress or failed.

Common failure examples:

Missing workspace UID for workspace search:

```json
{"error": "workspace_uid is required for workspace search"}
```

Missing memory ID:

```json
{"error": "memory not found: 8f6d..."}
```

Alias conflict:

```json
{"error": "workspace alias conflicts with existing workspace memories: recollectium-core. Use --migrate-existing to move those memories to recollectium and keep recollectium-core as an alias."}
```

## Security reminder

See [Security policy](../../SECURITY.md) for the full v1 security model.

- MCP stdio mode is local to the client process that starts it.
- Managed MCP service mode is local-first and intended for single-machine use.
- API and MCP services are unauthenticated in v1 and are not public internet APIs.
- The SQLite memory database is not encrypted by Recollectium.
- If you bind a managed service to a non-local interface, memory contents and memory-changing operations may be exposed to anyone who can reach that interface.
- Any user, process, or network client with sufficient access to the Recollectium data directory, database file, or unauthenticated service endpoint can read, modify, or delete memories. Because memories influence what agents recall, unauthorized memory changes can also influence agent behavior.
- If an agent must connect from another machine, use private networking with external access controls. For most users, Tailscale is the recommended split-machine path; WireGuard, SSH tunneling, firewall allowlists, or equivalent VPN/overlay networking can also work.

## Notes

- MCP tools return JSON strings.
- Tool names are part of the current MCP surface and should stay stable across v1-compatible changes.
- Only documented tool parameters are supported.
- `update_memory` currently exposes `type` and `content` updates through MCP. The HTTP API supports additional metadata-oriented fields.
- MCP tool errors currently use the simple `{"error":"message"}` shape rather than the HTTP API's structured error envelope.
- This document is tied to the current implementation and should be updated with MCP server changes.
