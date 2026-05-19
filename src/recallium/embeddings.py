"""Production embedding provider using FastEmbed."""

from __future__ import annotations

import math
import multiprocessing
import queue
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from recallium.errors import (
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


def _fastembed_readiness_worker(result_queue: multiprocessing.Queue[Any]) -> None:
    try:
        BuiltinFastEmbedProvider()._ensure_ready_unbounded()
    except Exception as exc:  # pragma: no cover - exercised through parent process
        result_queue.put(
            {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }
        )
        return

    result_queue.put({"ok": True})


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
    model_name = "mixedbread-ai/mxbai-embed-large-v1"
    dimensions = 1024
    version = "1"
    profile_name = "builtin-fastembed-mxbai-large-v1"
    max_tokens = 512
    chunk_tokens = 384
    chunk_overlap_tokens = 64
    query_prompt_policy = "raw"

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
            result = next(iter(embedder.embed([normalized])))
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
        result_queue: multiprocessing.Queue[Any] = context.Queue()
        process = context.Process(
            target=_fastembed_readiness_worker,
            args=(result_queue,),
        )
        process.start()
        process.join(timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            raise EmbeddingReadinessTimeoutError(
                "FastEmbed provider startup timed out after "
                f"{timeout_seconds:g} seconds"
            )

        try:
            result = cast(dict[str, object], result_queue.get_nowait())
        except queue.Empty as exc:
            raise EmbeddingGenerationError(
                "FastEmbed provider readiness check exited without reporting status"
            ) from exc
        finally:
            result_queue.close()
            result_queue.join_thread()

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

        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # pragma: no cover - import wrapper
            raise EmbeddingProviderUnavailableError(
                "FastEmbed is unavailable. Install fastembed and its runtime dependencies."
            ) from exc

        try:
            self._embedder = TextEmbedding(model_name=self.model_name)
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                f"failed to load embedding model '{self.model_name}'"
            ) from exc

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
