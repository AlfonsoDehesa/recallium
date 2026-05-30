# Recollectium Core Local Service API

This document describes the currently implemented FastAPI local HTTP JSON service in `src/recollectium/service.py`.

## Local access and security assumptions

See [`../SECURITY.md`](../SECURITY.md) for the full v1 security model.

- This service is local-first and intended for single-machine use.
- Default bind is `127.0.0.1` on port `8765`.
- API and MCP services are unauthenticated in v1 and are not public internet APIs.
- The SQLite memory database is not encrypted by Recollectium.
- If you bind a service to a non-local interface, memory contents and memory-changing operations may be exposed to anyone who can reach that interface.
- Any user, process, or network client with sufficient access to the Recollectium data directory, database file, or unauthenticated service endpoint can read, modify, or delete memories. Because memories influence what agents recall, unauthorized memory changes can also influence agent behavior.
- If an agent must connect from another machine, use private networking with external access controls. For most users, Tailscale is the recommended split-machine path; WireGuard, SSH tunneling, firewall allowlists, or equivalent VPN/overlay networking can also work.

For the managed service path used by adapters, start the API service with:

```bash
recollectium service start api
```

For foreground development or debugging, run the same API server directly:

```bash
recollectium serve
```

Or run the foreground server with explicit host/port/database path:

```bash
recollectium --db /path/to/recollectium.db serve --host 127.0.0.1 --port 8765
```

## Base URL and versioning

- Default base URL: `http://127.0.0.1:8765`
- API prefix: `/v1`
- Service API version value: `1`

## Adapter discovery workflow

Adapters and plugins should discover the local service with:

```bash
recollectium service discover
```

The command exits `0` when a managed service is running, exits `1` when no service is running, and exits `2` when config or discovery metadata is invalid. It prints human-readable output on stdout by default and does not create a config file just to inspect discovery state. Use `recollectium service discover --json` in adapters and scripts.

Running response shape:

```json
{
  "status": "running",
  "service": {
    "type": "api",
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

Adapters should validate the target service before enabling Recollectium-backed tools. This validation confirms compatibility, not authentication or authorization:

1. For local discovery, use the returned `health_url`, `version_url`, and
   `capabilities_url`. For remote Core config, derive `/v1/health`,
   `/v1/version`, and `/v1/capabilities` from the configured base URL.
2. Call the health endpoint and require an ok response.
3. Call the version endpoint and verify compatible `service_api_version`.
4. Call the capabilities endpoint and verify every required capability is
   present.

Adapters should autodiscover Recollectium after the host application loads the
plugin when the adapter and Core run on the same machine. Users should not need
to manually configure host, port, PID file, runtime path, or service type for
that local path. If local autodiscovery reports `not_running`, the plugin should
attempt `recollectium service start api` and then rerun discovery before guiding
the user. Private-network split-machine Core instances are different: the user points the
plugin at the Core base URL in plugin config, and the adapter validates that
configured endpoint by calling `/v1/health`, `/v1/version`, and
`/v1/capabilities`. Host-level plugin registration remains outside Recollectium
Core. See `docs/opencode-adapter-contract.md` for the adapter contract and
workspace UID rules.

The API is local-first and unauthenticated in Phase 1. Binding to a non-local interface can expose memory contents and memory-changing operations. Remote or split-machine access should use private networking with external access controls; see [`../SECURITY.md`](../SECURITY.md).

## Envelope shapes

Successful responses use:

```json
{
  "data": {}
}
```

Error responses use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "workspace_uid is required for workspace search",
    "details": {}
  }
}
```

`details` is currently always an object and defaults to `{}`.

## Version and capability discovery

### `GET /v1/health`

Purpose: service liveness check.

Response example:

```json
{
  "data": {
    "status": "ok"
  }
}
```

### `GET /v1/version`

Purpose: report service API and package version.

Response example:

```json
{
  "data": {
    "service_api_version": "1",
    "recollectium_version": "0.x.y"
  }
}
```

### `GET /v1/capabilities`

Purpose: list implemented operation capabilities.

Response example:

