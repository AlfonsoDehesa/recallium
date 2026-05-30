"""Seed data helpers for the optional development memory database."""

from __future__ import annotations

from pathlib import Path

from recollectium.embeddings import EmbeddingProvider, chunk_text_for_profile
from recollectium.models import Memory, SPACE_USER, SPACE_WORKSPACE
from recollectium.storage import SQLiteMemoryStore

DEV_SEED_USER_MEMORY_COUNT = 100
DEV_SEED_WORKSPACE_COUNT = 3
DEV_SEED_WORKSPACE_MEMORY_COUNT = 30
DEV_SEED_TOPIC_COUNT = 10
DEV_SEED_TOTAL_WORKSPACE_MEMORIES = (
    DEV_SEED_WORKSPACE_COUNT * DEV_SEED_WORKSPACE_MEMORY_COUNT
)
DEV_SEED_TIMESTAMP = "2026-01-01T00:00:00Z"
DEV_SEED_TOPICS: tuple[str, ...] = (
    "local-first storage",
    "embedding quality",
    "workspace continuity",
    "configuration hygiene",
    "release readiness",
    "agent collaboration",
    "privacy boundaries",
    "search ranking",
    "documentation polish",
    "maintenance workflows",
)
DEV_SEED_WORKSPACES: tuple[str, ...] = (
    "dev-workspace-alpha",
    "dev-workspace-beta",
    "dev-workspace-gamma",
)
USER_MEMORY_TYPES: tuple[str, ...] = (
    "fact",
    "preference",
    "personal_fact",
    "social_context",
    "goal",
    "communication_style",
    "note",
)
WORKSPACE_MEMORY_TYPES: tuple[str, ...] = (
    "fact",
    "decision",
    "task_context",
    "configuration",
    "bug_finding",
    "note",
)


def _unlink_sqlite_files(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def _insert_seed_memory(
    store: SQLiteMemoryStore,
    provider: EmbeddingProvider,
    memory: Memory,
) -> None:
    chunks = chunk_text_for_profile(memory.content, provider.embedding_profile)
    chunk_embeddings = [(chunk, provider.embed(chunk.text)) for chunk in chunks]
    store.insert_memory(
        memory,
        chunk_embeddings[0][1],
        provider.embedding_profile,
    )
    store.replace_memory_chunks(
        memory_id=memory.id,
        embedding_profile=provider.embedding_profile,
        chunk_embeddings=chunk_embeddings,
    )


def _user_seed_memory(index: int) -> Memory:
    topic_index = index % DEV_SEED_TOPIC_COUNT
    topic = DEV_SEED_TOPICS[topic_index]
    ordinal = index + 1
    return Memory(
        id=f"dev-user-{ordinal:03d}",
        space=SPACE_USER,
        type=USER_MEMORY_TYPES[index % len(USER_MEMORY_TYPES)],
        content=(
            f"Dev user memory {ordinal:03d} about {topic}. "
            f"This seeded record gives embedding tests stable user-scope recall data "
            f"for topic bucket {topic_index + 1}."
        ),
        metadata={
            "dev_seed": True,
            "dev_topic": topic,
            "dev_topic_index": topic_index,
            "dev_ordinal": ordinal,
        },
        source="dev-seed",
        confidence=0.75,
        created_at=DEV_SEED_TIMESTAMP,
        updated_at=DEV_SEED_TIMESTAMP,
    )


def _workspace_seed_memory(workspace_index: int, memory_index: int) -> Memory:
    topic_index = (workspace_index + memory_index) % DEV_SEED_TOPIC_COUNT
    topic = DEV_SEED_TOPICS[topic_index]
    workspace_uid = DEV_SEED_WORKSPACES[workspace_index]
    ordinal = memory_index + 1
    return Memory(
        id=f"dev-workspace-{workspace_index + 1:02d}-{ordinal:03d}",
        space=SPACE_WORKSPACE,
        workspace_uid=workspace_uid,
        type=WORKSPACE_MEMORY_TYPES[memory_index % len(WORKSPACE_MEMORY_TYPES)],
        content=(
            f"Dev workspace memory {ordinal:03d} for {workspace_uid} about {topic}. "
            f"This seeded record gives embedding tests stable workspace-scope recall data."
        ),
        metadata={
            "dev_seed": True,
            "dev_topic": topic,
            "dev_topic_index": topic_index,
            "dev_workspace_index": workspace_index,
            "dev_ordinal": ordinal,
        },
        source="dev-seed",
        confidence=0.75,
        created_at=DEV_SEED_TIMESTAMP,
        updated_at=DEV_SEED_TIMESTAMP,
    )


def seeded_dev_database_is_initialized(db_path: Path | str) -> bool:
    """Return True when *db_path* already has the complete seeded dev fixture."""
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    store = SQLiteMemoryStore(db_path)
    user_memories = store.list_memories(space=SPACE_USER, include_archived=True)
    workspace_memories = store.list_memories(
        space=SPACE_WORKSPACE, include_archived=True
    )
    topics = {
        memory.metadata.get("dev_topic")
        for memory in user_memories
        if memory.metadata.get("dev_seed") is True
    }
    return (
        len(user_memories) == DEV_SEED_USER_MEMORY_COUNT
        and len(workspace_memories) == DEV_SEED_TOTAL_WORKSPACE_MEMORIES
        and len(store.list_workspace_uids(include_archived=True))
        == DEV_SEED_WORKSPACE_COUNT
        and len(topics) == DEV_SEED_TOPIC_COUNT
        and all(memory.metadata.get("dev_seed") is True for memory in user_memories)
        and all(
            memory.metadata.get("dev_seed") is True for memory in workspace_memories
        )
    )


def reset_seeded_dev_database(
    db_path: Path | str,
    embedding_provider: EmbeddingProvider,
) -> dict[str, object]:
    """Replace *db_path* with the canonical seeded development database."""
    resolved_db_path = Path(db_path).expanduser()
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    _unlink_sqlite_files(resolved_db_path)
    store = SQLiteMemoryStore(resolved_db_path)

    for index in range(DEV_SEED_USER_MEMORY_COUNT):
        _insert_seed_memory(store, embedding_provider, _user_seed_memory(index))

    for workspace_index in range(DEV_SEED_WORKSPACE_COUNT):
        for memory_index in range(DEV_SEED_WORKSPACE_MEMORY_COUNT):
            _insert_seed_memory(
                store,
                embedding_provider,
                _workspace_seed_memory(workspace_index, memory_index),
            )

    return {
        "status": "reset",
        "database": str(resolved_db_path),
        "user_memories": DEV_SEED_USER_MEMORY_COUNT,
        "workspace_memories": DEV_SEED_TOTAL_WORKSPACE_MEMORIES,
        "workspaces": DEV_SEED_WORKSPACE_COUNT,
        "topics": DEV_SEED_TOPIC_COUNT,
    }


def ensure_seeded_dev_database(
    db_path: Path | str,
    embedding_provider: EmbeddingProvider,
) -> dict[str, object] | None:
    """Create the seeded development database when it is missing or incomplete."""
    if seeded_dev_database_is_initialized(db_path):
        return None
    return reset_seeded_dev_database(db_path, embedding_provider)
