"""SQLite persistence layer for Recallium memories."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from recallium.errors import NotFoundError
from recallium.models import Memory, SPACE_WORKSPACE, STATUS_ARCHIVED


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class SQLiteMemoryStore:
    """Small SQLite-backed store for memory records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    space TEXT NOT NULL,
                    workspace_id TEXT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    source TEXT NULL,
                    confidence REAL NULL,
                    sensitivity TEXT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_space_status ON memories(space, status)"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_space_workspace_status
                ON memories(space, workspace_id, status)
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at)"
            )
            connection.execute("PRAGMA user_version = 1")

    def insert_memory(self, memory: Memory, embedding: list[float]) -> Memory:
        workspace_identifier = memory.workspace_id
        if memory.space == SPACE_WORKSPACE and workspace_identifier is None:
            workspace_identifier = memory.workspace_path

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, space, workspace_id, type, content, metadata_json,
                    status, source, confidence, sensitivity, embedding_json,
                    created_at, updated_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.space,
                    workspace_identifier,
                    memory.type,
                    memory.content,
                    json.dumps(memory.metadata, sort_keys=True),
                    memory.status,
                    memory.source,
                    memory.confidence,
                    memory.sensitivity,
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

    def list_memories(
        self,
        *,
        space: str | None = None,
        memory_type: str | None = None,
        status: str | None = None,
        workspace_id: str | None = None,
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
        if workspace_id is not None:
            where_parts.append("workspace_id = ?")
            values.append(workspace_id)

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
        workspace_id: str | None = None,
        include_archived: bool = False,
    ) -> list[tuple[Memory, list[float]]]:
        where_parts: list[str] = []
        values: list[Any] = []

        if space is not None:
            where_parts.append("space = ?")
            values.append(space)
        if workspace_id is not None:
            where_parts.append("workspace_id = ?")
            values.append(workspace_id)
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

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            space=row["space"],
            workspace_id=row["workspace_id"],
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
