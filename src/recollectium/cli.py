"""CLI entrypoint for Recollectium Core."""

from __future__ import annotations

import argparse
import argcomplete
from argcomplete.completers import ChoicesCompleter
from copy import deepcopy
import json
import logging
import os
import re
import shutil
from importlib.metadata import PackageNotFoundError, version as package_version
import subprocess
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console
from rich.text import Text

from platformdirs import user_state_dir

from recollectium import (
    __version__,
    NotFoundError,
    RecollectiumCore,
    RecollectiumError,
    ValidationError,
)
from recollectium.errors import (
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
    MigrationError,
)
from recollectium.config import (
    CLI_OUTPUT_HUMAN_READABLE,
    CLI_OUTPUT_JSON,
    DEFAULTS,
    RecollectiumConfig,
    _deep_merge,
    _resolve_xdg_dirs,
    _validate_config_value,
    get_config_value,
    load_config_file,
    set_config_value,
    unset_config_value,
    validate_config_file,
)
from recollectium.embeddings import BuiltinFastEmbedProvider
from recollectium.logging import setup_logging
from recollectium.model_state import write_model_state
from recollectium.models import (
    ALL_MEMORY_TYPES,
    SPACE_USER,
    SPACE_WORKSPACE,
    SearchResult,
    USER_MEMORY_TYPES,
    WORKSPACE_MEMORY_TYPES,
)
from recollectium.mcp_server import create_mcp_server
from recollectium.service import run_service
from recollectium.service_contract import SERVICE_DEFAULT_HOST, SERVICE_DEFAULT_PORT
from recollectium.errors import ServiceConflictError, ServiceError
from recollectium.service_manager import (
    check_running_service,
    discover_service,
    get_pid_file_path,
    read_pid_file,
    start_service,
    stop_service,
)
from recollectium.storage import SQLiteMemoryStore
from recollectium.update import (
    GitHubReleaseClient,
    ReleaseInfo,
    ReleaseLookupError,
    SubprocessCommandRunner,
    apply_update,
    build_update_plan,
    detect_install_method,
    fetch_latest_release,
    find_source_checkout_root,
    load_install_metadata,
    plan_to_dict,
)

_log = logging.getLogger(__name__)
_INSTALL_METADATA_FILE = "install.json"
_PURGE_CONFIRMATION = "delete all recollectium data"

_COMPLETABLE_CONFIG_KEYS = [
    "version",
    "cli_output",
    "database.path",
    "embedding.provider",
    "embedding.model",
    "service.host",
    "service.port",
    "logging.level",
    "logging.format",
    "logging.max_bytes",
    "logging.backup_count",
    "directories.data",
    "directories.cache",
    "directories.logs",
    "directories.runtime",
    "workspace.uid_normalization",
]


def _memory_type_choices_for_space(space: Any | None) -> tuple[str, ...]:
    if space == SPACE_USER:
        return USER_MEMORY_TYPES
    if space == SPACE_WORKSPACE:
        return WORKSPACE_MEMORY_TYPES
    return ALL_MEMORY_TYPES


def _memory_type_completer(prefix: str, parsed_args: Any, **_: Any) -> list[str]:
    choices = _memory_type_choices_for_space(getattr(parsed_args, "space", None))
    return [choice for choice in choices if choice.startswith(prefix)]


class _CliLoggingConfig:
    def __init__(self, *, effective_config: dict[str, Any], log_dir: Path) -> None:
        self.effective_config = effective_config
        self.xdg_dirs = {"logs": log_dir}


class _UninstallConfig(RecollectiumConfig):
    def __init__(
        self,
        *,
        effective_config: dict[str, Any],
        xdg_dirs: dict[str, Path],
        config_path: Path,
        database_path: Path,
    ) -> None:
        self._effective_config = effective_config
        self._xdg_dirs = xdg_dirs
        self._config_file_path = config_path
        self._resolved_db_path = database_path


