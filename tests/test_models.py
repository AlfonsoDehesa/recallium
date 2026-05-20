import json
from typing import Any

import pytest

from recallium.errors import ValidationError
from recallium.models import (
    SPACE_USER,
    SPACE_WORKSPACE,
    STATUS_ACTIVE,
    Memory,
    SearchResult,
    validate_limit,
    validate_memory_create_input,
    validate_memory_update_input,
)


def build_memory(**overrides: object) -> Memory:
    payload = {
        "id": "mem-1",
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


def test_validate_memory_create_input_workspace_requires_workspace_field() -> None:
    with pytest.raises(ValidationError, match="workspace_uid"):
        validate_memory_create_input(
            space=SPACE_WORKSPACE,
            memory_type="fact",
            content="hello",
        )


def test_validate_memory_create_input_rejects_workspace_uid_for_user_memory() -> None:
    with pytest.raises(ValidationError, match="user memories must not include"):
        validate_memory_create_input(
            space=SPACE_USER,
            memory_type="fact",
            content="hello",
            workspace_uid="workspace-alpha",
        )


def test_validate_memory_create_input_rejects_invalid_fields() -> None:
    with pytest.raises(ValidationError, match="type"):
        validate_memory_create_input(space=SPACE_USER, memory_type="", content="hello")

    with pytest.raises(ValidationError, match="content"):
        validate_memory_create_input(space=SPACE_USER, memory_type="fact", content="  ")

    with pytest.raises(ValidationError, match="metadata"):
        validate_memory_create_input(
            space=SPACE_USER,
            memory_type="fact",
            content="hello",
            metadata=["not", "an", "object"],
        )

    with pytest.raises(ValidationError, match="confidence"):
        validate_memory_create_input(
            space=SPACE_USER,
            memory_type="fact",
            content="hello",
            confidence=2,
        )

    with pytest.raises(ValidationError, match="confidence"):
        validate_memory_create_input(
            space=SPACE_USER,
            memory_type="fact",
            content="hello",
            confidence=float("nan"),
        )

    with pytest.raises(ValidationError, match="JSON-serializable"):
        validate_memory_create_input(
            space=SPACE_USER,
            memory_type="fact",
            content="hello",
            metadata={"bad": object()},
        )


def test_validate_limit_requires_positive_integer() -> None:
    assert validate_limit(None) is None
    assert validate_limit(3) == 3

    with pytest.raises(ValidationError, match="positive integer"):
        validate_limit(0)

    with pytest.raises(ValidationError, match="positive integer"):
        validate_limit(True)


def test_validate_memory_update_input_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError, match="at least one update field"):
        validate_memory_update_input()


def test_validate_memory_update_input_validates_fields() -> None:
    with pytest.raises(ValidationError, match="type"):
        validate_memory_update_input(memory_type="")

    with pytest.raises(ValidationError, match="metadata"):
        validate_memory_update_input(metadata="not-an-object")

    with pytest.raises(ValidationError, match="confidence"):
        validate_memory_update_input(confidence=-0.1)


def test_memory_serialization_round_trip_is_stable_and_json_compatible() -> None:
    memory = build_memory(confidence=0.75)

    as_dict = memory.to_dict()
    assert as_dict["type"] == "fact"
    assert as_dict["confidence"] == 0.75

    as_json = memory.to_json()
    parsed = json.loads(as_json)
    assert parsed == as_dict

    restored = Memory.from_json(as_json)
    assert restored == memory


def test_memory_workspace_validation_applies_to_dataclass() -> None:
    with pytest.raises(ValidationError, match="workspace_uid"):
        build_memory(space=SPACE_WORKSPACE)

    with pytest.raises(ValidationError, match="user memories must not include"):
        build_memory(space=SPACE_USER, workspace_uid="workspace-alpha")


def test_search_result_serialization_round_trip() -> None:
    result = SearchResult(memory=build_memory(), score=0.88, rank=1)

    payload = result.to_dict()
    assert payload["score"] == 0.88
    assert payload["rank"] == 1
    assert payload["memory"]["id"] == "mem-1"
    assert "matched_text" not in payload
    assert "snippet" not in payload
    assert "chunk_index" not in payload

    restored = SearchResult.from_json(result.to_json())
    assert restored == result


def test_search_result_from_dict_accepts_legacy_payload_without_matched_context() -> (
    None
):
    payload = {
        "memory": build_memory().to_dict(),
        "score": 0.72,
        "rank": 2,
    }

    restored = SearchResult.from_dict(payload)

    assert restored.memory.id == "mem-1"
    assert restored.score == 0.72
    assert restored.rank == 2
    assert restored.matched_text is None
    assert restored.snippet is None
    assert restored.chunk_index is None


def test_search_result_rejects_invalid_values() -> None:
    bad_memory: Any = "not-memory"
    with pytest.raises(ValidationError, match="memory"):
        SearchResult(memory=bad_memory, score=0.1, rank=1)

    bad_score: Any = "bad"
    with pytest.raises(ValidationError, match="score"):
        SearchResult(memory=build_memory(), score=bad_score, rank=1)

    with pytest.raises(ValidationError, match="score"):
        SearchResult(memory=build_memory(), score=float("nan"), rank=1)

    with pytest.raises(ValidationError, match="rank"):
        SearchResult(memory=build_memory(), score=0.1, rank=0)
