"""Recallium configuration system.

Reads a JSON config file from an XDG-compliant path, merges user overrides
onto sensible defaults, validates the result, and resolves platform-appropriate
directory paths for data, cache, logs, and runtime state.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from platformdirs import (
    user_cache_dir,
    user_config_dir,
    user_data_dir,
    user_runtime_dir,
    user_state_dir,
)

from recallium.errors import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_VERSION = 1
SUPPORTED_EMBEDDING_PROVIDER = "builtin-fastembed"
SUPPORTED_EMBEDDING_MODEL = "jinaai/jina-embeddings-v2-small-en"
SUPPORTED_LOGGING_LEVELS = {"debug", "info", "warning", "error"}
SUPPORTED_LOGGING_FORMATS = {"json"}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "database": {"path": "recallium.db"},
    "embedding": {
        "provider": SUPPORTED_EMBEDDING_PROVIDER,
        "model": SUPPORTED_EMBEDDING_MODEL,
    },
    "service": {"host": "127.0.0.1", "port": 8765},
    "logging": {
        "level": "info",
        "format": "json",
        "max_bytes": 10485760,
        "backup_count": 5,
    },
    "directories": {"data": None, "cache": None, "logs": None, "runtime": None},
    "workspace": {
        "uid_normalization": "normalize",
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*.

    ``None`` values in the override dict are treated as "not set" and are
    skipped.
    """
    result = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_xdg_dirs(
    directories_override: dict[str, str | None],
) -> dict[str, Path]:
    """Resolve XDG-compliant directory paths.

    Returns a dict with keys ``config``, ``data``, ``cache``, ``logs``,
    and ``runtime``.  Respect overrides for data/cache/logs/runtime;
    ``config`` always comes from ``user_config_dir``.
    """
    runtime_dir = directories_override.get("runtime")
    if runtime_dir is None:
        runtime_dir = user_runtime_dir("recallium")
    if runtime_dir is None:
        runtime_dir = str(Path(user_data_dir("recallium")) / "run")

    return {
        "config": Path(user_config_dir("recallium")),
        "data": Path(directories_override.get("data") or user_data_dir("recallium")),
        "cache": Path(directories_override.get("cache") or user_cache_dir("recallium")),
        "logs": Path(
            directories_override.get("logs")
            or str(Path(user_state_dir("recallium")) / "logs")
        ),
        "runtime": Path(runtime_dir),
    }


def _validate_config_value(data: dict[str, Any], path: str = "") -> None:
    """Validate a fully-merged config dict.

    Raises ``ValidationError`` with a descriptive message for any invalid
    value.
    """
    _check_type(data, "version", int, path)
    if data["version"] < 1:
        raise ValidationError(f"version must be >= 1 (got {data['version']})")

    _validate_section(data, "database", {"path": str})
    _validate_section(data, "embedding", {"provider": str, "model": str})
    _validate_section(data, "service", {"host": str, "port": int})

    embedding = data.get("embedding", {})
    if isinstance(embedding, dict):
        provider = embedding.get("provider")
        if isinstance(provider, str) and provider != SUPPORTED_EMBEDDING_PROVIDER:
            raise ValidationError(
                "embedding.provider only supports "
                f"{SUPPORTED_EMBEDDING_PROVIDER!r} in this release "
                f"(got {provider!r})"
            )
        model = embedding.get("model")
        if isinstance(model, str) and model != SUPPORTED_EMBEDDING_MODEL:
            raise ValidationError(
                "embedding.model only supports "
                f"{SUPPORTED_EMBEDDING_MODEL!r} in this release "
                f"(got {model!r})"
            )

    # Service port range
    service = data.get("service", {})
    if isinstance(service, dict):
        port = service.get("port")
        if isinstance(port, int) and (port < 1 or port > 65535):
            raise ValidationError(
                f"service.port must be between 1 and 65535 (got {port})"
            )

    _validate_section(
        data,
        "logging",
        {"level": str, "format": str, "max_bytes": int, "backup_count": int},
    )
    logging_config = data.get("logging", {})
    if isinstance(logging_config, dict):
        level = logging_config.get("level")
        if isinstance(level, str) and level.lower() not in SUPPORTED_LOGGING_LEVELS:
            levels = ", ".join(sorted(SUPPORTED_LOGGING_LEVELS))
            raise ValidationError(
                f"logging.level must be one of: {levels} (got {level!r})"
            )
        if isinstance(level, str):
            logging_config["level"] = level.lower()

        fmt = logging_config.get("format")
        if isinstance(fmt, str) and fmt not in SUPPORTED_LOGGING_FORMATS:
            raise ValidationError(
                f"logging.format must be one of: {', '.join(sorted(SUPPORTED_LOGGING_FORMATS))} (got {fmt!r})"
            )

        max_bytes = logging_config.get("max_bytes")
        if isinstance(max_bytes, int) and max_bytes <= 0:
            raise ValidationError(
                f"logging.max_bytes must be a positive integer (got {max_bytes})"
            )

        backup_count = logging_config.get("backup_count")
        if isinstance(backup_count, int) and backup_count <= 0:
            raise ValidationError(
                f"logging.backup_count must be a positive integer (got {backup_count})"
            )

    # directories.* must be string or None
    directories = data.get("directories", {})
    if isinstance(directories, dict):
        for key, value in directories.items():
            if not isinstance(value, (str, type(None))):
                raise ValidationError(
                    f"directories.{key} must be a string or null (got {type(value).__name__})"
                )

    # workspace.uid_normalization must be normalize or exact
    workspace = data.get("workspace", {})
    if isinstance(workspace, dict):
        normalization = workspace.get("uid_normalization")
        if isinstance(normalization, str) and normalization not in {
            "normalize",
            "exact",
        }:
            raise ValidationError(
                "workspace.uid_normalization must be one of: normalize, exact "
                f"(got {normalization!r})"
            )


