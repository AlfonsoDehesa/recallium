"""Domain models and validation helpers for Recallium Core."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
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
    return dict(metadata)


def _validate_confidence(confidence: Any) -> float | None:
    if confidence is None:
        return None

    if not isinstance(confidence, (int, float)):
        raise ValidationError("confidence must be a number between 0 and 1")

    normalized = float(confidence)
    if normalized < 0 or normalized > 1:
        raise ValidationError("confidence must be between 0 and 1")

    return normalized


def validate_memory_create_input(
    *,
    space: Any,
    memory_type: Any,
    content: Any,
    workspace_id: Any = None,
    workspace_path: Any = None,
    metadata: Any = None,
    confidence: Any = None,
) -> dict[str, Any]:
    validated_space = _validate_non_empty_string("space", space)
    if validated_space not in {SPACE_USER, SPACE_WORKSPACE}:
        raise ValidationError("space must be one of: user, workspace")

    validated_workspace_id = _validate_optional_non_empty_string("workspace_id", workspace_id)
    validated_workspace_path = _validate_optional_non_empty_string("workspace_path", workspace_path)

    if validated_space == SPACE_WORKSPACE and not (
        validated_workspace_id or validated_workspace_path
    ):
        raise ValidationError("workspace_id or workspace_path is required for workspace memories")

    return {
        "space": validated_space,
        "type": _validate_non_empty_string("type", memory_type),
        "content": _validate_non_empty_string("content", content),
        "workspace_id": validated_workspace_id,
        "workspace_path": validated_workspace_path,
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
    workspace_id: str | None = None
    workspace_path: str | None = None
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

        self.workspace_id = _validate_optional_non_empty_string("workspace_id", self.workspace_id)
        self.workspace_path = _validate_optional_non_empty_string("workspace_path", self.workspace_path)
        if self.space == SPACE_WORKSPACE and not (self.workspace_id or self.workspace_path):
            raise ValidationError("workspace_id or workspace_path is required for workspace memories")

        self.metadata = _validate_metadata(self.metadata)
        self.confidence = _validate_confidence(self.confidence)
        self.source = _validate_optional_non_empty_string("source", self.source)
        self.sensitivity = _validate_optional_non_empty_string("sensitivity", self.sensitivity)

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

    def __post_init__(self) -> None:
        if not isinstance(self.memory, Memory):
            raise ValidationError("memory must be a Memory instance")
        if not isinstance(self.score, (int, float)):
            raise ValidationError("score must be numeric")
        self.score = float(self.score)
        if not isinstance(self.rank, int) or self.rank < 1:
            raise ValidationError("rank must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "score": self.score,
            "rank": self.rank,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SearchResult:
        memory_payload = payload.get("memory")
        return cls(
            memory=Memory.from_dict(memory_payload),
            score=payload["score"],
            rank=payload["rank"],
        )

    @classmethod
    def from_json(cls, payload: str) -> SearchResult:
        return cls.from_dict(json.loads(payload))
