# FAQ

## Is Recollectium cloud-hosted?

No. Recollectium Core is local-first. Data lives in a local SQLite database unless you deliberately place that database somewhere else.

## Does Recollectium encrypt the database?

No. Use host-level protections if required, such as OS account permissions, encrypted home directories, encrypted volumes, full-disk encryption, and protected backups.

## Does the API have authentication?

No. The v1 API and MCP services are unauthenticated and localhost-first. Do not expose them publicly.

## Which embedding model does it use?

The built-in local profile currently uses `jinaai/jina-embeddings-v2-small-en` through FastEmbed.

Other models are planned for future releases. The current v1 contract focuses on one reliable built-in local profile so installation, search, and re-embedding behavior are predictable.

## Should agents search by type first?

Usually no. Search by scope first: user or workspace.

Recollectium uses embedding-based semantic search, so it returns memories that are closest in meaning to the query. In many cases, `type` is already implied by the words in the query. For example, searching user memory for "preferences about wording" will naturally pull preference-like memories even without `--type preference`.

If the result set is too broad, narrow by type. Type filters are useful when the agent knows it only wants a specific bucket, such as `decision`, `configuration`, or `bug_finding`.

## What is the difference between `serve` and `service start api`?

`recollectium serve` runs the local HTTP API in the foreground. It is useful for development, debugging, and seeing logs directly in the terminal.

`recollectium service start api` starts a managed background API service, writes PID and discovery metadata, and is the recommended path for adapters and plugins.

## Can I run Core on one machine and an agent on another?

Yes, but treat it as an advanced setup. The API and MCP services are unauthenticated in v1. Use private networking and external access controls, such as Tailscale, WireGuard, SSH tunnels, or firewall allowlists.

## Is the OpenCode plugin available?

The OpenCode adapter is planned after the v1 Core release. The Core service, CLI, API, MCP tools, workspace UID rules, and plugin contract are being prepared first.
