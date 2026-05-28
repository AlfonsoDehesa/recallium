"""SQLite persistence layer for Recollectium memories."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from recollectium.embeddings import ContentChunk
from recollectium.errors import NotFoundError
from recollectium.migrations import MigrationRunner
from recollectium.models import Memory, STATUS_ARCHIVED
from recollectium.search import ChunkCandidate


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class SQLiteMemoryStore:
    """Small SQLite-backed store for memory records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_runner = MigrationRunner(self.db_path)
        self._migration_runner.migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.commit()
            connection.close()

    def migration_status(self) -> dict[str, object]:
        return self._migration_runner.status().to_dict()

    def insert_memory(
        self,
        memory: Memory,
        embedding: list[float],
        embedding_profile: dict[str, object],
    ) -> Memory:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, space, workspace_uid, type, content, metadata_json,
                    status, source, confidence, sensitivity, embedding_profile_json,
                    embedding_json,
                    created_at, updated_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.space,
                    memory.workspace_uid,
                    memory.type,
                    memory.content,
                    json.dumps(memory.metadata, sort_keys=True),
                    memory.status,
                    memory.source,
                    memory.confidence,
                    memory.sensitivity,
                    json.dumps(embedding_profile, sort_keys=True),
                    json.dumps(embedding),
                    memory.created_at,
                    memory.updated_at,
                    memory.last_accessed_at,
                ),
            )
        return memory

    def get_memory(self, memory_id: str) -> Memory:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()

        if row is None:
            raise NotFoundError(f"memory not found: {memory_id}")

        return self._row_to_memory(row)

    def update_memory(self, memory_id: str, **updates: Any) -> Memory:
        assignments: list[str] = []
        values: list[Any] = []

        editable_fields = {"type", "content", "source", "confidence", "sensitivity"}
        for field_name in editable_fields:
            if field_name in updates:
                assignments.append(f"{field_name} = ?")
                values.append(updates[field_name])

        if "metadata" in updates:
            assignments.append("metadata_json = ?")
            values.append(json.dumps(updates["metadata"], sort_keys=True))

        if "embedding" in updates:
            assignments.append("embedding_json = ?")
            values.append(json.dumps(updates["embedding"]))

        if "embedding_profile" in updates:
            assignments.append("embedding_profile_json = ?")
            values.append(json.dumps(updates["embedding_profile"], sort_keys=True))

        if not assignments:
            return self.get_memory(memory_id)

        assignments.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(memory_id)

        with self._connect() as connection:
            result = connection.execute(
                f"UPDATE memories SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

        if result.rowcount == 0:
            raise NotFoundError(f"memory not found: {memory_id}")

        return self.get_memory(memory_id)

    def refresh_memory_embedding_derived_fields(
        self,
        memory_id: str,
        *,
        embedding: list[float],
        embedding_profile: dict[str, object],
    ) -> Memory:
        values = (
            json.dumps(embedding),
            json.dumps(embedding_profile, sort_keys=True),
            memory_id,
        )

        with self._connect() as connection:
            result = connection.execute(
                "UPDATE memories SET embedding_json = ?, embedding_profile_json = ? WHERE id = ?",
                values,
            )

        if result.rowcount == 0:
            raise NotFoundError(f"memory not found: {memory_id}")

        return self.get_memory(memory_id)

    def touch_last_accessed_at(self, memory_id: str) -> Memory | None:
        timestamp = utc_now_iso()
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE memories SET last_accessed_at = ? WHERE id = ?",
                (timestamp, memory_id),
            )

        if result.rowcount == 0:
            return None

        return self.get_memory(memory_id)

    def archive_memory(self, memory_id: str) -> Memory:
        timestamp = utc_now_iso()
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (STATUS_ARCHIVED, timestamp, memory_id),
            )

        if result.rowcount == 0:
            raise NotFoundError(f"memory not found: {memory_id}")

        return self.get_memory(memory_id)

    # -- workspace operations ------------------------------------------------

    def list_workspace_uids(self, *, include_archived: bool = False) -> list[str]:
        """Return distinct non-null workspace_uid values, sorted alphabetically."""
        where_parts = [
            "workspace_uid IS NOT NULL",
            "space = 'workspace'",
        ]
        values: list[Any] = []
        if not include_archived:
            where_parts.append("status != ?")
            values.append(STATUS_ARCHIVED)

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT workspace_uid FROM memories "
                "WHERE " + " AND ".join(where_parts) + " ORDER BY workspace_uid ASC",
                values,
            ).fetchall()

        return [row["workspace_uid"] for row in rows]

    def rename_workspace(self, old_uid: str, new_uid: str) -> int:
        """Rename all workspace memories from old_uid to new_uid.

        Returns the number of updated rows.  Raises NotFoundError when
        *old_uid* has no matching workspace memories.
        """
        timestamp = utc_now_iso()
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE memories SET workspace_uid = ?, updated_at = ? "
                "WHERE workspace_uid = ? AND space = 'workspace'",
                (new_uid, timestamp, old_uid),
            )

        if result.rowcount == 0:
            raise NotFoundError(f"no workspace memories found for uid: {old_uid}")
        return result.rowcount

    def list_memories(
        self,
        *,
        space: str | None = None,
        memory_type: str | None = None,
        status: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> list[Memory]:
        where_parts: list[str] = []
        values: list[Any] = []

        if space is not None:
            where_parts.append("space = ?")
            values.append(space)
        if memory_type is not None:
            where_parts.append("type = ?")
            values.append(memory_type)
        if status is not None:
            where_parts.append("status = ?")
            values.append(status)
        elif not include_archived:
            where_parts.append("status != ?")
            values.append(STATUS_ARCHIVED)
        if workspace_uid is not None:
            where_parts.append("workspace_uid = ?")
            values.append(workspace_uid)

        where_clause = ""
        if where_parts:
            where_clause = f"WHERE {' AND '.join(where_parts)}"

        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            values.append(limit)

        query = (
            "SELECT * FROM memories "
            f"{where_clause} "
            "ORDER BY updated_at DESC, id ASC"
            f"{limit_clause}"
        )

        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def list_candidates(
        self,
        *,
        space: str | None = None,
        workspace_uid: str | None = None,
        embedding_profile: dict[str, object] | None = None,
        include_archived: bool = False,
    ) -> list[tuple[Memory, list[float]]]:
        where_parts: list[str] = []
        values: list[Any] = []

        if space is not None:
            where_parts.append("space = ?")
            values.append(space)
        if workspace_uid is not None:
            where_parts.append("workspace_uid = ?")
            values.append(workspace_uid)
        if embedding_profile is not None:
            where_parts.append("embedding_profile_json = ?")
            values.append(json.dumps(embedding_profile, sort_keys=True))
        if not include_archived:
            where_parts.append("status != ?")
            values.append(STATUS_ARCHIVED)

        where_clause = ""
        if where_parts:
            where_clause = f"WHERE {' AND '.join(where_parts)}"

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories "
                f"{where_clause} "
                "ORDER BY updated_at DESC, id ASC",
                values,
            ).fetchall()

        return [
            (self._row_to_memory(row), json.loads(row["embedding_json"]))
            for row in rows
        ]

    def replace_memory_chunks(
        self,
        *,
        memory_id: str,
        embedding_profile: dict[str, object],
        chunk_embeddings: list[tuple[ContentChunk, list[float]]],
    ) -> None:
        profile_json = json.dumps(embedding_profile, sort_keys=True)

        with self._connect() as connection:
            existing_memory = connection.execute(
                "SELECT id FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if existing_memory is None:
                raise NotFoundError(f"memory not found: {memory_id}")

            connection.execute(
                "DELETE FROM embedding_chunks WHERE memory_id = ? AND embedding_profile_json = ?",
                (memory_id, profile_json),
            )
            for chunk, embedding in chunk_embeddings:
                chunk_id = f"{memory_id}:{chunk.chunk_index}:{profile_json}"
                connection.execute(
                    """
                    INSERT INTO embedding_chunks (
                        id,
                        memory_id,
                        chunk_index,
                        content,
                        token_start,
                        token_end,
                        embedding_profile_json,
                        embedding_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        memory_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.token_start,
                        chunk.token_end,
                        profile_json,
                        json.dumps(embedding),
                    ),
                )

    def list_chunk_candidates(
        self,
        *,
        embedding_profile: dict[str, object],
        space: str | None = None,
        memory_type: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
    ) -> list[ChunkCandidate]:
        where_parts = ["chunks.embedding_profile_json = ?"]
        values: list[Any] = [json.dumps(embedding_profile, sort_keys=True)]

        if space is not None:
            where_parts.append("memories.space = ?")
            values.append(space)
        if memory_type is not None:
            where_parts.append("memories.type = ?")
            values.append(memory_type)
        if workspace_uid is not None:
            where_parts.append("memories.workspace_uid = ?")
            values.append(workspace_uid)
        if not include_archived:
            where_parts.append("memories.status != ?")
            values.append(STATUS_ARCHIVED)

        where_clause = " AND ".join(where_parts)

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    memories.*,
                    chunks.chunk_index,
                    chunks.content AS chunk_content,
                    chunks.embedding_json AS chunk_embedding_json
                FROM embedding_chunks AS chunks
                INNER JOIN memories ON memories.id = chunks.memory_id
                WHERE
                """
                + where_clause
                + " ORDER BY memories.updated_at DESC, memories.id ASC, chunks.chunk_index ASC",
                values,
            ).fetchall()

        candidates: list[ChunkCandidate] = []
        for row in rows:
            candidates.append(
                ChunkCandidate(
                    memory=self._row_to_memory(row),
                    embedding=json.loads(row["chunk_embedding_json"]),
                    chunk_index=row["chunk_index"],
                    matched_text=row["chunk_content"],
                    snippet=row["chunk_content"],
                )
            )
        return candidates

    def list_memories_needing_profile_reembedding(
        self,
        *,
        embedding_profile: dict[str, object],
        space: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> list[Memory]:
        where_parts = [
            "("
            "memories.embedding_profile_json != ? "
            "OR NOT EXISTS ("
            "SELECT 1 FROM embedding_chunks chunks "
            "WHERE chunks.memory_id = memories.id AND chunks.embedding_profile_json = ?"
            ")"
            ")"
        ]
        profile_json = json.dumps(embedding_profile, sort_keys=True)
        values: list[Any] = [profile_json, profile_json]

        if space is not None:
            where_parts.append("memories.space = ?")
            values.append(space)
        if workspace_uid is not None:
            where_parts.append("memories.workspace_uid = ?")
            values.append(workspace_uid)
        if not include_archived:
            where_parts.append("memories.status != ?")
            values.append(STATUS_ARCHIVED)

        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            values.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT memories.* FROM memories WHERE "
                + " AND ".join(where_parts)
                + " ORDER BY memories.updated_at DESC, memories.id ASC"
                + limit_clause,
                values,
            ).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def count_memories_needing_profile_reembedding(
        self,
        *,
        embedding_profile: dict[str, object],
        space: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
    ) -> int:
        where_parts = [
            "("
            "memories.embedding_profile_json != ? "
            "OR NOT EXISTS ("
            "SELECT 1 FROM embedding_chunks chunks "
            "WHERE chunks.memory_id = memories.id AND chunks.embedding_profile_json = ?"
            ")"
            ")"
        ]
        profile_json = json.dumps(embedding_profile, sort_keys=True)
        values: list[Any] = [profile_json, profile_json]

        if space is not None:
            where_parts.append("memories.space = ?")
            values.append(space)
        if workspace_uid is not None:
            where_parts.append("memories.workspace_uid = ?")
            values.append(workspace_uid)
        if not include_archived:
            where_parts.append("memories.status != ?")
            values.append(STATUS_ARCHIVED)

        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM memories WHERE "
                + " AND ".join(where_parts),
                values,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_embedding_job(
        self,
        *,
        job_id: str,
        state: str,
        total_count: int,
        processed_count: int,
        succeeded_count: int,
        failed_count: int,
        provider: str,
        model: str,
        embedding_profile: dict[str, object],
        error_message: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO embedding_jobs (
                    id,
                    state,
                    total_count,
                    processed_count,
                    succeeded_count,
                    failed_count,
                    provider,
                    model,
                    embedding_profile_json,
                    error_message,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    state,
                    total_count,
                    processed_count,
                    succeeded_count,
                    failed_count,
                    provider,
                    model,
                    json.dumps(embedding_profile, sort_keys=True),
                    error_message,
                    timestamp,
                    timestamp,
                    started_at,
                    completed_at,
                ),
            )
        return self.get_embedding_job(job_id)

    def update_embedding_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        assignments: list[str] = []
        values: list[Any] = []
        editable_fields = {
            "state",
            "total_count",
            "processed_count",
            "succeeded_count",
            "failed_count",
            "provider",
            "model",
            "error_message",
            "started_at",
            "completed_at",
        }
        for field_name in editable_fields:
            if field_name in updates:
                assignments.append(f"{field_name} = ?")
                values.append(updates[field_name])

        if "embedding_profile" in updates:
            assignments.append("embedding_profile_json = ?")
            values.append(json.dumps(updates["embedding_profile"], sort_keys=True))

        if not assignments:
            return self.get_embedding_job(job_id)

        assignments.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(job_id)

        with self._connect() as connection:
            result = connection.execute(
                f"UPDATE embedding_jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

        if result.rowcount == 0:
            raise NotFoundError(f"embedding job not found: {job_id}")
        return self.get_embedding_job(job_id)

    def get_embedding_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM embedding_jobs WHERE id = ?", (job_id,)
            ).fetchone()

        if row is None:
            raise NotFoundError(f"embedding job not found: {job_id}")
        return self._row_to_embedding_job(row)

    def list_embedding_jobs(
        self, *, state: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        where_clause = ""
        values: list[Any] = []
        if state is not None:
            where_clause = "WHERE state = ?"
            values.append(state)

        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            values.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM embedding_jobs "
                + where_clause
                + " ORDER BY updated_at DESC, id ASC"
                + limit_clause,
                values,
            ).fetchall()

        return [self._row_to_embedding_job(row) for row in rows]

    def _row_to_embedding_job(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "state": row["state"],
            "total_count": row["total_count"],
            "processed_count": row["processed_count"],
            "succeeded_count": row["succeeded_count"],
            "failed_count": row["failed_count"],
            "provider": row["provider"],
            "model": row["model"],
            "embedding_profile": json.loads(row["embedding_profile_json"]),
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            space=row["space"],
            workspace_uid=row["workspace_uid"],
            type=row["type"],
            content=row["content"],
            metadata=json.loads(row["metadata_json"]),
            status=row["status"],
            source=row["source"],
            confidence=row["confidence"],
            sensitivity=row["sensitivity"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
        )
