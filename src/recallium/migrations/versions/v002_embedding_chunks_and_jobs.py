"""Schema version 2: embedding chunks and jobs tables."""

from __future__ import annotations

import sqlite3


def upgrade(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_chunks (
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
        CREATE INDEX IF NOT EXISTS idx_embedding_chunks_memory_profile
        ON embedding_chunks(memory_id, embedding_profile_json, chunk_index)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embedding_chunks_profile_memory
        ON embedding_chunks(embedding_profile_json, memory_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_jobs (
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
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embedding_jobs_updated_at
        ON embedding_jobs(updated_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embedding_jobs_state_updated
        ON embedding_jobs(state, updated_at)
        """
    )
