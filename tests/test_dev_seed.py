from __future__ import annotations

from pathlib import Path

from recollectium.dev_seed import (
    ensure_seeded_dev_database,
    reset_seeded_dev_database,
    seeded_dev_database_is_initialized,
)
from recollectium.core import RecollectiumCore
from recollectium.storage import SQLiteMemoryStore


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.embedding_profile = {
            "provider": "fake",
            "model": "fake-model",
            "dimensions": 3,
            "version": "1",
            "profile": "fake-profile-v1",
            "max_tokens": 16,
            "chunk_tokens": 128,
            "chunk_overlap_tokens": 0,
            "query_prompt_policy": "raw",
        }

    def embed(self, text: str) -> list[float]:
        size = float(len(text))
        first = float(ord(text[0])) if text else 0.0
        return [size, first, 1.0]

    def similarity(self, first: list[float], second: list[float]) -> float:
        return sum(a * b for a, b in zip(first, second, strict=True))


def test_reset_seeded_dev_database_recreates_seed_state(tmp_path: Path) -> None:
    db_path = tmp_path / "dev.db"
    provider = FakeEmbeddingProvider()

    result = reset_seeded_dev_database(db_path, provider)

    store = SQLiteMemoryStore(db_path)
    user_memories = store.list_memories(space="user", include_archived=True)
    workspace_memories = store.list_memories(space="workspace", include_archived=True)
    workspaces = store.list_workspace_uids(include_archived=True)
    topics = {memory.metadata["dev_topic"] for memory in user_memories}

    assert result == {
        "status": "reset",
        "database": str(db_path),
        "user_memories": 100,
        "workspace_memories": 90,
        "workspaces": 3,
        "topics": 10,
    }
    assert len(user_memories) == 100
    assert len(workspace_memories) == 90
    assert len(workspaces) == 3
    assert len(topics) == 10
    assert seeded_dev_database_is_initialized(db_path)


def test_seeded_dev_database_is_reinitialized_after_mutation(tmp_path: Path) -> None:
    db_path = tmp_path / "dev.db"
    provider = FakeEmbeddingProvider()
    reset_seeded_dev_database(db_path, provider)
    store = SQLiteMemoryStore(db_path)
    first = store.list_memories(space="user", limit=1)[0]
    store.archive_memory(first.id)

    result = reset_seeded_dev_database(db_path, provider)

    store = SQLiteMemoryStore(db_path)
    assert result["status"] == "reset"
    assert len(store.list_memories(space="user", include_archived=True)) == 100
    assert len(store.list_memories(space="user")) == 100


def test_seeded_dev_database_ensure_skips_complete_seed_state(tmp_path: Path) -> None:
    db_path = tmp_path / "dev.db"
    provider = FakeEmbeddingProvider()
    reset_seeded_dev_database(db_path, provider)

    result = ensure_seeded_dev_database(db_path, provider)

    assert result is None


def test_core_uses_seeded_dev_database_when_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    regular_db = tmp_path / "regular.db"
    dev_db = tmp_path / "dev.db"
    config_path.write_text(
        "{"
        f'"database": {{"path": "{regular_db}"}}, '
        f'"development": {{"use_seeded_database": true, "seeded_database_path": "{dev_db}"}}'
        "}",
        encoding="utf-8",
    )

    core = RecollectiumCore(
        config_path=config_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert core.store.db_path == dev_db
    assert dev_db.exists()
    assert not regular_db.exists()
    assert len(core.list_memories(space="user", include_archived=True)) == 100
