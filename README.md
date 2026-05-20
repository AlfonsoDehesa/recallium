# Recallium Core MVP

Recallium Core is a local-first Python memory engine for agents.

This MVP provides:

- Local SQLite storage for memories.
- Explicit user and workspace memory scopes.
- Create, search, list, retrieve, update, and archive operations.
- A JSON CLI and Python API for local development.
- Smart local embeddings with built-in FastEmbed using `jinaai/jina-embeddings-v2-small-en`.

## Current boundaries (what this repo does not include yet)

This MVP does not include:

- OpenCode adapter integration.
- Historian summaries.
- Dreamer workflows.
- A long-running service or daemon.
- Cloud sync, multi-user support, or UI.

## Local-first behavior

- Recallium Core runs fully local.
- First-time model cache download may require network access to fetch `jinaai/jina-embeddings-v2-small-en`.
- Data is stored in a local SQLite file.

## Smart embedding behavior

- Recallium uses one production embedding path: built-in local FastEmbed.
- Active profile: `provider=builtin-fastembed`, `model=jinaai/jina-embeddings-v2-small-en`.
- Long memory content is chunked per model profile before embedding.
- On startup and during search, stale profile embeddings are refreshed and tracked as embedding jobs.
- Use CLI and local service status endpoints to inspect profile state and job progress.

## Install for development

Recallium Core requires Python 3.14 or newer. Use `uv` for environment and dependency management.

```bash
uv sync --group dev
```

Run the full local quality gate:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

Run the CLI through the managed environment:

```bash
uv run recallium --help
```

## Data path behavior

- Default database path: `~/.local/share/recallium/recallium.db`
- Override database path in CLI: `recallium --db /tmp/recallium.db ...`
- Override database path in Python: `RecalliumCore(db_path="/tmp/recallium.db")`

## CLI examples

Add a user memory:

```bash
recallium --db /tmp/recallium.db add \
  --space user \
  --type preference \
  --content "I prefer concise technical answers."
```

Search user memories:

```bash
recallium --db /tmp/recallium.db search-user "concise answers"
```

Add a workspace memory:

```bash
recallium --db /tmp/recallium.db add \
  --space workspace \
  --workspace-uid 7f3b0a5e-example-workspace \
  --type decision \
  --content "Use SQLite for local memory persistence."
```

Search workspace memories:

```bash
recallium --db /tmp/recallium.db search-workspace \
  "local persistence" \
  --workspace-uid 7f3b0a5e-example-workspace
```

Workspace memories are keyed by a stable workspace UID. Future adapters, such as
the OpenCode plugin, should create and pass that UID rather than using filesystem
paths as workspace identity.

All successful CLI commands return JSON.

Check embedding profile status:

```bash
recallium --db /tmp/recallium.db embedding-status
```

List embedding jobs:

```bash
recallium --db /tmp/recallium.db embedding-jobs
```

Get one embedding job:

```bash
recallium --db /tmp/recallium.db embedding-jobs --job-id <job-id>
```

## Python API examples

```python
from recallium import RecalliumCore

core = RecalliumCore(db_path="/tmp/recallium.db")

created = core.add_memory(
    space="user",
    type="preference",
    content="I prefer concise technical answers.",
)

results = core.search_user_memories("concise answers", limit=5)

print(created.id)
print(results[0].score if results else None)
```

## Local service status routes

- `GET /v1/embedding/status`
- `GET /v1/embedding/jobs`
- `GET /v1/embedding/jobs/{job_id}`
