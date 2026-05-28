"""Semantic ranking helper for memory candidates."""

from __future__ import annotations

from dataclasses import dataclass

from recollectium.embeddings import EmbeddingProvider
from recollectium.errors import ValidationError
from recollectium.models import Memory, SearchResult, validate_limit


@dataclass(slots=True)
class ChunkCandidate:
    memory: Memory
    embedding: list[float]
    chunk_index: int
    matched_text: str | None = None
    snippet: str | None = None


def rank_memory_candidates(
    *,
    query: str,
    candidates: list[tuple[Memory, list[float]]] | list[ChunkCandidate],
    embedding_provider: EmbeddingProvider,
    limit: int = 10,
) -> list[SearchResult]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("query must be a non-empty string")
    validated_limit = validate_limit(limit) or 10

    query_embedding = embedding_provider.embed(normalized_query)
    best_by_memory_id: dict[
        str, tuple[Memory, float, str | None, str | None, int | None]
    ] = {}

    for candidate in candidates:
        if isinstance(candidate, ChunkCandidate):
            memory = candidate.memory
            embedding = candidate.embedding
            chunk_index = candidate.chunk_index
            matched_text = candidate.matched_text
            snippet = candidate.snippet
        else:
            memory, embedding = candidate
            chunk_index = None
            matched_text = None
            snippet = None

        score = embedding_provider.similarity(query_embedding, embedding)
        if score > 0.0:
            previous = best_by_memory_id.get(memory.id)
            if previous is None or score > previous[1]:
                best_by_memory_id[memory.id] = (
                    memory,
                    score,
                    matched_text,
                    snippet,
                    chunk_index,
                )

    scored = list(best_by_memory_id.values())
    scored.sort(
        key=lambda item: (-item[1], item[0].updated_at, item[0].id), reverse=False
    )

    results: list[SearchResult] = []
    for rank, (memory, score, matched_text, snippet, chunk_index) in enumerate(
        scored[:validated_limit], start=1
    ):
        results.append(
            SearchResult(
                memory=memory,
                score=score,
                rank=rank,
                matched_text=matched_text,
                snippet=snippet,
                chunk_index=chunk_index,
            )
        )

    return results
