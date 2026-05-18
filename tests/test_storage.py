from pathlib import Path

import pytest

from recallium.errors import NotFoundError
from recallium.models import SPACE_USER, SPACE_WORKSPACE, STATUS_ACTIVE, STATUS_ARCHIVED, Memory
from recallium.storage import SQLiteMemoryStore


def build_memory(memory_id: str, **overrides: object) -> Memory:
    payload = {
        "id": memory_id,
        "space": SPACE_USER,
        "type": "fact",
        "content": "Kaylee likes black coffee",
        "status": STATUS_ACTIVE,
        "metadata": {"source": "chat"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return Memory(**payload)


def test_store_creates_parent_directories_and_persists_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "db" / "recallium.db"
    store = SQLiteMemoryStore(db_path)
    memory = build_memory("mem-1")

    store.insert_memory(memory, embedding=[0.1, 0.2])

    other_store = SQLiteMemoryStore(db_path)
    loaded = other_store.get_memory("mem-1")
    assert loaded == memory


def test_store_uses_schema_version_1(tmp_path: Path) -> None:
    db_path = tmp_path / "schema.db"
    SQLiteMemoryStore(db_path)

    import sqlite3

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()

    assert row is not None
    assert row[0] == 1


def test_get_update_archive_raise_not_found_for_missing_ids(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "missing.db")

    with pytest.raises(NotFoundError):
        store.get_memory("missing")

    with pytest.raises(NotFoundError):
        store.update_memory("missing", content="new")

    with pytest.raises(NotFoundError):
        store.archive_memory("missing")


def test_update_memory_updates_editable_fields_and_timestamp(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "update.db")
    memory = build_memory("mem-1")
    store.insert_memory(memory, embedding=[0.1, 0.2])

    updated = store.update_memory(
        "mem-1",
        content="Updated memory",
        type="updated-fact",
        metadata={"source": "manual"},
        source="import",
        confidence=0.6,
        sensitivity="low",
        embedding=[0.5, 0.6],
    )

    assert updated.content == "Updated memory"
    assert updated.type == "updated-fact"
    assert updated.metadata == {"source": "manual"}
    assert updated.source == "import"
    assert updated.confidence == 0.6
    assert updated.sensitivity == "low"
    assert updated.updated_at != memory.updated_at

    candidates = store.list_candidates(space=SPACE_USER)
    assert candidates[0][1] == [0.5, 0.6]


def test_archive_excluded_from_default_list_and_includable(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "archive.db")
    active = build_memory("mem-1")
    archived = build_memory("mem-2")
    store.insert_memory(active, embedding=[0.1])
    store.insert_memory(archived, embedding=[0.2])
    store.archive_memory("mem-2")

    default_results = store.list_memories()
    assert [memory.id for memory in default_results] == ["mem-1"]

    all_results = store.list_memories(include_archived=True)
    statuses = {memory.id: memory.status for memory in all_results}
    assert statuses == {"mem-1": STATUS_ACTIVE, "mem-2": STATUS_ARCHIVED}


def test_list_memories_filters_by_space_type_status_workspace(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "filters.db")
    store.insert_memory(build_memory("u1", space=SPACE_USER, type="fact"), embedding=[0.1])
    store.insert_memory(
        build_memory(
            "w1",
            space=SPACE_WORKSPACE,
            workspace_id="workspace-a",
            type="task",
            content="task a",
        ),
        embedding=[0.2],
    )
    store.insert_memory(
        build_memory(
            "w2",
            space=SPACE_WORKSPACE,
            workspace_id="workspace-b",
            type="task",
            content="task b",
        ),
        embedding=[0.3],
    )
    store.archive_memory("w2")

    workspace_results = store.list_memories(space=SPACE_WORKSPACE, workspace_id="workspace-a")
    assert [memory.id for memory in workspace_results] == ["w1"]

    task_results = store.list_memories(memory_type="task", include_archived=True)
    assert [memory.id for memory in task_results] == ["w2", "w1"]

    archived_only = store.list_memories(status=STATUS_ARCHIVED, include_archived=True)
    assert [memory.id for memory in archived_only] == ["w2"]

    limited = store.list_memories(include_archived=True, limit=2)
    assert len(limited) == 2


def test_list_candidates_respects_archived_filter(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "candidates.db")
    store.insert_memory(build_memory("mem-1"), embedding=[0.1])
    store.insert_memory(build_memory("mem-2"), embedding=[0.2])
    store.archive_memory("mem-2")

    default_candidates = store.list_candidates()
    assert [memory.id for memory, _ in default_candidates] == ["mem-1"]

    all_candidates = store.list_candidates(include_archived=True)
    assert [memory.id for memory, _ in all_candidates] == ["mem-2", "mem-1"]
