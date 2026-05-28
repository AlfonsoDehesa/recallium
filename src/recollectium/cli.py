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
from pathlib import Path
from typing import Any, Sequence

from platformdirs import user_state_dir

from recollectium import (
    __version__,
    NotFoundError,
    RecollectiumCore,
    RecollectiumError,
    ValidationError,
)
from recollectium.errors import (
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
)
from recollectium.config import (
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

_log = logging.getLogger(__name__)
_INSTALL_METADATA_FILE = "install.json"
_PURGE_CONFIRMATION = "delete all recollectium data"

_COMPLETABLE_CONFIG_KEYS = [
    "version",
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
        raise ValidationError(f"metadata must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValidationError("metadata must be a JSON object")
    return parsed


def _to_payload(data: Any) -> Any:
    if isinstance(data, SearchResult):
        return data.to_dict()
    if hasattr(data, "to_dict"):
        return data.to_dict()
    if isinstance(data, list):
        return [_to_payload(item) for item in data]
    return data


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
) -> int:
    """Handle the `recollectium config` command and its subcommands."""
    if args.config_action == "get":
        try:
            cfg = _load_effective_config(config_path, explicit=explicit)
            value = get_config_value(cfg.effective_config, args.key)
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
        except KeyError as exc:
            _log.error(f"key not found: {exc}", extra={"event": "config.missing"})
            return 1
        print(json.dumps(value, sort_keys=True))
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
            _log.error(
                f"ValidationError: {exc}",
                extra={"event": "config.invalid"},
            )
            return 2
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.config_action == "unset":
        if not config_path.exists():
            _log.error(
                f"config file not found: {config_path}",
                extra={"event": "config.missing"},
            )
            return 1
        raw = load_config_file(config_path)
        try:
            unset_config_value(raw, args.key)
        except KeyError as exc:
            _log.error(f"key not found: {exc}", extra={"event": "config.missing"})
            return 1
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.config_action == "init":
        if config_path.exists() and not args.force:
            _log.warning(
                f"config file already exists: {config_path}",
                extra={"event": "config.missing"},
            )
            return 1
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        return 0

    if args.config_action == "doctor":
        try:
            cfg = _load_effective_config(config_path, explicit=explicit)
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1

        failures: list[str] = []
        print(f"OK config: {cfg.config_file_path}")

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
            print(f"OK {name}: {directory}")

        db_parent = cfg.resolved_database_path.parent
        if not db_parent.exists():
            failures.append(f"database parent directory missing: {db_parent}")
        elif not db_parent.is_dir():
            failures.append(f"database parent path is not a directory: {db_parent}")
        elif not _directory_writable(db_parent):
            failures.append(f"database parent directory is not writable: {db_parent}")
        else:
            print(f"OK database parent: {db_parent}")

        if failures:
            for failure in failures:
                _log.error(
                    failure,
                    extra={"event": "config.doctor_failed"},
                )
                print(f"FAIL {failure}", file=sys.stderr)
            return 1

        print("Config doctor checks passed")
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
            _log.error(f"editor not found: {editor}", extra={"event": "config.missing"})
            return 1

    if args.config_action == "reset":
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        print(f"Config reset to defaults: {config_path}")
        return 0

    if args.validate:
        try:
            if explicit:
                validate_config_file(config_path)
            else:
                _load_effective_config(config_path, explicit=False)
        except ValidationError as exc:
            _log.error(str(exc), extra={"event": "config.invalid"})
            return 1
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        return 0

    if args.path:
        print(str(config_path))
        return 0

    if args.defaults:
        print(json.dumps(DEFAULTS, indent=2, sort_keys=True))
        return 0

    # No subcommand or flag: print effective config
    try:
        cfg = _load_effective_config(config_path, explicit=explicit)
    except FileNotFoundError as exc:
        _log.error(str(exc), extra={"event": "config.missing"})
        return 1
    except ValidationError as exc:
        _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
        return 2
    print(json.dumps(cfg.effective_config, indent=2, sort_keys=True))
    return 0


def _handle_init_command(
    config_path: Path,
    *,
    explicit: bool,
    db_path: str | None,
    log_level: str | None,
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
    print(json.dumps(result, sort_keys=True))
    return 0


def _handle_package_update_command() -> int:
    """Print upgrade instructions for common install methods."""
    instructions = {
        "status": "manual_update_required",
        "commands": {
            "bootstrap": "curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.sh | sh",
            "pip": "pip install --upgrade recollectium",
            "pipx": "pipx upgrade recollectium",
            "uv_tool": "uv tool upgrade recollectium",
        },
    }
    print(json.dumps(instructions, sort_keys=True))
    return 0


_COMPLETION_RC_FILES: dict[str, str] = {
    "bash": ".bashrc",
    "zsh": ".zshrc",
    "fish": ".config/fish/config.fish",
}
_COMPLETION_BLOCK_START = "# >>> recollectium completion >>>"
_COMPLETION_BLOCK_END = "# <<< recollectium completion <<<"
_COMPLETION_BLOCK_PATTERN = re.compile(
    rf"\n?{re.escape(_COMPLETION_BLOCK_START)}\n.*?\n"
    rf"{re.escape(_COMPLETION_BLOCK_END)}\n?",
    re.DOTALL,
)


def _detect_shell() -> str | None:
    shell_path = os.environ.get("SHELL", "")
    if not shell_path:
        return None
    basename = Path(shell_path).name
    if basename in _COMPLETION_RC_FILES:
        return basename
    return None


def _handle_completion_command(args: argparse.Namespace) -> int:
    shell = args.shell
    if shell is None:
        shell = _detect_shell()
    if shell is None:
        _log.error(
            "Could not detect shell from $SHELL. "
            "Pass the shell name explicitly: recollectium completion bash",
            extra={"event": "completion.unknown_shell"},
        )
        return 2

    if args.source:
        output = argcomplete.shellcode(["recollectium"], shell=shell)  # pyright: ignore[reportPrivateImportUsage]
        sys.stdout.write(output)
        return 0

    eval_line = f'eval "$(recollectium completion --source {shell})"'

    if args.install:
        rc_filename = _COMPLETION_RC_FILES.get(shell)
        if rc_filename is None:
            _log.error(
                f"No rc file mapping for shell {shell}",
                extra={"event": "completion.unknown_rc"},
            )
            return 1
        rc_path = Path.home() / rc_filename

        try:
            existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
        except OSError as exc:
            _log.error(
                f"Could not read rc file {rc_path}: {exc}",
                extra={"event": "completion.rc_read_error"},
            )
            return 1

        if eval_line in existing:
            print(
                json.dumps(
                    {"status": "already_installed", "rc_file": str(rc_path)},
                    sort_keys=True,
                )
            )
            return 0

        block = f"{_COMPLETION_BLOCK_START}\n{eval_line}\n{_COMPLETION_BLOCK_END}\n"

        if not args.yes:
            sys.stderr.write(
                f"Will append the following block to {rc_path}:\n\n{block}\n"
            )
            sys.stderr.write("Proceed? Type 'yes' to confirm: ")
            response = sys.stdin.readline().strip()
            if response.lower() != "yes":
                _log.warning(
                    "Completion installation cancelled.",
                    extra={"event": "completion.cancelled"},
                )
                return 1

        try:
            with rc_path.open("a", encoding="utf-8") as f:
                f.write("\n" + block)
        except OSError as exc:
            _log.error(
                f"Could not write to {rc_path}: {exc}",
                extra={"event": "completion.rc_write_error"},
            )
            return 1

        print(
            json.dumps(
                {"status": "installed", "rc_file": str(rc_path)},
                sort_keys=True,
            )
        )
        return 0

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

    install_metadata_path = (
        Path(user_state_dir("recollectium")) / _INSTALL_METADATA_FILE
    )
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

    home = Path.home()
    raw_paths.extend(home / filename for filename in _COMPLETION_RC_FILES.values())

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
) -> int:
    """Print uninstall instructions and optionally purge Recollectium-owned data."""
    if args.yes_delete_all_recollectium_data and not args.purge:
        _log.error(
            "--yes-delete-all-recollectium-data requires --purge",
            extra={"event": "uninstall.invalid_flags"},
        )
        return 2

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
            sys.stderr.write(
                "The following Recollectium-owned paths will be permanently deleted:\n"
            )
            for target in preview["targets"]:
                if target.get("reason") == "missing":
                    continue
                sys.stderr.write(f"  {target['path']}\n")
            sys.stderr.write("\n")

            if not args.yes_delete_all_recollectium_data:
                sys.stderr.write(
                    "Type 'delete all recollectium data' to permanently delete Recollectium data: "
                )
                sys.stderr.flush()
                response = sys.stdin.readline().rstrip("\n")
                if response != _PURGE_CONFIRMATION:
                    _log.warning(
                        "purge cancelled",
                        extra={"event": "uninstall.purge_cancelled"},
                    )
                    return 1

            data_payload["purge"] = _purge_targets(plan, dry_run=False)

    result = {
        "status": "manual_uninstall_required",
        "package": _uninstall_package_instructions(metadata),
        "service": service_payload,
        "shell_completion": completion_payload,
        "data": data_payload,
    }
    _log.info(
        "Uninstall instructions generated",
        extra={"event": "uninstall.instructions"},
    )
    print(json.dumps(result, sort_keys=True))
    return 0


def _handle_workspace_command(
    args: argparse.Namespace,
    *,
    core: RecollectiumCore,
) -> int:
    """Handle the `recollectium workspace` subcommands."""
    if args.workspace_action == "list":
        uids = core.list_workspaces(
            include_archived=getattr(args, "include_archived", False),
        )
        print(json.dumps(uids, sort_keys=True))
        return 0

    if args.workspace_action == "rename":
        try:
            result = core.rename_workspace(
                old_uid=args.old_uid,
                new_uid=args.new_uid,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "workspace.invalid"})
            return 1
        except NotFoundError as exc:
            _log.error(str(exc), extra={"event": "workspace.not_found"})
            return 1

    return 1  # pragma: no cover — parser enforces valid actions


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recollectium",
        description=(
            "Recollectium Core local memory CLI. Commands print JSON on success and "
            "write validation or not-found errors to stderr."
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
            "merged with explicit overrides) as formatted JSON."
        ),
    )
    config_parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the config file and exit 0 on success or 1 on error.",
    )
    config_parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved config file path without creating a file.",
    )
    config_parser.add_argument(
        "--defaults",
        action="store_true",
        help="Print built-in default values as formatted JSON without creating a file.",
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
        help="update Recollectium itself or editable memory fields",
        description=(
            "Without a memory ID, print Recollectium package upgrade instructions. "
            "With a memory ID, update one or more editable fields on that memory. "
            "Updating --content also regenerates that memory's embedding."
        ),
    )
    update_parser.add_argument(
        "memory_id",
        nargs="?",
        help="Memory ID to update. Omit to print package update instructions.",
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
            "Start a blocking local-only HTTP JSON service for Recollectium Core. "
            "By default it binds to localhost (127.0.0.1), exposes the /v1 "
            "service API, and keeps running until interrupted. Host and port "
            "can be set via config file or CLI flags. CLI flags override config."
        ),
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help=(
            "Host interface to bind. Overrides service.host from config. "
            "Defaults to 127.0.0.1."
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
        description="List known workspace UIDs and rename workspaces.",
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
            "Print shell completion setup instructions for bash, zsh, or fish. "
            "With --source, prints only the raw completion function definition "
            "for eval consumption."
        ),
    )
    completion_parser.add_argument(
        "shell",
        nargs="?",
        choices=["bash", "zsh", "fish"],
        help="Shell to generate completion for (default: auto-detect from $SHELL).",
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
            "Append the completion eval line to the current shell's rc file "
            "inside a managed comment block. Prompts for confirmation before "
            "modifying any file."
        ),
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
    parser = _build_parser()
    argcomplete.autocomplete(parser)
    if argv == [] or (argv is None and len(sys.argv) == 1):
        parser.print_help()
        return 0
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

    if args.command == "completion":
        return _handle_completion_command(args)

    # Resolve config path
    config_path = _resolve_config_path(args.config_path)
    core_config_path = _core_config_path(args.config_path)
    _setup_cli_logging(config_path, log_level=args.log_level)
    _log.info(
        "CLI command started",
        extra={"event": "cli.command", "context": {"command": args.command}},
    )

    # -- config command ---------------------------------------------------
    if args.command == "config":
        return _handle_config_command(
            args,
            config_path,
            explicit=args.config_path is not None,
        )

    if args.command == "init":
        try:
            return _handle_init_command(
                config_path,
                explicit=args.config_path is not None,
                db_path=args.db_path,
                log_level=args.log_level,
            )
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
        except EmbeddingReadinessTimeoutError as exc:
            _log.error(
                f"EmbeddingReadinessTimeoutError: {exc}\n"
                "Model preparation timed out. Check your internet connection "
                "and try 'recollectium init' again.",
                extra={"event": "embedding.readiness_timeout"},
            )
            return 1
        except EmbeddingModelUnavailableError as exc:
            _log.error(
                f"EmbeddingModelUnavailableError: {exc}\n"
                "The embedding model could not be downloaded. "
                "Check your internet connection and try 'recollectium init' again.",
                extra={"event": "embedding.model_unavailable"},
            )
            return 1
        except EmbeddingProviderUnavailableError as exc:
            _log.error(
                f"EmbeddingProviderUnavailableError: {exc}\n"
                "The embedding provider is unavailable. "
                "Check your internet connection and try 'recollectium init' again.",
                extra={"event": "embedding.provider_unavailable"},
            )
            return 1
        except RecollectiumError as exc:
            _log.error(f"{exc.__class__.__name__}: {exc}")
            return 1

    # -- serve command ----------------------------------------------------
    if args.command == "serve":
        # Resolve host/port from config or defaults
        host = args.host
        port = args.port
        if host is None or port is None:
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
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
            )
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
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
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
        store = SQLiteMemoryStore(db_path)
        print(json.dumps(store.migration_status(), sort_keys=True))
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
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
        except EmbeddingReadinessTimeoutError as exc:
            _log.error(
                f"EmbeddingReadinessTimeoutError: {exc}\n"
                "Model preparation timed out. Check your internet connection "
                "and try 'recollectium init' again.",
                extra={"event": "embedding.readiness_timeout"},
            )
            return 1
        except EmbeddingModelUnavailableError as exc:
            _log.error(
                f"EmbeddingModelUnavailableError: {exc}\n"
                "The embedding model could not be downloaded. "
                "Check your internet connection and try 'recollectium init' again.",
                extra={"event": "embedding.model_unavailable"},
            )
            return 1
        except EmbeddingProviderUnavailableError as exc:
            _log.error(
                f"EmbeddingProviderUnavailableError: {exc}\n"
                "The embedding provider is unavailable. "
                "Check your internet connection and try 'recollectium init' again.",
                extra={"event": "embedding.provider_unavailable"},
            )
            return 1
        try:
            mcp = create_mcp_server(core)
            import asyncio

            asyncio.run(mcp.run_stdio_async())
        except Exception as exc:
            _log.error(f"Error: {exc}")
            return 1
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
                print(json.dumps(payload, sort_keys=True))
                if payload["status"] == "not_running":
                    return 1
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
            except ServiceError as exc:
                _log.error(str(exc))
                return 2
            return 0

        if args.service_action == "start":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
            try:
                pid = start_service(
                    cfg, args.type, db_path=args.db_path, log_level=args.log_level
                )
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                endpoint = f"http://{host}:{port}"
                print(
                    json.dumps(
                        {
                            "status": "started",
                            "type": args.type,
                            "pid": pid,
                            "endpoint": endpoint,
                        },
                        sort_keys=True,
                    )
                )
            except ServiceConflictError as exc:
                _log.error(str(exc), extra={"event": "service.startup_rejected"})
                return 1
            except ServiceError as exc:
                _log.error(str(exc))
                return 1
            except ValueError as exc:
                _log.error(str(exc))
                return 2
            return 0

        if args.service_action == "stop":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
            pid = stop_service(cfg)
            if pid is not None:
                print(json.dumps({"status": "stopped", "pid": pid}, sort_keys=True))
            else:
                print(json.dumps({"status": "no_service_running"}, sort_keys=True))
            return 0

        if args.service_action == "status":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2
            pid_path = get_pid_file_path(cfg)
            try:
                raw_pid_info = read_pid_file(pid_path)
                running = check_running_service(cfg)
            except ServiceError as exc:
                _log.error(str(exc))
                return 1
            if running is not None:
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                print(
                    json.dumps(
                        {
                            "running": True,
                            "type": running["type"],
                            "pid": running["pid"],
                            "endpoint": f"http://{host}:{port}",
                        },
                        sort_keys=True,
                    )
                )
            else:
                status_info: dict[str, object] = {"running": False}
                if raw_pid_info is not None:
                    status_info["last_service"] = {
                        "type": raw_pid_info["type"],
                        "pid": raw_pid_info["pid"],
                    }
                print(json.dumps(status_info, sort_keys=True))
            return 0

        if args.service_action == "restart":
            try:
                cfg = RecollectiumConfig(core_config_path, log_level=args.log_level)
            except FileNotFoundError as exc:
                _log.error(str(exc), extra={"event": "config.missing"})
                return 1
            except ValidationError as exc:
                _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
                return 2

            pid_path = get_pid_file_path(cfg)
            try:
                raw_pid_info = read_pid_file(pid_path)
                running = check_running_service(cfg)
            except ServiceError as exc:
                _log.error(str(exc))
                return 1
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
                _log.warning(
                    "No running service found. Use --type to specify which "
                    "service to restart.",
                    extra={"event": "service.no_service"},
                )
                return 1

            try:
                pid = start_service(
                    cfg,
                    service_type,
                    db_path=args.db_path,
                    log_level=args.log_level,
                )
                host = cfg.effective_config["service"]["host"]
                port = cfg.effective_config["service"]["port"]
                print(
                    json.dumps(
                        {
                            "status": "restarted",
                            "type": service_type,
                            "pid": pid,
                            "endpoint": f"http://{host}:{port}",
                        },
                        sort_keys=True,
                    )
                )
            except ServiceConflictError as exc:
                _log.error(str(exc), extra={"event": "service.startup_rejected"})
                return 1
            except ServiceError as exc:
                _log.error(str(exc))
                return 1
            except ValueError as exc:
                _log.error(str(exc))
                return 2
            return 0

    if args.command == "update" and args.memory_id is None:
        return _handle_package_update_command()

    if args.command == "uninstall":
        try:
            return _handle_uninstall_command(
                args,
                config_path,
                explicit=args.config_path is not None,
            )
        except FileNotFoundError as exc:
            _log.error(str(exc), extra={"event": "config.missing"})
            return 1
        except ValidationError as exc:
            _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
            return 2
        except ServiceError as exc:
            _log.error(str(exc), extra={"event": "uninstall.service_stop_failed"})
            return 1
        except OSError as exc:
            _log.error(str(exc), extra={"event": "uninstall.purge_failed"})
            return 1

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
            return _handle_workspace_command(args, core=core)
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
    except ValidationError as exc:
        _log.error(f"ValidationError: {exc}", extra={"event": "config.invalid"})
        return 2
    except NotFoundError as exc:
        _log.error(f"NotFoundError: {exc}")
        return 1
    except FileNotFoundError as exc:
        _log.error(str(exc), extra={"event": "config.missing"})
        return 1
    except EmbeddingReadinessTimeoutError as exc:
        _log.error(
            f"EmbeddingReadinessTimeoutError: {exc}\n"
            "Model preparation timed out. The model may be downloading slowly. "
            "Check your internet connection and try 'recollectium init' again.",
            extra={"event": "embedding.readiness_timeout"},
        )
        return 1
    except EmbeddingModelUnavailableError as exc:
        _log.error(
            f"EmbeddingModelUnavailableError: {exc}\n"
            "The embedding model could not be downloaded. "
            "Check your internet connection and try 'recollectium init' again.",
            extra={"event": "embedding.model_unavailable"},
        )
        return 1
    except EmbeddingProviderUnavailableError as exc:
        _log.error(
            f"EmbeddingProviderUnavailableError: {exc}\n"
            "The embedding provider is unavailable. "
            "Check your internet connection and try 'recollectium init' again.",
            extra={"event": "embedding.provider_unavailable"},
        )
        return 1
    except RecollectiumError as exc:
        _log.error(f"{exc.__class__.__name__}: {exc}")
        return 1

    print(json.dumps(_to_payload(result), sort_keys=True))
    return 0
