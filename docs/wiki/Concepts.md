# Concepts

## Core

Recollectium Core is the memory engine. It owns storage, embeddings, migrations, search, APIs, MCP tools, service discovery, logging, and lifecycle behavior.

Adapters and plugins should stay thin. They provide host context, choose workspace UID candidates, and call Core.

## User memory

User memory is global to the person using the agent. It is good for durable preferences, personal facts, communication style, goals, and other information that should follow the user across projects.

User buckets:

- `fact`
- `preference`
- `personal_fact`
- `social_context`
- `goal`
- `communication_style`
- `note`

## Workspace memory

Workspace memory is scoped to a project, repo, task area, or other durable work context. It is good for project facts, design decisions, task context, configuration, and bug findings.

Workspace buckets:

- `fact`
- `decision`
- `task_context`
- `configuration`
- `bug_finding`
- `note`

## Recording vs recall

Choose a bucket when recording memory. Search by scope first when recalling memory.

In practice:

- Use `search-user` when the question is about the user.
- Use `search-workspace` when the question is about a project or workspace.
- Do not over-filter by type unless the intent is narrow.

## Workspace UIDs

Workspace memories require `--workspace-uid`.

Core receives a workspace UID candidate, normalizes it according to config, resolves aliases, and stores or searches against the canonical UID.

Adapters should choose the UID from where the work is actually happening. In a git repo, the repo name is usually the right candidate. Outside git, use the project or workspace folder name.

## Aliases and renames

Aliases let old workspace names point at a canonical workspace. Renames migrate workspace memories to a new UID.

```bash
recollectium workspace resolve recollectium-core
recollectium workspace alias add recollectium recollectium-core --migrate-existing
recollectium workspace rename old-project new-project
```

## Embeddings

Recollectium uses local FastEmbed embeddings with `jinaai/jina-embeddings-v2-small-en`.

First initialization downloads the model cache. Searches and memory writes use the local model after that.

Inspect embedding state:

```bash
recollectium embedding-status
recollectium embedding-jobs
```
