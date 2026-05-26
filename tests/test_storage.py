from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

import pytest

from recallium.embeddings import ContentChunk
from recallium.errors import MigrationError, NotFoundError
from recallium.migrations import Migration, MigrationRunner
from recallium.models import (
    SPACE_USER,
    SPACE_WORKSPACE,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    Memory,
)
from recallium.storage import SQLiteMemoryStore


EMBEDDING_PROFILE = {
    "provider": "test",
    "model": "test-model",
    "dimensions": 2,
    "version": "1",
}


@contextmanager
def sqlite_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    try:
        yield connection
    finally:
        connection.commit()
        connection.close()


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


def test_store_creates_parent_directories_and_persists_across_instances(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nested" / "db" / "recallium.db"
    store = SQLiteMemoryStore(db_path)
    memory = build_memory("mem-1")

    store.insert_memory(
        memory, embedding=[0.1, 0.2], embedding_profile=EMBEDDING_PROFILE
    )

    other_store = SQLiteMemoryStore(db_path)
    loaded = other_store.get_memory("mem-1")
    assert loaded == memory


def test_workspace_uid_memory_round_trips_through_storage(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "workspace-uid.db")
    memory = build_memory(
        "mem-workspace",
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-alpha",
    )

    store.insert_memory(
        memory, embedding=[0.2, 0.3], embedding_profile=EMBEDDING_PROFILE
    )

    loaded = store.get_memory("mem-workspace")
    assert loaded.space == SPACE_WORKSPACE
    assert loaded.workspace_uid == "workspace-alpha"


def test_store_uses_latest_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "schema.db"
    SQLiteMemoryStore(db_path)

    with sqlite_connection(db_path) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()

    assert row is not None
    assert row[0] == 2


def test_fresh_database_tracks_schema_migrations_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "schema-metadata.db"
    SQLiteMemoryStore(db_path)

    with sqlite_connection(db_path) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
        ]

    assert versions == [1, 2]


