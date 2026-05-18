"""Public service API for Recallium Core."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from recallium.embeddings import LocalEmbeddingProvider
from recallium.errors import ValidationError
from recallium.models import (
    SPACE_USER,
    SPACE_WORKSPACE,
    Memory,
    SearchResult,
    validate_limit,
    validate_memory_create_input,
    validate_memory_update_input,
)
from recallium.search import rank_memory_candidates
from recallium.storage import SQLiteMemoryStore, utc_now_iso


def _default_db_path() -> Path:
    xdg_data_home = Path.home() / ".local" / "share"
    return xdg_data_home / "recallium" / "recallium.db"


def _validate_optional_string(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


class RecalliumCore:
    """High-level service object used by clients and adapters."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        embedding_provider: LocalEmbeddingProvider | None = None,
    ) -> None:
        selected_path = db_path if db_path is not None else _default_db_path()
        self.store = SQLiteMemoryStore(selected_path)
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider()

    def add_memory(
        self,
        space: str,
        type: str,
        content: str,
        workspace_uid: str | None = None,
        metadata: dict[str, object] | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> Memory:
        payload = validate_memory_create_input(
            space=space,
            memory_type=type,
            content=content,
            workspace_uid=workspace_uid,
            metadata=metadata,
            confidence=confidence,
        )

        timestamp = utc_now_iso()
        memory = Memory(
            id=str(uuid4()),
            space=payload["space"],
            type=payload["type"],
            content=payload["content"],
            workspace_uid=payload["workspace_uid"],
            metadata=payload["metadata"],
            source=_validate_optional_string("source", source),
            confidence=payload["confidence"],
            sensitivity=_validate_optional_string("sensitivity", sensitivity),
            created_at=timestamp,
            updated_at=timestamp,
        )
        embedding = self.embedding_provider.embed(memory.content)
        return self.store.insert_memory(memory, embedding)

    def search_user_memories(
        self,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[SearchResult]:
        candidates = self.store.list_candidates(
            space=SPACE_USER, include_archived=include_archived
        )
        validated_limit = validate_limit(limit)
        assert validated_limit is not None
        return rank_memory_candidates(
            query=query,
            candidates=candidates,
            embedding_provider=self.embedding_provider,
            limit=validated_limit,
        )

    def search_workspace_memories(
        self,
        query: str,
        workspace_uid: str | None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[SearchResult]:
        workspace_uid = _validate_optional_string("workspace_uid", workspace_uid)
        if workspace_uid is None:
            raise ValidationError("workspace_uid is required for workspace search")

        candidates = self.store.list_candidates(
            space=SPACE_WORKSPACE,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
        )
        validated_limit = validate_limit(limit)
        assert validated_limit is not None
        return rank_memory_candidates(
            query=query,
            candidates=candidates,
            embedding_provider=self.embedding_provider,
            limit=validated_limit,
        )

    def list_memories(
        self,
        space: str | None = None,
        type: str | None = None,
        status: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> list[Memory]:
        workspace_uid = _validate_optional_string("workspace_uid", workspace_uid)

        return self.store.list_memories(
            space=space,
            memory_type=type,
            status=status,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
            limit=validate_limit(limit),
        )

    def get_memory(self, memory_id: str) -> Memory:
        memory = self.store.get_memory(memory_id)
        touched = self.store.touch_last_accessed_at(memory_id)
        if touched is not None:
            memory = touched
        return memory

    def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        type: str | None = None,
        metadata: dict[str, object] | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> Memory:
        has_model_updates = any(
            value is not None for value in (type, content, metadata, confidence)
        )
        validated: dict[str, object]
        if has_model_updates:
            validated = validate_memory_update_input(
                memory_type=type,
                content=content,
                metadata=metadata,
                confidence=confidence,
            )
        else:
            validated = {}

        if source is not None:
            validated["source"] = _validate_optional_string("source", source)
        if sensitivity is not None:
            validated["sensitivity"] = _validate_optional_string(
                "sensitivity", sensitivity
            )
        if not validated:
            raise ValidationError("at least one update field is required")
        content_update = validated.get("content")
        if isinstance(content_update, str):
            validated["embedding"] = self.embedding_provider.embed(content_update)

        return self.store.update_memory(memory_id, **validated)

    def archive_memory(self, memory_id: str) -> Memory:
        return self.store.archive_memory(memory_id)
