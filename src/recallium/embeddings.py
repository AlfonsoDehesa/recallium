"""Deterministic local embeddings for MVP semantic search."""

from __future__ import annotations

import hashlib
import math
import re


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class LocalEmbeddingProvider:
    """Simple, deterministic embedding provider with lightweight synonym support."""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        self.dimensions = dimensions
        self._synonym_map = self._build_synonym_map()

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._normalize_tokens(text):
            index = self._token_index(token)
            vector[index] += 1.0
        return self._normalize_vector(vector)

    def similarity(self, first: list[float], second: list[float]) -> float:
        if len(first) != len(second):
            raise ValueError("embedding vectors must have the same size")

        first_norm = self._vector_norm(first)
        second_norm = self._vector_norm(second)
        if first_norm == 0.0 or second_norm == 0.0:
            return 0.0

        dot_product = sum(a * b for a, b in zip(first, second, strict=True))
        return dot_product / (first_norm * second_norm)

    def _normalize_tokens(self, text: str) -> list[str]:
        lowered = text.lower()
        tokens = TOKEN_PATTERN.findall(lowered)
        normalized_tokens: list[str] = []
        for token in tokens:
            canonical = self._synonym_map.get(token)
            normalized_tokens.append(canonical if canonical is not None else token)
        return normalized_tokens

    def _token_index(self, token: str) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        token_hash = int.from_bytes(digest[:8], byteorder="big", signed=False)
        return token_hash % self.dimensions

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        norm = self._vector_norm(vector)
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    @staticmethod
    def _vector_norm(vector: list[float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    @staticmethod
    def _build_synonym_map() -> dict[str, str]:
        buckets = {
            "buy": {"buy", "purchase", "acquire", "obtain", "get"},
            "fix": {"fix", "repair", "patch", "resolve"},
            "bug": {"bug", "issue", "problem", "defect", "fail", "fails", "failure"},
            "quick": {"quick", "fast", "rapid", "speedy"},
            "idea": {"idea", "concept", "notion", "thought"},
            "meeting": {"meeting", "sync", "standup", "checkin"},
            "important": {"important", "critical", "urgent", "priority"},
        }

        synonym_map: dict[str, str] = {}
        for canonical, words in buckets.items():
            for word in words:
                synonym_map[word] = canonical
        return synonym_map
