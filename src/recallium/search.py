"""Semantic ranking helper for memory candidates."""

from __future__ import annotations

from recallium.embeddings import LocalEmbeddingProvider
from recallium.errors import ValidationError
from recallium.models import Memory, SearchResult, validate_limit


def rank_memory_candidates(
    *,
    query: str,
    candidates: list[tuple[Memory, list[float]]],
    embedding_provider: LocalEmbeddingProvider,
    limit: int = 10,
) -> list[SearchResult]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("query must be a non-empty string")
    validated_limit = validate_limit(limit) or 10

    query_embedding = embedding_provider.embed(normalized_query)
    scored: list[tuple[Memory, float]] = []

    for memory, embedding in candidates:
        score = embedding_provider.similarity(query_embedding, embedding)
        if score > 0.0:
            scored.append((memory, score))

    scored.sort(
        key=lambda item: (-item[1], item[0].updated_at, item[0].id), reverse=False
    )

    results: list[SearchResult] = []
    for rank, (memory, score) in enumerate(scored[:validated_limit], start=1):
        results.append(SearchResult(memory=memory, score=score, rank=rank))

    return results