class _UninstallPlan:
    def __init__(
        self,
        *,
        config: _UninstallConfig,
        config_path: Path,
        database_path: Path,
        install_metadata_path: Path,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.database_path = database_path
        self.install_metadata_path = install_metadata_path


class _MetadataInvalidError(ValidationError):
    """Raised when CLI --metadata is malformed or not an object."""


def _parse_metadata(raw_metadata: str | None) -> dict[str, object] | None:
    if raw_metadata is None:
        return None

    payload = raw_metadata
    if raw_metadata.startswith("@"):
        metadata_path = Path(raw_metadata[1:])
        payload = metadata_path.read_text(encoding="utf-8")

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _MetadataInvalidError(f"metadata must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise _MetadataInvalidError("metadata must be a JSON object")
    return parsed


def _write_tty(text: str) -> bool:
    """Write interactive prompt text to the controlling TTY, not stdout/stderr."""
    try:
        with Path("/dev/tty").open("w", encoding="utf-8") as tty:
            tty.write(text)
            tty.flush()
    except OSError:
        return False
    return True


def _to_payload(data: Any) -> Any:
    if isinstance(data, SearchResult):
        return data.to_dict()
    if hasattr(data, "to_dict"):
        return data.to_dict()
    if isinstance(data, list):
        return [_to_payload(item) for item in data]
    return data


def _json_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


_RICH_BOLD = "bold"
_RICH_HEADING = "bold cyan"
_RICH_ERROR = "bold red"
_RICH_HINT = "yellow"


def _supports_color(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


def _style(text: str, style: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system="standard",
        legacy_windows=False,
        soft_wrap=True,
        width=120,
    )
    console.print(Text(text, style=style), end="")
    return stream.getvalue()


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").capitalize()


def _format_label(label: str, *, color: bool) -> str:
    return _style(f"{label}:", _RICH_BOLD, enabled=color)


def _format_mapping_lines(
    mapping: dict[str, Any], *, indent: int = 0, color: bool = False
) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in mapping.items():
        label = _humanize_key(str(key))
        if isinstance(value, dict):
            lines.append(f"{prefix}{_format_label(label, color=color)}")
            lines.extend(_format_mapping_lines(value, indent=indent + 2, color=color))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{_format_label(label, color=color)} none")
            else:
                lines.append(f"{prefix}{_format_label(label, color=color)}")
                for item in value:
                    if isinstance(item, dict):
                        lines.extend(
                            _format_mapping_lines(item, indent=indent + 2, color=color)
                        )
                    else:
                        lines.append(f"{' ' * (indent + 2)}- {_json_scalar(item)}")
        elif value is not None:
            lines.append(
                f"{prefix}{_format_label(label, color=color)} {_json_scalar(value)}"
            )
    return lines


def _memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "memory" in payload and isinstance(payload["memory"], dict):
        return payload["memory"]
    return payload


def _format_memory(
    payload: dict[str, Any], *, index: int | None = None, color: bool = False
) -> list[str]:
    memory = _memory_payload(payload)
    title_prefix = f"{index}. " if index is not None else ""
    memory_id = memory.get("id", "unknown")
    type_value = memory.get("type")
    status = memory.get("status")
    score = payload.get("score", memory.get("score"))
    headline = f"{title_prefix}Memory {memory_id}"
    details = [str(item) for item in (type_value, status) if item]
    if details:
        headline += f" ({', '.join(details)})"
    if score is not None:
        headline += f" score={score}"
    lines = [_style(headline, _RICH_HEADING, enabled=color)]
    for key in ("space", "workspace_uid", "source", "confidence", "sensitivity"):
        if memory.get(key) is not None:
            lines.append(
                f"  {_format_label(_humanize_key(key), color=color)} "
                f"{_json_scalar(memory[key])}"
            )
    content = memory.get("content")
    if content is not None:
        lines.append(f"  {_format_label('Content', color=color)} {content}")
    metadata = memory.get("metadata")
    if metadata:
        lines.append(
            f"  {_format_label('Metadata', color=color)} "
            f"{json.dumps(metadata, sort_keys=True)}"
        )
    for key in ("created_at", "updated_at", "archived_at"):
        if memory.get(key):
            lines.append(
                f"  {_format_label(_humanize_key(key), color=color)} {memory[key]}"
            )
    return lines


def _format_human_output(
    payload: Any,
    *,
    command: str | None = None,
    label: str | None = None,
    color: bool = False,
) -> str:
    payload = _to_payload(payload)
    if payload is None:
        return "Done\n"
    if isinstance(payload, list):
        if not payload:
            return "No results\n"
        if all(isinstance(item, dict) for item in payload):
            lines = [
                _style(
                    f"{len(payload)} result{'s' if len(payload) != 1 else ''}",
                    _RICH_HEADING,
                    enabled=color,
                )
            ]
            for index, item in enumerate(payload, start=1):
                if "content" in item or "memory" in item:
                    lines.extend(_format_memory(item, index=index, color=color))
                else:
                    lines.append(f"{index}. {json.dumps(item, sort_keys=True)}")
            return "\n".join(lines) + "\n"
        return "\n".join(f"- {_json_scalar(item)}" for item in payload) + "\n"
    if command == "config get" and label is not None:
        return f"{_format_label(label, color=color)} {_json_scalar(payload)}\n"
    if not isinstance(payload, dict):
        if label:
            return f"{label}: {_json_scalar(payload)}\n"
        return f"{_json_scalar(payload)}\n"

    if command in {"add", "get", "update", "archive"} or "content" in payload:
        title = "Memory"
        if command == "add":
            title = "Memory added"
        elif command == "update":
            title = "Memory updated"
        elif command == "archive":
            title = "Memory archived"
        return (
            "\n".join(
                [
                    _style(title, _RICH_HEADING, enabled=color),
                    *_format_memory(payload, color=color),
                ]
            )
            + "\n"
        )

    if command == "config set":
        heading = _style("Config updated:", _RICH_HEADING, enabled=color)
        return (
            f"{heading} {payload.get('key')} = {_json_scalar(payload.get('value'))}\n"
        )
    if command == "config unset":
        heading = _style("Config key removed:", _RICH_HEADING, enabled=color)
        return f"{heading} {payload.get('key')}\n"
    if command == "config init":
        heading = _style("Config initialized:", _RICH_HEADING, enabled=color)
        return f"{heading} {payload.get('path')}\n"
    if command == "config reset":
        heading = _style("Config reset to defaults:", _RICH_HEADING, enabled=color)
        return f"{heading} {payload.get('path')}\n"
    if command == "config doctor":
        lines = [_style("Config doctor", _RICH_HEADING, enabled=color)]
        lines.extend(_format_mapping_lines(payload, indent=2, color=color))
        return "\n".join(lines) + "\n"
    if command == "config":
        return (
            _style("Effective configuration", _RICH_HEADING, enabled=color)
            + "\n"
            + "\n".join(_format_mapping_lines(payload, indent=2, color=color))
            + "\n"
        )

    if command == "init":
        lines = [_style("Recollectium initialized", _RICH_HEADING, enabled=color)]
        lines.extend(_format_mapping_lines(payload, indent=2, color=color))
        return "\n".join(lines) + "\n"

    if command and command.startswith("workspace"):
        lines = [_style("Workspace result", _RICH_HEADING, enabled=color)]
        lines.extend(_format_mapping_lines(payload, indent=2, color=color))
        return "\n".join(lines) + "\n"

    if command and command.startswith("service"):
        lines = [_style("Service result", _RICH_HEADING, enabled=color)]
        lines.extend(_format_mapping_lines(payload, indent=2, color=color))
        return "\n".join(lines) + "\n"

    if command in {
        "db-status",
        "embedding-status",
        "embedding-jobs",
        "upgrade",
        "uninstall",
        "completion",
    }:
        heading = _humanize_key(command)
        lines = [_style(heading, _RICH_HEADING, enabled=color)]
        lines.extend(_format_mapping_lines(payload, indent=2, color=color))
        return "\n".join(lines) + "\n"

    lines = [_style(_humanize_key(command or "result"), _RICH_HEADING, enabled=color)]
    lines.extend(_format_mapping_lines(payload, indent=2, color=color))
    return "\n".join(lines) + "\n"


def _emit_success(
    payload: Any,
    *,
    output_format: str,
    command: str | None = None,
    label: str | None = None,
    json_indent: int | None = None,
) -> None:
    payload = _to_payload(payload)
    if output_format == CLI_OUTPUT_HUMAN_READABLE:
        sys.stdout.write(
            _format_human_output(
                payload,
                command=command,
                label=label,
                color=_supports_color(sys.stdout),
            )
        )
        return
    print(json.dumps(payload, indent=json_indent, sort_keys=True))


def _parse_config_value(raw: str) -> Any:
    """Parse a CLI-provided config value as JSON; fall back to string on failure."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _resolve_config_path(explicit_path: str | None) -> Path:
    """Resolve the config file path from --config flag or default XDG location."""
    from platformdirs import user_config_dir

    if explicit_path is not None:
        return Path(explicit_path)
    return Path(user_config_dir("recollectium")) / "config.json"


def _core_config_path(explicit_path: str | None) -> Path | None:
    """Return only explicit config paths for core/service initialization."""
    if explicit_path is None:
        return None
    return Path(explicit_path)


def _extract_cli_output_override(
    argv: Sequence[str] | None,
) -> tuple[list[str] | None, str | None, bool]:
    """Remove output override flags so they work before or after subcommands."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    output_format: str | None = None
    cleaned: list[str] = []
    conflict = False
    literal_args = False
    for item in raw_args:
        if literal_args:
            cleaned.append(item)
            continue
        if item == "--":
            literal_args = True
            cleaned.append(item)
            continue
        if item == "--json":
            if output_format == CLI_OUTPUT_HUMAN_READABLE:
                conflict = True
            output_format = CLI_OUTPUT_JSON
            continue
        if item == "--human-readable":
            if output_format == CLI_OUTPUT_JSON:
                conflict = True
            output_format = CLI_OUTPUT_HUMAN_READABLE
            continue
        cleaned.append(item)
    if argv is None:
        return None if cleaned == raw_args else cleaned, output_format, conflict
    return cleaned, output_format, conflict


def _resolve_output_format(
    *,
    config_path: Path,
    explicit: bool,
    override: str | None,
) -> str:
    if override is not None:
        return override
    if not config_path.exists():
        return CLI_OUTPUT_HUMAN_READABLE
    try:
        raw = load_config_file(config_path)
        merged = _deep_merge(deepcopy(DEFAULTS), raw)
        try:
            _validate_config_value(merged)
        except ValidationError:
            configured = raw.get("cli_output") if isinstance(raw, dict) else None
            if configured in {CLI_OUTPUT_JSON, CLI_OUTPUT_HUMAN_READABLE}:
                return str(configured)
            return CLI_OUTPUT_HUMAN_READABLE
    except (FileNotFoundError, ValidationError, OSError):
        return CLI_OUTPUT_HUMAN_READABLE
    return str(merged.get("cli_output", CLI_OUTPUT_HUMAN_READABLE))


def _load_effective_config(config_path: Path, *, explicit: bool) -> RecollectiumConfig:
    """Load effective config with first-run default creation semantics."""
    if explicit:
        return RecollectiumConfig(config_path)
    return RecollectiumConfig()


def _setup_cli_logging(
    config_path: Path,
    *,
    log_level: str | None,
) -> None:
    """Start file logging before commands that do not build RecollectiumCore."""

    def _fallback_config() -> _CliLoggingConfig:
        effective_config = deepcopy(DEFAULTS)
        if log_level is not None:
            effective_config["logging"]["level"] = log_level
        return _CliLoggingConfig(
            effective_config=effective_config,
            log_dir=Path(user_state_dir("recollectium")) / "logs",
        )

    try:
        if config_path.exists():
            config = RecollectiumConfig(config_path, log_level=log_level)
        else:
            config = _fallback_config()
        setup_logging(config)
    except OSError:
        setup_logging(_fallback_config())
    except ValidationError:
        setup_logging(_fallback_config())


def _directory_writable(path: Path) -> bool:
    """Return True when *path* is writable by current user."""
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def _handle_config_command(
    args: argparse.Namespace,
    config_path: Path,
    *,
    explicit: bool,
    output_format: str,
) -> int:
    """Handle the `recollectium config` command and its subcommands."""
    if args.config_action == "get":
        try:
            cfg = _load_effective_config(config_path, explicit=explicit)
            value = get_config_value(cfg.effective_config, args.key)
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command="config get")
        except ValidationError as exc:
            return _config_invalid_error(exc, command="config get")
        except KeyError as exc:
            return _not_found_error(exc, command="config get")
        _emit_success(
            value, output_format=output_format, command="config get", label=args.key
        )
        return 0

    if args.config_action == "set":
        value = _parse_config_value(args.value)
        if not config_path.exists():
            config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
            )
            config_path.chmod(0o600)
        raw = load_config_file(config_path)
        set_config_value(raw, args.key, value)
        # Validate the resulting config before writing
        try:
            merged = _deep_merge(deepcopy(DEFAULTS), raw)
            _validate_config_value(merged)
        except ValidationError as exc:
            return _config_invalid_error(exc, command="config set")
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        if output_format == CLI_OUTPUT_HUMAN_READABLE:
            _emit_success(
                {"key": args.key, "value": value},
                output_format=output_format,
                command="config set",
            )
        return 0

    if args.config_action == "unset":
        if not config_path.exists():
            return _config_missing_error(
                FileNotFoundError(f"config file not found: {config_path}"),
                command="config unset",
            )
        raw = load_config_file(config_path)
        try:
            unset_config_value(raw, args.key)
        except KeyError as exc:
            return _not_found_error(exc, command="config unset")
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        if output_format == CLI_OUTPUT_HUMAN_READABLE:
            _emit_success(
                {"key": args.key},
                output_format=output_format,
                command="config unset",
            )
        return 0

    if args.config_action == "init":
        if config_path.exists() and not args.force:
            return _emit_cli_failure(
                status="operation_failed",
                message="Config file already exists.",
                detail=f"config file already exists: {config_path}",
                hint="Use recollectium config init --force to overwrite it.",
                exit_code=1,
                command="config init",
                event="config.exists",
            )
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        if output_format == CLI_OUTPUT_HUMAN_READABLE:
            _emit_success(
                {"path": str(config_path)},
                output_format=output_format,
                command="config init",
            )
        return 0

    if args.config_action == "doctor":
        try:
            cfg = _load_effective_config(config_path, explicit=explicit)
        except ValidationError as exc:
            return _config_invalid_error(exc, command="config doctor")
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command="config doctor")

        failures: list[str] = []
        checks: dict[str, str] = {"config": str(cfg.config_file_path)}

        for name in ("data", "cache", "logs", "runtime"):
            directory = cfg.xdg_dirs[name]
            if not directory.exists():
                failures.append(f"{name} directory missing: {directory}")
                continue
            if not directory.is_dir():
                failures.append(f"{name} path is not a directory: {directory}")
                continue
            if not _directory_writable(directory):
                failures.append(f"{name} directory is not writable: {directory}")
                continue
            checks[name] = str(directory)

        db_parent = cfg.resolved_database_path.parent
        if not db_parent.exists():
            failures.append(f"database parent directory missing: {db_parent}")
        elif not db_parent.is_dir():
            failures.append(f"database parent path is not a directory: {db_parent}")
        elif not _directory_writable(db_parent):
            failures.append(f"database parent directory is not writable: {db_parent}")
        else:
            checks["database_parent"] = str(db_parent)

        if failures:
            for failure in failures:
                _log.info(failure, extra={"event": "config.doctor_failed"})
            return _emit_cli_failure(
                status="operation_failed",
                message="Config doctor found filesystem problems.",
                detail="; ".join(f"FAIL {failure}" for failure in failures),
                exit_code=1,
                command="config doctor",
                event="config.doctor_failed",
                failures=failures,
            )

        _emit_success(
            {"status": "ok", "checks": checks},
            output_format=output_format,
            command="config doctor",
        )
        return 0

    if args.config_action == "edit":
        if not config_path.exists():
            config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
            )
            config_path.chmod(0o600)
        editor = os.environ.get("EDITOR", "vi")
        try:
            return subprocess.call([editor, str(config_path)])
        except FileNotFoundError:
            return _emit_cli_failure(
                status="operation_failed",
                message="Editor was not found.",
                detail=f"editor not found: {editor}",
                hint="Set EDITOR to an installed editor or edit the config file directly.",
                exit_code=1,
                command="config edit",
                event="config.editor_missing",
            )

    if args.config_action == "reset":
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        _emit_success(
            {"path": str(config_path)},
            output_format=output_format,
            command="config reset",
        )
        return 0

    if args.validate:
        try:
            if explicit:
                validate_config_file(config_path)
            else:
                _load_effective_config(config_path, explicit=False)
        except ValidationError as exc:
            return _config_invalid_error(exc, command="config --validate")
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command="config --validate")
        return 0

    if args.path:
        print(str(config_path))
        return 0

    if args.defaults:
        _emit_success(
            DEFAULTS,
            output_format=output_format,
            command="config",
            json_indent=2,
        )
        return 0

    # No subcommand or flag: print effective config
    try:
        cfg = _load_effective_config(config_path, explicit=explicit)
    except FileNotFoundError as exc:
        return _config_missing_error(exc, command="config")
    except ValidationError as exc:
        return _config_invalid_error(exc, command="config")
    _emit_success(
        cfg.effective_config,
        output_format=output_format,
        command="config",
        json_indent=2,
    )
    return 0


def _handle_init_command(
    config_path: Path,
    *,
    explicit: bool,
    db_path: str | None,
    log_level: str | None,
    output_format: str,
) -> int:
    """Initialize Recollectium config, directories, database, and model cache."""
    if explicit and not config_path.exists():
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)

    cfg = RecollectiumConfig(config_path if explicit else None, log_level=log_level)
    selected_db_path = (
        Path(db_path) if db_path is not None else cfg.resolved_database_path
    )
    SQLiteMemoryStore(selected_db_path)
    _log.info(
        "preparing embedding model (first run may download ~100 MB)",
        extra={"event": "init.model_prepare"},
    )
    BuiltinFastEmbedProvider().ensure_ready()

    # Record the prepared model so the readiness gate sees it.
    model_name = cfg.effective_config["embedding"]["model"]
    provider = BuiltinFastEmbedProvider()
    write_model_state(
        Path(user_state_dir("recollectium")),
        model=model_name,
        dimensions=provider.dimensions,
        profile=provider.profile_name,
    )

    result = {
        "status": "initialized",
        "config": str(cfg.config_file_path),
        "data": str(cfg.xdg_dirs["data"]),
        "cache": str(cfg.xdg_dirs["cache"]),
        "logs": str(cfg.xdg_dirs["logs"]),
        "runtime": str(cfg.xdg_dirs["runtime"]),
        "database": str(selected_db_path),
        "embedding_model": cfg.effective_config["embedding"]["model"],
    }
    _emit_success(result, output_format=output_format, command="init")
    return 0


