import json
from pathlib import Path
import sqlite3
import threading

import pytest

from recallium.core import RecalliumCore
from recallium.errors import (
    NotFoundError,
    ReembeddingFailedError,
    ReembeddingInProgressError,
    ValidationError,
)
from recallium.models import SPACE_USER, SPACE_WORKSPACE, STATUS_ARCHIVED


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.embedding_profile = {
            "provider": "fake",
            "model": "fake-model",
            "dimensions": 3,
            "version": "1",
            "profile": "fake-profile-v1",
            "max_tokens": 16,
            "chunk_tokens": 4,
            "chunk_overlap_tokens": 0,
            "query_prompt_policy": "raw",
        }

    def embed(self, text: str) -> list[float]:
        size = float(len(text))
        first = float(ord(text[0])) if text else 0.0
        return [size, first, 1.0]

    def similarity(self, first: list[float], second: list[float]) -> float:
        return sum(a * b for a, b in zip(first, second, strict=True))


class BlockingFakeEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.block_texts: set[str] = set()
        self.started = threading.Event()
        self.release = threading.Event()
        self.fail_texts: set[str] = set()

    def embed(self, text: str) -> list[float]:
        if text in self.block_texts:
            self.started.set()
            if not self.release.wait(5):
                raise RuntimeError("timed out waiting to unblock fake embedding")
        if text in self.fail_texts:
            raise RuntimeError(f"forced embedding failure for {text}")
        return super().embed(text)


def make_memories_stale(
    db_path: Path,
    memory_ids: list[str],
    active_profile: dict[str, object],
) -> None:
    stale_profile = {
        **active_profile,
        "profile": "stale-profile",
    }
    stale_json = json.dumps(stale_profile, sort_keys=True)
    placeholders = ", ".join("?" for _ in memory_ids)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE memories SET embedding_profile_json = ? WHERE id IN ({placeholders})",
            [stale_json, *memory_ids],
        )


def test_core_user_memory_flow_add_get_search_list_update_archive(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "core.db")

    created = core.add_memory(
        space="user",
        type="note",
        content="Need to fix bug before release",
        metadata={"source": "chat"},
    )

    assert created.id
    assert created.created_at
    assert created.updated_at

    fetched = core.get_memory(created.id)
    assert fetched.id == created.id
    assert fetched.last_accessed_at is not None

    search_results = core.search_user_memories("repair defect")
    assert [result.memory.id for result in search_results] == [created.id]

    listed = core.list_memories(space="user")
    assert [memory.id for memory in listed] == [created.id]

    updated = core.update_memory(created.id, content="Need to write release notes")
    assert updated.content == "Need to write release notes"
    assert updated.updated_at != created.updated_at

    refreshed_results = core.search_user_memories("release notes")
    assert refreshed_results[0].memory.id == created.id

    archived = core.archive_memory(created.id)
    assert archived.status == STATUS_ARCHIVED

    active_results = core.search_user_memories("release notes")
    assert active_results == []

    archived_results = core.search_user_memories("release notes", include_archived=True)
    assert [result.memory.id for result in archived_results] == [created.id]


def test_core_workspace_search_isolation_by_workspace_uid(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "workspace.db")

    workspace_a = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase milk",
        workspace_uid="workspace-alpha",
    )
    workspace_b = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase bread",
        workspace_uid="workspace-beta",
    )

    assert workspace_a.workspace_uid == "workspace-alpha"

    search_a = core.search_workspace_memories(
        "buy milk", workspace_uid="workspace-alpha"
    )
    assert [result.memory.id for result in search_a] == [workspace_a.id]

    search_b = core.search_workspace_memories(
        "buy milk", workspace_uid="workspace-beta"
    )
    assert [result.memory.id for result in search_b] == [workspace_b.id]

    user_results = core.search_user_memories("buy")
    assert user_results == []


