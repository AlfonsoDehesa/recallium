"""Tests for _ensure_model_ready() — central embedding readiness wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recallium.core import RecalliumCore
from recallium.model_state import read_model_state, write_model_state

# The only model name config validation currently accepts.
_SUPPORTED_MODEL = "jinaai/jina-embeddings-v2-small-en"


class TrackedEmbeddingProvider:
    """Fake provider that tracks ensure_ready calls."""

    def __init__(self) -> None:
        self.ensure_ready_calls: list[tuple] = []
        self.should_fail: str | None = None
        self.embedding_profile: dict[str, object] = {
            "provider": "fake",
            "model": _SUPPORTED_MODEL,
            "dimensions": 3,
            "version": "1",
            "profile": "fake-profile-v1",
            "max_tokens": 16,
            "chunk_tokens": 4,
            "chunk_overlap_tokens": 0,
            "query_prompt_policy": "raw",
        }

    def embed(self, text: str) -> list[float]:
        size = float(len(text))
        first = float(ord(text[0])) if text else 0.0
        return [size, first, 1.0]

    def similarity(self, first: list[float], second: list[float]) -> float:
        return sum(a * b for a, b in zip(first, second, strict=True))

    def ensure_ready(self, *, timeout_seconds: float = 60.0) -> None:
        self.ensure_ready_calls.append((timeout_seconds,))
        if self.should_fail:
            from recallium.errors import EmbeddingModelUnavailableError

            raise EmbeddingModelUnavailableError(self.should_fail)


def _make_config(tmp_path: Path) -> Path:
    """Write a minimal valid Recallium config pointing to a temp database."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database": {"path": str(tmp_path / "recallium.db")},
                "embedding": {
                    "provider": "builtin-fastembed",
                    "model": _SUPPORTED_MODEL,
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_ensure_model_ready_noop_when_model_matches(tmp_path: Path):
    """If model state matches config, ensure_ready is NOT called."""
    state_dir = tmp_path / "state"
    write_model_state(
        state_dir,
        model=_SUPPORTED_MODEL,
        dimensions=3,
        profile="fake-profile-v1",
    )
    provider = TrackedEmbeddingProvider()
    config = _make_config(tmp_path)
    core = RecalliumCore(
        db_path=tmp_path / "test.db",
        config_path=config,
        embedding_provider=provider,
    )
    core._ensure_model_ready(state_dir=state_dir)
    assert provider.ensure_ready_calls == []


def test_ensure_model_ready_prepares_when_state_missing(tmp_path: Path):
    """If no state file, ensure_ready is called and state is written."""
    state_dir = tmp_path / "state"
    provider = TrackedEmbeddingProvider()
    config = _make_config(tmp_path)
    core = RecalliumCore(
        db_path=tmp_path / "test.db",
        config_path=config,
        embedding_provider=provider,
    )
    core._ensure_model_ready(state_dir=state_dir)
    assert len(provider.ensure_ready_calls) == 1
    state = read_model_state(state_dir)
    assert state is not None
    assert state["prepared_model"] == _SUPPORTED_MODEL
    assert state["dimensions"] == 3


def test_ensure_model_ready_prepares_when_model_mismatch(tmp_path: Path):
    """If model in state file differs from config, ensure_ready is called."""
    state_dir = tmp_path / "state"
    write_model_state(
        state_dir, model="old-model", dimensions=128, profile="old-profile"
    )
    provider = TrackedEmbeddingProvider()
    config = _make_config(tmp_path)
    core = RecalliumCore(
        db_path=tmp_path / "test.db",
        config_path=config,
        embedding_provider=provider,
    )
    core._ensure_model_ready(state_dir=state_dir)
    assert len(provider.ensure_ready_calls) == 1
    state = read_model_state(state_dir)
    assert state["prepared_model"] == _SUPPORTED_MODEL


def test_ensure_model_ready_raises_on_provider_failure(tmp_path: Path):
    """If ensure_ready fails, the error propagates."""
    state_dir = tmp_path / "state"
    provider = TrackedEmbeddingProvider()
    provider.should_fail = "model download failed"
    config = _make_config(tmp_path)
    core = RecalliumCore(
        db_path=tmp_path / "test.db",
        config_path=config,
        embedding_provider=provider,
    )
    from recallium.errors import EmbeddingModelUnavailableError

    with pytest.raises(EmbeddingModelUnavailableError, match="model download failed"):
        core._ensure_model_ready(state_dir=state_dir)


def test_ensure_model_ready_writes_state_with_provider_dimensions(tmp_path: Path):
    """State file uses the provider's actual dimensions from embedding_profile."""
    state_dir = tmp_path / "state"
    provider = TrackedEmbeddingProvider()
    provider.embedding_profile["dimensions"] = 768
    config = _make_config(tmp_path)
    core = RecalliumCore(
        db_path=tmp_path / "test.db",
        config_path=config,
        embedding_provider=provider,
    )
    core._ensure_model_ready(state_dir=state_dir)
    state = read_model_state(state_dir)
    assert state["dimensions"] == 768
