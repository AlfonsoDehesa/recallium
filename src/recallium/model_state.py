"""Model readiness state file for Recallium Core.

Tracks the last-prepared embedding model so Recallium can detect
when the configured model has changed and needs re-preparation.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone


_MODEL_STATE_FILENAME = "model-state.json"


def read_model_state(state_dir: Path) -> dict | None:
    """Return the last-prepared model state, or None if unavailable."""
    state_path = state_dir / _MODEL_STATE_FILENAME
    if not state_path.is_file():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_model_state(
    state_dir: Path,
    *,
    model: str,
    dimensions: int,
    profile: str,
) -> None:
    """Write the prepared model state atomically."""
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "prepared_model": model,
        "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dimensions": dimensions,
        "profile": profile,
    }
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix=".model-state-", dir=str(state_dir)
    )
    try:
        with open(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        Path(tmp_path).replace(state_dir / _MODEL_STATE_FILENAME)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