def test_core_persistence_across_instances_and_not_found(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    first_core = RecalliumCore(db_path=db_path)
    created = first_core.add_memory(
        space="user", type="fact", content="Kaylee likes tea"
    )

    second_core = RecalliumCore(db_path=db_path)
    loaded = second_core.get_memory(created.id)
    assert loaded.content == "Kaylee likes tea"

    with pytest.raises(NotFoundError):
        second_core.get_memory("missing-id")


def test_workspace_identity_validation(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "workspace-uid.db")

    with pytest.raises(ValidationError, match="workspace_uid is required"):
        core.add_memory(
            space=SPACE_WORKSPACE,
            type="task",
            content="Need to purchase milk",
        )

    with pytest.raises(ValidationError, match="user memories must not include"):
        core.add_memory(
            space="user",
            type="preference",
            content="I like short answers",
            workspace_uid="workspace-alpha",
        )

    with pytest.raises(ValidationError, match="workspace_uid"):
        core.search_workspace_memories("buy milk", workspace_uid=" ")


def test_core_rejects_invalid_list_limit(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "limit.db")

    with pytest.raises(ValidationError, match="positive integer"):
        core.list_memories(limit=0)


def test_add_memory_persists_chunk_embeddings_and_searches_from_chunks(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chunks.db"
    core = RecalliumCore(db_path=db_path)

    created = core.add_memory(
        space=SPACE_USER,
        type="note",
        content="dragon fruit smoothie prep for breakfast",
    )

    results = core.search_user_memories("dragon fruit breakfast")
    assert [result.memory.id for result in results] == [created.id]
    assert results[0].matched_text is not None
    assert results[0].chunk_index == 0

    with sqlite3.connect(db_path) as connection:
        chunk_count = connection.execute(
            "SELECT COUNT(*) FROM embedding_chunks WHERE memory_id = ?",
            (created.id,),
        ).fetchone()[0]
        assert chunk_count >= 1


def test_update_memory_content_refreshes_chunks(tmp_path: Path) -> None:
    db_path = tmp_path / "update-chunks.db"
    core = RecalliumCore(db_path=db_path)

    created = core.add_memory(
        space=SPACE_USER,
        type="note",
        content="old release checklist",
    )
    updated = core.update_memory(created.id, content="new launch checklist")
    assert updated.content == "new launch checklist"

    with sqlite3.connect(db_path) as connection:
        chunk_texts = connection.execute(
            "SELECT content FROM embedding_chunks WHERE memory_id = ? ORDER BY chunk_index ASC",
            (created.id,),
        ).fetchall()
    assert chunk_texts
    assert all("new" in row[0] for row in chunk_texts)
    assert all("old" not in row[0] for row in chunk_texts)


def test_startup_reembeds_stale_memories_for_active_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "startup-stale.db"
    core = RecalliumCore(db_path=db_path)
    memory = core.add_memory(space=SPACE_USER, type="fact", content="kiwi notebook")

    stale_profile = {
        **core.embedding_provider.embedding_profile,
        "profile": "stale-profile",
    }
    core.store.update_memory(memory.id, embedding_profile=stale_profile)

    restarted = RecalliumCore(db_path=db_path)
    stale_count = restarted.store.count_memories_needing_profile_reembedding(
        embedding_profile=restarted.embedding_provider.embedding_profile,
        space=SPACE_USER,
    )
    assert stale_count == 0

    jobs = restarted.list_embedding_jobs(limit=1)
    assert jobs
    assert jobs[0]["state"] == "completed"
    assert jobs[0]["total_count"] >= 1

    status = restarted.active_embedding_status()
    assert status["provider_status"] == "configured"
    assert status["model_status"] == "managed_by_fastembed_cache"
    assert status["runtime"] == {"name": "fastembed", "threads": 1, "parallel": None}
    assert status["startup_reembedding_job_id"] == jobs[0]["id"]
    assert status["startup_reembedding_status_path"].endswith(jobs[0]["id"])
    assert status["embedding_jobs_status_path"] == "/v1/embedding/jobs"
    assert status["recent_embedding_jobs"]


def test_search_reembeds_missing_profile_chunks_below_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "search-reembed.db"
    core = RecalliumCore(db_path=db_path)
    created = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="calibrate laser cutter",
        workspace_uid="shop",
    )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DELETE FROM embedding_chunks WHERE memory_id = ?", (created.id,)
        )

    results = core.search_workspace_memories("laser calibration", workspace_uid="shop")
    assert [result.memory.id for result in results] == [created.id]

    with sqlite3.connect(db_path) as connection:
        refreshed_chunk_count = connection.execute(
            "SELECT COUNT(*) FROM embedding_chunks WHERE memory_id = ?",
            (created.id,),
        ).fetchone()[0]
    assert refreshed_chunk_count >= 1


