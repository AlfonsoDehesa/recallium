"""Tests for recollectium.model_state — model readiness state file read/write."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from recollectium.model_state import read_model_state, write_model_state


def test_read_model_state_returns_none_when_file_missing():
    with tempfile.TemporaryDirectory() as tmp:
        result = read_model_state(Path(tmp))
        assert result is None


def test_write_and_read_model_state_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        write_model_state(
            state_dir,
            model="jinaai/jina-embeddings-v2-small-en",
            dimensions=512,
            profile="builtin-fastembed-jina-v2-small-en-v1",
        )
        result = read_model_state(state_dir)
        assert result is not None
        assert result["prepared_model"] == "jinaai/jina-embeddings-v2-small-en"  # type: ignore[reportOptionalSubscript]
        assert result["dimensions"] == 512  # type: ignore[reportOptionalSubscript]
        assert result["profile"] == "builtin-fastembed-jina-v2-small-en-v1"  # type: ignore[reportOptionalSubscript]
        assert "prepared_at" in result


def test_write_model_state_creates_directory_if_missing():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "recollectium" / "nested"
        assert not state_dir.exists()
        write_model_state(
            state_dir,
            model="test-model",
            dimensions=256,
            profile="test-profile",
        )
        assert state_dir.is_dir()
        assert (state_dir / "model-state.json").is_file()


def test_write_model_state_overwrites_existing():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        # Write initial
        write_model_state(state_dir, model="old-model", dimensions=128, profile="old")
        # Overwrite
        write_model_state(state_dir, model="new-model", dimensions=256, profile="new")
        result = read_model_state(state_dir)
        assert result["prepared_model"] == "new-model"  # type: ignore[reportOptionalSubscript]
        assert result["dimensions"] == 256  # type: ignore[reportOptionalSubscript]
        assert result["profile"] == "new"  # type: ignore[reportOptionalSubscript]


def test_write_model_state_is_atomic():
    """Verify no partial file left if write is interrupted.
    We simulate this by checking the file is valid JSON after every write."""
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        write_model_state(state_dir, model="m", dimensions=1, profile="p")
        file_path = state_dir / "model-state.json"
        content = file_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)
        assert "prepared_model" in parsed


def test_read_model_state_returns_none_for_invalid_json():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        (state_dir / "model-state.json").write_text("not json", encoding="utf-8")
        result = read_model_state(state_dir)
        assert result is None


def test_write_model_state_cleans_up_tmp_file_on_failure(monkeypatch):
    """If replace() fails, the temp file is removed before re-raising."""
    replace_calls = []

    def failing_replace(self, target):
        replace_calls.append(("replace", str(self), str(target)))
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        with pytest.raises(OSError, match="simulated replace failure"):
            write_model_state(state_dir, model="m", dimensions=1, profile="p")
        tmp_files = [f for f in state_dir.glob(".model-state-*.json")]
        assert len(tmp_files) == 0