```json
{
  "data": {
    "service_api_version": "1",
    "capabilities": [
      "health.read",
      "version.read",
      "capabilities.read",
      "memories.search_user",
      "memories.search_workspace",
      "memories.add",
      "memories.update",
      "memories.archive",
      "memories.list",
      "memories.get",
      "embedding.status",
      "embedding.jobs.list",
      "embedding.jobs.get",
      "workspaces.list",
      "workspaces.rename",
      "workspaces.resolve",
      "workspaces.aliases.list",
      "workspaces.aliases.add",
      "workspaces.aliases.remove"
    ],
    "memory_types": {
      "user": [
        "fact",
        "preference",
        "personal_fact",
        "social_context",
        "goal",
        "communication_style",
        "note"
      ],
      "workspace": [
        "fact",
        "decision",
        "task_context",
        "configuration",
        "bug_finding",
        "note"
      ],
      "all": [
        "fact",
        "preference",
        "personal_fact",
        "social_context",
        "goal",
        "communication_style",
        "note",
        "decision",
        "task_context",
        "configuration",
        "bug_finding"
      ]
    }
  }
}
```

## Workspace UID requirements

- Workspace search requires `workspace_uid`.
- Adding workspace memories requires `space="workspace"` and `workspace_uid`.
- Adding user memories requires `space="user"` and must not include `workspace_uid`.
- Workspace filters on list are optional.

Violations return `validation_error`.

## Endpoints

All request bodies below are JSON objects.
All successful endpoint responses currently return HTTP `200` with a `{"data": ...}` payload.

### 1) Search user memories

- Method and path: `POST /v1/memories/search_user`
- Purpose: semantic search in user-space memories only.
- Required inputs:
  - `query` (string, non-empty)
- Optional inputs:
  - `type` (string bucket filter; optional)
  - `limit` (positive integer, default `10`)
  - `include_archived` (boolean, default `false`)
- Side effects: none.
- Successful response: HTTP `200` with `data` list of search results (`memory`, `score`, `rank`).

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/memories/search_user \
  -H 'Content-Type: application/json' \
  -d '{"query":"likes tea","type":"fact","limit":5}'
