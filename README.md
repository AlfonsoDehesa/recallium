# Recallium Core MVP

Recallium Core is a local-first Python memory engine for agents.

This MVP provides:

- Local SQLite storage for memories.
- Explicit user and workspace memory scopes.
- Create, search, list, retrieve, update, and archive operations.
- A JSON CLI and Python API for local development.

## Current boundaries (what this repo does not include yet)

This MVP does not include:

- OpenCode adapter integration.
- Historian summaries.
- Dreamer workflows.
- A long-running service or daemon.
- Cloud sync, multi-user support, or UI.

## Local-first behavior

- Recallium Core runs fully local.
- No network calls are required for memory operations.
- Data is stored in a local SQLite file.

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

## Semantic search limitation in this MVP

Semantic search is deterministic and local, based on lightweight token normalization and hashing for testable behavior. It is useful for MVP validation, but it is not a production-grade embedding model.
