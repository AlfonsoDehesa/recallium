from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from recollectium.embeddings import (
    BuiltinFastEmbedProvider,
    _fastembed_readiness_worker,
    chunk_text_for_profile,
)
from recollectium.errors import (
    EmbeddingDimensionMismatchError,
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
    ValidationError,
)
from recollectium.models import SPACE_USER, STATUS_ACTIVE, Memory, SearchResult
from recollectium.search import ChunkCandidate, rank_memory_candidates
from recollectium.storage import SQLiteMemoryStore


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
    vector = provider.embed("Recollectium should return stable embedding dimensions")

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


def test_chunk_text_for_profile_handles_empty_text_and_bad_token_settings() -> None:
    provider = BuiltinFastEmbedProvider()
    profile = dict(provider.embedding_profile)

    chunks = chunk_text_for_profile("   ", profile)
    assert len(chunks) == 1

    empty_chunk = chunks[0]
    assert empty_chunk.text == ""
    assert empty_chunk.token_start == 0
    assert empty_chunk.token_end == 0

    bad_chunk_profile = dict(profile)
    bad_chunk_profile["chunk_tokens"] = True
    with pytest.raises(EmbeddingGenerationError, match="chunk_tokens"):
        chunk_text_for_profile("hello", bad_chunk_profile)

    bad_overlap_profile = dict(profile)
    bad_overlap_profile["chunk_overlap_tokens"] = -1
    with pytest.raises(EmbeddingGenerationError, match="chunk_overlap_tokens"):
        chunk_text_for_profile("hello", bad_overlap_profile)


def test_builtin_fastembed_embed_handles_empty_text_and_empty_provider_result() -> None:
    provider = BuiltinFastEmbedProvider()
    assert provider.embed("   ") == [0.0] * provider.dimensions

    class EmptyEmbedder:
        def embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
            return []

    provider._embedder = EmptyEmbedder()
    with pytest.raises(EmbeddingGenerationError, match="no vector"):
        provider.embed("hello")


def test_builtin_fastembed_similarity_validates_vectors() -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(EmbeddingGenerationError, match="same size"):
        provider.similarity([1.0, 0.0], [1.0])

    with pytest.raises(EmbeddingGenerationError, match="embedding vector size"):
        provider.similarity([1.0, 0.0], [1.0, 0.0])

    assert (
        provider.similarity([0.0] * provider.dimensions, [1.0] * provider.dimensions)
        == 0.0
    )


def test_builtin_fastembed_get_embedder_import_load_and_cache_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BuiltinFastEmbedProvider._shared_embedders.clear()
    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(EmbeddingProviderUnavailableError):
        BuiltinFastEmbedProvider()._get_embedder()

    fastembed_module = ModuleType("fastembed")

    class BrokenTextEmbedding:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("model unavailable")

    setattr(fastembed_module, "TextEmbedding", BrokenTextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)
    with pytest.raises(EmbeddingModelUnavailableError, match="failed to load"):
        BuiltinFastEmbedProvider()._get_embedder()

    class WorkingTextEmbedding:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
            return [[1.0] + [0.0] * 511 for _text in texts]

    setattr(fastembed_module, "TextEmbedding", WorkingTextEmbedding)
    provider = BuiltinFastEmbedProvider()
    embedder = provider._get_embedder()
    assert provider._get_embedder() is embedder
    other_provider = BuiltinFastEmbedProvider()
    assert other_provider._get_embedder() is embedder
    BuiltinFastEmbedProvider._shared_embedders.clear()


def test_builtin_fastembed_dimension_validation_and_zero_ready_check() -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(EmbeddingDimensionMismatchError, match="expected 512"):
        provider._validate_dimensions([1.0])

    class ZeroProvider(BuiltinFastEmbedProvider):
        def embed(self, text: str) -> list[float]:
            return [0.0] * self.dimensions

    with pytest.raises(EmbeddingGenerationError, match="empty vector"):
        ZeroProvider()._ensure_ready_unbounded()

    class ReadyProvider(BuiltinFastEmbedProvider):
        def embed(self, text: str) -> list[float]:
            return [1.0] + [0.0] * (self.dimensions - 1)

    ReadyProvider()._ensure_ready_unbounded()

    zero_vector = [0.0] * provider.dimensions
    assert provider._normalize_vector(zero_vector) == zero_vector


class FakeConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.closed = False

    def send(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)

    def close(self) -> None:
        self.closed = True


