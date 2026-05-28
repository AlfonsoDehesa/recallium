"""Production embedding provider using FastEmbed."""

from __future__ import annotations

import math
import multiprocessing
import re
from collections.abc import Iterable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, ClassVar, Protocol, cast

from recollectium.errors import (
    EmbeddingDimensionMismatchError,
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
)


class EmbeddingProvider(Protocol):
    @property
    def embedding_profile(self) -> dict[str, object]: ...

    def embed(self, text: str) -> list[float]: ...

    def similarity(self, first: list[float], second: list[float]) -> float: ...


def _fastembed_readiness_worker(result_connection: Connection) -> None:
    try:
        BuiltinFastEmbedProvider()._ensure_ready_unbounded()
    except Exception as exc:  # pragma: no cover - exercised through parent process
        result_connection.send(
            {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }
        )
        result_connection.close()
        return

    result_connection.send({"ok": True})
    result_connection.close()


@dataclass(slots=True)
class ContentChunk:
    chunk_index: int
    text: str
    token_start: int
    token_end: int


def chunk_text_for_profile(text: str, profile: dict[str, object]) -> list[ContentChunk]:
    """Split text into overlapping chunks using embedding profile token policy."""
    chunk_tokens = _as_positive_int(profile.get("chunk_tokens"), "chunk_tokens")
    overlap_tokens = _as_non_negative_int(
        profile.get("chunk_overlap_tokens"), "chunk_overlap_tokens"
    )
    if overlap_tokens >= chunk_tokens:
        raise EmbeddingGenerationError(
            "chunk_overlap_tokens must be smaller than chunk_tokens"
        )

    tokens = _tokenize_for_chunking(text)
    if not tokens:
        return [ContentChunk(chunk_index=0, text="", token_start=0, token_end=0)]

    chunks: list[ContentChunk] = []
    step = chunk_tokens - overlap_tokens
    start = 0
    chunk_index = 0
    while start < len(tokens):
        end = min(start + chunk_tokens, len(tokens))
        chunk_tokens_slice = tokens[start:end]
        chunks.append(
            ContentChunk(
                chunk_index=chunk_index,
                text=" ".join(chunk_tokens_slice),
                token_start=start,
                token_end=end,
            )
        )
        if end >= len(tokens):
            break
        start += step
        chunk_index += 1

    return chunks


def _tokenize_for_chunking(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _as_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EmbeddingGenerationError(f"{field_name} must be a positive integer")
    return value


def _as_non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EmbeddingGenerationError(f"{field_name} must be a non-negative integer")
    return value


class BuiltinFastEmbedProvider:
    """Built-in production embedding provider backed by FastEmbed."""

    provider_name = "builtin-fastembed"
    model_name = "jinaai/jina-embeddings-v2-small-en"
    dimensions = 512
    version = "1"
    profile_name = "builtin-fastembed-jina-v2-small-en-v1"
    max_tokens = 8192
    chunk_tokens = 6144
    chunk_overlap_tokens = 512
    query_prompt_policy = "raw"
    runtime_threads = 1
    _shared_embedders: ClassVar[dict[tuple[str, int], Any]] = {}

    def __init__(self) -> None:
        self._embedder: Any | None = None

    @property
    def embedding_profile(self) -> dict[str, object]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "dimensions": self.dimensions,
            "version": self.version,
            "profile": self.profile_name,
            "max_tokens": self.max_tokens,
            "chunk_tokens": self.chunk_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
            "query_prompt_policy": self.query_prompt_policy,
        }

    def embed(self, text: str) -> list[float]:
        normalized = text.strip()
        if not normalized:
            return [0.0] * self.dimensions

        embedder = self._get_embedder()
        try:
            result = next(iter(embedder.embed([normalized], batch_size=1)))
        except StopIteration as exc:
            raise EmbeddingGenerationError(
                "embedding provider returned no vector"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive runtime wrapper
            raise EmbeddingGenerationError(
                f"failed to generate embedding with {self.provider_name}"
            ) from exc

        vector = [float(value) for value in cast(Iterable[float], result)]
        self._validate_dimensions(vector)
        return self._normalize_vector(vector)

    def ensure_ready(self, *, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise EmbeddingReadinessTimeoutError(
                "FastEmbed provider startup timed out after 0 seconds"
            )

        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_fastembed_readiness_worker,
            args=(child_connection,),
        )
        process.start()
        child_connection.close()
        process.join(timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            parent_connection.close()
            raise EmbeddingReadinessTimeoutError(
                "FastEmbed provider startup timed out after "
                f"{timeout_seconds:g} seconds"
            )

        if not parent_connection.poll():
            parent_connection.close()
            raise EmbeddingGenerationError(
                "FastEmbed provider readiness check exited without reporting status"
            )

        result = cast(dict[str, object], parent_connection.recv())
        parent_connection.close()

        if result.get("ok") is True:
            return

        message = str(result.get("message") or "FastEmbed provider readiness failed")
        error_type = result.get("error_type")
        if error_type == "EmbeddingProviderUnavailableError":
            raise EmbeddingProviderUnavailableError(message)
        if error_type == "EmbeddingModelUnavailableError":
            raise EmbeddingModelUnavailableError(message)
        if error_type == "EmbeddingDimensionMismatchError":
            raise EmbeddingDimensionMismatchError(message)
        if error_type == "EmbeddingReadinessTimeoutError":
            raise EmbeddingReadinessTimeoutError(message)
        raise EmbeddingGenerationError(message)

    def _ensure_ready_unbounded(self) -> None:
        vector = self.embed("healthcheck")
        self._validate_dimensions(vector)
        if not any(value != 0.0 for value in vector):
            raise EmbeddingGenerationError(
                "FastEmbed provider readiness check returned an empty vector"
            )

    def similarity(self, first: list[float], second: list[float]) -> float:
        if len(first) != len(second):
            raise EmbeddingGenerationError("embedding vectors must have the same size")
        if len(first) != self.dimensions:
            raise EmbeddingGenerationError(
                f"embedding vector size must be {self.dimensions}"
            )

        first_norm = self._vector_norm(first)
        second_norm = self._vector_norm(second)
        if first_norm == 0.0 or second_norm == 0.0:
            return 0.0

        dot_product = sum(a * b for a, b in zip(first, second, strict=True))
        return dot_product / (first_norm * second_norm)

    def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder

        cache_key = (self.model_name, self.runtime_threads)
        cached_embedder = self._shared_embedders.get(cache_key)
        if cached_embedder is not None:
            self._embedder = cached_embedder
            return cached_embedder

        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # pragma: no cover - import wrapper
            raise EmbeddingProviderUnavailableError(
                "FastEmbed is unavailable. Install fastembed and its runtime dependencies."
            ) from exc

        try:
            self._embedder = TextEmbedding(
                model_name=self.model_name,
                threads=self.runtime_threads,
            )
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                f"failed to load embedding model '{self.model_name}'"
            ) from exc

        self._shared_embedders[cache_key] = self._embedder
        return self._embedder

    def _validate_dimensions(self, vector: list[float]) -> None:
        if len(vector) != self.dimensions:
            raise EmbeddingDimensionMismatchError(
                f"unexpected embedding dimension: expected {self.dimensions}, got {len(vector)}"
            )

    @staticmethod
    def _vector_norm(vector: list[float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        norm = self._vector_norm(vector)
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
