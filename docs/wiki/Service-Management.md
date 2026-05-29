# Service Management

Recollectium can run as a managed service for adapters and clients, or as a foreground process for development.

## Service types

- `api`: local HTTP JSON API with memory, workspace, embedding, health, version, and capability operations.
- `mcp`: MCP HTTP server using SSE transport.

Only one managed service runs at a time.

## Start

```bash
recollectium service start api
recollectium service start mcp
```

Example success output:

```json
{"endpoint":"http://127.0.0.1:8765","pid":12345,"status":"started","type":"api"}
```

## Status

```bash
recollectium service status
```

Running:

```json
{"endpoint":"http://127.0.0.1:8765","pid":12345,"running":true,"type":"api"}
```

Not running:

```json
{"running":false}
```

## Discovery

```bash
recollectium service discover
```

Adapters should use discovery instead of hardcoding PID files, runtime paths, host, port, or service type.

When a managed service is running, discovery returns service type, endpoint, API prefix, health URL, version URL, capabilities URL, PID path, discovery file path, runtime directory, config path, and version information.

When no service is running, discovery exits 1 and prints machine-readable `status: "not_running"` JSON to stdout.

## Stop

```bash
recollectium service stop
```

Recollectium sends SIGTERM and waits for graceful exit. If needed, it falls back to SIGKILL.

## Restart

```bash
recollectium service restart
recollectium service restart --type api
recollectium service restart --type mcp
```

Use `--type` when no running service or stale PID metadata can identify the previous type.

## Foreground serve mode

```bash
recollectium serve --host 127.0.0.1 --port 8765
```

`serve` is useful for development and debugging. It blocks until interrupted.

## Runtime files

The service manager writes runtime metadata under the configured runtime directory. It includes a PID file and `service-discovery.json`.

Service stdout and stderr go to service logs in the logs directory. See [Logs](Logs.md).

## Security reminder

The v1 API and MCP services are unauthenticated. Keep them bound to localhost unless private networking and access controls protect the endpoint.
