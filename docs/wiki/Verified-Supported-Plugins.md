# Verified Supported Plugins

## Current status

Recollectium Core is in final v1.0 release preparation. Core is implemented. OpenCode plugin implementation is planned after v1.

## Verified today

| Integration | Status | Notes |
|---|---|---|
| CLI | Supported | Primary user and development interface. |
| Python API | Supported | Direct in-process Core usage. |
| Local HTTP API | Supported | For adapters and local tools. |
| MCP stdio | Supported | For MCP clients that spawn Recollectium. |
| Managed MCP service | Supported | Local HTTP/SSE service, localhost-first. |
| OpenCode plugin | Planned | Contract is documented, implementation planned after v1. |

## Compatibility rule

Plugins and adapters should validate health, version, and capabilities before enabling tools.

## Want to add a plugin?

Start with [Adapter and Plugin Integration](Adapter-and-Plugin-Integration.md) and the canonical [OpenCode adapter contract](https://github.com/AlfonsoDehesa/Recollectium/blob/main/docs/opencode-adapter-contract.md).
