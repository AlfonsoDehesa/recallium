# API Reference

## What the API is for

The local HTTP API is for adapters, plugins, and local tools that need a stable machine-readable contract to Recollectium Core. Use it when the caller should discover a running Core service, validate compatibility, and perform memory operations without using the CLI process for every call.

For the canonical contract, see the repo docs:

- [Local service API](https://github.com/AlfonsoDehesa/Recollectium/blob/main/docs/local-service-api.md)
- [OpenAPI JSON](https://github.com/AlfonsoDehesa/Recollectium/blob/main/docs/local-service-openapi.json)

## Base URL

Default local endpoint:

```text
http://127.0.0.1:8765
```

API prefix:

```text
/v1
```

## Service endpoints

- `GET /v1/health`
- `GET /v1/version`
- `GET /v1/capabilities`

Use these before enabling adapter tools.

## Memory endpoints

- `POST /v1/memories/search_user`
- `POST /v1/memories/search_workspace`
- `POST /v1/memories`
- `GET /v1/memories`
- `GET /v1/memories/{memory_id}`
- `PATCH /v1/memories/{memory_id}`
- `POST /v1/memories/{memory_id}/archive`

## Embedding endpoints

- `GET /v1/embedding/status`
- `GET /v1/embedding/jobs`
- `GET /v1/embedding/jobs/{job_id}`

## Workspace endpoints

- `GET /v1/workspaces`
- `GET /v1/workspaces/resolve?uid=...`
- `GET /v1/workspaces/{uid}/aliases`
- `POST /v1/workspaces/{uid}/aliases`
- `DELETE /v1/workspaces/aliases/{alias_uid}`
- `POST /v1/workspaces/{uid}/rename`

## Response envelope

Success responses usually return:

```json
{"data": {}}
```

Errors return:

```json
{
  "error": {
    "code": "validation_error",
    "message": "request validation failed",
    "details": {}
  }
}
```

## Example: health

```bash
curl http://127.0.0.1:8765/v1/health
```

## Example: add memory

```bash
curl -X POST http://127.0.0.1:8765/v1/memories   -H 'Content-Type: application/json'   -d '{"space":"user","type":"preference","content":"I prefer concise answers."}'
```

## Security reminder

The v1 API has no built-in authentication. Keep it bound to localhost unless private networking and external access controls protect it.
