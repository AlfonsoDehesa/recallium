"""Domain models and validation helpers for Recallium Core."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any

from recallium.errors import ValidationError

SPACE_USER = "user"
SPACE_WORKSPACE = "workspace"
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"


def _validate_non_empty_string(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_optional_non_empty_string(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _validate_non_empty_string(field_name, value)


def _validate_metadata(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be an object")
    normalized = dict(metadata)
    try:
        json.dumps(normalized)
    except (TypeError, ValueError) as exc:
        raise ValidationError("metadata must be JSON-serializable") from exc
    return normalized


def validate_limit(limit: Any) -> int | None:
    if limit is None:
        return None
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValidationError("limit must be a positive integer")
    if limit < 1:
        raise ValidationError("limit must be a positive integer")
    return limit


def _validate_confidence(confidence: Any) -> float | None:
    if confidence is None:
        return None

    if not isinstance(confidence, (int, float)):
        raise ValidationError("confidence must be a number between 0 and 1")

    normalized = float(confidence)
    if not math.isfinite(normalized):
        raise ValidationError("confidence must be a finite number between 0 and 1")
    if normalized < 0 or normalized > 1:
        raise ValidationError("confidence must be between 0 and 1")

    return normalized


def validate_memory_create_input(
    *,
    space: Any,
    memory_type: Any,
    content: Any,
    workspace_uid: Any = None,
    metadata: Any = None,
    confidence: Any = None,
) -> dict[str, Any]:
    validated_space = _validate_non_empty_string("space", space)
    if validated_space not in {SPACE_USER, SPACE_WORKSPACE}:
        raise ValidationError("space must be one of: user, workspace")

    validated_workspace_uid = _validate_optional_non_empty_string(
        "workspace_uid", workspace_uid
    )

    if validated_space == SPACE_USER and validated_workspace_uid is not None:
        raise ValidationError("user memories must not include workspace_uid")

    if validated_space == SPACE_WORKSPACE and validated_workspace_uid is None:
        raise ValidationError("workspace_uid is required for workspace memories")

    return {
        "space": validated_space,
        "type": _validate_non_empty_string("type", memory_type),
        "content": _validate_non_empty_string("content", content),
        "workspace_uid": validated_workspace_uid,
        "metadata": _validate_metadata(metadata),
        "confidence": _validate_confidence(confidence),
    }


def validate_memory_update_input(
    *,
    memory_type: Any = None,
    content: Any = None,
    metadata: Any = None,
    confidence: Any = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    if memory_type is not None:
        updates["type"] = _validate_non_empty_string("type", memory_type)
    if content is not None:
        updates["content"] = _validate_non_empty_string("content", content)
    if metadata is not None:
        updates["metadata"] = _validate_metadata(metadata)
    if confidence is not None:
        updates["confidence"] = _validate_confidence(confidence)

    if not updates:
        raise ValidationError("at least one update field is required")

    return updates


@dataclass(slots=True)
class Memory:
    id: str
    space: str
    type: str
    content: str
    status: str = STATUS_ACTIVE
    workspace_uid: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    confidence: float | None = None
    sensitivity: str | None = None
    created_at: str = ""
    updated_at: str = ""
    last_accessed_at: str | None = None

    def __post_init__(self) -> None:
        self.id = _validate_non_empty_string("id", self.id)
        self.space = _validate_non_empty_string("space", self.space)
        if self.space not in {SPACE_USER, SPACE_WORKSPACE}:
            raise ValidationError("space must be one of: user, workspace")

        self.type = _validate_non_empty_string("type", self.type)
        self.content = _validate_non_empty_string("content", self.content)

        self.status = _validate_non_empty_string("status", self.status)
        if self.status not in {STATUS_ACTIVE, STATUS_ARCHIVED}:
            raise ValidationError("status must be one of: active, archived")

        self.workspace_uid = _validate_optional_non_empty_string(
            "workspace_uid", self.workspace_uid
        )
        if self.space == SPACE_USER and self.workspace_uid is not None:
            raise ValidationError("user memories must not include workspace_uid")
        if self.space == SPACE_WORKSPACE and self.workspace_uid is None:
            raise ValidationError("workspace_uid is required for workspace memories")

        self.metadata = _validate_metadata(self.metadata)
        self.confidence = _validate_confidence(self.confidence)
        self.source = _validate_optional_non_empty_string("source", self.source)
        self.sensitivity = _validate_optional_non_empty_string(
            "sensitivity", self.sensitivity
        )

        self.created_at = _validate_non_empty_string("created_at", self.created_at)
        self.updated_at = _validate_non_empty_string("updated_at", self.updated_at)
        self.last_accessed_at = _validate_optional_non_empty_string(
            "last_accessed_at", self.last_accessed_at
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Memory:
        return cls(**payload)

    @classmethod
    def from_json(cls, payload: str) -> Memory:
        return cls.from_dict(json.loads(payload))


@dataclass(slots=True)
class SearchResult:
    memory: Memory
    score: float
    rank: int
    matched_text: str | None = None
    snippet: str | None = None
    chunk_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.memory, Memory):
            raise ValidationError("memory must be a Memory instance")
        if not isinstance(self.score, (int, float)):
            raise ValidationError("score must be numeric")
        self.score = float(self.score)
        if not math.isfinite(self.score):
            raise ValidationError("score must be a finite number")
        if not isinstance(self.rank, int) or self.rank < 1:
            raise ValidationError("rank must be a positive integer")
        self.matched_text = _validate_optional_non_empty_string(
            "matched_text", self.matched_text
        )
        self.snippet = _validate_optional_non_empty_string("snippet", self.snippet)
        if self.chunk_index is not None:
            if not isinstance(self.chunk_index, int) or self.chunk_index < 0:
                raise ValidationError("chunk_index must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "memory": self.memory.to_dict(),
            "score": self.score,
            "rank": self.rank,
        }
        if self.matched_text is not None:
            payload["matched_text"] = self.matched_text
        if self.snippet is not None:
            payload["snippet"] = self.snippet
        if self.chunk_index is not None:
            payload["chunk_index"] = self.chunk_index
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SearchResult:
        memory_payload = payload.get("memory")
        if not isinstance(memory_payload, dict):
            raise ValidationError("memory must be an object")
        return cls(
            memory=Memory.from_dict(memory_payload),
            score=payload["score"],
            rank=payload["rank"],
            matched_text=payload.get("matched_text"),
            snippet=payload.get("snippet"),
            chunk_index=payload.get("chunk_index"),
        )

    @classmethod
    def from_json(cls, payload: str) -> SearchResult:
        return cls.from_dict(json.loads(payload))