def test_fastembed_readiness_worker_reports_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReadyProvider:
        def _ensure_ready_unbounded(self) -> None:
            pass

    monkeypatch.setattr(
        "recollectium.embeddings.BuiltinFastEmbedProvider", ReadyProvider
    )
    success_connection = FakeConnection()
    _fastembed_readiness_worker(cast(Any, success_connection))
    assert success_connection.messages == [{"ok": True}]
    assert success_connection.closed is True

    class FailingProvider:
        def _ensure_ready_unbounded(self) -> None:
            raise EmbeddingModelUnavailableError("missing model")

    monkeypatch.setattr(
        "recollectium.embeddings.BuiltinFastEmbedProvider", FailingProvider
    )
    failure_connection = FakeConnection()
    _fastembed_readiness_worker(cast(Any, failure_connection))
    assert failure_connection.messages == [
        {
            "ok": False,
            "error_type": "EmbeddingModelUnavailableError",
            "message": "missing model",
        }
    ]
    assert failure_connection.closed is True


class FakeProcess:
    def __init__(self, alive_results: list[bool]) -> None:
        self.alive_results = alive_results
        self.started = False
        self.terminated = False
        self.killed = False

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        if self.alive_results:
            return self.alive_results.pop(0)
        return False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class FakeParentConnection:
    def __init__(self, result: dict[str, object] | None) -> None:
        self.result = result
        self.closed = False

    def poll(self) -> bool:
        return self.result is not None

    def recv(self) -> dict[str, object]:
        assert self.result is not None
        return self.result

    def close(self) -> None:
        self.closed = True


class FakeChildConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSpawnContext:
    def __init__(
        self,
        result: dict[str, object] | None,
        alive_results: list[bool] | None = None,
    ) -> None:
        self.parent = FakeParentConnection(result)
        self.child = FakeChildConnection()
        self.process = FakeProcess(alive_results or [False])

    def Pipe(self, *, duplex: bool) -> tuple[FakeParentConnection, FakeChildConnection]:
        assert duplex is False
        return self.parent, self.child

    def Process(self, *, target: object, args: tuple[object, ...]) -> FakeProcess:
        assert target is _fastembed_readiness_worker
        assert args == (self.child,)
        return self.process


def test_builtin_fastembed_ensure_ready_timeout_and_result_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = BuiltinFastEmbedProvider()

    with pytest.raises(EmbeddingReadinessTimeoutError, match="0 seconds"):
        provider.ensure_ready(timeout_seconds=0)

    timeout_context = FakeSpawnContext(None, alive_results=[True, True, False])
    monkeypatch.setattr(
        "recollectium.embeddings.multiprocessing.get_context",
        lambda method: timeout_context,
    )
    with pytest.raises(EmbeddingReadinessTimeoutError, match="timed out"):
        provider.ensure_ready(timeout_seconds=0.01)
    assert timeout_context.process.terminated is True
    assert timeout_context.process.killed is True

    no_result_context = FakeSpawnContext(None)
    monkeypatch.setattr(
        "recollectium.embeddings.multiprocessing.get_context",
        lambda method: no_result_context,
    )
    with pytest.raises(EmbeddingGenerationError, match="without reporting status"):
        provider.ensure_ready(timeout_seconds=1)

    ok_context = FakeSpawnContext({"ok": True})
    monkeypatch.setattr(
        "recollectium.embeddings.multiprocessing.get_context",
        lambda method: ok_context,
    )
    provider.ensure_ready(timeout_seconds=1)

    error_cases: list[tuple[str, type[Exception]]] = [
        ("EmbeddingProviderUnavailableError", EmbeddingProviderUnavailableError),
        ("EmbeddingModelUnavailableError", EmbeddingModelUnavailableError),
        ("EmbeddingDimensionMismatchError", EmbeddingDimensionMismatchError),
        ("EmbeddingReadinessTimeoutError", EmbeddingReadinessTimeoutError),
        ("OtherError", EmbeddingGenerationError),
    ]
    for error_type, expected_error in error_cases:
        error_context = FakeSpawnContext(
            {"ok": False, "error_type": error_type, "message": "mapped error"}
        )
        monkeypatch.setattr(
            "recollectium.embeddings.multiprocessing.get_context",
            lambda method, context=error_context: context,
        )
        with pytest.raises(expected_error, match="mapped error"):
            provider.ensure_ready(timeout_seconds=1)


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
