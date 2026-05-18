from pathlib import Path

import pytest

from recallium.embeddings import LocalEmbeddingProvider
from recallium.errors import ValidationError
from recallium.models import SPACE_USER, STATUS_ACTIVE, Memory
from recallium.search import rank_memory_candidates
from recallium.storage import SQLiteMemoryStore


def build_memory(memory_id: str, content: str, **overrides: object) -> Memory:
    payload = {
        "id": memory_id,
        "space": SPACE_USER,
        "type": "note",
        "content": content,
        "status": STATUS_ACTIVE,
        "metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return Memory(**payload)


def test_semantic_search_matches_synonym_without_exact_term(tmp_path: Path) -> None:
    provider = LocalEmbeddingProvider()
    store = SQLiteMemoryStore(tmp_path / "semantic.db")

    memory = build_memory("mem-1", "Need to fix bug before release")
    store.insert_memory(memory, embedding=provider.embed(memory.content))

    candidates = store.list_candidates(space=SPACE_USER)
    results = rank_memory_candidates(query="repair defect", candidates=candidates, embedding_provider=provider)

    assert results
    assert results[0].memory.id == "mem-1"
    assert results[0].score > 0
    assert results[0].rank == 1


def test_ranking_includes_score_and_rank_order() -> None:
    provider = LocalEmbeddingProvider()

    primary = build_memory("mem-1", "buy groceries and fruit")
    secondary = build_memory("mem-2", "purchase household supplies")
    candidates = [
        (secondary, provider.embed(secondary.content)),
        (primary, provider.embed(primary.content)),
    ]

    results = rank_memory_candidates(query="purchase fruit", candidates=candidates, embedding_provider=provider)

    assert [result.memory.id for result in results] == ["mem-1", "mem-2"]
    assert results[0].rank == 1
    assert results[1].rank == 2
    assert results[0].score >= results[1].score


def test_rank_memory_candidates_rejects_empty_query() -> None:
    provider = LocalEmbeddingProvider()

    with pytest.raises(ValidationError, match="query"):
        rank_memory_candidates(query="   ", candidates=[], embedding_provider=provider)


def test_rank_memory_candidates_excludes_zero_score_results() -> None:
    provider = LocalEmbeddingProvider()
    unrelated = build_memory("mem-1", "apples oranges bananas")

    results = rank_memory_candidates(
        query="repair defect",
        candidates=[(unrelated, provider.embed(unrelated.content))],
        embedding_provider=provider,
    )

    assert results == []


def test_rank_memory_candidates_rejects_invalid_limit() -> None:
    provider = LocalEmbeddingProvider()

    with pytest.raises(ValidationError, match="positive integer"):
        rank_memory_candidates(
            query="repair defect",
            candidates=[],
            embedding_provider=provider,
            limit=0,
        )


def test_archived_filter_is_respected_by_candidate_selection(tmp_path: Path) -> None:
    provider = LocalEmbeddingProvider()
    store = SQLiteMemoryStore(tmp_path / "archive-filter.db")

    active = build_memory("active", "buy coffee beans")
    archived = build_memory("archived", "purchase coffee beans")
    store.insert_memory(active, embedding=provider.embed(active.content))
    store.insert_memory(archived, embedding=provider.embed(archived.content))
    store.archive_memory("archived")

    active_candidates = store.list_candidates(space=SPACE_USER)
    active_results = rank_memory_candidates(
        query="buy coffee",
        candidates=active_candidates,
        embedding_provider=provider,
    )
    assert [result.memory.id for result in active_results] == ["active"]

    all_candidates = store.list_candidates(space=SPACE_USER, include_archived=True)
    all_results = rank_memory_candidates(
        query="buy coffee",
        candidates=all_candidates,
        embedding_provider=provider,
    )
    assert [result.memory.id for result in all_results] == ["active", "archived"]
