"""Versioned schema migrations for Recallium SQLite storage."""

from __future__ import annotations

from recallium.migrations.runner import Migration
from recallium.migrations.versions import (
    v001_initial_memory_schema,
    v002_embedding_chunks_and_jobs,
)


def list_migrations() -> list[Migration]:
    return [
        Migration(
            version=1,
            name="initial_memory_schema",
            upgrade=v001_initial_memory_schema.upgrade,
        ),
        Migration(
            version=2,
            name="embedding_chunks_and_jobs",
            upgrade=v002_embedding_chunks_and_jobs.upgrade,
        ),
    ]
