# OpenCode adapter contract for Recallium

This document describes the contract between Recallium Core and a future
OpenCode adapter or plugin.

Recallium Core already exposes the local service, workspace memory operations,
and workspace UID normalization contract that an adapter needs. The adapter's
job is to bridge OpenCode's workspace context and agent tool surface to
Recallium's local service, not to reimplement memory logic inside OpenCode.

## What the adapter must do

A Recallium adapter should:

- Discover the running local Recallium service automatically for same-machine
  deployments where practical.
- Allow explicit remote Core endpoint or base-URL configuration in plugin config
  for deployments where the adapter and Recallium are not on the same machine.
- Validate that the target service is healthy and compatible before use, whether
  it was found by local discovery or supplied through explicit configuration.
- Instruct the model at prompt level to choose the workspace UID candidate for
  the current task from the project it is actively working in.
- Prefer the base folder name of the whole project, not a full filesystem path
  and not the adapter, agent, or sandbox directory if that is different from the
  project being changed.
- If the selected project lives inside a git-managed tree, prefer the git
  repository name from the repository root as the canonical workspace UID
  candidate. Nested subfolders inherit that same project UID candidate.
- If there is no git-managed tree, use the selected project's base folder name
  or the base folder name of the containing project workspace.
- Pass the UID candidate to Recallium Core and let Core apply its configured
  workspace UID normalization at the storage boundary.
- Expose user-memory and workspace-memory operations as separate tools.
- Treat Recallium Core as the source of truth for memory storage and search.

## Service discovery contract

For same-machine workflows, use the machine-readable discovery command rather
than hardcoding host, port, or service paths:

```bash
recallium service discover
```

Local discovery is the first step for same-machine adapter workflows. For
same-machine installs, discovery should be automatic and the adapter should not
require the user to enter host, port, PID file, runtime path, or service type
manually.

For deployments where the adapter talks to Recallium Core on another machine,
the user should configure an explicit endpoint, such as a host, IP, port, or
base URL. In that mode, the adapter does not need local discovery metadata. It
should derive the API URLs from the configured base URL, then run the same
health, version, and capability validation described below.

Discovery returns JSON that includes:

- service type
- process ID
- endpoint
- API prefix
- health URL
- version URL
- capabilities URL
- Recallium version
- service API version
- config path
- runtime directory
- PID file path
- discovery file path

Adapter behavior:

- If discovery reports a running service, use the returned URLs directly.
- If discovery reports `not_running` and the plugin is configured for local
  autodiscovery, attempt to start the local API service with
  `recallium service start api`, then run discovery again.
- If the start attempt fails, or if local autodiscovery is disabled, guide the
  user to start the API service or configure the remote Core endpoint.
- If discovery reports invalid or stale metadata, treat that as a local recovery
  problem and surface the error clearly.

## Validation contract

Before enabling Recallium-backed tools, the adapter should validate the target
service in this order:

1. Resolve the endpoint:
   - For same-machine use, run `recallium service discover` and use the returned
     `health_url`, `version_url`, and `capabilities_url`.
   - For remote or hosted Core use, read the explicit plugin configuration and
     derive `/v1/health`, `/v1/version`, and `/v1/capabilities` from the
     configured base URL.
2. Call the health endpoint and require an ok response.
3. Call the version endpoint and verify the service API version is compatible.
4. Call the capabilities endpoint and verify the capabilities needed by the
   adapter are present.

The current service contract exposes these core capabilities:

- `health.read`
- `version.read`
- `capabilities.read`
- `memories.search_user`
- `memories.search_workspace`
- `memories.add`
- `memories.update`
- `memories.archive`
- `memories.list`
- `memories.get`
- `embedding.status`
- `embedding.jobs.list`
- `embedding.jobs.get`
- `workspaces.list`
- `workspaces.rename`

The adapter should treat capability names as the compatibility check, not the
transport details.

## Workspace UID contract

Workspace memories are keyed by a stable workspace UID. The adapter must not
use a filesystem path as the canonical key or invent a separate workspace
registry.

Recommended adapter behavior:

- Treat workspace UID selection as model-handled behavior. The adapter should
  inject prompt guidance that tells the model how to choose the UID candidate
  for the project it is currently working in and making changes to.
- The UID candidate should be the base folder name of that project, not the full
  path.
- The UID candidate should come from the project under work, not from the agent
  runtime, adapter package, sandbox, temporary checkout, or tool execution
  directory when those differ from the actual project.
- If the current project or active subfolder is inside a git-managed tree,
  prefer the git repository name from the repository root as the canonical UID
  candidate. Work done inside nested subfolders of the same repo should use that
  same repo-name candidate.
- If there is no git-managed tree, use the base folder name of the selected
  project workspace or, when the model is working inside a subfolder, the base
  folder name of the containing project workspace.
- The adapter may maintain prompt-injected workspace UID hints or defaults, for
  example values selected through plugin commands. If a hint is clearly close
  enough to the active project, the model should prefer that hint. Otherwise it
  should fall back to the folder/git rules above.
- Pass the selected UID candidate into Recallium workspace memory operations.
  Recallium Core normalizes workspace UIDs at the storage boundary according to
  `workspace.uid_normalization`; the plugin does not need to pre-normalize the
  value to match Core behavior.

If the adapter maintains workspace metadata in a repo-local file, that file is
an adapter concern, not a Core requirement. Recallium Core does not require any
specific file format, registry, or git-based identity. The only contract is
that the adapter prompts for and passes the model-selected UID candidate before
calling Core.

The adapter should preserve the distinction between:

- workspace identity, which is a stable UID
- workspace location hints, which may be useful metadata but are not the key
- transport settings such as host, IP, or base URL, which are separate from the
  workspace identity and only matter for remote deployments

## Memory operation contract

Expose separate tools or actions for:

- user memory search
- workspace memory search
- add memory
- update memory
- archive memory
- list memories
- get memory by ID
- list workspace UIDs
- rename workspace UID

Workspace operations should require a workspace UID when the underlying Core
operation does.

User memory operations must remain scope-separated from workspace memory
operations.

## Error handling contract

The adapter should surface service problems clearly:

- local service not running
- configured remote endpoint unreachable
- incompatible service API version
- missing capability
- missing or invalid workspace UID
- stale local discovery metadata

When the service is unavailable, the adapter should fail with a message that
helps the user start or rediscover a local service, or correct the configured
remote Core endpoint, instead of silently falling back or inventing a workspace
identity.

## Recommended workflow

1. Install Recallium Core.
2. Start the local service or configure the plugin with the remote Core base URL.
3. For same-machine use, run `recallium service discover`. If the plugin is set
   to local autodiscovery and discovery reports `not_running`, attempt
   `recallium service start api` and then rerun discovery. For remote Core use,
   read the explicit plugin endpoint.
4. Validate health, version, and capabilities against the resolved endpoint.
5. Prompt the model to select the active workspace UID candidate from the
   project it is currently working in: use the project base folder name, prefer
   the git repository root name when inside a git-managed tree, avoid sandbox or
   adapter runtime directories, and only prefer prompt-injected plugin defaults
   when they clearly match the active project.
6. Pass the selected UID candidate to Core and call the memory endpoints needed
   for the user task. Core applies workspace UID normalization.

## Documentation expectations

When this contract changes, update the corresponding Core docs in the same PR:

- `README.md`
- `docs/local-service-api.md`
- `ROADMAP.md`
- `CONTRIBUTING.md` if the maintenance gate changes

This document should stay aligned with the live Core service contract and the
roadmap item's completion status.
