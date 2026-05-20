"""Schema version 1: base memories table and indexes."""

from __future__ import annotations

import sqlite3


def upgrade(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
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
        "CREATE INDEX IF NOT EXISTS idx_memories_space_status ON memories(space, status)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_space_workspace_status
        ON memories(space, workspace_uid, status)
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at)"
    )
