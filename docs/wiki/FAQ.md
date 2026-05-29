# FAQ

## Is Recollectium cloud-hosted?

No. Recollectium Core is local-first. Data lives in a local SQLite database.

## Does Recollectium encrypt the database?

No. Use host-level protections such as OS account permissions, encrypted home directories, encrypted volumes, full-disk encryption, and protected backups.

## Does the API have authentication?

No. The v1 API and MCP services are unauthenticated and localhost-first. Do not expose them publicly.

## Which embedding model does it use?

The built-in local profile is `jinaai/jina-embeddings-v2-small-en` through FastEmbed.

## Should agents search by type first?

Usually no. Search by scope first: user or workspace. Use a type filter only when the query is deliberately narrow.

## What is the difference between `serve` and `service start api`?

`recollectium serve` runs the API in the foreground for development and debugging. `recollectium service start api` starts a managed service with discovery metadata for adapters.

## Can I run Core on one machine and an agent on another?

Yes, but only over private networking with external access controls. The v1 service has no built-in authentication.

## Is the OpenCode plugin available?

Not yet. Recollectium Core is preparing for v1. The OpenCode adapter contract is documented, and plugin implementation is planned after v1.
