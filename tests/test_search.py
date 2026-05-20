from pathlib import Path

import pytest

from recallium.embeddings import BuiltinFastEmbedProvider, chunk_text_for_profile
from recallium.errors import EmbeddingGenerationError, ValidationError
from recallium.models import SPACE_USER, STATUS_ACTIVE, Memory, SearchResult
from recallium.search import ChunkCandidate, rank_memory_candidates
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


def test_provider_profile_matches_fastembed_spec() -> None:
    provider = BuiltinFastEmbedProvider()

    assert provider.embedding_profile == {
        "provider": "builtin-fastembed",
        "model": "jinaai/jina-embeddings-v2-small-en",
        "dimensions": 512,
        "version": "1",
        "profile": "builtin-fastembed-jina-v2-small-en-v1",
        "max_tokens": 8192,
        "chunk_tokens": 6144,
        "chunk_overlap_tokens": 512,
        "query_prompt_policy": "raw",
    }


def test_real_embedding_shape_is_512() -> None:
    pytest.importorskip("fastembed")
    provider = BuiltinFastEmbedProvider()
    vector = provider.embed("Recallium should return stable embedding dimensions")

    assert len(vector) == 512
    assert any(value != 0.0 for value in vector)


def test_semantic_search_returns_relevant_memory(tmp_path: Path) -> None:
    provider = BuiltinFastEmbedProvider()
    store = SQLiteMemoryStore(tmp_path / "semantic.db")

    memory = build_memory("mem-1", "Need to fix a release-blocking software bug")
    store.insert_memory(
        memory,
        embedding=provider.embed(memory.content),
        embedding_profile=provider.embedding_profile,
    )

    candidates = store.list_candidates(
        space=SPACE_USER, embedding_profile=provider.embedding_profile
    )
    results = rank_memory_candidates(
        query="repair software defect",
        candidates=candidates,
        embedding_provider=provider,
    )

    assert results
    assert results[0].memory.id == "mem-1"
    assert results[0].score > 0
    assert results[0].rank == 1


def test_ranking_includes_score_and_rank_order() -> None:
    provider = BuiltinFastEmbedProvider()

    primary = build_memory("mem-1", "buy apples bananas and fresh fruit")
    secondary = build_memory("mem-2", "plan database migration rollback")
    candidates = [
        (secondary, provider.embed(secondary.content)),
        (primary, provider.embed(primary.content)),
    ]

    results = rank_memory_candidates(
        query="fresh fruit groceries",
        candidates=candidates,
        embedding_provider=provider,
    )

    assert [result.memory.id for result in results] == ["mem-1", "mem-2"]
    assert results[0].rank == 1
    assert results[1].rank == 2
    assert results[0].score >= results[1].score


def test_rank_memory_candidates_rejects_empty_query() -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(ValidationError, match="query"):
        rank_memory_candidates(query="   ", candidates=[], embedding_provider=provider)


def test_similarity_rejects_dimension_mismatch() -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(EmbeddingGenerationError, match="same size"):
        provider.similarity([1.0, 0.0], [1.0])


def test_rank_memory_candidates_rejects_invalid_limit() -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(ValidationError, match="positive integer"):
        rank_memory_candidates(
            query="fix software defect",
            candidates=[],
            embedding_provider=provider,
            limit=0,
        )


def test_chunk_text_for_profile_creates_single_chunk_at_boundary() -> None:
    provider = BuiltinFastEmbedProvider()
    profile = dict(provider.embedding_profile)
    profile["chunk_tokens"] = 4
    profile["chunk_overlap_tokens"] = 1

    text = "one two three four"
    chunks = chunk_text_for_profile(text, profile)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == text
    assert chunks[0].token_start == 0
    assert chunks[0].token_end == 4