# -- CLI failure contract -------------------------------------------------
#
# Except for argparse-generated help/usage output, command failures follow the
# active CLI output format on stderr and keep stdout reserved for success output.
# Logs are diagnostic telemetry only: they must not be used as CLI control-flow
# payloads, must not write to stdout, and must avoid sensitive content.
def _print_json_stderr(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


_CURRENT_CLI_OUTPUT_FORMAT = CLI_OUTPUT_JSON


def _set_cli_output_format(output_format: str) -> None:
    global _CURRENT_CLI_OUTPUT_FORMAT
    _CURRENT_CLI_OUTPUT_FORMAT = output_format


def _format_human_error(payload: dict[str, object], *, color: bool = False) -> str:
    lines = [
        _style(
            str(payload.get("message") or "Command failed."), _RICH_ERROR, enabled=color
        )
    ]
    status = payload.get("status")
    if status is not None:
        lines.append(f"  {_format_label('Status', color=color)} {_json_scalar(status)}")
    detail = payload.get("detail")
    if detail is not None:
        lines.append(f"  {_format_label('Detail', color=color)} {_json_scalar(detail)}")
    hint = payload.get("hint")
    if hint is not None:
        lines.append(
            f"  {_format_label('Hint', color=color)} "
            f"{_style(_json_scalar(hint), _RICH_HINT, enabled=color)}"
        )
    for key, value in payload.items():
        if key in {"message", "status", "detail", "hint"}:
            continue
        lines.append(
            f"  {_format_label(_humanize_key(key), color=color)} {_json_scalar(value)}"
        )
    return "\n".join(lines)


def _emit_failure_payload(payload: dict[str, object]) -> None:
    if _CURRENT_CLI_OUTPUT_FORMAT == CLI_OUTPUT_HUMAN_READABLE:
        print(
            _format_human_error(payload, color=_supports_color(sys.stderr)),
            file=sys.stderr,
        )
        return
    _print_json_stderr(payload)


def _emit_cli_failure(
    *,
    status: str,
    message: str,
    exit_code: int,
    command: str | None = None,
    detail: str | None = None,
    hint: str | None = None,
    event: str = "cli.failure",
    **fields: object,
) -> int:
    payload: dict[str, object] = {"status": status, "message": message}
    if detail is not None:
        payload["detail"] = detail
    if hint is not None:
        payload["hint"] = hint
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    _emit_failure_payload(payload)
    _log.info(
        "CLI command failed",
        extra={
            "event": event,
            "context": {
                "command": command,
                "status": status,
                "exit_code": exit_code,
            },
        },
    )
    return exit_code


def _config_missing_error(exc: FileNotFoundError, *, command: str | None) -> int:
    return _emit_cli_failure(
        status="config_missing",
        message="Config file was not found.",
        detail=str(exc),
        hint="Check the --config path or omit --config to use the default config location.",
        exit_code=1,
        command=command,
        event="config.missing",
    )


def _config_invalid_error(exc: ValidationError, *, command: str | None) -> int:
    return _emit_cli_failure(
        status="config_invalid",
        message="Config is invalid.",
        detail=f"ValidationError: {exc}",
        hint="Fix the config file or run recollectium config reset to restore defaults.",
        exit_code=2,
        command=command,
        event="config.invalid",
    )


def _validation_error(
    exc: ValidationError,
    *,
    command: str | None,
    status: str = "validation_error",
    event: str = "cli.failure",
    exit_code: int = 2,
) -> int:
    message = "Input validation failed."
    return _emit_cli_failure(
        status=status,
        message=message,
        detail=f"ValidationError: {exc}",
        exit_code=exit_code,
        command=command,
        event=event,
    )


def _metadata_invalid_error(exc: _MetadataInvalidError) -> int:
    return _emit_cli_failure(
        status="metadata_invalid",
        message="Metadata must be a JSON object.",
        detail=f"ValidationError: {exc}",
        hint='Pass metadata as a JSON object, for example --metadata \'{"source": "notes"}\'.',
        exit_code=2,
        command="memory metadata",
        event="memory.metadata_invalid",
    )


def _workspace_validation_error(exc: ValidationError, *, command: str) -> int:
    detail = str(exc)
    if (
        "workspace alias already exists" in detail
        or "workspace alias conflicts with existing workspace memories" in detail
    ):
        return _emit_cli_failure(
            status="operation_failed",
            message="Workspace operation could not be completed because of existing resources.",
            detail=f"ValidationError: {exc}",
            hint="Resolve the existing workspace or alias conflict and retry.",
            exit_code=1,
            command=command,
            event="workspace.resource_conflict",
        )
    return _validation_error(exc, command=command, event="workspace.invalid")


def _not_found_error(exc: Exception, *, command: str | None) -> int:
    return _emit_cli_failure(
        status="not_found",
        message="Requested resource was not found.",
        detail=f"{exc.__class__.__name__}: {exc}",
        exit_code=1,
        command=command,
    )


def _service_error(
    exc: Exception,
    *,
    command: str | None,
    status: str = "service_error",
    exit_code: int = 1,
    event: str = "cli.failure",
) -> int:
    return _emit_cli_failure(
        status=status,
        message="Service operation failed.",
        detail=f"{exc.__class__.__name__}: {exc}",
        exit_code=exit_code,
        command=command,
        event=event,
    )


def _embedding_error(exc: Exception, *, command: str | None) -> int:
    if isinstance(exc, EmbeddingReadinessTimeoutError):
        return _emit_cli_failure(
            status="embedding_timeout",
            message="Embedding model readiness timed out.",
            detail=f"{exc.__class__.__name__}: {exc}",
            hint="Check your internet connection and retry recollectium init.",
            exit_code=1,
            command=command,
            event="embedding.readiness_timeout",
        )
    if isinstance(exc, EmbeddingModelUnavailableError):
        return _emit_cli_failure(
            status="embedding_model_unavailable",
            message="Embedding model could not be loaded or downloaded.",
            detail=f"{exc.__class__.__name__}: {exc}",
            hint="Check your internet connection and retry recollectium init.",
            exit_code=1,
            command=command,
            event="embedding.model_unavailable",
        )
    if isinstance(exc, EmbeddingProviderUnavailableError):
        return _emit_cli_failure(
            status="embedding_provider_unavailable",
            message="Embedding provider is unavailable.",
            detail=f"{exc.__class__.__name__}: {exc}",
            hint="Check the local runtime and retry recollectium init.",
            exit_code=1,
            command=command,
            event="embedding.provider_unavailable",
        )
    return _emit_cli_failure(
        status="embedding_error",
        message="Embedding operation failed.",
        detail=f"{exc.__class__.__name__}: {exc}",
        exit_code=1,
        command=command,
    )


def _operation_failed_error(exc: Exception, *, command: str | None) -> int:
    return _emit_cli_failure(
        status="operation_failed",
        message="Operation failed.",
        detail=f"{exc.__class__.__name__}: {exc}",
        exit_code=1,
        command=command,
    )


def _handle_upgrade_command(
    args: argparse.Namespace, config_path: Path, *, output_format: str
) -> int:
    """Check for and optionally apply a Recollectium package upgrade."""
    metadata = load_install_metadata()
    install_method = (
        detect_install_method(metadata)
        if args.install_method == "auto"
        else args.install_method
    )
    repo = args.repo or "AlfonsoDehesa/recollectium"
    allow_main = args.allow_main or args.repo is not None

    latest_release: ReleaseInfo | None
    try:
        latest_release = fetch_latest_release(GitHubReleaseClient(), repo=repo)
    except ReleaseLookupError as exc:
        if exc.reason == "no_latest_release" and allow_main:
            latest_release = None
        else:
            return _emit_cli_failure(
                status="network_error",
                message="Could not fetch latest Recollectium release from GitHub.",
                detail=str(exc),
                reason=exc.reason,
                hint="Check your network connection or retry later.",
                exit_code=1,
                command="upgrade",
                event="upgrade.release_lookup_failed",
            )

    source_root = find_source_checkout_root(Path(__file__).resolve())
    plan = build_update_plan(
        current_version=__version__,
        latest_release=latest_release,
        install_method=install_method,
        metadata=metadata,
        force=args.force,
        dry_run=args.dry_run or args.check,
        allow_main=allow_main,
        repo=repo,
        source_root=source_root,
    )
    payload = plan_to_dict(plan)

    services_to_restart: list[str] = []
    cfg: RecollectiumConfig | None = None
    service_config_path = _core_config_path(
        str(config_path) if args.config_path is not None else None
    )
    should_check_services = not (
        (args.check or args.dry_run)
        and (service_config_path is None or not service_config_path.exists())
    )
    if should_check_services:
        try:
            cfg = RecollectiumConfig(
                service_config_path,
                log_level=args.log_level,
            )
            running = check_running_service(cfg)
            if running is not None:
                services_to_restart.append(str(running["type"]))
        except (FileNotFoundError, ValidationError, ServiceError):
            cfg = None
    payload["services_to_restart"] = services_to_restart

    if plan.status in {"up_to_date", "dry_run", "update_available"} and (
        args.check or args.dry_run or plan.command is None
    ):
        _emit_success(payload, output_format=output_format, command="upgrade")
        return 0

    if plan.status == "unsupported_install_method":
        return _emit_cli_failure(
            status=plan.status,
            message="Could not determine how Recollectium was installed.",
            detail=plan.reason,
            hint="Run recollectium upgrade --install-method pip, pipx, uv_tool, or source if you know the install method.",
            exit_code=2,
            command="upgrade",
            event="upgrade.unsupported_install_method",
        )
    if plan.status == "network_error":
        return _emit_cli_failure(
            status=plan.status,
            message="Could not fetch latest Recollectium release from GitHub.",
            detail=plan.reason,
            hint="Check your network connection or retry later.",
            exit_code=1,
            command="upgrade",
            event="upgrade.network_error",
        )
    if plan.status == "update_failed" and plan.command is None:
        return _emit_cli_failure(
            status="update_failed",
            message="Could not prepare the Recollectium package upgrade.",
            detail=plan.reason,
            hint="Run from a Recollectium source checkout or choose a different --install-method.",
            returncode=1,
            exit_code=1,
            command="upgrade",
            event="upgrade.prepare_failed",
        )

    service_stop_errors: list[dict[str, str]] = []
    if cfg is not None:
        for service_type in services_to_restart:
            try:
                stop_service(cfg)
            except ServiceError as exc:
                service_stop_errors.append({"type": service_type, "error": str(exc)})
    if service_stop_errors:
        payload["service_stop_errors"] = service_stop_errors
        return _emit_cli_failure(
            status="service_error",
            message="Could not stop running Recollectium services before upgrade.",
            detail="; ".join(error["error"] for error in service_stop_errors),
            service_stop_errors=service_stop_errors,
            exit_code=1,
            command="upgrade",
            event="upgrade.service_stop_failed",
        )

    result = apply_update(
        plan, runner=SubprocessCommandRunner(), timeout_seconds=args.timeout
    )
    payload["stdout"] = result.stdout
    payload["stderr"] = result.stderr
    service_restart_errors: list[dict[str, str]] = []
    if result.returncode != 0:
        payload["status"] = "update_failed"
        payload["returncode"] = result.returncode
        payload["message"] = "Recollectium package upgrade failed."
        payload["detail"] = result.stderr or result.stdout or plan.reason
        payload["hint"] = (
            "Review stderr, check that the package manager is installed, and retry after resolving the error."
        )
        if cfg is not None:
            for service_type in services_to_restart:
                try:
                    start_service(
                        cfg,
                        service_type,
                        db_path=args.db_path,
                        log_level=args.log_level,
                    )
                except (ServiceConflictError, ServiceError, ValueError) as exc:
                    service_restart_errors.append(
                        {"type": service_type, "error": str(exc)}
                    )
        if service_restart_errors:
            payload["service_restart_errors"] = service_restart_errors
        return _emit_cli_failure(
            status="update_failed",
            message="Recollectium package upgrade failed.",
            detail=result.stderr or result.stdout or plan.reason,
            hint="Review stderr, check that the package manager is installed, and retry after resolving the error.",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            service_restart_errors=service_restart_errors or None,
            exit_code=result.returncode if 1 <= result.returncode <= 125 else 1,
            command="upgrade",
            event="upgrade.update_failed",
        )

    payload["status"] = "updated"
    if cfg is not None:
        for service_type in services_to_restart:
            try:
                time.sleep(0.5)
                start_service(
                    cfg, service_type, db_path=args.db_path, log_level=args.log_level
                )
            except (ServiceConflictError, ServiceError, ValueError) as exc:
                service_restart_errors.append({"type": service_type, "error": str(exc)})
    if service_restart_errors:
        payload["service_restart_errors"] = service_restart_errors
        return _emit_cli_failure(
            status="service_error",
            message="Recollectium upgraded, but services could not be restarted.",
            detail="; ".join(error["error"] for error in service_restart_errors),
            service_restart_errors=service_restart_errors,
            exit_code=1,
            command="upgrade",
            event="upgrade.service_restart_failed",
        )
    _emit_success(payload, output_format=output_format, command="upgrade")
    return 0


_COMPLETION_RC_FILES: dict[str, str] = {
    "bash": ".bashrc",
    "zsh": ".zshrc",
    "fish": ".config/fish/config.fish",
}
_COMPLETION_SHELLS = ("bash", "zsh", "fish", "powershell")
_COMPLETION_BLOCK_START = "# >>> recollectium completion >>>"
_COMPLETION_BLOCK_END = "# <<< recollectium completion <<<"
_COMPLETION_BLOCK_PATTERN = re.compile(
    rf"\n?{re.escape(_COMPLETION_BLOCK_START)}\n.*?\n"
    rf"{re.escape(_COMPLETION_BLOCK_END)}\n?",
    re.DOTALL,
)


def _detect_shell() -> str | None:
    shell_path = os.environ.get("SHELL", "")
    basename = Path(shell_path).name
    if basename in _COMPLETION_RC_FILES:
        return basename
    if sys.platform.startswith("win") or os.environ.get("PSModulePath"):
        return "powershell"
    return None


def _powershell_profile_path() -> Path:
    override = os.environ.get("RECOLLECTIUM_POWERSHELL_PROFILE")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        documents = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        return documents / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    return Path.home() / ".config" / "powershell" / "Microsoft.PowerShell_profile.ps1"


def _completion_target_path(shell: str) -> Path:
    if shell == "powershell":
        return _powershell_profile_path()
    rc_filename = _COMPLETION_RC_FILES.get(shell)
    if rc_filename is None:
        raise KeyError(shell)
    return Path.home() / rc_filename


def _powershell_completion_script() -> str:
    return r"""
Register-ArgumentCompleter -Native -CommandName recollectium -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $line = $commandAst.Extent.Text
    $json = & recollectium completion --complete-line $line --point $cursorPosition 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        return
    }

    try {
        $candidates = $json | ConvertFrom-Json
    }
    catch {
        return
    }

    foreach ($candidate in $candidates) {
        [System.Management.Automation.CompletionResult]::new(
            $candidate,
            $candidate,
            [System.Management.Automation.CompletionResultType]::ParameterValue,
            $candidate
        )
    }
}
""".strip()


def _completion_source(shell: str) -> str:
    if shell == "powershell":
        return _powershell_completion_script()
    return argcomplete.shellcode(["recollectium"], shell=shell)  # pyright: ignore[reportPrivateImportUsage]


def _powershell_completion_profile_block() -> str:
    return r"""
if (Get-Command recollectium -ErrorAction SilentlyContinue) {
    Invoke-Expression (& recollectium completion --source powershell)
}
""".strip()


def _completion_block(shell: str) -> str:
    if shell == "powershell":
        body = _powershell_completion_profile_block()
    else:
        body = f'eval "$(recollectium completion --source {shell})"'
    return f"{_COMPLETION_BLOCK_START}\n{body}\n{_COMPLETION_BLOCK_END}\n"


def _completion_marker(shell: str) -> str:
    return f"recollectium completion --source {shell}"


def _completion_candidates(line: str, point: int | None) -> list[str]:
    parser = _build_parser()
    prequote, prefix, _suffix, words, last_wordbreak_pos = argcomplete.split_line(  # pyright: ignore[reportPrivateImportUsage]
        line, point
    )
    finder = argcomplete.CompletionFinder(parser)  # pyright: ignore[reportPrivateImportUsage]
    raw = finder._get_completions(  # pyright: ignore[reportPrivateUsage]
        words,
        prefix,
        prequote,
        last_wordbreak_pos,
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for item in raw:
        candidate = item.rstrip()
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def _handle_completion_command(args: argparse.Namespace, *, output_format: str) -> int:
    if args.complete_line is not None:
        candidates = _completion_candidates(args.complete_line, args.point)
        print(json.dumps(candidates, sort_keys=True))
        return 0

    shell = args.shell
    if shell is None:
        shell = _detect_shell()
    if shell is None:
        return _emit_cli_failure(
            status="validation_error",
            message="Could not detect a supported shell.",
            hint="Pass the shell name explicitly, such as recollectium completion --install bash.",
            exit_code=2,
            command="completion",
            event="completion.unknown_shell",
        )

    if args.source:
        output = _completion_source(shell)
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if args.install:
        try:
            rc_path = _completion_target_path(shell)
        except KeyError:
            return _emit_cli_failure(
                status="operation_failed",
                message="No shell rc file mapping is available.",
                detail=f"No rc file mapping for shell {shell}",
                exit_code=1,
                command="completion --install",
                event="completion.unknown_rc",
            )

        try:
            existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
        except OSError as exc:
            return _emit_cli_failure(
                status="operation_failed",
                message="Could not read rc file.",
                detail=str(exc),
                exit_code=1,
                command="completion --install",
                event="completion.rc_read_error",
                path=str(rc_path),
            )

        marker = _completion_marker(shell)
        if marker in existing and _COMPLETION_BLOCK_START not in existing:
            response_payload: dict[str, Any] = {
                "status": "already_installed",
                "rc_file": str(rc_path),
                "shell": shell,
                "updated": False,
            }
            if shell == "powershell":
                response_payload["profile"] = str(rc_path)
            _emit_success(
                response_payload, output_format=output_format, command="completion"
            )
            return 0

        block = _completion_block(shell)
        status = "installed"
        updated_content = existing
        block_found = _COMPLETION_BLOCK_PATTERN.search(existing) is not None
        if block_found:
            updated_content = _COMPLETION_BLOCK_PATTERN.sub("\n" + block, existing)
            status = "updated"
        else:
            updated_content = existing + (
                "\n" if existing and not existing.endswith("\n") else ""
            )
            updated_content += "\n" + block

        if marker in existing and block_found and block in existing:
            response_payload = {
                "status": "already_installed",
                "rc_file": str(rc_path),
                "shell": shell,
                "updated": False,
            }
            if shell == "powershell":
                response_payload["profile"] = str(rc_path)
            _emit_success(
                response_payload, output_format=output_format, command="completion"
            )
            return 0

        if not args.yes:
            if sys.stdin.isatty():
                _write_tty(
                    f"Will append or refresh the following managed block in {rc_path}:\n\n{block}\n"
                    "Proceed? Type 'yes' to confirm: "
                )
            response = sys.stdin.readline().strip()
            if response.lower() != "yes":
                return _emit_cli_failure(
                    status="operation_failed",
                    message="Completion installation cancelled.",
                    hint="Re-run with --yes to skip the confirmation prompt.",
                    exit_code=1,
                    command="completion --install",
                    event="completion.cancelled",
                )

        try:
            rc_path.parent.mkdir(parents=True, exist_ok=True)
            rc_path.write_text(updated_content, encoding="utf-8")
        except OSError as exc:
            return _emit_cli_failure(
                status="operation_failed",
                message=f"Could not write to {rc_path}.",
                detail=str(exc),
                exit_code=1,
                command="completion --install",
                event="completion.rc_write_error",
                path=str(rc_path),
            )

        response_payload: dict[str, Any] = {
            "status": status,
            "rc_file": str(rc_path),
            "shell": shell,
            "updated": status == "updated",
        }
        if shell == "powershell":
            response_payload["profile"] = str(rc_path)
        _emit_success(
            response_payload, output_format=output_format, command="completion"
        )
        return 0

    if shell == "powershell":
        instructions = [
            "Add this block to $PROFILE.CurrentUserCurrentHost for PowerShell tab completion:",
            "",
            "  recollectium completion powershell --source | Invoke-Expression",
            "",
            "Or run this to install it automatically:",
            "",
            "  recollectium completion --install powershell",
            "",
            "For all hosts, manually add the same source command to $PROFILE.CurrentUserAllHosts.",
        ]
    else:
        eval_line = f'eval "$(recollectium completion --source {shell})"'
        instructions = [
            f"Add this line to your shell rc file for {shell} tab completion:",
            "",
            f"  {eval_line}",
            "",
            "Or run this to install it automatically:",
            "",
            f"  recollectium completion --install {shell}",
            "",
            "After adding the line, restart your shell or run:",
            f"  source ~/{_COMPLETION_RC_FILES[shell]}",
        ]
    sys.stdout.write("\n".join(instructions) + "\n")
    return 0


def _load_uninstall_plan(config_path: Path, *, explicit: bool) -> _UninstallPlan:
    """Resolve uninstall targets without creating files or directories."""
    if explicit and not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    if config_path.exists():
        raw = load_config_file(config_path)
    else:
        raw = {}
    effective_config = _deep_merge(deepcopy(DEFAULTS), raw)
    _validate_config_value(effective_config)
    xdg_dirs = _resolve_xdg_dirs(effective_config.get("directories", {}))

    database_path = Path(effective_config["database"]["path"])
    if not database_path.is_absolute():
        database_path = xdg_dirs["data"] / database_path

    install_metadata_path = _resolve_install_metadata_path()
    return _UninstallPlan(
        config=_UninstallConfig(
            effective_config=effective_config,
            xdg_dirs=xdg_dirs,
            config_path=config_path,
            database_path=database_path,
        ),
        config_path=config_path,
        database_path=database_path,
        install_metadata_path=install_metadata_path,
    )


def _resolve_install_metadata_path() -> Path:
    """Return install metadata path, including bootstrap-script legacy paths."""
    default_path = Path(user_state_dir("recollectium")) / _INSTALL_METADATA_FILE
    candidates = [default_path]
    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "recollectium" / _INSTALL_METADATA_FILE
            )
    else:
        candidates.append(
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "recollectium"
            / _INSTALL_METADATA_FILE
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return default_path


def _load_install_metadata(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _uninstall_package_instructions(
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    commands = {
        "bootstrap": "uv tool uninstall recollectium",
        "uv_tool": "uv tool uninstall recollectium",
        "pip": "python -m pip uninstall recollectium",
        "pipx": "pipx uninstall recollectium",
        "dev_source": "deactivate this checkout or remove it from your shell path manually",
    }
    install_method = None
    source_ref = None
    managed_path_edits: list[str] = []
    if metadata is not None:
        raw_method = metadata.get("install_method")
        raw_ref = metadata.get("source_ref")
        raw_path_edits = metadata.get("managed_path_edits")
        if isinstance(raw_method, str):
            install_method = raw_method
        if isinstance(raw_ref, str):
            source_ref = raw_ref
        if isinstance(raw_path_edits, list):
            managed_path_edits = [
                item for item in raw_path_edits if isinstance(item, str)
            ]

    recommended_key = install_method if install_method in commands else "uv_tool"
    return {
        "install_method": install_method or "unknown",
        "source_ref": source_ref,
        "recommended": commands[recommended_key],
        "commands": commands,
        "managed_path_edits": managed_path_edits,
    }


def _bootstrap_package_uninstall_status(
    metadata: dict[str, Any] | None,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    command = "uv tool uninstall recollectium"
    if not metadata or metadata.get("install_method") != "bootstrap":
        return {"status": "manual", "command": command}
    if dry_run:
        return {"status": "dry_run", "command": command}

    if sys.platform.startswith("win"):
        popen_cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "Start-Sleep -Seconds 1; uv tool uninstall recollectium",
        ]
    else:
        popen_cmd = ["sh", "-c", "sleep 1; uv tool uninstall recollectium"]
    try:
        subprocess.Popen(  # noqa: S603 - command is fixed, no user input.
            popen_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=not sys.platform.startswith("win"),
        )
    except OSError as exc:
        return {"status": "failed", "command": command, "error": str(exc)}
    return {"status": "started", "command": command}


def _completion_rc_paths(metadata: dict[str, Any] | None) -> list[Path]:
    raw_paths: list[Path] = []
    if metadata is not None:
        raw_path_edits = metadata.get("managed_path_edits")
        if isinstance(raw_path_edits, list):
            for item in raw_path_edits:
                if not isinstance(item, str):
                    continue
                if "recollectium completion --source" not in item:
                    continue
                raw_paths.append(Path(item.split(": ", 1)[0]))

        raw_completion_edits = metadata.get("managed_completion_edits")
        if isinstance(raw_completion_edits, list):
            for item in raw_completion_edits:
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("path")
                if isinstance(raw_path, str):
                    raw_paths.append(Path(raw_path))

    home = Path.home()
    raw_paths.extend(home / filename for filename in _COMPLETION_RC_FILES.values())
    raw_paths.append(_powershell_profile_path())

    paths: list[Path] = []
    seen: set[Path] = set()
    for path in raw_paths:
        resolved = path.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(path)
    return paths


def _remove_completion_blocks(
    metadata: dict[str, Any] | None,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for path in _completion_rc_paths(metadata):
        payload: dict[str, Any] = {"path": str(path), "removed": False}
        if not path.exists():
            payload["reason"] = "missing"
            results.append(payload)
            continue

        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            payload["reason"] = f"read_error: {exc}"
            results.append(payload)
            continue

        updated, count = _COMPLETION_BLOCK_PATTERN.subn("\n", existing)
        if count == 0:
            payload["reason"] = "not_found"
            results.append(payload)
            continue

        payload["blocks"] = count
        if dry_run:
            payload["reason"] = "dry_run"
            results.append(payload)
            continue

        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            payload["reason"] = f"write_error: {exc}"
            results.append(payload)
            continue

        payload["removed"] = True
        results.append(payload)

    return {
        "dry_run": dry_run,
        "targets": results,
        "removed": [item for item in results if item["removed"]],
        "skipped": [item for item in results if not item["removed"]],
    }


def _is_suspicious_purge_path(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    home = Path.home().expanduser().resolve(strict=False)
    cwd = Path.cwd().resolve(strict=False)
    return resolved in {Path(resolved.anchor), home, cwd}


def _is_recollectium_owned_path(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    parts = {part.lower() for part in resolved.parts}
    if "recollectium" in parts:
        return True
    if resolved.name in {"config.json", _INSTALL_METADATA_FILE}:
        return "recollectium" in {part.lower() for part in resolved.parent.parts}
    return False


def _path_payload(
    path: Path, *, deleted: bool, reason: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path), "deleted": deleted}
    if reason is not None:
        payload["reason"] = reason
    return payload


def _delete_purge_target(path: Path, *, dry_run: bool) -> dict[str, Any]:
    if _is_suspicious_purge_path(path):
        return _path_payload(path, deleted=False, reason="suspicious_path")
    if not _is_recollectium_owned_path(path):
        return _path_payload(path, deleted=False, reason="not_recollectium_owned")
    if not path.exists():
        return _path_payload(path, deleted=False, reason="missing")
    if dry_run:
        return _path_payload(path, deleted=False, reason="dry_run")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return _path_payload(path, deleted=True)


def _purge_targets(plan: _UninstallPlan, *, dry_run: bool) -> dict[str, Any]:
    raw_targets = [
        plan.config_path,
        plan.config_path.parent,
        plan.config.xdg_dirs["data"],
        plan.config.xdg_dirs["cache"],
        plan.config.xdg_dirs["logs"],
        plan.config.xdg_dirs["runtime"],
        plan.install_metadata_path,
    ]
    targets: list[Path] = []
    seen: set[Path] = set()
    for target in raw_targets:
        resolved = target.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        targets.append(target)

    results = [_delete_purge_target(target, dry_run=dry_run) for target in targets]
    return {
        "dry_run": dry_run,
        "targets": results,
        "deleted": [item for item in results if item["deleted"]],
        "skipped": [item for item in results if not item["deleted"]],
    }


def _handle_uninstall_command(
    args: argparse.Namespace,
    config_path: Path,
    *,
    explicit: bool,
    output_format: str,
) -> int:
    """Print uninstall instructions and optionally purge Recollectium-owned data."""
    if args.yes_delete_all_recollectium_data and not args.purge:
        return _emit_cli_failure(
            status="uninstall_invalid_flags",
            message="--yes-delete-all-recollectium-data requires --purge.",
            hint="Add --purge or remove --yes-delete-all-recollectium-data.",
            exit_code=2,
            command="uninstall",
            event="uninstall.invalid_flags",
        )

    plan = _load_uninstall_plan(config_path, explicit=explicit)
    metadata = _load_install_metadata(plan.install_metadata_path)

    service_payload: dict[str, Any]
    if args.dry_run:
        service_payload = {"status": "dry_run", "note": "service would be stopped"}
    else:
        stopped_pid = stop_service(plan.config)
        service_payload = {"status": "no_service_running"}
        if stopped_pid is not None:
            service_payload = {"status": "stopped", "pid": stopped_pid}

    data_payload: dict[str, Any] = {
        "preserved": not args.purge,
        "paths": {
            "config": str(plan.config_path),
            "data": str(plan.config.xdg_dirs["data"]),
            "cache": str(plan.config.xdg_dirs["cache"]),
            "logs": str(plan.config.xdg_dirs["logs"]),
            "runtime": str(plan.config.xdg_dirs["runtime"]),
            "database": str(plan.database_path),
        },
    }
    completion_payload = _remove_completion_blocks(metadata, dry_run=args.dry_run)

    if args.purge:
        if args.dry_run:
            data_payload["purge"] = _purge_targets(plan, dry_run=True)
        else:
            preview = _purge_targets(plan, dry_run=True)
            interactive = sys.stdin.isatty()

            if not args.yes_delete_all_recollectium_data:
                if interactive:
                    _write_tty(
                        "Type 'delete all recollectium data' to permanently delete Recollectium data: "
                    )
                response = sys.stdin.readline().rstrip("\n")
                if response != _PURGE_CONFIRMATION:
                    return _emit_cli_failure(
                        status="purge_cancelled",
                        message="purge cancelled",
                        hint="Type the exact confirmation phrase to permanently delete Recollectium data.",
                        exit_code=1,
                        command="uninstall --purge",
                        event="uninstall.purge_cancelled",
                    )

            sys.stderr.write(
                "The following Recollectium-owned paths will be permanently deleted:\n"
            )
            for target in preview["targets"]:
                if target.get("reason") == "missing":
                    continue
                sys.stderr.write(f"  {target['path']}\n")
            sys.stderr.write("\n")

            logging.shutdown()
            data_payload["purge"] = _purge_targets(plan, dry_run=False)

    package_payload = _uninstall_package_instructions(metadata)
    package_payload["uninstall"] = _bootstrap_package_uninstall_status(
        metadata, dry_run=args.dry_run
    )
    result = {
        "status": "manual_uninstall_required",
        "package": package_payload,
        "service": service_payload,
        "shell_completion": completion_payload,
        "data": data_payload,
    }
    if not args.purge:
        _log.info(
            "Uninstall instructions generated",
            extra={"event": "uninstall.instructions"},
        )
    _emit_success(result, output_format=output_format, command="uninstall")
    return 0


def _handle_workspace_command(
    args: argparse.Namespace,
    *,
    core: RecollectiumCore,
    output_format: str,
) -> int:
    """Handle the `recollectium workspace` subcommands."""
    if args.workspace_action == "list":
        uids = core.list_workspaces(
            include_archived=getattr(args, "include_archived", False),
            include_aliases=getattr(args, "include_aliases", False),
        )
        _emit_success(uids, output_format=output_format, command="workspace list")
        return 0

    if args.workspace_action == "resolve":
        try:
            result = core.resolve_workspace(args.uid)
            _emit_success(
                result, output_format=output_format, command="workspace resolve"
            )
            return 0
        except ValidationError as exc:
            return _validation_error(
                exc, command="workspace resolve", event="workspace.invalid"
            )

    if args.workspace_action == "alias":
        try:
            if args.alias_action == "add":
                result = core.add_workspace_alias(
                    canonical_uid=args.canonical_uid,
                    alias_uid=args.alias_uid,
                    migrate_existing=getattr(args, "migrate_existing", False),
                )
            elif args.alias_action == "list":
                result = core.list_workspace_aliases(
                    canonical_uid=getattr(args, "workspace", None)
                )
            elif args.alias_action == "remove":
                result = core.remove_workspace_alias(args.alias_uid)
            else:  # pragma: no cover — parser enforces valid actions
                return 1
            _emit_success(
                result, output_format=output_format, command="workspace alias"
            )
            return 0
        except ValidationError as exc:
            return _workspace_validation_error(exc, command="workspace alias")
        except NotFoundError as exc:
            return _not_found_error(exc, command="workspace alias")

    if args.workspace_action == "rename":
        try:
            result = core.rename_workspace(
                old_uid=args.old_uid,
                new_uid=args.new_uid,
            )
            _emit_success(
                result, output_format=output_format, command="workspace rename"
            )
            return 0
        except ValidationError as exc:
            return _workspace_validation_error(exc, command="workspace rename")
        except NotFoundError as exc:
            return _not_found_error(exc, command="workspace rename")

    return 1  # pragma: no cover — parser enforces valid actions


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recollectium",
        description=(
            "Recollectium Core local memory CLI. Commands print JSON on success and "
            "structured JSON on stderr for non-argparse failures."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help=(
            "Path to Recollectium JSON config file. Defaults to the XDG config "
            "location and auto-creates there on first use. Explicit missing "
            "paths fail except config creation commands."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        help=(
            "SQLite database path. Overrides the database.path config value. "
            "Defaults to ~/.local/share/recollectium/recollectium.db."
        ),
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["debug", "info", "warning", "error"],
        help=(
            "Override the logging.level config value for this invocation. "
            "Does not modify the config file."
        ),
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output for this invocation, overriding cli_output.",
    )
    output_group.add_argument(
        "--human-readable",
        action="store_true",
        help="Print human-readable output for this invocation, overriding cli_output.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print installed Recollectium version and exit.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="COMMAND",
    )

    subparsers.add_parser(
        "init",
        help="initialize Recollectium config, database, and model cache",
        description=(
            "Create the config file and XDG directories, run database migrations, "
            "and download the built-in FastEmbed model so Recollectium is ready to use. "
            "The first run downloads ~100 MB and may take 30-120 seconds."
        ),
    )
    init_parser = subparsers.choices["init"]
    init_parser.add_argument(
        "--db",
        dest="db_path",
        help=(
            "SQLite database path for initialization. Also available as the global "
            "--db flag before the command."
        ),
    )

    # -- config ----------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config",
        help="inspect, validate, and edit Recollectium configuration",
        description=(
            "Inspect, validate, and edit the Recollectium JSON config file. "
            "Without arguments, prints the effective configuration (defaults "
            "merged with explicit overrides) as human-readable text by default, "
            "or as JSON when requested."
        ),
    )
    config_parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the config file and exit 0 on success, 1 when a file is missing, or 2 when invalid.",
    )
    config_parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved config file path without creating a file.",
    )
    config_parser.add_argument(
        "--defaults",
        action="store_true",
        help=(
            "Print built-in default values without creating a file. Uses JSON "
            "by default, or human-readable text when requested."
        ),
    )

    config_sub = config_parser.add_subparsers(
        dest="config_action",
        title="config actions",
        metavar="ACTION",
    )

    get_parser = config_sub.add_parser(
        "get",
        help="get a single config value by dot-notation key",
        description="Print the effective config value for a dot-notation key.",
    )
    get_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    ).completer = ChoicesCompleter(_COMPLETABLE_CONFIG_KEYS)  # pyright: ignore[reportAttributeAccessIssue]

    set_parser = config_sub.add_parser(
        "set",
        help="set a config value by dot-notation key",
        description="Write a value to the config file, auto-creating it if needed.",
    )
    set_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    ).completer = ChoicesCompleter(_COMPLETABLE_CONFIG_KEYS)  # pyright: ignore[reportAttributeAccessIssue]
    set_parser.add_argument(
        "value",
        help="Value to write. Parsed as JSON when possible; stored as string otherwise.",
    )

    unset_parser = config_sub.add_parser(
        "unset",
        help="remove a key from the config file",
        description="Remove a key from the config file so the built-in default applies.",
    )
    unset_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    ).completer = ChoicesCompleter(_COMPLETABLE_CONFIG_KEYS)  # pyright: ignore[reportAttributeAccessIssue]

    init_parser = config_sub.add_parser(
        "init",
        help="create or overwrite the starter config file",
        description="Create a starter config file with all built-in default values.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the config file if it already exists.",
    )

    config_sub.add_parser(
        "doctor",
        help="run config and filesystem checks",
        description=(
            "Validate config and check that resolved data, cache, logs, runtime, "
            "and database parent directories exist, are directories, and are writable."
        ),
    )

    config_sub.add_parser(
        "edit",
        help="open the config file in $EDITOR",
        description=(
            "Open the active config file in $EDITOR. Creates the config file with "
            "defaults first if it does not exist."
        ),
    )

    config_sub.add_parser(
        "reset",
        help="reset the config file to defaults",
        description=(
            "Replace the config file with a fresh copy of built-in defaults. "
            "Creates the file if it does not exist."
        ),
    )

    # -- add --------------------------------------------------------------
    add_parser = subparsers.add_parser(
        "add",
        help="add a user or workspace memory",
        description=(
            "Add a memory to the local Recollectium database. User memories must not "
            "include --workspace-uid. Workspace memories require --workspace-uid."
        ),
    )
    add_parser.add_argument(
        "--space",
        required=True,
        help="Memory space: 'user' for global user memory or 'workspace' for workspace memory.",
    )
    add_parser.add_argument(
        "--type",
        required=True,
        help="Canonical memory type bucket, such as fact, preference, note, decision, or task_context.",
    ).completer = _memory_type_completer  # pyright: ignore[reportAttributeAccessIssue]
    add_parser.add_argument(
        "--content",
        required=True,
        help="Memory text to store and embed for search.",
    )
    add_parser.add_argument(
        "--workspace-uid",
        help="Stable workspace UID. Required when --space workspace; forbidden when --space user.",
    )
    add_parser.add_argument(
        "--metadata",
        help="Optional JSON object metadata, either inline JSON or @path/to/file.json.",
    )
    add_parser.add_argument(
        "--source",
        help="Optional source label describing where the memory came from.",
    )
    add_parser.add_argument(
        "--confidence",
        type=float,
        help="Optional confidence score from 0.0 to 1.0.",
    )
    add_parser.add_argument(
        "--sensitivity",
        help="Optional sensitivity label for privacy-aware handling later.",
    )

    # -- search-user ------------------------------------------------------
    search_user_parser = subparsers.add_parser(
        "search-user",
        help="search global user memories",
        description=(
            "Search active user memories semantically and return ranked JSON results. "
            "Searches default to all user buckets unless --type narrows the scope."
        ),
    )
    search_user_parser.add_argument(
        "query", help="Search text to match against user memories."
    )
    search_user_parser.add_argument(
        "--type",
        help="Optional canonical type bucket to narrow user search results.",
    ).completer = ChoicesCompleter(USER_MEMORY_TYPES)  # pyright: ignore[reportAttributeAccessIssue]
    search_user_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of ranked results to return. Must be positive. Defaults to 10.",
    )
    search_user_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in search candidates.",
    )

    # -- search-workspace -------------------------------------------------
    search_workspace_parser = subparsers.add_parser(
        "search-workspace",
        help="search memories for one workspace UID",
        description=(
            "Search active memories for a specific workspace UID and return ranked "
            "JSON results. Searches default to all workspace buckets unless --type narrows the scope."
        ),
    )
    search_workspace_parser.add_argument(
        "query", help="Search text to match against workspace memories."
    )
    search_workspace_parser.add_argument(
        "--type",
        help="Optional canonical type bucket to narrow workspace search results.",
    ).completer = ChoicesCompleter(WORKSPACE_MEMORY_TYPES)  # pyright: ignore[reportAttributeAccessIssue]
    search_workspace_parser.add_argument(
        "--workspace-uid",
        required=True,
        help="Stable workspace UID whose memories should be searched.",
    )
    search_workspace_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of ranked results to return. Must be positive. Defaults to 10.",
    )
    search_workspace_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in search candidates.",
    )

    # -- list --------------------------------------------------------------
    list_parser = subparsers.add_parser(
        "list",
        help="list memories with optional filters across all buckets by default",
        description=(
            "List memories as JSON, optionally filtered by space, type, status, "
            "workspace UID, or result limit. Archived memories are hidden unless "
            "requested."
        ),
    )
    list_parser.add_argument(
        "--space", help="Filter by memory space, usually 'user' or 'workspace'."
    )
    list_parser.add_argument(
        "--type", help="Filter by canonical memory type bucket."
    ).completer = ChoicesCompleter(ALL_MEMORY_TYPES)  # pyright: ignore[reportAttributeAccessIssue]
    list_parser.add_argument(
        "--status", help="Filter by memory status, such as active or archived."
    )
    list_parser.add_argument(
        "--workspace-uid", help="Filter to memories for one stable workspace UID."
    )
    list_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in list results.",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of memories to return. Must be positive.",
    )

    # -- get ---------------------------------------------------------------
    get_parser = subparsers.add_parser(
        "get",
        help="retrieve one memory by ID",
        description="Retrieve one memory by its ID and print it as JSON.",
    )
    get_parser.add_argument("memory_id", help="Memory ID to retrieve.")

    # -- update ------------------------------------------------------------
    update_parser = subparsers.add_parser(
        "update",
        help="update editable memory fields",
        description=(
            "Update one or more editable fields on a memory. "
            "Updating --content also regenerates that memory's embedding."
        ),
    )
    update_parser.add_argument(
        "memory_id",
        nargs="?",
        help="Memory ID to update. Use `recollectium upgrade` for package upgrades.",
    )
    update_parser.add_argument(
        "--type", help="Replacement canonical memory type bucket."
    ).completer = _memory_type_completer  # pyright: ignore[reportAttributeAccessIssue]
    update_parser.add_argument(
        "--content", help="Replacement memory text. Regenerates the stored embedding."
    )
    update_parser.add_argument(
        "--metadata",
        help="Replacement JSON object metadata, either inline JSON or @path/to/file.json.",
    )
    update_parser.add_argument(
        "--source",
        help="Replacement source label describing where the memory came from.",
    )
    update_parser.add_argument(
        "--confidence",
        type=float,
        help="Replacement confidence score from 0.0 to 1.0.",
    )
    update_parser.add_argument(
        "--sensitivity",
        help="Replacement sensitivity label for privacy-aware handling later.",
    )

    # -- upgrade -----------------------------------------------------------
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="upgrade the installed Recollectium package",
        description=(
            "Check the installed Recollectium version against the latest release and "
            "upgrade through the detected install method. Use --check or --dry-run for "
            "non-mutating modes."
        ),
    )
    upgrade_parser.add_argument(
        "--check",
        action="store_true",
        help="Check for an available upgrade and print the plan without applying it.",
    )
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upgrade command that would run without applying it.",
    )
    upgrade_parser.add_argument(
        "--force",
        action="store_true",
        help="Build and apply an upgrade plan even when versions appear current.",
    )
    upgrade_parser.add_argument(
        "--install-method",
        choices=["auto", "bootstrap", "pip", "pipx", "uv_tool", "source"],
        default="auto",
        help="Override install-method detection. Defaults to auto.",
    )
    upgrade_parser.add_argument(
        "--repo",
        help=(
            "GitHub OWNER/REPO to check for releases. Passing this also permits "
            "main fallback when no release exists."
        ),
    )
    upgrade_parser.add_argument(
        "--allow-main",
        action="store_true",
        help="Permit main-branch fallback for bootstrap/source upgrades if no release exists.",
    )
    upgrade_parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Package-manager command timeout in seconds. Defaults to 600.",
    )

    # -- uninstall ---------------------------------------------------------
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="print safe uninstall instructions or purge Recollectium data",
        description=(
            "Print package manager uninstall instructions while preserving memories by "
            "default. Use --purge to delete Recollectium-owned config, data, cache, logs, "
            "and runtime paths after explicit confirmation."
        ),
    )
    uninstall_parser.add_argument(
        "--purge",
        action="store_true",
        help=(
            "Permanently delete your memories and all Recollectium-owned config, data, "
            "cache, logs, and runtime paths. Without this flag, local data is preserved."
        ),
    )
    uninstall_parser.add_argument(
        "--yes-delete-all-recollectium-data",
        action="store_true",
        help=(
            "Confirm destructive data deletion for non-interactive purge. Requires --purge."
        ),
    )
    uninstall_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show planned actions without deleting files, stopping services, or "
            "removing data. Use with --purge to preview full deletion paths."
        ),
    )

    # -- archive -----------------------------------------------------------
    archive_parser = subparsers.add_parser(
        "archive",
        help="archive one memory by ID",
        description=(
            "Archive a memory by ID. Archived memories are hidden from default list "
            "and search results but are not hard-deleted."
        ),
    )
    archive_parser.add_argument("memory_id", help="Memory ID to archive.")

    # -- serve -------------------------------------------------------------
    serve_parser = subparsers.add_parser(
        "serve",
        help="run the local Recollectium HTTP service",
        description=(
            "Start a blocking local-first HTTP JSON service for Recollectium Core. "
            "By default it binds to localhost (127.0.0.1), exposes the /v1 "
            "service API, and keeps running until interrupted. Host and port "
            "can be set via config file or CLI flags. CLI flags override config. "
            "Non-local binds can expose unauthenticated memory operations unless "
            "protected by private networking and external access controls."
        ),
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help=(
            "Host interface to bind. Overrides service.host from config. "
            "Defaults to 127.0.0.1. Non-local binds should be protected by "
            "private networking and external access controls."
        ),
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "TCP port for the local service API. Overrides service.port from config. "
            "Defaults to 8765."
        ),
    )

    # -- service ------------------------------------------------------------
    service_parser = subparsers.add_parser(
        "service",
        help="manage Recollectium service lifecycle",
        description="Start, stop, check status, and restart Recollectium services.",
    )
    service_sub = service_parser.add_subparsers(
        dest="service_action",
        required=True,
        title="service actions",
        metavar="ACTION",
    )

    # service start
    start_parser = service_sub.add_parser("start", help="start a Recollectium service")
    start_parser.add_argument(
        "type",
        choices=["api", "mcp"],
        help="Service type to start: api (REST API) or mcp (MCP HTTP server)",
    )

    # service stop
    service_sub.add_parser("stop", help="stop the running Recollectium service")

    # service status
    service_sub.add_parser("status", help="show running service details")

    # service discover
    service_sub.add_parser(
        "discover",
        help="print machine-readable connection details for the running service",
        description=(
            "Print machine-readable connection details for local adapters as JSON. "
            "The command reports the running endpoint, version and capability URLs, "
            "PID path, and discovery file path without creating a config file."
        ),
    )

    # service restart
    restart_parser = service_sub.add_parser(
        "restart", help="restart the running service"
    )
    restart_parser.add_argument(
        "--type",
        choices=["api", "mcp"],
        help=(
            "Service type to restart (required if no running service is found "
            "or only a stale PID file exists)"
        ),
    )

    # -- db-status ---------------------------------------------------------
    subparsers.add_parser(
        "db-status",
        help="show database schema migration status",
        description=(
            "Show SQLite migration status as JSON for the selected database path. "
            "This command initializes the database if needed and reports current "
            "and pending schema versions."
        ),
    )

    # -- workspace ---------------------------------------------------------
    workspace_parser = subparsers.add_parser(
        "workspace",
        help="list and manage workspace UIDs",
        description="List, resolve, rename, and manage aliases for workspace UIDs.",
    )
    workspace_sub = workspace_parser.add_subparsers(
        dest="workspace_action",
        required=True,
        title="workspace actions",
        metavar="ACTION",
    )

    list_ws_parser = workspace_sub.add_parser(
        "list",
        help="list known workspace UIDs",
        description="List distinct workspace UIDs from the database as a sorted JSON array.",
    )
    list_ws_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include UIDs that only appear on archived memories.",
    )
    list_ws_parser.add_argument(
        "--include-aliases",
        action="store_true",
        help="Return workspace objects with nested alias arrays.",
    )

    resolve_parser = workspace_sub.add_parser(
        "resolve",
        help="resolve a workspace UID to its canonical UID",
        description="Normalize a workspace UID candidate and resolve any alias mapping.",
    )
    resolve_parser.add_argument("uid", help="Workspace UID candidate to resolve.")

    alias_parser = workspace_sub.add_parser(
        "alias",
        help="manage workspace UID aliases",
        description="Add, list, and remove workspace UID aliases.",
    )
    alias_sub = alias_parser.add_subparsers(
        dest="alias_action",
        required=True,
        title="alias actions",
        metavar="ACTION",
    )
    alias_add_parser = alias_sub.add_parser(
        "add",
        help="add a workspace UID alias",
        description="Create an alias mapping to a canonical workspace UID.",
    )
    alias_add_parser.add_argument("canonical_uid", help="Canonical workspace UID.")
    alias_add_parser.add_argument("alias_uid", help="Alias workspace UID.")
    alias_add_parser.add_argument(
        "--migrate-existing",
        action="store_true",
        help="Move existing alias workspace memories to the canonical UID in the same transaction.",
    )
    alias_list_parser = alias_sub.add_parser(
        "list",
        help="list workspace UID aliases",
        description="List alias mappings, optionally filtered by canonical workspace UID.",
    )
    alias_list_parser.add_argument(
        "--workspace",
        help="Optional canonical workspace UID filter.",
    )
    alias_remove_parser = alias_sub.add_parser(
        "remove",
        help="remove a workspace UID alias",
        description="Remove an alias mapping by alias UID.",
    )
    alias_remove_parser.add_argument("alias_uid", help="Alias workspace UID to remove.")

    rename_parser = workspace_sub.add_parser(
        "rename",
        help="rename a workspace and migrate its memories",
        description=(
            "Rename a workspace by migrating all its memories to a new UID. "
            "Both UIDs are normalized according to the workspace.uid_normalization "
            "config setting before the operation. Archived memories are included."
        ),
    )
    rename_parser.add_argument(
        "old_uid",
        help="Current workspace UID to rename.",
    )
    rename_parser.add_argument(
        "new_uid",
        help="New workspace UID to migrate memories to.",
    )

    # -- embedding-status --------------------------------------------------
    subparsers.add_parser(
        "embedding-status",
        help="show active local FastEmbed profile and startup job",
        description=(
            "Show the active built-in local FastEmbed embedding profile plus startup "
            "re-embedding job metadata. Recollectium uses the local model cache for "
            "jinaai/jina-embeddings-v2-small-en."
        ),
    )

    # -- embedding-jobs ----------------------------------------------------
    embedding_jobs_parser = subparsers.add_parser(
        "embedding-jobs",
        help="list embedding jobs or fetch one job by id",
        description=(
            "List embedding jobs by default or fetch one job with --job-id. "
            "Jobs track local FastEmbed model download and re-embedding progress."
        ),
    )
    embedding_jobs_parser.add_argument(
        "--job-id",
        help="If provided, return exactly one embedding job by ID.",
    )
    embedding_jobs_parser.add_argument(
        "--state",
        help="Optional list filter by job state, such as pending, in_progress, completed, or failed.",
    )
    embedding_jobs_parser.add_argument(
        "--limit",
        type=int,
        help="Optional positive integer limit for list mode.",
    )

    # -- mcp-stdio ---------------------------------------------------------
    subparsers.add_parser(
        "mcp-stdio",
        help="run MCP server over stdin/stdout",
        description=(
            "Start an MCP (Model Context Protocol) server over stdin/stdout. "
            "This is intended to be spawned by MCP-compatible clients. "
            "No PID file is created — the server runs for the lifetime of the client connection."
        ),
    )

    # -- completion ---------------------------------------------------------
    completion_parser = subparsers.add_parser(
        "completion",
        help="print shell completion setup instructions",
        description=(
            "Print shell completion setup instructions for bash, zsh, fish, or PowerShell. "
            "With --source, prints only the raw completion function definition "
            "for eval consumption."
        ),
    )
    completion_parser.add_argument(
        "shell",
        nargs="?",
        choices=list(_COMPLETION_SHELLS),
        help="Shell to generate completion for (default: auto-detect bash, zsh, fish, or PowerShell).",
    )
    action_group = completion_parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--source",
        action="store_true",
        help=(
            "Print only the raw completion function definition for eval "
            "consumption. No instructions or human-readable output."
        ),
    )
    action_group.add_argument(
        "--install",
        action="store_true",
        help=(
            "Write completion setup to the shell's startup file "
            "inside a managed comment block. Prompts for confirmation before "
            "modifying any file."
        ),
    )
    action_group.add_argument(
        "--complete-line",
        help=argparse.SUPPRESS,
    )
    completion_parser.add_argument(
        "--point",
        type=int,
        help=argparse.SUPPRESS,
    )
    completion_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when used with --install.",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Recollectium CLI."""
    _set_cli_output_format(CLI_OUTPUT_JSON)
    argv, output_override, output_conflict = _extract_cli_output_override(argv)
    parser = _build_parser()
    argcomplete.autocomplete(parser)
    effective_argv = sys.argv[1:] if argv is None else list(argv)
    if not effective_argv:
        parser.print_help()
        return 0
    if output_conflict:
        _set_cli_output_format(output_override or CLI_OUTPUT_JSON)
        return _emit_cli_failure(
            status="validation_error",
            message="Choose either --json or --human-readable, not both.",
            exit_code=2,
            command="output",
        )
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        try:
            installed_version = package_version("recollectium")
        except PackageNotFoundError:
            installed_version = __version__
        print(f"recollectium {installed_version}")
        return 0

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "completion" and (args.source or args.complete_line is not None):
        return _handle_completion_command(args, output_format=CLI_OUTPUT_JSON)

    # Resolve config path
    config_path = _resolve_config_path(args.config_path)
    core_config_path = _core_config_path(args.config_path)
    output_format = _resolve_output_format(
        config_path=config_path,
        explicit=args.config_path is not None,
        override=output_override,
    )
    _set_cli_output_format(output_format)
    if not (args.command == "upgrade" and (args.check or args.dry_run)):
        _setup_cli_logging(config_path, log_level=args.log_level)
    _log.info(
        "CLI command started",
        extra={"event": "cli.command", "context": {"command": args.command}},
    )

    if args.command == "completion":
        return _handle_completion_command(args, output_format=output_format)

    # -- config command ---------------------------------------------------
    if args.command == "config":
        return _handle_config_command(
            args,
            config_path,
            explicit=args.config_path is not None,
            output_format=output_format,
        )

    if args.command == "init":
        try:
            return _handle_init_command(
                config_path,
                explicit=args.config_path is not None,
                db_path=args.db_path,
                log_level=args.log_level,
                output_format=output_format,
            )
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command="init")
        except ValidationError as exc:
            return _config_invalid_error(exc, command="init")
        except (
            EmbeddingReadinessTimeoutError,
            EmbeddingModelUnavailableError,
            EmbeddingProviderUnavailableError,
            EmbeddingGenerationError,
        ) as exc:
            return _embedding_error(exc, command="init")
        except MigrationError as exc:
            return _emit_cli_failure(
                status="migration_error",
                message="Database migration failed.",
                detail=str(exc),
                exit_code=1,
                command="init",
                event="database.migration_failed",
            )
        except RecollectiumError as exc:
            return _operation_failed_error(exc, command="init")

    # -- serve command ----------------------------------------------------
    if args.command == "serve":
        # Resolve host/port from config or defaults
        host = args.host
        port = args.port
        if host is None or port is None:
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
            if host is None:
                host = (
                    cfg.effective_config["service"]["host"]
                    if cfg
                    else SERVICE_DEFAULT_HOST
                )
            if port is None:
                port = (
                    cfg.effective_config["service"]["port"]
                    if cfg
                    else SERVICE_DEFAULT_PORT
                )
        try:
            run_service(
                host=host,
                port=port,
                db_path=args.db_path,
                config_path=core_config_path,
                log_level=args.log_level,
                cli_structured_errors=True,
            )
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command=args.command)
        except ValidationError as exc:
            return _config_invalid_error(exc, command=args.command)
        except (
            EmbeddingReadinessTimeoutError,
            EmbeddingModelUnavailableError,
            EmbeddingProviderUnavailableError,
            EmbeddingGenerationError,
        ) as exc:
            return _embedding_error(exc, command=args.command)
        except ServiceError as exc:
            return _service_error(
                exc, command=args.command, event="serve.service_error"
            )
        except RecollectiumError as exc:
            return _operation_failed_error(exc, command=args.command)
        return 0

    # -- db-status command ------------------------------------------------
    if args.command == "db-status":
        if args.db_path:
            db_path = Path(args.db_path)
        else:
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
                db_path = cfg.resolved_database_path
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
        try:
            store = SQLiteMemoryStore(db_path)
            _emit_success(
                store.migration_status(),
                output_format=output_format,
                command="db-status",
            )
        except MigrationError as exc:
            return _emit_cli_failure(
                status="migration_error",
                message="Database migration status failed.",
                detail=str(exc),
                exit_code=1,
                command="db-status",
                event="database.migration_status_failed",
            )
        return 0

    # -- mcp-stdio command ------------------------------------------------
    if args.command == "mcp-stdio":
        try:
            core = RecollectiumCore(
                db_path=args.db_path,
                config_path=core_config_path,
                log_level=args.log_level,
            )
            core._ensure_model_ready()
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command=args.command)
        except ValidationError as exc:
            return _config_invalid_error(exc, command=args.command)
        except (
            EmbeddingReadinessTimeoutError,
            EmbeddingModelUnavailableError,
            EmbeddingProviderUnavailableError,
            EmbeddingGenerationError,
        ) as exc:
            return _embedding_error(exc, command=args.command)
        try:
            mcp = create_mcp_server(core)
            import asyncio

            asyncio.run(mcp.run_stdio_async())
        except Exception as exc:
            return _operation_failed_error(exc, command="mcp-stdio")
        return 0

    # -- service commands --------------------------------------------------
    if args.command == "service":
        if args.service_action == "discover":
            try:
                plan = _load_uninstall_plan(
                    config_path,
                    explicit=args.config_path is not None,
                )
                payload = discover_service(plan.config)
                _emit_success(
                    payload, output_format=output_format, command="service discover"
                )
                if payload["status"] == "not_running":
                    return 1
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
            except ServiceError as exc:
                return _service_error(exc, command="service discover", exit_code=2)
            return 0

        if args.service_action == "start":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
            try:
                pid = start_service(
                    cfg, args.type, db_path=args.db_path, log_level=args.log_level
                )
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                endpoint = f"http://{host}:{port}"
                _emit_success(
                    {
                        "status": "started",
                        "type": args.type,
                        "pid": pid,
                        "endpoint": endpoint,
                    },
                    output_format=output_format,
                    command="service start",
                )
            except ServiceConflictError as exc:
                return _service_error(
                    exc,
                    command=f"service {args.service_action}",
                    status="service_conflict",
                    event="service.startup_rejected",
                )
            except ServiceError as exc:
                return _service_error(exc, command=f"service {args.service_action}")
            except ValueError as exc:
                return _emit_cli_failure(
                    status="validation_error",
                    message="Invalid service request.",
                    detail=str(exc),
                    exit_code=2,
                    command=f"service {args.service_action}",
                )
            return 0

        if args.service_action == "stop":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
            pid = stop_service(cfg)
            if pid is not None:
                _emit_success(
                    {"status": "stopped", "pid": pid},
                    output_format=output_format,
                    command="service stop",
                )
            else:
                _emit_success(
                    {"status": "no_service_running"},
                    output_format=output_format,
                    command="service stop",
                )
            return 0

        if args.service_action == "status":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)
            pid_path = get_pid_file_path(cfg)
            try:
                raw_pid_info = read_pid_file(pid_path)
                running = check_running_service(cfg)
            except ServiceError as exc:
                return _service_error(exc, command=f"service {args.service_action}")
            if running is not None:
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                _emit_success(
                    {
                        "running": True,
                        "type": running["type"],
                        "pid": running["pid"],
                        "endpoint": f"http://{host}:{port}",
                    },
                    output_format=output_format,
                    command="service status",
                )
            else:
                status_info: dict[str, object] = {"running": False}
                if raw_pid_info is not None:
                    status_info["last_service"] = {
                        "type": raw_pid_info["type"],
                        "pid": raw_pid_info["pid"],
                    }
                _emit_success(
                    status_info, output_format=output_format, command="service status"
                )
            return 0

        if args.service_action == "restart":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                return _config_missing_error(exc, command=args.command)
            except ValidationError as exc:
                return _config_invalid_error(exc, command=args.command)

            pid_path = get_pid_file_path(cfg)
            try:
                raw_pid_info = read_pid_file(pid_path)
                running = check_running_service(cfg)
            except ServiceError as exc:
                return _service_error(exc, command=f"service {args.service_action}")
            if running is not None:
                # Service is running: stop it first, then restart same type
                service_type = running["type"]
                _log.warning(
                    f"Stopping existing {service_type} service...",
                    extra={"event": "service.stop"},
                )
                stop_service(cfg)
                time.sleep(0.5)  # let port release before binding again
            elif raw_pid_info is not None:
                service_type = raw_pid_info["type"]
            elif args.type is not None:
                service_type = args.type
            else:
                return _emit_cli_failure(
                    status="service_not_running",
                    message="No running service found.",
                    hint="Use --type to specify which service to restart.",
                    exit_code=1,
                    command="service restart",
                    event="service.no_service",
                )

            try:
                pid = start_service(
                    cfg,
                    service_type,
                    db_path=args.db_path,
                    log_level=args.log_level,
                )
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                _emit_success(
                    {
                        "status": "restarted",
                        "type": service_type,
                        "pid": pid,
                        "endpoint": f"http://{host}:{port}",
                    },
                    output_format=output_format,
                    command="service restart",
                )
            except ServiceConflictError as exc:
                return _service_error(
                    exc,
                    command=f"service {args.service_action}",
                    status="service_conflict",
                    event="service.startup_rejected",
                )
            except ServiceError as exc:
                return _service_error(exc, command=f"service {args.service_action}")
            except ValueError as exc:
                return _emit_cli_failure(
                    status="validation_error",
                    message="Invalid service request.",
                    detail=str(exc),
                    exit_code=2,
                    command=f"service {args.service_action}",
                )
            return 0

    if args.command == "update" and args.memory_id is None:
        return _emit_cli_failure(
            status="validation_error",
            message="Memory ID is required for recollectium update.",
            hint="Use recollectium upgrade to upgrade the installed Recollectium package.",
            exit_code=2,
            command="update",
        )

    if args.command == "upgrade":
        return _handle_upgrade_command(args, config_path, output_format=output_format)

    if args.command == "uninstall":
        try:
            return _handle_uninstall_command(
                args,
                config_path,
                explicit=args.config_path is not None,
                output_format=output_format,
            )
        except FileNotFoundError as exc:
            return _config_missing_error(exc, command=args.command)
        except ValidationError as exc:
            return _config_invalid_error(exc, command=args.command)
        except ServiceError as exc:
            return _service_error(
                exc, command="uninstall", event="uninstall.service_stop_failed"
            )
        except OSError as exc:
            return _emit_cli_failure(
                status="operation_failed",
                message="Uninstall purge failed.",
                detail=str(exc),
                exit_code=1,
                command="uninstall",
                event="uninstall.purge_failed",
            )

    # -- all other commands use RecollectiumCore ------------------------------
    try:
        core = RecollectiumCore(
            db_path=args.db_path, config_path=core_config_path, log_level=args.log_level
        )

        # Ensure embedding model is ready before commands that need it.
        # Non-embedding commands (list, get, archive, workspace, db-status,
        # config, update metadata-only) skip this gate.
        _EMBEDDING_COMMANDS = frozenset({"add", "search-user", "search-workspace"})
        _needs_embedding = args.command in _EMBEDDING_COMMANDS or (
            args.command == "update" and args.content is not None
        )
        if _needs_embedding:
            core._ensure_model_ready()

        if args.command == "add":
            result = core.add_memory(
                space=args.space,
                type=args.type,
                content=args.content,  # type: ignore[reportArgumentType]
                workspace_uid=args.workspace_uid,
                metadata=_parse_metadata(args.metadata),
                source=args.source,
                confidence=args.confidence,
                sensitivity=args.sensitivity,
            )
        elif args.command == "search-user":
            result = core.search_user_memories(
                query=args.query,
                limit=args.limit,
                include_archived=args.include_archived,
                type=args.type,
            )
        elif args.command == "search-workspace":
            result = core.search_workspace_memories(
                query=args.query,
                workspace_uid=args.workspace_uid,
                limit=args.limit,
                include_archived=args.include_archived,
                type=args.type,
            )
        elif args.command == "list":
            result = core.list_memories(
                space=args.space,
                type=args.type,
                status=args.status,
                workspace_uid=args.workspace_uid,
                include_archived=args.include_archived,
                limit=args.limit,
            )
        elif args.command == "get":
            result = core.get_memory(args.memory_id)
        elif args.command == "update":
            result = core.update_memory(
                args.memory_id,
                type=args.type,
                content=args.content,
                metadata=_parse_metadata(args.metadata),
                source=args.source,
                confidence=args.confidence,
                sensitivity=args.sensitivity,
            )
        elif args.command == "archive":
            result = core.archive_memory(args.memory_id)
        elif args.command == "workspace":
            return _handle_workspace_command(
                args, core=core, output_format=output_format
            )
        elif args.command == "embedding-status":
            result = core.active_embedding_status()
        elif args.command == "embedding-jobs":
            if args.job_id:
                result = core.get_embedding_job(args.job_id)
            else:
                result = core.list_embedding_jobs(state=args.state, limit=args.limit)
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
    except _MetadataInvalidError as exc:
        return _metadata_invalid_error(exc)
    except ValidationError as exc:
        return _validation_error(exc, command=args.command)
    except NotFoundError as exc:
        return _not_found_error(exc, command=args.command)
    except FileNotFoundError as exc:
        return _config_missing_error(exc, command=args.command)
    except (
        EmbeddingReadinessTimeoutError,
        EmbeddingModelUnavailableError,
        EmbeddingProviderUnavailableError,
        EmbeddingGenerationError,
    ) as exc:
        return _embedding_error(exc, command=args.command)
    except MigrationError as exc:
        return _emit_cli_failure(
            status="migration_error",
            message="Database migration failed.",
            detail=str(exc),
            exit_code=1,
            command=args.command,
            event="database.migration_failed",
        )
    except RecollectiumError as exc:
        return _operation_failed_error(exc, command=args.command)

    _emit_success(result, output_format=output_format, command=args.command)
    return 0
