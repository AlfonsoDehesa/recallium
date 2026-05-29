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

Embeddings are what make semantic search work. When you add or update memory content, Recollectium turns that text into a local vector representation and stores it with the memory. Later, searches compare the query embedding to stored memory embeddings and return the closest matches by meaning.

First initialization downloads the model cache. Searches and memory writes use the local model after that.

### Embedding migration and re-embedding

Embedding profiles can change over time. A future release may support additional models, dimensions, chunking rules, or provider profiles. When Recollectium detects memories whose stored embeddings do not match the active embedding profile, it can schedule re-embedding work so old memories become searchable with the current profile.

This is why embedding status and embedding jobs exist:

- `embedding-status` shows the active provider, model, dimensions, profile metadata, runtime status, and recent jobs.
- `embedding-jobs` lists background work that prepares or refreshes embeddings.
- A job can be `pending`, `in_progress`, `completed`, or `failed`.
- If re-embedding is still running or failed, API calls may report structured embedding errors with a job ID and status path.

Inspect embedding state:

```bash
recollectium embedding-status
recollectium embedding-jobs
recollectium embedding-jobs --state failed
recollectium embedding-jobs --job-id JOB_ID
```

For normal users, this usually only matters during first install, after an upgrade, or when troubleshooting search quality. For adapter authors, these commands and the matching API endpoints are the compatibility and readiness checks for semantic memory.