```

Example response:

```json
{
  "data": [
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
}
```

### 2) Search workspace memories

- Method and path: `POST /v1/memories/search_workspace`
- Purpose: semantic search in one workspace UID only.
- Required inputs:
  - `query` (string, non-empty)
  - `workspace_uid` (string, non-empty)
- Optional inputs:
  - `type` (string bucket filter; optional)
  - `limit` (positive integer, default `10`)
  - `include_archived` (boolean, default `false`)
- Side effects: none.
- Successful response: HTTP `200` with `data` list of search results (`memory`, `score`, `rank`).

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/memories/search_workspace \
  -H 'Content-Type: application/json' \
  -d '{"query":"sqlite","workspace_uid":"ws-1","type":"decision"}'
```

Example response:

```json
{
  "data": [
    {
      "memory": {
        "id": "d22a...",
        "space": "workspace",
        "workspace_uid": "ws-1",
        "type": "decision",
        "content": "Use sqlite for local db",
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
}
```

### 3) Add memory

- Method and path: `POST /v1/memories`
- Purpose: create one memory.
- Required inputs:
  - `space` (`"user"` or `"workspace"`)
  - `type` (string, non-empty)
  - `content` (string, non-empty)
- Conditionally required:
  - `workspace_uid` required when `space="workspace"`
  - `workspace_uid` forbidden when `space="user"`
- Optional inputs:
  - `metadata` (JSON object, default `{}`)
  - `source` (string)
  - `confidence` (number in range `0` to `1`)
  - `sensitivity` (string)
- Side effects:
  - Inserts memory into SQLite store.
  - Generates and stores embedding for `content`.
- Successful response: HTTP `200` with `data` set to the created memory object.

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/memories \
  -H 'Content-Type: application/json' \
  -d '{"space":"workspace","type":"decision","content":"Use sqlite","workspace_uid":"ws-1"}'
```

Example response:

```json
{
  "data": {
    "id": "d22a...",
    "space": "workspace",
    "workspace_uid": "ws-1",
    "type": "decision",
    "content": "Use sqlite",
    "metadata": {},
    "status": "active",
    "source": null,
    "confidence": null,
    "sensitivity": null,
    "created_at": "2026-05-18T12:34:56+00:00",
    "updated_at": "2026-05-18T12:34:56+00:00",
    "last_accessed_at": null
  }
}
```

### 4) Update memory

- Method and path: `PATCH /v1/memories/{memory_id}`
- Purpose: update one existing memory.
- Path params:
  - `memory_id` (string)
- Optional inputs (at least one required):
  - `type` (string)
  - `content` (string)
  - `metadata` (JSON object)
  - `source` (string)
  - `confidence` (number in range `0` to `1`)
  - `sensitivity` (string)
- Side effects:
  - Updates memory fields.
  - If `content` changes, embedding is regenerated.
- Successful response: HTTP `200` with `data` set to the updated memory object.

Example request:

```bash
curl -sS -X PATCH http://127.0.0.1:8765/v1/memories/8f6d... \
  -H 'Content-Type: application/json' \
  -d '{"content":"Alfonso likes green tea"}'
```

Example response:

```json
{
  "data": {
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
}
```

### 5) Archive memory

- Method and path: `POST /v1/memories/{memory_id}/archive`
- Purpose: mark a memory archived.
- Path params:
  - `memory_id` (string)
- Side effects:
  - Sets memory status to archived.
  - Archived memories are excluded from default search and list results.
- Successful response: HTTP `200` with `data` set to the archived memory object.

Example request:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/memories/8f6d.../archive
```

Example response:

```json
{
  "data": {
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
}
```

### 6) List memories

- Method and path: `GET /v1/memories`
- Purpose: list memories with optional filters.
- Query params (all optional):
  - `space` (string)
  - `type` (string)
  - `status` (string)
  - `workspace_uid` (string)
  - `include_archived` (`true` or `false`, default `false`)
  - `limit` (positive integer)
- Side effects: none.
- Successful response: HTTP `200` with `data` list of memory objects.

Archived behavior:

- By default (`include_archived` omitted), archived memories are excluded.
- Set `include_archived=true` to include archived memories.

Example request:

```bash
curl -sS 'http://127.0.0.1:8765/v1/memories?space=workspace&workspace_uid=ws-1&include_archived=true&limit=20'
```

Example response:

```json
{
  "data": [
    {
      "id": "d22a...",
      "space": "workspace",
      "workspace_uid": "ws-1",
      "type": "decision",
      "content": "Use sqlite",
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
}
```

### 7) Get memory by ID

- Method and path: `GET /v1/memories/{memory_id}`
- Purpose: fetch one memory by ID.
- Path params:
  - `memory_id` (string)
- Side effects:
  - Updates `last_accessed_at` when possible.
- Successful response: HTTP `200` with `data` set to one memory object.

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/memories/8f6d...
```

Example response:

```json
{
  "data": {
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
}
```

## Memory object shape

Memory responses use this JSON object shape:

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

Search responses return a list of:

```json
{
  "memory": {"id": "..."},
  "score": 0.91,
  "rank": 1
}
```

### 8) Embedding status

- Method and path: `GET /v1/embedding/status`
- Purpose: return the active local embedding profile, runtime posture, startup re-embedding job reference, status paths, and recent embedding jobs.
- Side effects: none.
- Successful response: HTTP `200` with current embedding profile and optional startup job ID.

Example response:

```json
{
  "data": {
    "embedding_profile": {
      "provider": "builtin-fastembed",
      "model": "jinaai/jina-embeddings-v2-small-en",
      "dimensions": 512,
      "version": "1",
      "profile": "builtin-fastembed-jina-v2-small-en-v1",
      "max_tokens": 8192,
      "chunk_tokens": 6144,
      "chunk_overlap_tokens": 512,
      "query_prompt_policy": "raw"
    },
    "provider_status": "configured",
    "model_status": "managed_by_fastembed_cache",
    "runtime": {
      "name": "fastembed",
      "threads": 1,
      "parallel": null
    },
    "startup_reembedding_job_id": "job-123",
    "startup_reembedding_status_path": "/v1/embedding/jobs/job-123",
    "embedding_jobs_status_path": "/v1/embedding/jobs",
    "recent_embedding_jobs": []
  }
}
```

### 9) List embedding jobs

- Method and path: `GET /v1/embedding/jobs`
- Purpose: list embedding jobs for model readiness or stale-profile re-embedding.
- Optional query params:
  - `state` (string, commonly `pending`, `in_progress`, `completed`, or `failed`)
  - `limit` (positive integer)
- Side effects: none.
- Successful response: HTTP `200` with a `data` list ordered by most recent first.

Example request:

```bash
curl -sS "http://127.0.0.1:8765/v1/embedding/jobs?state=failed&limit=5"
```

Example response:

```json
{
  "data": [
    {
      "id": "job-123",
      "state": "failed",
      "total_count": 3,
      "processed_count": 1,
      "succeeded_count": 0,
      "failed_count": 1,
      "provider": "builtin-fastembed",
      "model": "jinaai/jina-embeddings-v2-small-en",
      "embedding_profile": {
        "provider": "builtin-fastembed",
        "model": "jinaai/jina-embeddings-v2-small-en"
      },
      "error_message": "runtime re-embedding failed",
      "started_at": "2026-05-19T10:10:00+00:00",
      "completed_at": "2026-05-19T10:10:05+00:00"
    }
  ]
}
```

### 10) Get embedding job

- Method and path: `GET /v1/embedding/jobs/{job_id}`
- Purpose: fetch one embedding job by ID.
- Job states: deferred work can appear as `pending` briefly before the in-process worker starts it, `in_progress` while memories are being refreshed, `completed` when all stale memories succeeded, or `failed` when one or more memories could not be re-embedded.
- Path params:
  - `job_id` (string)
- Side effects: none.
- Successful response: HTTP `200` with one job object in `data`.

Example response:

```json
{
  "data": {
    "id": "job-123",
    "state": "in_progress",
    "total_count": 12,
    "processed_count": 4,
    "succeeded_count": 4,
    "failed_count": 0,
    "provider": "builtin-fastembed",
    "model": "jinaai/jina-embeddings-v2-small-en",
    "embedding_profile": {
      "provider": "builtin-fastembed",
      "model": "jinaai/jina-embeddings-v2-small-en"
    },
    "error_message": "triggered by search",
    "started_at": "2026-05-19T10:10:00+00:00",
    "completed_at": null
  }
}
```

## Error codes and common failures

Implemented error codes:

- `validation_error` (`400`)
  - Examples: missing required fields, invalid `space`, bad `limit`, missing `workspace_uid` for workspace search, empty JSON body.
- `not_found` (`404`)
  - Example: `GET /v1/memories/{memory_id}` for missing ID.
- `unsupported_operation` (`404`)
  - Example: unknown path or unsupported method on a known path.
- `invalid_json` (`400`)
  - Example: malformed JSON request body.
- `embedding_provider_unavailable` (`503`)
  - Example: built-in provider runtime could not initialize.
- `embedding_model_unavailable` (`503`)
  - Example: FastEmbed model cache missing or load failed.
- `embedding_generation_failed` (`500`)
  - Example: provider failed during embedding generation.
- `embedding_profile_mismatch` (`500`)
  - Example: returned embedding dimension does not match active profile.
- `embedding_readiness_timeout` (`503`)
  - Example: provider readiness check exceeded timeout.
- `reembedding_in_progress` (`409`)
  - Includes `details.job_id` and `details.status_path`.
- `reembedding_failed` (`503`)
  - Includes `details.job_id` and `details.status_path`.
- `internal_error` (`500`)
  - Unexpected server-side exception at request boundary.

Common failure examples:

Invalid JSON:

```json
{
  "error": {
    "code": "invalid_json",
    "message": "invalid JSON: Expecting property name enclosed in double quotes",
    "details": {}
  }
}
```

Missing workspace UID for workspace search:

```json
{
  "error": {
    "code": "validation_error",
    "message": "workspace_uid is required for workspace search",
    "details": {}
  }
}
```

Unsupported route/method:

```json
{
  "error": {
    "code": "unsupported_operation",
    "message": "unsupported operation",
    "details": {}
  }
}
```

## Workspace operations

### `GET /v1/workspaces`

Purpose: list distinct workspace UIDs visible through the API. With `include_aliases=true`, return workspace objects with nested alias arrays.

**Query parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `include_archived` | bool | `false` | Include UIDs that appear only on archived memories. |
| `include_aliases` | bool | `false` | Return objects shaped as `{workspace_uid, aliases}` instead of UID strings. |

**Response 200**

```json
{
  "data": ["generalist-ai", "recollectium"]
}
```

**Response 200 with aliases**

```json
{
  "data": [
    {"workspace_uid": "recollectium", "aliases": ["recollectium-core"]},
    {"workspace_uid": "generalist-ai", "aliases": []}
  ]
}
```

### `GET /v1/workspaces/resolve`

Purpose: normalize a workspace UID candidate and resolve it to the canonical UID if it is an alias.

Example request:

```bash
curl -sS 'http://127.0.0.1:8765/v1/workspaces/resolve?uid=Recollectium%20Core'
```

Example response:

```json
{
  "data": {
    "input_uid": "Recollectium Core",
    "normalized_uid": "recollectium-core",
    "canonical_uid": "recollectium",
    "resolved_by_alias": true
  }
}
```

### `GET /v1/workspaces/{uid}/aliases`

Purpose: list aliases for a canonical workspace UID. The `uid` path value is normalized and resolved before filtering.

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/workspaces/recollectium/aliases
```

Example response:

```json
{
  "data": [
    {
      "alias_uid": "recollectium-core",
      "canonical_uid": "recollectium",
      "created_at": "2026-05-28T00:00:00Z",
      "updated_at": "2026-05-28T00:00:00Z"
    }
  ]
}
```

### `POST /v1/workspaces/{uid}/aliases`

Purpose: add an alias for a canonical workspace UID. Use `migrate_existing=true` to move existing alias-owned memories into the canonical workspace in the same transaction.

Example request:

```bash
curl -sS http://127.0.0.1:8765/v1/workspaces/recollectium/aliases \
  -H 'Content-Type: application/json' \
  -d '{"alias_uid":"recollectium-core","migrate_existing":false}'
```

Example response:

```json
{
  "data": {
    "alias": {
      "alias_uid": "recollectium-core",
      "canonical_uid": "recollectium",
      "created_at": "2026-05-28T00:00:00Z",
      "updated_at": "2026-05-28T00:00:00Z"
    },
    "migrated_memories": 0
  }
}
```

**Error 400 (existing memories under alias UID)**

```json
{
  "error": {
    "code": "validation_error",
    "message": "workspace alias conflicts with existing workspace memories: recollectium-core. Use --migrate-existing to move those memories to recollectium and keep recollectium-core as an alias.",
    "details": {}
  }
}
```

### `DELETE /v1/workspaces/aliases/{alias_uid}`

Purpose: remove an alias mapping by alias UID.

Example request:

```bash
curl -sS -X DELETE http://127.0.0.1:8765/v1/workspaces/aliases/recollectium-core
```

Example response:

```json
{
  "data": {
    "alias_uid": "recollectium-core",
    "canonical_uid": "recollectium",
    "created_at": "2026-05-28T00:00:00Z",
    "updated_at": "2026-05-28T00:00:00Z"
  }
}
```

### `POST /v1/workspaces/{uid}/rename`

Rename a workspace. Migrates all workspace memories (including archived) from
the old UID to a new UID. Both UIDs are normalized according to the
`workspace.uid_normalization` config setting before the operation.

**Request body**

```json
{
  "new_uid": "recollectium"
}
```

**Response 200**

```json
{
  "data": {
    "old_uid": "recollectium-core",
    "new_uid": "recollectium",
    "memories_updated": 42,
    "aliases_updated": 3
  }
}
```

**Error 404 (workspace not found)**

```json
{
  "error": {
    "code": "not_found",
    "message": "no workspace memories found for uid: nonexistent",
    "details": {}
  }
}
```

**Error 400 (empty new_uid after normalization)**

```json
{
  "error": {
    "code": "validation_error",
    "message": "workspace UID normalizes to an empty string: '!!!'",
    "details": {}
  }
}
```

## Notes

- Only documented fields are supported.
- JSON body is required for `POST` and `PATCH` endpoints that accept request-body inputs (`POST /v1/memories/search_user`, `POST /v1/memories/search_workspace`, `POST /v1/memories`, and `PATCH /v1/memories/{memory_id}`).
- `POST /v1/memories/{memory_id}/archive` is body-less.
- This document is tied to the current implementation and should be updated with service contract changes.