def test_fresh_schema_creates_chunk_and_job_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "schema-v2.db"
    SQLiteMemoryStore(db_path)

    with sqlite_connection(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "memories" in tables
    assert "embedding_chunks" in tables
    assert "embedding_jobs" in tables


def test_v1_database_migrates_to_v2_without_losing_memories(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate-v1.db"
    memory = build_memory("legacy")

    with sqlite_connection(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                space TEXT NOT NULL,
                workspace_uid TEXT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                source TEXT NULL,
                confidence REAL NULL,
                sensitivity TEXT NULL,
                embedding_profile_json TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memories (
                id, space, workspace_uid, type, content, metadata_json,
                status, source, confidence, sensitivity, embedding_profile_json,
                embedding_json, created_at, updated_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.space,
                memory.workspace_uid,
                memory.type,
                memory.content,
                '{"source": "chat"}',
                memory.status,
                memory.source,
                memory.confidence,
                memory.sensitivity,
                '{"provider": "test", "model": "v1"}',
                "[0.1, 0.2]",
                memory.created_at,
                memory.updated_at,
                memory.last_accessed_at,
            ),
        )
        connection.execute("PRAGMA user_version = 1")

    store = SQLiteMemoryStore(db_path)
    loaded = store.get_memory("legacy")
    assert loaded.id == "legacy"
    assert loaded.content == memory.content

    with sqlite_connection(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
    assert version is not None
    assert version[0] == 2


def test_current_v2_database_without_metadata_remains_compatible(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "v2-without-metadata.db"

    with sqlite_connection(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                space TEXT NOT NULL,
                workspace_uid TEXT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                source TEXT NULL,
                confidence REAL NULL,
                sensitivity TEXT NULL,
                embedding_profile_json TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE embedding_chunks (
                id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                token_start INTEGER NOT NULL,
                token_end INTEGER NOT NULL,
                embedding_profile_json TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                UNIQUE(memory_id, chunk_index, embedding_profile_json)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE embedding_jobs (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                total_count INTEGER NOT NULL,
                processed_count INTEGER NOT NULL,
                succeeded_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                embedding_profile_json TEXT NOT NULL,
                error_message TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT NULL,
                completed_at TEXT NULL
            )
            """
        )
        connection.execute("PRAGMA user_version = 2")

    store = SQLiteMemoryStore(db_path)
    status = store.migration_status()

    assert status["current_version"] == 2
    assert status["pending_versions"] == []
    assert status["up_to_date"] is True

    with sqlite_connection(db_path) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
        ]

    assert versions == [1, 2]


def test_migration_status_reports_versions_and_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "status.db"
    store = SQLiteMemoryStore(db_path)

    status = store.migration_status()

    assert status["db_path"] == str(db_path)
    assert status["current_version"] == 2
    assert status["latest_version"] == 2
    assert status["pending_versions"] == []
    assert status["up_to_date"] is True


def test_migrations_are_loaded_in_deterministic_order(tmp_path: Path) -> None:
    db_path = tmp_path / "order.db"
    calls: list[int] = []

    def _upgrade_v1(connection: sqlite3.Connection) -> None:
        calls.append(1)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ordered_1 (id INTEGER PRIMARY KEY)"
        )

    def _upgrade_v2(connection: sqlite3.Connection) -> None:
        calls.append(2)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ordered_2 (id INTEGER PRIMARY KEY)"
        )

    runner = MigrationRunner(
        db_path,
        migrations=[
            Migration(version=2, name="second", upgrade=_upgrade_v2),
            Migration(version=1, name="first", upgrade=_upgrade_v1),
        ],
    )

    status = runner.migrate()

    assert calls == [1, 2]
    assert status.current_version == 2
    assert status.pending_versions == []


def test_migration_failure_does_not_mark_version_upgraded(tmp_path: Path) -> None:
    db_path = tmp_path / "failed-migration.db"

    def _upgrade_v1(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE IF NOT EXISTS ok_1 (id INTEGER PRIMARY KEY)")

    def _upgrade_v2(_connection: sqlite3.Connection) -> None:
        msg = "boom"
        raise sqlite3.OperationalError(msg)

    runner = MigrationRunner(
        db_path,
        migrations=[
            Migration(version=1, name="ok", upgrade=_upgrade_v1),
            Migration(version=2, name="broken", upgrade=_upgrade_v2),
        ],
    )

    with pytest.raises(MigrationError):
        runner.migrate()

    with sqlite_connection(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        applied = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
        ]

    assert version is not None
    assert version[0] == 1
    assert applied == [1]


def test_newer_database_version_raises_migration_error(tmp_path: Path) -> None:
    db_path = tmp_path / "future.db"
    with sqlite_connection(db_path) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(MigrationError):
        SQLiteMemoryStore(db_path)


def test_migration_runner_rejects_invalid_versions(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid-versions.db"

    def noop(_connection: sqlite3.Connection) -> None:
        return None

    with pytest.raises(MigrationError):
        MigrationRunner(
            db_path,
            migrations=[
                Migration(version=1, name="a", upgrade=noop),
                Migration(version=1, name="b", upgrade=noop),
            ],
        )

    with pytest.raises(MigrationError):
        MigrationRunner(
            db_path,
            migrations=[Migration(version=0, name="bad", upgrade=noop)],
        )


def test_migration_runner_handles_empty_migration_set(tmp_path: Path) -> None:
    db_path = tmp_path / "empty-migrations.db"
    runner = MigrationRunner(db_path, migrations=[])

    status = runner.migrate()

    assert status.current_version == 0
    assert status.latest_version == 0
    assert status.pending_versions == []
    assert status.up_to_date is True


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
    store.insert_memory(
        memory, embedding=[0.1, 0.2], embedding_profile=EMBEDDING_PROFILE
    )

    updated = store.update_memory(
        "mem-1",
        content="Updated memory",
        type="updated-fact",
        metadata={"source": "manual"},
        source="import",
        confidence=0.6,
        sensitivity="low",
        embedding=[0.5, 0.6],
        embedding_profile=EMBEDDING_PROFILE,
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


def test_storage_noop_updates_and_missing_derived_rows(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "noop-and-missing.db")
    memory = build_memory("mem-1")
    store.insert_memory(
        memory, embedding=[0.1, 0.2], embedding_profile=EMBEDDING_PROFILE
    )

    assert store.update_memory("mem-1") == memory
    assert store.touch_last_accessed_at("missing") is None

    touched = store.touch_last_accessed_at("mem-1")
    assert touched is not None
    assert touched.last_accessed_at is not None

    refreshed = store.refresh_memory_embedding_derived_fields(
        "mem-1",
        embedding=[0.4, 0.5],
        embedding_profile=EMBEDDING_PROFILE,
    )
    assert refreshed.id == "mem-1"
    assert store.list_candidates(space=SPACE_USER)[0][1] == [0.4, 0.5]

    with pytest.raises(NotFoundError):
        store.refresh_memory_embedding_derived_fields(
            "missing",
            embedding=[0.1, 0.2],
            embedding_profile=EMBEDDING_PROFILE,
        )

    with pytest.raises(NotFoundError):
        store.replace_memory_chunks(
            memory_id="missing",
            embedding_profile=EMBEDDING_PROFILE,
            chunk_embeddings=[],
        )


def test_archive_excluded_from_default_list_and_includable(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "archive.db")
    active = build_memory("mem-1")
    archived = build_memory("mem-2")
    store.insert_memory(active, embedding=[0.1], embedding_profile=EMBEDDING_PROFILE)
    store.insert_memory(archived, embedding=[0.2], embedding_profile=EMBEDDING_PROFILE)
    store.archive_memory("mem-2")

    default_results = store.list_memories()
    assert [memory.id for memory in default_results] == ["mem-1"]

    all_results = store.list_memories(include_archived=True)
    statuses = {memory.id: memory.status for memory in all_results}
    assert statuses == {"mem-1": STATUS_ACTIVE, "mem-2": STATUS_ARCHIVED}


def test_list_memories_filters_by_space_type_status_workspace(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "filters.db")
    store.insert_memory(
        build_memory("u1", space=SPACE_USER, type="fact"),
        embedding=[0.1],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory(
            "w1",
            space=SPACE_WORKSPACE,
            workspace_uid="workspace-a",
            type="task",
            content="task a",
        ),
        embedding=[0.2],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory(
            "w2",
            space=SPACE_WORKSPACE,
            workspace_uid="workspace-b",
            type="task",
            content="task b",
        ),
        embedding=[0.3],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.archive_memory("w2")

    workspace_results = store.list_memories(
        space=SPACE_WORKSPACE, workspace_uid="workspace-a"
    )
    assert [memory.id for memory in workspace_results] == ["w1"]

    task_results = store.list_memories(memory_type="task", include_archived=True)
    assert [memory.id for memory in task_results] == ["w2", "w1"]

    archived_only = store.list_memories(status=STATUS_ARCHIVED, include_archived=True)
    assert [memory.id for memory in archived_only] == ["w2"]

    limited = store.list_memories(include_archived=True, limit=2)
    assert len(limited) == 2


def test_list_candidates_respects_archived_filter(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "candidates.db")
    store.insert_memory(
        build_memory("mem-1"), embedding=[0.1], embedding_profile=EMBEDDING_PROFILE
    )
    store.insert_memory(
        build_memory("mem-2"), embedding=[0.2], embedding_profile=EMBEDDING_PROFILE
    )
    store.archive_memory("mem-2")

    default_candidates = store.list_candidates()
    assert [memory.id for memory, _ in default_candidates] == ["mem-1"]

    all_candidates = store.list_candidates(include_archived=True)
    assert [memory.id for memory, _ in all_candidates] == ["mem-2", "mem-1"]


def test_list_candidates_can_filter_by_embedding_profile(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "embedding-profile.db")
    stale_profile = {
        "provider": "test",
        "model": "old-model",
        "dimensions": 2,
        "version": "1",
    }

    store.insert_memory(
        build_memory("current"),
        embedding=[0.1, 0.2],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory("stale"),
        embedding=[0.3, 0.4],
        embedding_profile=stale_profile,
    )

    candidates = store.list_candidates(embedding_profile=EMBEDDING_PROFILE)

    assert [memory.id for memory, _ in candidates] == ["current"]


def test_list_candidates_can_filter_by_workspace_uid(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "candidate-workspace.db")
    store.insert_memory(
        build_memory(
            "workspace-a",
            space=SPACE_WORKSPACE,
            workspace_uid="workspace-a",
        ),
        embedding=[0.1, 0.2],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory(
            "workspace-b",
            space=SPACE_WORKSPACE,
            workspace_uid="workspace-b",
        ),
        embedding=[0.3, 0.4],
        embedding_profile=EMBEDDING_PROFILE,
    )

    candidates = store.list_candidates(
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-a",
    )

    assert [memory.id for memory, _embedding in candidates] == ["workspace-a"]


def test_replace_memory_chunks_is_atomic_per_memory_and_profile(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "chunks.db")
    memory = build_memory("mem-1")
    store.insert_memory(
        memory, embedding=[0.1, 0.2], embedding_profile=EMBEDDING_PROFILE
    )

    first_chunks = [
        (
            ContentChunk(chunk_index=0, text="first chunk", token_start=0, token_end=2),
            [0.1, 0.2],
        ),
        (
            ContentChunk(
                chunk_index=1, text="second chunk", token_start=2, token_end=4
            ),
            [0.3, 0.4],
        ),
    ]
    store.replace_memory_chunks(
        memory_id="mem-1",
        embedding_profile=EMBEDDING_PROFILE,
        chunk_embeddings=first_chunks,
    )

    candidates = store.list_chunk_candidates(embedding_profile=EMBEDDING_PROFILE)
    assert [candidate.chunk_index for candidate in candidates] == [0, 1]

    replacement_chunks = [
        (
            ContentChunk(chunk_index=0, text="replacement", token_start=0, token_end=1),
            [0.9, 0.8],
        )
    ]
    store.replace_memory_chunks(
        memory_id="mem-1",
        embedding_profile=EMBEDDING_PROFILE,
        chunk_embeddings=replacement_chunks,
    )

    replaced = store.list_chunk_candidates(embedding_profile=EMBEDDING_PROFILE)
    assert len(replaced) == 1
    assert replaced[0].chunk_index == 0
    assert replaced[0].matched_text == "replacement"
    assert replaced[0].embedding == [0.9, 0.8]


def test_list_chunk_candidates_respects_scope_workspace_archive_filters(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "chunk-filters.db")

    user_memory = build_memory("user-1", space=SPACE_USER)
    workspace_memory = build_memory(
        "workspace-1",
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-a",
    )
    archived_workspace = build_memory(
        "workspace-2",
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-b",
    )

    store.insert_memory(
        user_memory,
        embedding=[0.1, 0.2],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        workspace_memory,
        embedding=[0.2, 0.3],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        archived_workspace,
        embedding=[0.3, 0.4],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.archive_memory("workspace-2")

    for memory_id, text in [
        ("user-1", "user chunk"),
        ("workspace-1", "workspace chunk"),
        ("workspace-2", "archived chunk"),
    ]:
        store.replace_memory_chunks(
            memory_id=memory_id,
            embedding_profile=EMBEDDING_PROFILE,
            chunk_embeddings=[
                (
                    ContentChunk(chunk_index=0, text=text, token_start=0, token_end=2),
                    [0.5, 0.6],
                )
            ],
        )

    workspace_only = store.list_chunk_candidates(
        embedding_profile=EMBEDDING_PROFILE,
        space=SPACE_WORKSPACE,
    )
    assert [candidate.memory.id for candidate in workspace_only] == ["workspace-1"]

    workspace_a = store.list_chunk_candidates(
        embedding_profile=EMBEDDING_PROFILE,
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-a",
    )
    assert [candidate.memory.id for candidate in workspace_a] == ["workspace-1"]

    include_archived = store.list_chunk_candidates(
        embedding_profile=EMBEDDING_PROFILE,
        space=SPACE_WORKSPACE,
        include_archived=True,
    )
    assert [candidate.memory.id for candidate in include_archived] == [
        "workspace-2",
        "workspace-1",
    ]


def test_reembedding_detectors_find_stale_or_missing_profile_chunks(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "reembedding.db")
    stale_profile = {
        "provider": "test",
        "model": "old-model",
        "dimensions": 2,
        "version": "1",
    }
    store.insert_memory(
        build_memory("current-ready"),
        embedding=[0.1, 0.2],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory("current-missing"),
        embedding=[0.2, 0.3],
        embedding_profile=EMBEDDING_PROFILE,
    )
    store.insert_memory(
        build_memory("stale-profile"),
        embedding=[0.3, 0.4],
        embedding_profile=stale_profile,
    )

    store.replace_memory_chunks(
        memory_id="current-ready",
        embedding_profile=EMBEDDING_PROFILE,
        chunk_embeddings=[
            (
                ContentChunk(chunk_index=0, text="ready", token_start=0, token_end=1),
                [0.1, 0.2],
            )
        ],
    )

    needing = store.list_memories_needing_profile_reembedding(
        embedding_profile=EMBEDDING_PROFILE
    )
    assert {memory.id for memory in needing} == {"stale-profile", "current-missing"}
    assert (
        store.count_memories_needing_profile_reembedding(
            embedding_profile=EMBEDDING_PROFILE
        )
        == 2
    )

    limited = store.list_memories_needing_profile_reembedding(
        embedding_profile=EMBEDDING_PROFILE,
        limit=1,
    )
    assert len(limited) == 1

    workspace_count = store.count_memories_needing_profile_reembedding(
        embedding_profile=EMBEDDING_PROFILE,
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-a",
        include_archived=True,
    )
    assert workspace_count == 0


def test_embedding_job_persistence_create_update_get_list(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "jobs.db")

    created = store.create_embedding_job(
        job_id="job-1",
        state="pending",
        total_count=10,
        processed_count=0,
        succeeded_count=0,
        failed_count=0,
        provider="builtin-fastembed",
        model="jinaai/jina-embeddings-v2-small-en",
        embedding_profile=EMBEDDING_PROFILE,
    )
    assert created["id"] == "job-1"
    assert created["state"] == "pending"
    assert created["total_count"] == 10

    updated = store.update_embedding_job(
        "job-1",
        state="running",
        processed_count=3,
        succeeded_count=3,
        started_at="2026-01-01T01:00:00Z",
    )
    assert updated["state"] == "running"
    assert updated["processed_count"] == 3
    assert updated["succeeded_count"] == 3

    fetched = store.get_embedding_job("job-1")
    assert fetched["id"] == "job-1"
    assert fetched["embedding_profile"] == EMBEDDING_PROFILE

    store.create_embedding_job(
        job_id="job-2",
        state="failed",
        total_count=4,
        processed_count=4,
        succeeded_count=3,
        failed_count=1,
        provider="builtin-fastembed",
        model="jinaai/jina-embeddings-v2-small-en",
        embedding_profile=EMBEDDING_PROFILE,
        error_message="provider unavailable",
        completed_at="2026-01-01T02:00:00Z",
    )

    all_jobs = store.list_embedding_jobs()
    assert [job["id"] for job in all_jobs] == ["job-2", "job-1"]

    failed_jobs = store.list_embedding_jobs(state="failed")
    assert [job["id"] for job in failed_jobs] == ["job-2"]

    limited_jobs = store.list_embedding_jobs(limit=1)
    assert len(limited_jobs) == 1

    no_op_job = store.update_embedding_job("job-1")
    assert no_op_job["id"] == "job-1"

    reprofilled = store.update_embedding_job(
        "job-1",
        embedding_profile={**EMBEDDING_PROFILE, "version": "2"},
    )
    assert reprofilled["embedding_profile"]["version"] == "2"

    with pytest.raises(NotFoundError):
        store.update_embedding_job("missing", state="failed")

    with pytest.raises(NotFoundError):
        store.get_embedding_job("missing")
