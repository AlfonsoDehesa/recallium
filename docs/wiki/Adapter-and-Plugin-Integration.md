# Adapter and Plugin Integration

This page gives the practical integration path for adapters and plugins. The canonical contract remains in the repo at [docs/opencode-adapter-contract.md](https://github.com/AlfonsoDehesa/Recollectium/blob/main/docs/opencode-adapter-contract.md).

## Adapter responsibilities

Adapters should:

- Discover or configure the Recollectium Core endpoint.
- Validate health, version, and capabilities before enabling tools.
- Choose workspace UID candidates from where work is actually happening.
- Pass memory operations to Core instead of owning durable memory state.
- Keep host-specific details out of Core.

Adapters should not:

- Reimplement storage, embeddings, search, migrations, or workspace alias behavior.
- Invent a second memory taxonomy.
- Treat health/version/capability checks as authentication.
- Expose Core publicly without external protection.

## Local autodiscovery

For same-machine integrations, use:

```bash
recollectium service discover
```

If discovery reports `not_running`, a local adapter may try:

```bash
recollectium service start api
```

Then rerun discovery and validate the service.

## Remote or split-machine Core

For private-network Core deployments, the user should configure an explicit base URL. The adapter should derive `/v1/health`, `/v1/version`, and `/v1/capabilities` from that base URL and validate them before enabling tools.

Do not run local discovery for explicitly remote Core configuration.

## Compatibility validation

Before enabling tools, adapters should call:

1. Health.
2. Version.
3. Capabilities.

They should confirm the API version and required capability names for the operations they expose.

## Workspace UID selection

The adapter or agent layer chooses the workspace UID candidate. Core normalizes and resolves it.

Recommended UID candidate order:

1. Git repository name when the work is inside a git repo.
2. Selected project or workspace folder name outside git.
3. Containing workspace folder name when that is the stable project boundary.

Do not use temporary agent directories, sandbox paths, or adapter process directories when those differ from the project under work.

## Memory operations

Adapters should map host actions to Core operations:

- Search user memory for user-wide preferences and facts.
- Search workspace memory for project-specific context.
- Add memory when the user or agent has a durable fact, preference, decision, task context, configuration, or bug finding worth keeping.
- Update or archive memory when old information becomes stale.

## Security warning

Remote Core access still has no built-in authentication in v1. Private networking and external controls are required.