def test_chunk_text_for_profile_splits_with_overlap_without_truncation() -> None:
    provider = BuiltinFastEmbedProvider()
    profile = dict(provider.embedding_profile)
    profile["chunk_tokens"] = 4
    profile["chunk_overlap_tokens"] = 1

    text = "zero one two three four five six"
    chunks = chunk_text_for_profile(text, profile)

    assert [chunk.text for chunk in chunks] == [
        "zero one two three",
        "three four five six",
    ]
    assert [(chunk.token_start, chunk.token_end) for chunk in chunks] == [
        (0, 4),
        (3, 7),
    ]
    covered_tokens = []
    for chunk in chunks:
        covered_tokens.extend(chunk.text.split())
    assert "six" in covered_tokens


def test_chunk_text_for_profile_rejects_overlap_greater_than_or_equal_to_chunk_size() -> (
    None
):
    provider = BuiltinFastEmbedProvider()
    profile = dict(provider.embedding_profile)
    profile["chunk_tokens"] = 4
    profile["chunk_overlap_tokens"] = 4

    with pytest.raises(
        EmbeddingGenerationError,
        match="chunk_overlap_tokens must be smaller than chunk_tokens",
    ):
        chunk_text_for_profile("zero one two three", profile)


def test_rank_memory_candidates_deduplicates_parent_memory_by_best_chunk() -> None:
    provider = BuiltinFastEmbedProvider()
    memory = build_memory("mem-1", "parent memory")

    candidates: list[ChunkCandidate] = [
        ChunkCandidate(
            memory=memory,
            embedding=provider.embed("today I should buy groceries and fruit"),
            chunk_index=0,
            matched_text="today I should buy groceries and fruit",
            snippet="buy groceries and fruit",
        ),
        ChunkCandidate(
            memory=memory,
            embedding=provider.embed("database migrations and SQL rollback planning"),
            chunk_index=1,
            matched_text="database migrations and SQL rollback planning",
            snippet="SQL rollback planning",
        ),
    ]

    results = rank_memory_candidates(
        query="buy fruit",
        candidates=candidates,
        embedding_provider=provider,
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-1"
    assert results[0].chunk_index == 0
    assert results[0].matched_text == "today I should buy groceries and fruit"
    assert results[0].snippet == "buy groceries and fruit"


def test_search_result_json_round_trip_with_matched_context() -> None:
    result = SearchResult(
        memory=build_memory("mem-1", "hello world"),
        score=0.91,
        rank=1,
        matched_text="hello",
        snippet="hello",
        chunk_index=2,
    )

    restored = SearchResult.from_json(result.to_json())

    assert restored.memory.id == result.memory.id
    assert restored.score == result.score
    assert restored.rank == result.rank
    assert restored.matched_text == "hello"
    assert restored.snippet == "hello"
    assert restored.chunk_index == 2


def test_archived_filter_is_respected_by_candidate_selection(tmp_path: Path) -> None:
    provider = BuiltinFastEmbedProvider()
    store = SQLiteMemoryStore(tmp_path / "archive-filter.db")

    active = build_memory("active", "buy coffee beans")
    archived = build_memory("archived", "purchase coffee beans")
    store.insert_memory(
        active,
        embedding=provider.embed(active.content),
        embedding_profile=provider.embedding_profile,
    )
    store.insert_memory(
        archived,
        embedding=provider.embed(archived.content),
        embedding_profile=provider.embedding_profile,
    )
    store.archive_memory("archived")

    active_candidates = store.list_candidates(
        space=SPACE_USER, embedding_profile=provider.embedding_profile
    )
    active_results = rank_memory_candidates(
        query="buy coffee",
        candidates=active_candidates,
        embedding_provider=provider,
    )
    assert [result.memory.id for result in active_results] == ["active"]

    all_candidates = store.list_candidates(
        space=SPACE_USER,
        embedding_profile=provider.embedding_profile,
        include_archived=True,
    )
    all_results = rank_memory_candidates(
        query="buy coffee",
        candidates=all_candidates,
        embedding_provider=provider,
    )
    assert [result.memory.id for result in all_results] == ["active", "archived"]
