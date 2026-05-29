# Security Policy

## Short version

Recollectium v1 is local-first software. It is designed for agents and clients running on the same machine as Recollectium Core.

Do not expose Recollectium directly to the public internet.

In v1, Recollectium services are not hardened as public network services:

- The API service has no built-in authentication.
- The MCP service has no built-in authentication.
- Recollectium does not provide API keys, user accounts, ACLs, or built-in TLS termination in v1.
- Health, version, and capability checks confirm service compatibility. They are not authentication or authorization controls.
- The SQLite memory database is not encrypted by Recollectium.

## Supported security model for v1

The recommended deployment is simple:

1. Run Recollectium on the same machine as the agent or client.
2. Keep services bound to localhost, usually `127.0.0.1`.
3. Use local service discovery for same-machine adapters.
4. Protect config, logs, cache, runtime files, and the memory database with normal operating-system account protections.

The default local service endpoint is:

```text
http://127.0.0.1:8765
```

Under ordinary host networking rules, this default keeps the service reachable only from the local machine.

## Running services safely

Recollectium can run managed API and MCP services:

```bash
recollectium service start api
recollectium service start mcp
```

It can also run the API service in the foreground for development and debugging:

```bash
recollectium serve --host 127.0.0.1 --port 8765
```

Keep API and MCP services bound to `127.0.0.1` unless you are deliberately running Recollectium over a private network with external access controls.

Binding to a non-local interface, such as `0.0.0.0`, a LAN address, a VPN address, a container bridge, or a public interface, can expose unauthenticated memory operations to anyone who can reach that interface.

## What a reachable client can do

Any user, process, or network client with sufficient access to the Recollectium data directory, database file, or unauthenticated service endpoint can read, modify, or delete memories.

That matters because memories influence what agents recall. Unauthorized memory changes can also influence agent behavior.

Treat access to Recollectium as access to a sensitive local application database.

## Local filesystem and database protection

Recollectium stores memory data in SQLite. The database is not encrypted by Recollectium.

Protect these paths like other sensitive local application data:

- The Recollectium config directory.
- The Recollectium data directory.
- The SQLite database file.
- The model cache directory.
- The logs directory.
- The runtime directory and service discovery files.
- Any backups that include Recollectium data.

Host-level protections remain the user's responsibility, including:

- Operating-system account permissions.
- Encrypted home directories.
- Full-disk encryption.
- Encrypted volumes.
- Backup access controls.
- Endpoint security.

## Recommended deployment patterns

Recommended for v1:

- Same-machine agent plus Recollectium Core.
- Services bound to `127.0.0.1`.
- Local service discovery for same-machine adapters.
- Standard OS permissions protecting the database and config directories.
- Private-network access only when split-machine deployment is truly needed.

If the agent and Recollectium must run on different machines, expose Recollectium only over private networking with external access controls.

For most users who need split-machine access, Tailscale is the friendliest path. Equivalent private-network approaches can also work, including WireGuard, SSH tunneling, firewall allowlists, or other VPN/overlay networking.

## Risky or unsupported deployment patterns

Avoid these v1 deployment patterns unless you have added external protections and understand the risk:

- Binding Recollectium to `0.0.0.0` on an untrusted network.
- Exposing Recollectium on a public IP address.
- Publishing Recollectium through a public reverse proxy.
- Tunneling Recollectium through a public tunnel without restricting who can connect.
- Assuming Docker, container networking, or a VM boundary alone makes an unauthenticated service safe.

Public reverse-proxy exposure is unsupported for v1 unless an advanced user fully supplies and owns external authentication, TLS, and access controls.

Direct public exposure is unsupported for v1.

## If you must connect from another machine

Use a private network path and restrict which clients can reach Recollectium:

1. Prefer a private overlay network such as Tailscale for split-machine access.
2. Keep Recollectium bound to a private or localhost-only interface where practical.
3. Restrict access with ACLs, firewall rules, SSH tunnel configuration, or equivalent controls.
4. Validate the Recollectium service with health, version, and capability checks before enabling tools.
5. Remember that compatibility validation is not authentication. It does not protect the endpoint from other clients that can reach it.

For remote or split-machine adapter setups, configure the adapter to reach the private Core endpoint explicitly, then validate health, version, and capabilities before enabling Recollectium tools.

## Vulnerability reporting

Please do not publish sensitive vulnerability details in a public GitHub issue.

Use GitHub private vulnerability reporting for this repository if it is enabled. If private vulnerability reporting is unavailable, open a public GitHub issue that asks for a private reporting channel but does not include vulnerability details, proof-of-concept code, private data, or exploit steps.

When reporting, include enough context for maintainers to reproduce and assess the issue safely:

- Affected Recollectium version.
- Affected command, endpoint, MCP mode, installer, or integration path.
- Operating system and deployment shape.
- Whether the service was bound to localhost, a private interface, or a public interface.
- A high-level impact description that does not expose private data.