def _check_type(data: dict[str, Any], key: str, expected: type, path: str) -> None:
    full_key = f"{path}.{key}" if path else key
    value = data.get(key)
    if value is None:
        if expected is not type(None):
            raise ValidationError(f"{full_key} must be {expected.__name__} (got None)")
        return
    if not isinstance(value, expected):
        raise ValidationError(
            f"{full_key} must be {expected.__name__} (got {type(value).__name__})"
        )


def _validate_section(
    data: dict[str, Any],
    section: str,
    fields: dict[str, type],
) -> None:
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        raise ValidationError(
            f"{section} must be an object (got {type(section_data).__name__})"
        )
    for field, expected_type in fields.items():
        _check_type(section_data, field, expected_type, section)


def _write_starter_config(path: Path) -> None:
    """Create a starter config file at *path* with all defaults."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _ensure_config_directories(paths: dict[str, Path]) -> None:
    """Create resolved config directories with private permissions."""
    for path in paths.values():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)


def load_config_file(path: Path) -> dict[str, Any]:
    """Read and parse a JSON config file from *path*."""
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in config file {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Public helpers (for CLI config commands)
# ---------------------------------------------------------------------------


def get_config_value(config: dict[str, Any], key: str) -> Any:
    """Retrieve a value by dot-notation key (e.g. ``"service.port"``)."""
    parts = key.split(".")
    current: Any = config
    for part in parts:
        if not isinstance(current, dict):
            raise KeyError(
                f"cannot traverse into {type(current).__name__} for key {key!r}"
            )
        if part not in current:
            raise KeyError(f"key {key!r} not found in config")
        current = current[part]
    return current


def set_config_value(config: dict[str, Any], key: str, value: Any) -> None:
    """Set a value by dot-notation key, auto-creating intermediate dicts."""
    parts = key.split(".")
    current: dict[str, Any] = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def unset_config_value(config: dict[str, Any], key: str) -> Any:
    """Remove a value by dot-notation key, returning the removed value."""
    parts = key.split(".")
    current: Any = config
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"key {key!r} not found in config")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise KeyError(f"key {key!r} not found in config")
    return current.pop(parts[-1])


def validate_config_file(path: Path) -> None:
    """Load a config file, merge with defaults, and validate.

    Raises ``ValidationError`` if anything is wrong.  Returns ``None`` on
    success.  Does **not** create the file or resolve directories.
    """
    raw = load_config_file(path)
    merged = _deep_merge(dict(DEFAULTS), raw)
    _validate_config_value(merged)


# ---------------------------------------------------------------------------
# Config object
# ---------------------------------------------------------------------------


class RecalliumConfig:
    """Recallium configuration loaded from disk and merged with defaults."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        log_level: str | None = None,
    ) -> None:
        # 1. Resolve config path
        if config_path is not None:
            self._config_file_path = Path(config_path)
            explicit = True
        else:
            self._config_file_path = Path(user_config_dir("recallium")) / "config.json"
            explicit = False

        # 2. Explicit path but file missing -> error
        if explicit and not self._config_file_path.exists():
            raise FileNotFoundError(f"config file not found: {self._config_file_path}")

        # 3. Default path missing -> write starter config
        if not explicit and not self._config_file_path.exists():
            _write_starter_config(self._config_file_path)

        # 4. Load
        raw = load_config_file(self._config_file_path)

        # 5. Deep-merge loaded overrides onto defaults
        merged = _deep_merge(deepcopy(DEFAULTS), raw)

        # 6. Apply runtime overrides
        if log_level is not None:
            merged["logging"]["level"] = log_level.lower()

        # 7. Validate
        _validate_config_value(merged)

        # 8. Resolve XDG directories
        self._xdg_dirs = _resolve_xdg_dirs(merged.get("directories", {}))

        # 9. Ensure all required directories exist with private permissions
        _ensure_config_directories(self._xdg_dirs)

        # 10. Resolve database path
        db_path = Path(merged["database"]["path"])
        if not db_path.is_absolute():
            db_path = self._xdg_dirs["data"] / db_path
        self._resolved_db_path = db_path

        # 10. Store final effective config
        self._effective_config = merged

    # -- properties -----------------------------------------------------------

    @property
    def effective_config(self) -> dict[str, Any]:
        """The full merged config dict (defaults + user overrides)."""
        return self._effective_config

    @property
    def resolved_database_path(self) -> Path:
        """The resolved absolute database path."""
        return self._resolved_db_path

    @property
    def config_file_path(self) -> Path:
        """The config file Path that was loaded."""
        return self._config_file_path

    @property
    def xdg_dirs(self) -> dict[str, Path]:
        """Resolved XDG directory paths (config, data, cache, logs, runtime)."""
        return self._xdg_dirs