def test_search_raises_retryable_error_when_stale_count_exceeds_threshold(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "threshold.db"
    core = RecalliumCore(db_path=db_path, immediate_reembedding_threshold=1)
    one = core.add_memory(space=SPACE_USER, type="note", content="alpha")
    two = core.add_memory(space=SPACE_USER, type="note", content="beta")

    stale_profile = {
        **core.embedding_provider.embedding_profile,
        "profile": "stale-user-profile",
    }
    core.store.update_memory(one.id, embedding_profile=stale_profile)
    core.store.update_memory(two.id, embedding_profile=stale_profile)

    with pytest.raises(ReembeddingInProgressError) as exc_info:
        core.search_user_memories("alpha")

    error = exc_info.value
    assert error.job_id
    assert error.status_path.endswith(error.job_id)

    job = core.get_embedding_job(error.job_id)
    assert job["state"] in {"pending", "in_progress", "completed"}
    assert job["total_count"] == 2


def test_deferred_reembedding_worker_completes_and_preserves_memory_fields(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "deferred-worker.db"
    provider = BlockingFakeEmbeddingProvider()
    core = RecalliumCore(
        db_path=db_path,
        embedding_provider=provider,
        immediate_reembedding_threshold=0,
    )
    first = core.add_memory(
        space=SPACE_USER,
        type="fact",
        content="alpha one",
        metadata={"kept": True},
        source="user",
        confidence=0.8,
        sensitivity="normal",
    )
    second = core.add_memory(space=SPACE_USER, type="fact", content="beta two")
    make_memories_stale(
        db_path,
        [first.id, second.id],
        provider.embedding_profile,
    )
    provider.block_texts.add(first.content)

    with pytest.raises(ReembeddingInProgressError) as exc_info:
        core.search_user_memories("alpha")

    job_id = exc_info.value.job_id
    assert exc_info.value.status_path.endswith(job_id)
    assert provider.started.wait(5)

    with pytest.raises(ReembeddingInProgressError) as duplicate_exc_info:
        core.search_user_memories("alpha")
    assert duplicate_exc_info.value.job_id == job_id

    listed = core.list_memories(space=SPACE_USER)
    assert {memory.id for memory in listed} == {first.id, second.id}
    fetched_during_work = core.get_memory(first.id)
    assert fetched_during_work.content == first.content

    provider.release.set()
    core._join_embedding_job(job_id)

    job = core.get_embedding_job(job_id)
    assert job["state"] == "completed"
    assert job["processed_count"] == 2
    assert job["succeeded_count"] == 2
    assert job["failed_count"] == 0
    assert job["started_at"] is not None
    assert job["completed_at"] is not None

    after = core.get_memory(first.id)
    assert after.content == first.content
    assert after.status == first.status
    assert after.space == first.space
    assert after.workspace_uid == first.workspace_uid
    assert after.type == first.type
    assert after.source == first.source
    assert after.confidence == first.confidence
    assert after.sensitivity == first.sensitivity
    assert after.metadata == first.metadata
    assert after.created_at == first.created_at
    assert after.updated_at == first.updated_at

    stale_count = core.store.count_memories_needing_profile_reembedding(
        embedding_profile=provider.embedding_profile,
        space=SPACE_USER,
    )
    assert stale_count == 0
    with sqlite3.connect(db_path) as connection:
        chunk_count = connection.execute(
            "SELECT COUNT(*) FROM embedding_chunks WHERE memory_id = ?",
            (first.id,),
        ).fetchone()[0]
    assert chunk_count >= 1
    results = core.search_user_memories("alpha")
    assert [result.memory.id for result in results]


def test_deferred_reembedding_worker_reports_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "deferred-failure.db"
    provider = BlockingFakeEmbeddingProvider()
    core = RecalliumCore(
        db_path=db_path,
        embedding_provider=provider,
        immediate_reembedding_threshold=1,
    )
    first = core.add_memory(space=SPACE_USER, type="note", content="alpha one")
    second = core.add_memory(space=SPACE_USER, type="note", content="beta two")
    make_memories_stale(
        db_path,
        [first.id, second.id],
        provider.embedding_profile,
    )
    provider.fail_texts.add(second.content)

    with pytest.raises(ReembeddingInProgressError) as exc_info:
        core.search_user_memories("alpha")

    job_id = exc_info.value.job_id
    core._join_embedding_job(job_id)

    job = core.get_embedding_job(job_id)
    assert job["state"] == "failed"
    assert job["processed_count"] == 2
    assert job["succeeded_count"] == 1
    assert job["failed_count"] == 1
    assert "forced embedding failure" in job["error_message"]

    stale_count = core.store.count_memories_needing_profile_reembedding(
        embedding_profile=provider.embedding_profile,
        space=SPACE_USER,
    )
    assert stale_count == 1


def test_deferred_reembedding_scope_safety_and_archived_exclusion(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "deferred-scope.db"
    provider = BlockingFakeEmbeddingProvider()
    core = RecalliumCore(
        db_path=db_path,
        embedding_provider=provider,
        immediate_reembedding_threshold=0,
    )
    user_memory = core.add_memory(space=SPACE_USER, type="fact", content="user alpha")
    workspace_a = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="workspace alpha",
        workspace_uid="workspace-a",
    )
    workspace_b = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="workspace beta",
        workspace_uid="workspace-b",
    )
    archived = core.add_memory(space=SPACE_USER, type="fact", content="archived alpha")
    core.archive_memory(archived.id)
    make_memories_stale(
        db_path,
        [user_memory.id, workspace_a.id, workspace_b.id, archived.id],
        provider.embedding_profile,
    )
    provider.block_texts.add(workspace_a.content)

    with pytest.raises(ReembeddingInProgressError) as exc_info:
        core.search_workspace_memories("alpha", workspace_uid="workspace-a")

    job_id = exc_info.value.job_id
    assert provider.started.wait(5)
    provider.release.set()
    core._join_embedding_job(job_id)

    job = core.get_embedding_job(job_id)
    assert job["state"] == "completed"
    assert job["total_count"] == 1
    assert job["succeeded_count"] == 1

    workspace_a_stale = core.store.count_memories_needing_profile_reembedding(
        embedding_profile=provider.embedding_profile,
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-a",
    )
    workspace_b_stale = core.store.count_memories_needing_profile_reembedding(
        embedding_profile=provider.embedding_profile,
        space=SPACE_WORKSPACE,
        workspace_uid="workspace-b",
    )
    user_stale = core.store.count_memories_needing_profile_reembedding(
        embedding_profile=provider.embedding_profile,
        space=SPACE_USER,
    )
    assert workspace_a_stale == 0
    assert workspace_b_stale == 1
    assert user_stale == 1

    with sqlite3.connect(db_path) as connection:
        archived_profile_json = connection.execute(
            "SELECT embedding_profile_json FROM memories WHERE id = ?",
            (archived.id,),
        ).fetchone()[0]
    assert json.loads(archived_profile_json)["profile"] == "stale-profile"


def test_reembedding_preserves_updated_at_for_startup_and_runtime(
    tmp_path: Path,
) -> None:
    startup_db = tmp_path / "startup-preserve-updated-at.db"
    core = RecalliumCore(db_path=startup_db)
    startup_memory = core.add_memory(space=SPACE_USER, type="fact", content="alpha")

    stale_profile = {
        **core.embedding_provider.embedding_profile,
        "profile": "stale-profile",
    }
    with sqlite3.connect(startup_db) as connection:
        connection.execute(
            "UPDATE memories SET embedding_profile_json = ? WHERE id = ?",
            (json.dumps(stale_profile, sort_keys=True), startup_memory.id),
        )

    restarted = RecalliumCore(db_path=startup_db)
    startup_after = restarted.get_memory(startup_memory.id)
    assert startup_after.updated_at == startup_memory.updated_at

    runtime_db = tmp_path / "runtime-preserve-updated-at.db"
    runtime_core = RecalliumCore(db_path=runtime_db)
    runtime_memory = runtime_core.add_memory(
        space=SPACE_USER, type="fact", content="beta"
    )

    with sqlite3.connect(runtime_db) as connection:
        connection.execute(
            "UPDATE memories SET embedding_profile_json = ? WHERE id = ?",
            (json.dumps(stale_profile, sort_keys=True), runtime_memory.id),
        )

    _ = runtime_core.search_user_memories("beta")
    runtime_after = runtime_core.get_memory(runtime_memory.id)
    assert runtime_after.updated_at == runtime_memory.updated_at


def test_runtime_reembedding_failure_blocks_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "runtime-reembed-failure.db"
    core = RecalliumCore(db_path=db_path)
    first = core.add_memory(space=SPACE_USER, type="note", content="memory one")
    second = core.add_memory(space=SPACE_USER, type="note", content="memory two")

    stale_profile = {
        **core.embedding_provider.embedding_profile,
        "profile": "stale-profile",
    }
    stale_json = json.dumps(stale_profile, sort_keys=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE memories SET embedding_profile_json = ? WHERE id IN (?, ?)",
            (stale_json, first.id, second.id),
        )

    original_chunk_embed_pairs = core._chunk_embed_pairs

    def fail_on_second(text: str):
        if text == second.content:
            raise RuntimeError("forced runtime re-embed failure")
        return original_chunk_embed_pairs(text)

    monkeypatch.setattr(core, "_chunk_embed_pairs", fail_on_second)

    with pytest.raises(ReembeddingFailedError) as exc_info:
        core.search_user_memories("memory")

    error = exc_info.value
    job = core.get_embedding_job(error.job_id)
    assert job["state"] == "failed"
    assert job["failed_count"] == 1
    assert error.status_path.endswith(error.job_id)
