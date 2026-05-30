"""CLI tests for Recollectium Core."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib.metadata import PackageNotFoundError
from pathlib import Path
import runpy
import shutil
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pytest import CaptureFixture

from recollectium.config import DEFAULTS
from recollectium.cli import (
    _extract_cli_output_override,
    _format_human_error,
    _format_human_output,
    _resolve_output_format,
    main,
)
from recollectium.models import (
    ALL_MEMORY_TYPES,
    USER_MEMORY_TYPES,
    WORKSPACE_MEMORY_TYPES,
)
from recollectium.errors import (
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
    RecollectiumError,
    ServiceError,
    ValidationError,
)
from recollectium.storage import SQLiteMemoryStore
from recollectium.core import RecollectiumCore


class FakeEmbeddingProvider:
    """Lightweight fake embedding provider for CLI workspace tests."""

    def __init__(self) -> None:
        self.embedding_profile = {
            "provider": "fake",
            "model": "fake-model",
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


def _run_cli(
    args: list[str],
    capsys: CaptureFixture[str],
    *,
    json_by_default: bool = True,
) -> tuple[int, str, str]:
    if json_by_default and "--json" not in args and "--human-readable" not in args:
        args = ["--json", *args]
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _run_help(args: list[str], capsys: CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out


def test_cli_help_documents_commands_and_flags(capsys) -> None:
    top_level_help = _run_help(["--help"], capsys)
    assert "Recollectium Core local memory CLI" in top_level_help
    assert "--version" in top_level_help
    assert "--json" in top_level_help
    assert "--human-readable" in top_level_help
    assert "initialize Recollectium config" in top_level_help
    assert "add a user or workspace memory" in top_level_help
    assert "search memories for one workspace UID" in top_level_help
    assert "embedding-status" in top_level_help
    assert "embedding-jobs" in top_level_help
    assert "db-status" in top_level_help
    assert "upgrade" in top_level_help
    assert "uninstall" in top_level_help
    assert "completion" in top_level_help


def test_cli_memory_type_completer_prefers_known_space() -> None:
    from recollectium.cli import _memory_type_choices_for_space, _memory_type_completer

    assert _memory_type_choices_for_space("user") == USER_MEMORY_TYPES
    assert _memory_type_choices_for_space("workspace") == WORKSPACE_MEMORY_TYPES
    assert _memory_type_choices_for_space(None) == ALL_MEMORY_TYPES
    assert _memory_type_choices_for_space("unknown") == ALL_MEMORY_TYPES

    assert _memory_type_completer("", SimpleNamespace(space="user")) == list(
        USER_MEMORY_TYPES
    )
    assert _memory_type_completer("d", SimpleNamespace(space="workspace")) == [
        "decision"
    ]
    assert _memory_type_completer("f", SimpleNamespace(space=None)) == ["fact"]


def test_cli_subcommand_help_documents_commands_and_flags(capsys) -> None:
    add_help = _run_help(["add", "--help"], capsys)
    assert "User memories must not" in add_help
    assert "include --workspace-uid" in add_help
    assert "Workspace memories require --workspace-uid" in add_help
    assert "Memory space: 'user'" in add_help
    assert "inline JSON" in add_help
    assert "@path/to/file.json" in add_help
    assert "confidence score from 0.0 to 1.0" in add_help

    search_help = _run_help(["search-workspace", "--help"], capsys)
    assert "Stable workspace UID" in search_help
    assert "searched" in search_help
    assert "Defaults to 10" in search_help

    update_help = _run_help(["update", "--help"], capsys)
    assert "regenerates" in update_help
    assert "embedding" in update_help
    assert "recollectium upgrade" in update_help

    upgrade_help = _run_help(["upgrade", "--help"], capsys)
    assert "--check" in upgrade_help
    assert "--dry-run" in upgrade_help
    assert "--install-method" in upgrade_help
    assert "--allow-main" in upgrade_help

    archive_help = _run_help(["archive", "--help"], capsys)
    assert "not hard-deleted" in archive_help

    serve_help = _run_help(["serve", "--help"], capsys)
    assert "blocking" in serve_help
    assert "local-first" in serve_help
    assert "127.0.0.1" in serve_help
    assert "/v1" in serve_help
    assert "--host" in serve_help
    assert "--port" in serve_help

    # --config and --db are global flags
    top_level_help_2 = _run_help(["--help"], capsys)
    assert "--config" in top_level_help_2
    assert "--db" in top_level_help_2

    embedding_status_help = _run_help(["embedding-status", "--help"], capsys)
    assert "built-in local FastEmbed" in embedding_status_help
    assert "jinaai/jina-" in embedding_status_help
    assert "embeddings-v2-small-en" in embedding_status_help

    embedding_jobs_help = _run_help(["embedding-jobs", "--help"], capsys)
    assert "--job-id" in embedding_jobs_help
    assert "--state" in embedding_jobs_help
    assert "--limit" in embedding_jobs_help

    db_status_help = _run_help(["db-status", "--help"], capsys)
    assert "migration status" in db_status_help
    assert "pending" in db_status_help
    assert "schema versions" in db_status_help

    uninstall_help = _run_help(["uninstall", "--help"], capsys)
    assert "preserving memories" in uninstall_help
    assert "--purge" in uninstall_help
    assert "--yes-delete-all-recollectium-data" in uninstall_help
    assert "--dry-run" in uninstall_help

    service_discover_help = _run_help(["service", "discover", "--help"], capsys)
    assert "machine-readable connection details" in service_discover_help
    assert "without creating a config file" in service_discover_help


def test_cli_no_args_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Recollectium Core local memory CLI" in captured.out
    assert captured.err == ""


def test_cli_parser_without_command_prints_help(monkeypatch, capsys) -> None:
    class FakeArgs:
        version = False
        command = None

    class FakeParser:
        def parse_args(self, argv: object) -> FakeArgs:
            return FakeArgs()

        def print_help(self) -> None:
            print("fake help")

    monkeypatch.setattr("recollectium.cli._build_parser", lambda: FakeParser())

    assert main(["--not-real-for-fake-parser"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "fake help\n"


def test_cli_log_level_applies_to_missing_config_fallback(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    exit_code, stdout, stderr = _run_cli(
        ["--log-level", "debug", "config", "--path"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    assert "config.json" in stdout


def test_cli_logging_falls_back_after_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    def _fake_setup_logging(config: object) -> None:
        calls.append(config)
        if len(calls) == 1:
            raise OSError("disk unavailable")

    monkeypatch.setattr("recollectium.cli.setup_logging", _fake_setup_logging)

    from recollectium.cli import _setup_cli_logging

    _setup_cli_logging(tmp_path / "missing.json", log_level="debug")

    assert len(calls) == 2


def test_module_entrypoint_delegates_to_cli_main(monkeypatch) -> None:
    calls: list[object] = []

    def fake_main() -> int:
        calls.append(None)
        return 7

    monkeypatch.setattr("recollectium.cli.main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recollectium.__main__", run_name="__main__")

    assert exc_info.value.code == 7
    assert calls == [None]


def test_cli_serve_passes_flags_to_service_runner(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "serve.db"
    call: dict[str, object] = {}

    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path
        call["log_level"] = log_level

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    exit_code = main(
        [
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--log-level",
            "debug",
            "serve",
            "--host",
            "127.0.0.2",
            "--port",
            "9001",
        ]
    )

    assert exit_code == 0
    assert call["host"] == "127.0.0.2"
    assert call["port"] == 9001
    assert call["db_path"] == str(db_path)
    assert str(call["config_path"]) == str(config_path)
    assert call["log_level"] == "debug"


def test_cli_serve_uses_default_host_and_port_without_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call: dict[str, object] = {}

    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path
        call["log_level"] = log_level

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

    exit_code = main(["serve"])

    assert exit_code == 0
    assert call["host"] == "127.0.0.1"
    assert call["port"] == 8765
    assert call["db_path"] is None
    assert call["config_path"] is None
    assert call["log_level"] is None
    assert (tmp_path / "config" / "recollectium" / "config.json").exists()


def test_cli_serve_explicit_missing_config_fails_clearly(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        raise AssertionError("run_service should not run with a missing config")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)
    config_path = tmp_path / "missing" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "serve"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_cli_serve_invalid_config_fails_clearly(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        raise AssertionError("run_service should not run with invalid config")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)
    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "service": {"port": "bad"}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "serve"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "service.port must be int" in stderr


def test_cli_serve_explicit_missing_config_fails_after_flag_overrides(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "missing" / "config.json"

    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        raise FileNotFoundError(f"config file not found: {config_path}")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "serve",
            "--host",
            "127.0.0.2",
            "--port",
            "9001",
        ],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_cli_serve_invalid_config_fails_after_flag_overrides(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"

    def _fake_run_service(
        *,
        host: str,
        port: int,
        db_path: str | None,
        config_path: str | None,
        log_level: str | None,
        cli_structured_errors: bool = False,
    ) -> None:
        raise ValidationError("invalid JSON in config file")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "serve",
            "--host",
            "127.0.0.2",
            "--port",
            "9001",
        ],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError: invalid JSON in config file" in stderr


def test_cli_first_run_without_config_creates_default_config(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "first-run.db"), "list", "--limit", "1"], capsys
    )

    config_path = config_home / "recollectium" / "config.json"
    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout) == []
    assert json.loads(config_path.read_text(encoding="utf-8")) == DEFAULTS


def test_cli_explicit_missing_config_fails_for_normal_command(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "missing" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "--db",
            str(tmp_path / "explicit-missing.db"),
            "list",
            "--limit",
            "1",
        ],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_cli_full_workflow(tmp_path, capsys) -> None:
    db_path = tmp_path / "cli.db"

    add_user_code, add_user_out, add_user_err = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "user",
            "--type",
            "preference",
            "--content",
            "I like short answers",
            "--metadata",
            '{"priority": "high"}',
        ],
        capsys,
    )
    assert add_user_code == 0
    assert add_user_err == ""
    user_memory = json.loads(add_user_out)
    user_memory_id = user_memory["id"]

    add_workspace_code, add_workspace_out, _ = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "workspace",
            "--workspace-uid",
            "ws-123",
            "--type",
            "note",
            "--content",
            "The gearbox fails under load",
        ],
        capsys,
    )
    assert add_workspace_code == 0
    workspace_memory = json.loads(add_workspace_out)
    workspace_memory_id = workspace_memory["id"]

    search_user_code, search_user_out, _ = _run_cli(
        ["--db", str(db_path), "search-user", "short answers", "--limit", "5"],
        capsys,
    )
    assert search_user_code == 0
    search_user_payload = json.loads(search_user_out)
    assert len(search_user_payload) == 1
    assert search_user_payload[0]["memory"]["id"] == user_memory_id

    search_workspace_code, search_workspace_out, _ = _run_cli(
        [
            "--db",
            str(db_path),
            "search-workspace",
            "mechanical stress issue",
            "--workspace-uid",
            "ws-123",
        ],
        capsys,
    )
    assert search_workspace_code == 0
    search_workspace_payload = json.loads(search_workspace_out)
    assert len(search_workspace_payload) == 1
    assert search_workspace_payload[0]["memory"]["id"] == workspace_memory_id

    list_code, list_out, _ = _run_cli(
        ["--db", str(db_path), "list", "--space", "workspace", "--limit", "10"],
        capsys,
    )
    assert list_code == 0
    list_payload = json.loads(list_out)
    assert len(list_payload) == 1
    assert list_payload[0]["id"] == workspace_memory_id

    get_code, get_out, _ = _run_cli(
        ["--db", str(db_path), "get", user_memory_id], capsys
    )
    assert get_code == 0
    get_payload = json.loads(get_out)
    assert get_payload["id"] == user_memory_id

    update_code, update_out, _ = _run_cli(
        [
            "--db",
            str(db_path),
            "update",
            user_memory_id,
            "--content",
            "I prefer concise responses",
            "--confidence",
            "0.9",
        ],
        capsys,
    )
    assert update_code == 0
    update_payload = json.loads(update_out)
    assert update_payload["content"] == "I prefer concise responses"
    assert update_payload["confidence"] == 0.9

    archive_code, archive_out, _ = _run_cli(
        ["--db", str(db_path), "archive", user_memory_id],
        capsys,
    )
    assert archive_code == 0
    archive_payload = json.loads(archive_out)
    assert archive_payload["status"] == "archived"


def test_cli_reads_metadata_from_json_file(tmp_path, capsys) -> None:
    db_path = tmp_path / "cli-file-metadata.db"
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text('{"origin": "file"}', encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "user",
            "--type",
            "fact",
            "--content",
            "file metadata memory",
            "--metadata",
            f"@{metadata_path}",
        ],
        capsys,
    )

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout)["metadata"] == {"origin": "file"}


def test_cli_db_status_reports_migration_state(tmp_path, capsys) -> None:
    db_path = tmp_path / "db-status.db"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "db-status"],
        capsys,
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["db_path"] == str(db_path)
    assert payload["current_version"] == 3
    assert payload["latest_version"] == 3
    assert payload["pending_versions"] == []
    assert payload["up_to_date"] is True


def test_cli_human_readable_flag_formats_failure_output(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "config",
            "set",
            "logging.level",
            "trace",
            "--human-readable",
        ],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert stderr.startswith("Config is invalid.\n")
    assert "Status: config_invalid" in stderr
    assert "Detail: ValidationError: logging.level must be one of" in stderr
    with pytest.raises(json.JSONDecodeError):
        json.loads(stderr)


def test_cli_human_readable_config_formats_failure_output(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cli_output": "human_readable",
                "service": {"port": "not-an-int"},
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "config", "get", "service.port"],
        capsys,
        json_by_default=False,
    )

    assert exit_code == 2
    assert stdout == ""
    assert stderr.startswith("Config is invalid.\n")
    assert "Status: config_invalid" in stderr
    assert "service.port must be int" in stderr


def test_cli_json_flag_formats_failure_output_as_json(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cli_output": "human_readable",
                "service": {"port": "not-an-int"},
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "config", "get", "service.port", "--json"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "config_invalid"
    assert "service.port must be int" in payload["detail"]


def test_cli_human_readable_flag_formats_success_output(tmp_path, capsys) -> None:
    db_path = tmp_path / "human-status.db"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "db-status", "--human-readable"],
        capsys,
    )

    assert exit_code == 0
    assert stderr == ""
    assert stdout.startswith("Db status\n")
    assert "Db path:" in stdout
    assert "Up to date: true" in stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(stdout)


def test_cli_human_readable_is_default_output(tmp_path, capsys) -> None:
    db_path = tmp_path / "default-human-status.db"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "db-status"], capsys, json_by_default=False
    )

    assert exit_code == 0
    assert stderr == ""
    assert stdout.startswith("Db status\n")
    with pytest.raises(json.JSONDecodeError):
        json.loads(stdout)


def test_cli_output_config_controls_success_output(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "configured-human.db"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cli_output": "human_readable",
                "database": {"path": str(db_path)},
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "db-status"],
        capsys,
        json_by_default=False,
    )

    assert exit_code == 0
    assert stderr == ""
    assert stdout.startswith("Db status\n")


def test_cli_json_flag_overrides_human_readable_config(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "configured-json.db"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cli_output": "human_readable",
                "database": {"path": str(db_path)},
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "db-status", "--json"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["db_path"] == str(db_path)


def test_cli_output_flags_work_before_command(tmp_path, capsys) -> None:
    db_path = tmp_path / "before-command.db"

    human_code, human_out, human_err = _run_cli(
        ["--human-readable", "--db", str(db_path), "db-status"], capsys
    )
    assert human_code == 0
    assert human_err == ""
    assert human_out.startswith("Db status\n")

    json_code, json_out, json_err = _run_cli(
        ["--json", "--db", str(db_path), "db-status"], capsys
    )
    assert json_code == 0
    assert json_err == ""
    assert json.loads(json_out)["db_path"] == str(db_path)


def test_cli_output_flag_literals_can_follow_double_dash(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "config",
            "set",
            "logging.level",
            "--",
            "--json",
        ],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "logging.level must be one of" in stderr
    assert "--json" in stderr


def test_cli_output_flags_are_mutually_exclusive(capsys) -> None:
    exit_code, stdout, stderr = _run_cli(
        ["db-status", "--json", "--human-readable"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert stderr.startswith("Choose either --json or --human-readable, not both.\n")
    assert "Status: validation_error" in stderr


def test_completion_complete_line_stays_json_under_human_output_config(
    tmp_path, capsys
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"version": 1, "cli_output": "human_readable"}), encoding="utf-8"
    )

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "completion",
            "--complete-line",
            "recollectium c",
            "--point",
            "14",
        ],
        capsys,
    )

    assert exit_code == 0
    assert stderr == ""
    assert isinstance(json.loads(stdout), list)


def test_cli_human_formatter_covers_command_shapes() -> None:
    memory = {
        "id": 123,
        "space": "workspace",
        "workspace_uid": "demo",
        "type": "decision",
        "status": "active",
        "source": "test",
        "confidence": 0.9,
        "sensitivity": "normal",
        "content": "Use SQLite.",
        "metadata": {"ticket": "R-1"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "archived_at": "2026-01-03T00:00:00Z",
    }

    assert _format_human_output(None) == "Done\n"
    assert _format_human_output([]) == "No results\n"
    assert "- plain" in _format_human_output(["plain", 2])
    assert "1. Memory 123" in _format_human_output([{"memory": memory, "score": 0.75}])
    assert '1. {"name": "demo"}' in _format_human_output([{"name": "demo"}])
    assert _format_human_output(3, label="count") == "count: 3\n"
    assert _format_human_output("ok") == "ok\n"
    assert "Memory added" in _format_human_output(memory, command="add")
    assert "Memory updated" in _format_human_output(memory, command="update")
    assert "Memory archived" in _format_human_output(memory, command="archive")
    assert "cli_output: human_readable" in _format_human_output(
        "human_readable", command="config get", label="cli_output"
    )
    assert 'embedding: {"model": "demo"}' in _format_human_output(
        {"model": "demo"}, command="config get", label="embedding"
    )
    assert "Config updated:" in _format_human_output(
        {"key": "cli_output", "value": "json"}, command="config set"
    )
    assert "Config key removed:" in _format_human_output(
        {"key": "cli_output"}, command="config unset"
    )
    assert "Exit code: 2" in _format_human_error(
        {
            "status": "validation_error",
            "message": "Input validation failed.",
            "detail": "bad value",
            "hint": "try again",
            "exit_code": 2,
        }
    )
    assert "Config initialized:" in _format_human_output(
        {"path": "/tmp/config.json"}, command="config init"
    )
    assert "Config reset to defaults:" in _format_human_output(
        {"path": "/tmp/config.json"}, command="config reset"
    )
    assert "Config doctor" in _format_human_output(
        {"status": "ok", "checks": {"config": "/tmp/config.json"}},
        command="config doctor",
    )
    assert "Effective configuration" in _format_human_output(
        {
            "nested": {"key": "value"},
            "items": [{"name": "one"}, "two"],
            "empty": [],
        },
        command="config",
    )
    assert "Recollectium initialized" in _format_human_output(
        {"database": "/tmp/recollectium.db"}, command="init"
    )
    assert "Workspace result" in _format_human_output(
        {"canonical_uid": "demo"}, command="workspace resolve"
    )
    assert "Service result" in _format_human_output(
        {"status": "running"}, command="service status"
    )
    assert "Embedding status" in _format_human_output(
        {"provider": "builtin-fastembed"}, command="embedding-status"
    )
    assert "Result" in _format_human_output({"ok": True})


def test_cli_output_helpers_cover_sys_argv_and_invalid_config_shapes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("sys.argv", ["recollectium", "list", "--human-readable"])
    cleaned, output_format, conflict = _extract_cli_output_override(None)
    assert cleaned == ["list"]
    assert output_format == "human_readable"
    assert conflict is False

    cleaned, output_format, conflict = _extract_cli_output_override(
        ["--human-readable", "list", "--json"]
    )
    assert cleaned == ["list"]
    assert output_format == "json"
    assert conflict is True

    cleaned, output_format, conflict = _extract_cli_output_override(
        ["config", "set", "logging.level", "--", "--json"]
    )
    assert cleaned == ["config", "set", "logging.level", "--", "--json"]
    assert output_format is None
    assert conflict is False

    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "cli_output": "invalid"}', encoding="utf-8")
    assert (
        _resolve_output_format(config_path=config_path, explicit=True, override=None)
        == "human_readable"
    )
    config_path.write_text("{bad", encoding="utf-8")
    assert (
        _resolve_output_format(config_path=config_path, explicit=True, override=None)
        == "human_readable"
    )


def test_cli_config_human_readable_setup_commands(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"

    init_code, init_out, init_err = _run_cli(
        ["--config", str(config_path), "config", "init", "--human-readable"], capsys
    )
    assert init_code == 0
    assert init_err == ""
    assert "Config initialized:" in init_out

    set_code, set_out, set_err = _run_cli(
        [
            "--config",
            str(config_path),
            "config",
            "set",
            "cli_output",
            "human_readable",
            "--human-readable",
        ],
        capsys,
    )
    assert set_code == 0
    assert set_err == ""
    assert "Config updated: cli_output = human_readable" in set_out

    unset_code, unset_out, unset_err = _run_cli(
        [
            "--config",
            str(config_path),
            "config",
            "unset",
            "cli_output",
            "--human-readable",
        ],
        capsys,
    )
    assert unset_code == 0
    assert unset_err == ""
    assert "Config key removed: cli_output" in unset_out


def test_cli_db_status_missing_explicit_config_errors(tmp_path, capsys) -> None:
    config_path = tmp_path / "nonexistent" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "db-status"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_cli_db_status_invalid_config_errors(tmp_path, capsys) -> None:
    config_path = tmp_path / "bad.json"
    config_path.write_text('{"version": 1, "database": {"path": 3}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "db-status"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "database.path must be str" in stderr


def test_cli_db_status_invalid_default_config_errors(
    tmp_path, capsys, monkeypatch
) -> None:
    config_home = tmp_path / "config"
    config_path = config_home / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"version": 1, "database": {"path": 3}}')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    exit_code, stdout, stderr = _run_cli(["db-status"], capsys)

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "database.path must be str" in stderr


def test_cli_rejects_invalid_metadata_json_and_non_object(
    tmp_path: Path, capsys
) -> None:
    invalid_json_path = tmp_path / "invalid.json"
    invalid_json_path.write_text("{", encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "bad-json.db"),
            "add",
            "--space",
            "user",
            "--type",
            "fact",
            "--content",
            "bad json memory",
            "--metadata",
            f"@{invalid_json_path}",
        ],
        capsys,
    )
    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "metadata_invalid"
    assert "metadata must be valid JSON" in payload["detail"]

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "bad-type.db"),
            "add",
            "--space",
            "user",
            "--type",
            "fact",
            "--content",
            "bad metadata memory",
            "--metadata",
            "[]",
        ],
        capsys,
    )
    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "metadata_invalid"
    assert "metadata must be a JSON object" in payload["detail"]


def test_cli_validation_error_returns_2(tmp_path, capsys) -> None:
    db_path = tmp_path / "cli.db"

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "workspace",
            "--type",
            "note",
            "--content",
            "Missing workspace",
        ],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "workspace_uid is required" in stderr


def test_cli_not_found_returns_1(tmp_path, capsys) -> None:
    db_path = tmp_path / "cli.db"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "get", "missing-id"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert "NotFoundError:" in stderr


def test_cli_embedding_error_returns_clear_message(
    tmp_path, capsys, monkeypatch
) -> None:
    class UnavailableCore:
        def __init__(self, *args, **kwargs) -> None:
            raise EmbeddingProviderUnavailableError("FastEmbed is unavailable")

    monkeypatch.setattr("recollectium.cli.RecollectiumCore", UnavailableCore)

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "provider.db"), "embedding-status"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingProviderUnavailableError: FastEmbed is unavailable" in stderr


def test_cli_model_unavailable_error_returns_guidance(
    tmp_path, capsys, monkeypatch
) -> None:
    class UnavailableCore:
        def __init__(self, *args, **kwargs) -> None:
            raise EmbeddingModelUnavailableError("failed to load embedding model")

    monkeypatch.setattr("recollectium.cli.RecollectiumCore", UnavailableCore)

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "model.db"),
            "add",
            "--space",
            "user",
            "--type",
            "note",
            "--content",
            "test",
        ],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingModelUnavailableError: failed to load embedding model" in stderr
    assert "recollectium init" in stderr


def test_cli_readiness_timeout_error_returns_guidance(
    tmp_path, capsys, monkeypatch
) -> None:
    class TimeoutCore:
        def __init__(self, *args, **kwargs) -> None:
            raise EmbeddingReadinessTimeoutError("startup timed out")

    monkeypatch.setattr("recollectium.cli.RecollectiumCore", TimeoutCore)

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "timeout.db"),
            "add",
            "--space",
            "user",
            "--type",
            "note",
            "--content",
            "test",
        ],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingReadinessTimeoutError: startup timed out" in stderr
    assert "recollectium init" in stderr


def test_cli_update_with_content_gates_model_readiness(
    tmp_path, capsys, monkeypatch
) -> None:
    """Update --content triggers embedding readiness gate."""
    import recollectium.cli as cli_mod

    readiness_called = []

    class TrackingCore:
        def __init__(self, *args, **kwargs) -> None:
            self.store = type(
                "FakeStore",
                (),
                {
                    "get_memory": lambda *a, **kw: {
                        "id": "m1",
                        "space": "user",
                        "type": "note",
                        "content": "old",
                        "status": "active",
                        "embedding_profile": {
                            "provider": "fake",
                            "model": "x",
                            "dimensions": 3,
                            "version": "1",
                            "profile": "p",
                            "max_tokens": 16,
                            "chunk_tokens": 4,
                            "chunk_overlap_tokens": 0,
                            "query_prompt_policy": "raw",
                        },
                        "embedding": [1.0, 2.0, 3.0],
                    },
                    "update_memory": lambda *a, **kw: None,
                },
            )()

        def update_memory(self, memory_id, **kwargs):
            return {
                "id": memory_id,
                "space": "user",
                "type": "note",
                "content": kwargs.get("content", "old"),
            }

        def _ensure_model_ready(self):
            readiness_called.append(True)

    monkeypatch.setattr(cli_mod, "RecollectiumCore", TrackingCore)

    # update with --content should gate
    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "udb.db"), "update", "m1", "--content", "new content"],
        capsys,
    )
    assert exit_code == 0
    assert len(readiness_called) == 1


def test_cli_update_metadata_only_skips_readiness_gate(
    tmp_path, capsys, monkeypatch
) -> None:
    """Update without --content skips the embedding readiness gate."""
    import recollectium.cli as cli_mod

    readiness_called = []

    class TrackingCore:
        def __init__(self, *args, **kwargs) -> None:
            self.store = type(
                "FakeStore",
                (),
                {
                    "get_memory": lambda *a, **kw: {
                        "id": "m1",
                        "space": "user",
                        "type": "note",
                        "content": "old",
                        "status": "active",
                        "embedding_profile": {
                            "provider": "fake",
                            "model": "x",
                            "dimensions": 3,
                            "version": "1",
                            "profile": "p",
                            "max_tokens": 16,
                            "chunk_tokens": 4,
                            "chunk_overlap_tokens": 0,
                            "query_prompt_policy": "raw",
                        },
                        "embedding": [1.0, 2.0, 3.0],
                    },
                    "update_memory": lambda *a, **kw: None,
                },
            )()

        def update_memory(self, memory_id, **kwargs):
            return {"id": memory_id, "space": "user", "type": "note", "content": "old"}

        def _ensure_model_ready(self):
            readiness_called.append(True)

    monkeypatch.setattr(cli_mod, "RecollectiumCore", TrackingCore)

    # update with --source only should skip gate
    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "udb2.db"), "update", "m1", "--source", "new-source"],
        capsys,
    )
    assert exit_code == 0
    assert len(readiness_called) == 0


def test_cli_embedding_generation_error_returns_1(
    tmp_path, capsys, monkeypatch
) -> None:
    class FailingCore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def active_embedding_status(self) -> dict[str, object]:
            raise EmbeddingGenerationError("provider returned no vector")

    monkeypatch.setattr("recollectium.cli.RecollectiumCore", FailingCore)

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "generation.db"), "embedding-status"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingGenerationError: provider returned no vector" in stderr


def test_cli_fetches_one_embedding_job(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli-job.db"
    store = SQLiteMemoryStore(db_path)
    store.create_embedding_job(
        job_id="job-1",
        state="completed",
        total_count=1,
        processed_count=1,
        succeeded_count=1,
        failed_count=0,
        provider="test",
        model="fake",
        embedding_profile={"provider": "test", "model": "fake", "dimensions": 3},
    )

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "embedding-jobs", "--job-id", "job-1"],
        capsys,
    )

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout)["id"] == "job-1"


def test_cli_unknown_command_defensive_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeArgs:
        command = "mystery"
        db_path = None
        config_path = None
        log_level = None

    class FakeParser:
        def parse_args(self, argv: object) -> FakeArgs:
            return FakeArgs()

        def error(self, message: str) -> None:
            assert message == "unknown command: mystery"

    class FakeCore:
        def __init__(
            self,
            *,
            db_path: object,
            config_path: object = None,
            log_level: object = None,
        ) -> None:
            assert db_path is None

    monkeypatch.setattr("recollectium.cli._build_parser", lambda: FakeParser())
    monkeypatch.setattr("recollectium.cli.RecollectiumCore", FakeCore)

    assert main(["mystery"]) == 2


def test_cli_db_status_with_valid_config(tmp_path, capsys) -> None:
    """db-status uses resolved_database_path from config when available."""
    config_path = tmp_path / "config.json"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(
        json.dumps({"version": 1}),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "db-status"], capsys
    )
    assert exit_code == 0
    payload = json.loads(stdout)
    assert "db_path" in payload


def test_cli_parse_config_value_plain_string(tmp_path, capsys) -> None:
    """config set with a non-JSON value falls back to string."""
    config_path = tmp_path / "config.json"
    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "config", "set", "logging.level", "debug"],
        capsys,
    )
    assert exit_code == 0
    loaded = json.loads(config_path.read_text())
    assert loaded["logging"]["level"] == "debug"


def test_cli_embedding_status_and_jobs_output_json(tmp_path, capsys) -> None:
    db_path = tmp_path / "cli-embedding.db"

    add_code, _, add_err = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "user",
            "--type",
            "fact",
            "--content",
            "Local embedding status smoke",
        ],
        capsys,
    )
    assert add_code == 0
    assert add_err == ""

    status_code, status_out, status_err = _run_cli(
        ["--db", str(db_path), "embedding-status"],
        capsys,
    )
    assert status_code == 0
    assert status_err == ""
    status_payload = json.loads(status_out)
    assert status_payload["embedding_profile"]["provider"] == "builtin-fastembed"
    assert status_payload["provider_status"] == "configured"
    assert status_payload["model_status"] == "managed_by_fastembed_cache"
    assert status_payload["runtime"] == {
        "name": "fastembed",
        "threads": 1,
        "parallel": None,
    }
    assert status_payload["embedding_jobs_status_path"] == "/v1/embedding/jobs"
    assert isinstance(status_payload["recent_embedding_jobs"], list)

    jobs_code, jobs_out, jobs_err = _run_cli(
        ["--db", str(db_path), "embedding-jobs"],
        capsys,
    )
    assert jobs_code == 0
    assert jobs_err == ""
    jobs_payload = json.loads(jobs_out)
    assert isinstance(jobs_payload, list)
    if jobs_payload:
        job_id = jobs_payload[0]["id"]

        one_job_code, one_job_out, one_job_err = _run_cli(
            ["--db", str(db_path), "embedding-jobs", "--job-id", job_id],
            capsys,
        )
        assert one_job_code == 0
        assert one_job_err == ""
        one_job_payload = json.loads(one_job_out)
        assert one_job_payload["id"] == job_id

    state_code, state_out, state_err = _run_cli(
        [
            "--db",
            str(db_path),
            "embedding-jobs",
            "--state",
            "completed",
            "--limit",
            "1",
        ],
        capsys,
    )
    assert state_code == 0
    assert state_err == ""
    state_payload = json.loads(state_out)
    assert isinstance(state_payload, list)


# ---------------------------------------------------------------------------
# Config command tests
# ---------------------------------------------------------------------------


class TestConfigCommand:
    def test_directory_writable_returns_false_for_file_path(self, tmp_path) -> None:
        from recollectium.cli import _directory_writable

        non_directory = tmp_path / "not-a-dir"
        non_directory.write_text("x", encoding="utf-8")

        assert _directory_writable(non_directory) is False

    def test_config_prints_effective_json(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1}),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config"], capsys
        )
        assert exit_code == 0
        assert stderr == ""
        payload = json.loads(stdout)
        assert payload["service"]["port"] == 8765

    def test_config_validate_success(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1}),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "--validate"], capsys
        )
        assert exit_code == 0
        assert stderr == ""

    def test_config_validate_failure(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text("{bad", encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "--validate"], capsys
        )
        assert exit_code == 2
        assert "invalid JSON" in stderr

    def test_config_validate_missing_file(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "nonexistent.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "--validate"], capsys
        )
        assert exit_code == 1
        assert "config file not found" in stderr

    def test_config_validate_default_creates_file(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

        exit_code, stdout, stderr = _run_cli(["config", "--validate"], capsys)

        config_path = config_home / "recollectium" / "config.json"
        assert exit_code == 0
        assert stdout == ""
        assert stderr == ""
        assert config_path.exists()

    def test_config_path_flag(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "--path"], capsys
        )
        assert exit_code == 0
        assert stderr == ""
        assert str(config_path) in stdout

    def test_config_path_writes_structured_log_without_creating_config(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        state_home = tmp_path / "state"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

        exit_code, stdout, stderr = _run_cli(["config", "--path"], capsys)

        config_path = config_home / "recollectium" / "config.json"
        log_file = state_home / "recollectium" / "logs" / "recollectium.log"
        assert exit_code == 0
        assert stderr == ""
        assert str(config_path) in stdout
        assert not config_path.exists()
        payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
        assert payload["event"] == "cli.command"
        assert payload["context"] == {"command": "config"}

    def test_config_defaults(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "--defaults"], capsys
        )
        assert exit_code == 0
        assert stderr == ""
        payload = json.loads(stdout)
        assert payload["version"] == 1
        assert payload["service"]["port"] == 8765

    def test_config_get_value(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "service": {"port": 9999}}),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "get", "service.port"], capsys
        )
        assert exit_code == 0
        assert stderr == ""
        assert json.loads(stdout) == 9999

    def test_config_get_missing_key(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "get", "nonexistent"], capsys
        )
        assert exit_code == 1
        assert "not found" in stderr

    def test_config_get_missing_explicit_file_errors(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "missing.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "get", "service.port"], capsys
        )

        assert exit_code == 1
        assert stdout == ""
        assert f"config file not found: {config_path}" in stderr

    def test_config_get_invalid_config_errors(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("{bad", encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "get", "service.port"], capsys
        )

        assert exit_code == 2
        assert stdout == ""
        assert "ValidationError: invalid JSON" in stderr

    def test_config_set_creates_file(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "set", "service.port", "9090"],
            capsys,
        )
        assert exit_code == 0
        assert config_path.exists()
        loaded = json.loads(config_path.read_text())
        assert loaded["service"]["port"] == 9090
        assert "version" in loaded

    def test_config_set_parses_json_values(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "set", "service.port", "9090"],
            capsys,
        )
        assert exit_code == 0
        loaded = json.loads(config_path.read_text())
        assert loaded["service"]["port"] == 9090
        assert isinstance(loaded["service"]["port"], int)

    def test_config_set_preserves_existing_keys(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "logging": {"level": "debug"}}),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "set", "service.port", "8080"],
            capsys,
        )
        assert exit_code == 0
        loaded = json.loads(config_path.read_text())
        assert loaded["logging"]["level"] == "debug"
        assert loaded["service"]["port"] == 8080

    def test_config_unset_removes_key(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "service": {"host": "0.0.0.0", "port": 8765}}),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "unset", "service.host"], capsys
        )
        assert exit_code == 0
        loaded = json.loads(config_path.read_text())
        assert "host" not in loaded["service"]
        assert loaded["service"]["port"] == 8765

    def test_config_unset_missing_key(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "unset", "nonexistent"], capsys
        )
        assert exit_code == 1
        assert "not found" in stderr

    def test_config_unset_missing_file(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "nonexistent.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "unset", "service.port"], capsys
        )
        assert exit_code == 1
        assert "config file not found" in stderr

    def test_config_init_creates_file(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "recollectium" / "config.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "init"], capsys
        )
        assert exit_code == 0
        assert config_path.exists()
        loaded = json.loads(config_path.read_text())
        assert loaded["version"] == 1

    def test_config_init_without_force_existing(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1, "custom": "data"}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "init"], capsys
        )
        assert exit_code == 1
        assert "already exists" in stderr
        # File should NOT be overwritten
        loaded = json.loads(config_path.read_text())
        assert loaded.get("custom") == "data"

    def test_config_init_force_overwrites(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1, "custom": "data"}', encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "init", "--force"], capsys
        )
        assert exit_code == 0
        loaded = json.loads(config_path.read_text())
        assert "custom" not in loaded
        assert loaded["version"] == 1

    def test_config_explicit_missing_file_errors(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "nonexistent" / "config.json"
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config"], capsys
        )
        assert exit_code == 1
        assert stdout == ""
        assert f"config file not found: {config_path}" in stderr

    def test_config_no_args_invalid_config_errors(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("{bad", encoding="utf-8")
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config"], capsys
        )

        assert exit_code == 2
        assert stdout == ""
        assert "ValidationError: invalid JSON" in stderr

    def test_config_default_no_args_creates_file(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

        exit_code, stdout, stderr = _run_cli(["config"], capsys)

        config_path = config_home / "recollectium" / "config.json"
        assert exit_code == 0
        assert stderr == ""
        assert config_path.exists()
        payload = json.loads(stdout)
        assert payload["service"]["port"] == 8765

    def test_config_default_get_creates_file(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

        exit_code, stdout, stderr = _run_cli(["config", "get", "service.port"], capsys)

        config_path = config_home / "recollectium" / "config.json"
        assert exit_code == 0
        assert stderr == ""
        assert json.loads(stdout) == 8765
        assert config_path.exists()

    def test_config_path_and_defaults_do_not_create_default_file(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

        path_code, path_stdout, path_stderr = _run_cli(["config", "--path"], capsys)
        defaults_code, defaults_stdout, defaults_stderr = _run_cli(
            ["config", "--defaults"], capsys
        )

        config_path = config_home / "recollectium" / "config.json"
        assert path_code == 0
        assert path_stderr == ""
        assert str(config_path) in path_stdout
        assert defaults_code == 0
        assert defaults_stderr == ""
        assert json.loads(defaults_stdout) == DEFAULTS
        assert not config_path.exists()

    def test_config_doctor_success_and_default_creation(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_home = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

        exit_code, stdout, stderr = _run_cli(["config", "doctor"], capsys)

        config_path = config_home / "recollectium" / "config.json"
        assert exit_code == 0
        assert stderr == ""
        assert config_path.exists()
        payload = json.loads(stdout)
        assert payload["status"] == "ok"
        assert payload["checks"]["config"] == str(config_path)
        assert "data" in payload["checks"]
        assert "cache" in payload["checks"]
        assert "logs" in payload["checks"]
        assert "runtime" in payload["checks"]

    def test_config_doctor_explicit_missing_file_errors(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "missing" / "config.json"

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "doctor"], capsys
        )

        assert exit_code == 1
        assert stdout == ""
        assert f"config file not found: {config_path}" in stderr

    def test_config_doctor_invalid_embedding_settings_fail_validation(
        self, tmp_path, capsys
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "embedding": {
                        "provider": "custom-provider",
                        "model": "custom-model",
                    },
                }
            ),
            encoding="utf-8",
        )

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "doctor"], capsys
        )

        assert exit_code == 2
        assert stdout == ""
        assert "ValidationError:" in stderr
        assert "embedding.provider only supports" in stderr

    def test_config_doctor_reports_directory_writability_failure(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": 1}), encoding="utf-8")
        monkeypatch.setattr("recollectium.cli._directory_writable", lambda _path: False)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "doctor"], capsys
        )

        assert exit_code == 1
        assert stdout == ""
        assert "FAIL data directory is not writable:" in stderr
        assert "FAIL cache directory is not writable:" in stderr
        assert "FAIL logs directory is not writable:" in stderr
        assert "FAIL runtime directory is not writable:" in stderr
        assert "FAIL database parent directory is not writable:" in stderr

    def test_config_doctor_reports_missing_and_nondirectory_paths(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        state_home = tmp_path / "state"
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        non_dir = tmp_path / "not-a-dir"
        non_dir.write_text("x", encoding="utf-8")
        monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

        fake_cfg = SimpleNamespace(
            config_file_path=tmp_path / "config.json",
            xdg_dirs={
                "data": tmp_path / "missing-data",
                "cache": non_dir,
                "logs": existing_dir,
                "runtime": existing_dir,
            },
            resolved_database_path=(tmp_path / "missing-db-parent" / "recollectium.db"),
        )
        monkeypatch.setattr(
            "recollectium.cli._load_effective_config", lambda _path, explicit: fake_cfg
        )

        exit_code, stdout, stderr = _run_cli(["config", "doctor"], capsys)

        assert exit_code == 1
        assert stdout == ""
        assert "FAIL data directory missing:" in stderr
        assert "FAIL cache path is not a directory:" in stderr
        assert "FAIL database parent directory missing:" in stderr
        log_file = state_home / "recollectium" / "logs" / "recollectium.log"
        payloads = [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
        ]
        doctor_failures = [
            payload
            for payload in payloads
            if payload["event"] == "config.doctor_failed"
        ]
        assert {payload["message"] for payload in doctor_failures} >= {
            f"data directory missing: {tmp_path / 'missing-data'}",
            f"cache path is not a directory: {non_dir}",
            f"database parent directory missing: {tmp_path / 'missing-db-parent'}",
        }

    def test_config_doctor_reports_database_parent_not_directory(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        shared_dir = tmp_path / "dirs"
        shared_dir.mkdir()
        db_parent_file = tmp_path / "db-parent-file"
        db_parent_file.write_text("x", encoding="utf-8")

        fake_cfg = SimpleNamespace(
            config_file_path=tmp_path / "config.json",
            xdg_dirs={
                "data": shared_dir,
                "cache": shared_dir,
                "logs": shared_dir,
                "runtime": shared_dir,
            },
            resolved_database_path=db_parent_file / "recollectium.db",
        )
        monkeypatch.setattr(
            "recollectium.cli._load_effective_config", lambda _path, explicit: fake_cfg
        )

        exit_code, stdout, stderr = _run_cli(["config", "doctor"], capsys)

        assert exit_code == 1
        assert "FAIL database parent path is not a directory:" in stderr

    # -- edit ---------------------------------------------------------------

    def test_config_edit_creates_file_and_opens_editor(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "recollectium" / "config.json"
        editor_calls: list[list[str]] = []

        def _fake_call(args, **kwargs) -> int:
            editor_calls.append(args)
            return 0

        monkeypatch.setattr("subprocess.call", _fake_call)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "edit"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        assert config_path.exists()
        loaded = json.loads(config_path.read_text())
        assert loaded["version"] == 1
        assert len(editor_calls) == 1
        assert editor_calls[0][0] == "vi"
        assert editor_calls[0][1] == str(config_path)

    def test_config_edit_opens_existing_config(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "logging": {"level": "debug"}}),
            encoding="utf-8",
        )
        editor_calls: list[list[str]] = []

        def _fake_call(args, **kwargs) -> int:
            editor_calls.append(args)
            return 0

        monkeypatch.setattr("subprocess.call", _fake_call)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "edit"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        # File should not be overwritten
        loaded = json.loads(config_path.read_text())
        assert loaded["logging"]["level"] == "debug"
        assert len(editor_calls) == 1
        assert editor_calls[0][1] == str(config_path)

    def test_config_edit_respects_editor_env(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")
        monkeypatch.setenv("EDITOR", "nano")

        editor_calls: list[list[str]] = []

        def _fake_call(args, **kwargs) -> int:
            editor_calls.append(args)
            return 0

        monkeypatch.setattr("subprocess.call", _fake_call)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "edit"], capsys
        )

        assert exit_code == 0
        assert editor_calls[0][0] == "nano"

    def test_config_edit_editor_not_found(self, tmp_path, capsys, monkeypatch) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")

        def _fake_call(args, **kwargs) -> int:
            raise FileNotFoundError("no such editor")

        monkeypatch.setattr("subprocess.call", _fake_call)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "edit"], capsys
        )

        assert exit_code == 1
        assert "editor not found" in stderr

    def test_config_edit_returns_editor_exit_code(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text('{"version": 1}', encoding="utf-8")

        def _fake_call(args, **kwargs) -> int:
            return 42

        monkeypatch.setattr("subprocess.call", _fake_call)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "edit"], capsys
        )

        assert exit_code == 42

    # -- reset --------------------------------------------------------------

    def test_config_reset_creates_file_when_missing(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "recollectium" / "config.json"

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "reset"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        assert json.loads(stdout) == {"path": str(config_path)}
        assert config_path.exists()
        loaded = json.loads(config_path.read_text())
        assert loaded["version"] == 1
        assert loaded["service"]["port"] == 8765

    def test_config_reset_overwrites_existing(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "logging": {"level": "debug"}, "custom": "data"}),
            encoding="utf-8",
        )

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "reset"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        assert json.loads(stdout) == {"path": str(config_path)}
        loaded = json.loads(config_path.read_text())
        assert "custom" not in loaded
        assert loaded["logging"]["level"] == "info"  # back to default

    def test_config_reset_prints_message(self, tmp_path, capsys) -> None:
        config_path = tmp_path / "config.json"

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "reset"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        assert json.loads(stdout) == {"path": str(config_path)}

    def test_config_help_shows_actions(self, capsys) -> None:
        help_text = _run_help(["config", "--help"], capsys)
        assert "inspect, validate, and edit" in help_text.lower()
        assert "get" in help_text
        assert "set" in help_text
        assert "unset" in help_text
        assert "init" in help_text
        assert "doctor" in help_text
        assert "edit" in help_text
        assert "reset" in help_text
        assert "--validate" in help_text
        assert "--path" in help_text
        assert "--defaults" in help_text


def test_cli_version_prints_package_version(capsys, monkeypatch) -> None:
    monkeypatch.setattr("recollectium.cli.package_version", lambda _name: "1.2.3")

    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout == "recollectium 1.2.3\n"
    assert stderr == ""


def test_cli_version_uses_source_fallback(capsys, monkeypatch) -> None:
    def _missing_package(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("recollectium.cli.package_version", _missing_package)
    monkeypatch.setattr("recollectium.cli.__version__", "0.1.0-dev")

    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout == "recollectium 0.1.0-dev\n"
    assert stderr == ""


def test_cli_version_without_command_does_not_require_subcommand(capsys) -> None:
    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout.startswith("recollectium ")
    assert stderr == ""


def test_cli_init_creates_runtime_files_and_downloads_model(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    ready_calls: list[object] = []

    def _fake_ensure_ready(self) -> None:
        ready_calls.append(self)

    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _fake_ensure_ready,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    payload = json.loads(stdout)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    db_path = tmp_path / "data" / "recollectium" / "recollectium.db"
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "initialized"
    assert payload["config"] == str(config_path)
    assert payload["database"] == str(db_path)
    assert payload["embedding_model"] == "jinaai/jina-embeddings-v2-small-en"
    assert config_path.exists()
    assert db_path.exists()
    assert (tmp_path / "cache" / "recollectium").is_dir()
    assert (tmp_path / "state" / "recollectium" / "logs").is_dir()
    assert ready_calls


def test_cli_init_explicit_missing_config_creates_file(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "custom" / "config.json"
    ready_calls: list[object] = []

    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        lambda self: ready_calls.append(self),
    )

    exit_code, stdout, stderr = _run_cli(["--config", str(config_path), "init"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["config"] == str(config_path)
    assert config_path.exists()
    assert ready_calls


def test_cli_init_accepts_db_after_subcommand(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = tmp_path / "custom.db"
    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        lambda self: None,
    )

    exit_code, stdout, stderr = _run_cli(["init", "--db", str(db_path)], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["database"] == str(db_path)
    assert db_path.exists()


def test_cli_init_reports_validation_error(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"version": 1, "logging": {"level": "bad"}}))

    exit_code, stdout, stderr = _run_cli(["--config", str(config_path), "init"], capsys)

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr


def test_cli_init_reports_file_not_found_from_handler(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_file_not_found(*args, **kwargs) -> int:
        raise FileNotFoundError("config disappeared")

    monkeypatch.setattr("recollectium.cli._handle_init_command", _raise_file_not_found)

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "config disappeared" in stderr


def test_cli_init_reports_model_readiness_error(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def _raise_readiness_error(self) -> None:
        raise EmbeddingProviderUnavailableError("model unavailable")

    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _raise_readiness_error,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingProviderUnavailableError: model unavailable" in stderr


def test_cli_init_reports_readiness_timeout_error(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def _raise_timeout(self) -> None:
        raise EmbeddingReadinessTimeoutError("startup timed out")

    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _raise_timeout,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingReadinessTimeoutError: startup timed out" in stderr
    assert "recollectium init" in stderr


def test_cli_init_reports_model_unavailable_error(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def _raise_model_error(self) -> None:
        raise EmbeddingModelUnavailableError("model not found")

    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _raise_model_error,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingModelUnavailableError: model not found" in stderr
    assert "recollectium init" in stderr


def test_cli_init_reports_generic_recollectium_error(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_recollectium_error(*args: object, **kwargs: object) -> int:
        raise RecollectiumError("init failed")

    monkeypatch.setattr(
        "recollectium.cli._handle_init_command", _raise_recollectium_error
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "RecollectiumError: init failed" in stderr


def test_cli_update_without_memory_id_requires_memory_id(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unexpected_core(*args, **kwargs):
        raise AssertionError("missing memory id should not initialise RecollectiumCore")

    monkeypatch.setattr("recollectium.cli.RecollectiumCore", _unexpected_core)

    exit_code, stdout, stderr = _run_cli(["update"], capsys)

    payload = json.loads(stderr)
    assert exit_code == 2
    assert stdout == ""
    assert payload["status"] == "validation_error"
    assert "recollectium upgrade" in payload["hint"]


def _set_xdg_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


def test_cli_service_discover_not_running_does_not_create_config(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)

    exit_code, stdout, stderr = _run_cli(["service", "discover"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 1
    assert stderr == ""
    assert payload["status"] == "not_running"
    assert payload["service"] is None
    assert "service start api" in payload["next_step"]
    assert not (tmp_path / "config" / "recollectium" / "config.json").exists()


def test_cli_service_discover_running_returns_success(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)

    def _fake_discover(config: object) -> dict[str, object]:
        return {
            "status": "running",
            "service": {"type": "api", "pid": 123},
            "paths": {},
        }

    monkeypatch.setattr("recollectium.cli.discover_service", _fake_discover)

    exit_code, stdout, stderr = _run_cli(["service", "discover"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout)["status"] == "running"


def test_cli_service_discover_invalid_config_exits_two(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"service": {"port": "bad"}}), encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "discover"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError" in stderr


def test_cli_service_discover_explicit_missing_config_exits_one(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    missing_path = tmp_path / "missing.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(missing_path), "service", "discover"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {missing_path}" in stderr


def test_cli_service_discover_service_error_exits_two(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)

    def _raise_service_error(config: object) -> dict[str, object]:
        raise ServiceError("corrupted PID file")

    monkeypatch.setattr("recollectium.cli.discover_service", _raise_service_error)

    exit_code, stdout, stderr = _run_cli(["service", "discover"], capsys)

    assert exit_code == 2
    assert stdout == ""
    assert "corrupted PID file" in stderr


def test_cli_uninstall_preserves_data_and_uses_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    db_path = tmp_path / "data" / "recollectium" / "recollectium.db"
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    config_path.parent.mkdir(parents=True)
    db_path.parent.mkdir(parents=True)
    metadata_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    db_path.write_text("preserved", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "install_method": "bootstrap",
                "source_ref": "main",
                "managed_path_edits": ["profile path edit"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "recollectium.cli.RecollectiumCore", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "manual_uninstall_required"
    assert payload["data"]["preserved"] is True
    assert payload["data"]["paths"]["database"] == str(db_path)
    assert payload["package"]["install_method"] == "bootstrap"
    assert payload["package"]["source_ref"] == "main"
    assert payload["package"]["recommended"] == "uv tool uninstall recollectium"
    assert payload["package"]["managed_path_edits"] == ["profile path edit"]
    assert config_path.exists()
    assert db_path.read_text(encoding="utf-8") == "preserved"


def test_cli_uninstall_uses_bootstrap_legacy_state_metadata_path(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "legacy-state"))
    monkeypatch.setattr(
        "recollectium.cli.user_state_dir",
        lambda _app_name: str(tmp_path / "platform-state"),
    )
    metadata_path = tmp_path / "legacy-state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"install_method": "bootstrap", "source_ref": "ci"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "bootstrap"
    assert payload["package"]["source_ref"] == "ci"


def test_cli_uninstall_uses_windows_bootstrap_metadata_path(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setattr(
        "recollectium.cli.user_state_dir",
        lambda _app_name: str(tmp_path / "platform-state"),
    )
    metadata_path = tmp_path / "local-app-data" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"install_method": "bootstrap", "source_ref": "ci"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "bootstrap"
    assert payload["package"]["source_ref"] == "ci"


def test_cli_uninstall_purge_closes_log_handlers_before_deleting_logs(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    shutdown_called = False

    original_rmtree = shutil.rmtree

    def _shutdown() -> None:
        nonlocal shutdown_called
        shutdown_called = True

    def _assert_shutdown_before_delete(path: Path) -> None:
        if path == tmp_path / "state" / "recollectium" / "logs":
            assert shutdown_called
        original_rmtree(path)

    monkeypatch.setattr("recollectium.cli.logging.shutdown", _shutdown)
    monkeypatch.setattr(
        "recollectium.cli.shutil.rmtree", _assert_shutdown_before_delete
    )

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recollectium-data"], capsys
    )

    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert json.loads(stdout)["data"]["purge"]["deleted"]
    assert shutdown_called


def test_cli_uninstall_removes_managed_completion_block(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(
        "before\n"
        "# >>> recollectium completion >>>\n"
        'eval "$(recollectium completion --source bash)"\n'
        "# <<< recollectium completion <<<\n"
        "after\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert bashrc.read_text(encoding="utf-8") == "before\nafter\n"
    assert payload["shell_completion"]["removed"] == [
        {"path": str(bashrc), "removed": True, "blocks": 1}
    ]


def test_cli_uninstall_dry_run_preserves_managed_completion_block(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    content = (
        "# >>> recollectium completion >>>\n"
        'eval "$(recollectium completion --source bash)"\n'
        "# <<< recollectium completion <<<\n"
    )
    bashrc.write_text(content, encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--dry-run"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert bashrc.read_text(encoding="utf-8") == content
    assert payload["shell_completion"]["removed"] == []
    assert any(
        item["path"] == str(bashrc) and item["reason"] == "dry_run"
        for item in payload["shell_completion"]["skipped"]
    )


def test_cli_uninstall_removes_completion_block_from_install_metadata_path(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    custom_rc = tmp_path / "custom" / "recollectium-shell-setup"
    custom_rc.parent.mkdir()
    custom_rc.write_text(
        "# >>> recollectium completion >>>\n"
        'eval "$(recollectium completion --source bash)"\n'
        "# <<< recollectium completion <<<\n",
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "managed_path_edits": [
                    f'{custom_rc}: eval "$(recollectium completion --source bash)"'
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert custom_rc.read_text(encoding="utf-8") == "\n"
    assert payload["shell_completion"]["removed"] == [
        {"path": str(custom_rc), "removed": True, "blocks": 1}
    ]


def test_cli_uninstall_removes_powershell_completion_from_structured_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    profile = tmp_path / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "before\n"
        "# >>> recollectium completion >>>\n"
        "if (Get-Command recollectium -ErrorAction SilentlyContinue) {\n"
        "    Invoke-Expression (& recollectium completion --source powershell)\n"
        "}\n"
        "# <<< recollectium completion <<<\n"
        "after\n",
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "managed_completion_edits": [
                    {
                        "shell": "powershell",
                        "path": str(profile),
                        "source_command": "recollectium completion --source powershell",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert profile.read_text(encoding="utf-8") == "before\nafter\n"
    assert payload["shell_completion"]["removed"] == [
        {"path": str(profile), "removed": True, "blocks": 1}
    ]


def test_cli_uninstall_ignores_invalid_structured_completion_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"managed_completion_edits": ["not structured"]}),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["shell_completion"]["removed"] == []


def test_cli_uninstall_bootstrap_starts_package_removal_handoff(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"install_method": "bootstrap", "managed_path_edits": []}),
        encoding="utf-8",
    )
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []

    class FakePopen:
        def __init__(self, cmd: list[str], **kwargs: Any) -> None:
            popen_calls.append((cmd, kwargs))

    monkeypatch.setattr("recollectium.cli.subprocess.Popen", FakePopen)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["uninstall"]["status"] == "started"
    assert (
        payload["package"]["uninstall"]["command"] == "uv tool uninstall recollectium"
    )
    assert popen_calls
    assert "uv tool uninstall recollectium" in " ".join(popen_calls[0][0])


def test_cli_uninstall_dry_run_does_not_start_bootstrap_package_removal(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"install_method": "bootstrap", "managed_path_edits": []}),
        encoding="utf-8",
    )
    popen_calls: list[list[str]] = []
    monkeypatch.setattr(
        "recollectium.cli.subprocess.Popen",
        lambda cmd, **kwargs: popen_calls.append(cmd),
    )

    exit_code, stdout, stderr = _run_cli(["uninstall", "--dry-run"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["uninstall"]["status"] == "dry_run"
    assert popen_calls == []


def test_cli_uninstall_completion_cleanup_skips_duplicate_metadata_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.cli import _remove_completion_blocks

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("", encoding="utf-8")

    payload = _remove_completion_blocks(
        {
            "managed_path_edits": [
                123,
                f'{bashrc}: eval "$(recollectium completion --source bash)"',
            ]
        },
        dry_run=True,
    )

    paths = [item["path"] for item in payload["targets"]]
    assert paths.count(str(bashrc)) == 1


def test_cli_uninstall_completion_cleanup_reports_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.cli import _remove_completion_blocks

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("", encoding="utf-8")
    original_read_text = Path.read_text

    def _raise_for_bashrc(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == bashrc:
            raise OSError("cannot read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_for_bashrc)

    payload = _remove_completion_blocks(None, dry_run=False)

    assert any(
        item["path"] == str(bashrc) and item["reason"] == "read_error: cannot read"
        for item in payload["skipped"]
    )


def test_cli_uninstall_completion_cleanup_reports_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.cli import _remove_completion_blocks

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(
        "# >>> recollectium completion >>>\n"
        'eval "$(recollectium completion --source bash)"\n'
        "# <<< recollectium completion <<<\n",
        encoding="utf-8",
    )
    original_write_text = Path.write_text

    def _raise_for_bashrc(path: Path, *args: Any, **kwargs: Any) -> int:
        if path == bashrc:
            raise OSError("cannot write")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _raise_for_bashrc)

    payload = _remove_completion_blocks(None, dry_run=False)

    assert any(
        item["path"] == str(bashrc) and item["reason"] == "write_error: cannot write"
        for item in payload["skipped"]
    )


def test_cli_uninstall_stops_running_service(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    stopped_configs: list[object] = []

    def _fake_stop(config: object) -> int:
        stopped_configs.append(config)
        return 123

    monkeypatch.setattr("recollectium.cli.stop_service", _fake_stop)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["service"] == {"status": "stopped", "pid": 123}
    assert stopped_configs


def test_cli_uninstall_rejects_destructive_yes_without_purge(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--yes-delete-all-recollectium-data"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert "requires --purge" in stderr


def test_cli_uninstall_reports_explicit_missing_config(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(tmp_path / "missing.json"), "uninstall"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert "config file not found" in stderr


def test_cli_uninstall_reports_invalid_config(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"logging": {"level": "bad"}}), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "uninstall"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError" in stderr


def test_cli_uninstall_reports_service_stop_error(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_service_error(_config: object) -> None:
        raise ServiceError("service stop failed")

    monkeypatch.setattr("recollectium.cli.stop_service", _raise_service_error)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "service stop failed" in stderr


def test_cli_uninstall_ignores_unreadable_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "unknown"


def test_cli_uninstall_ignores_non_object_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(["bootstrap"]), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "unknown"


def test_cli_uninstall_purge_dry_run_lists_targets_without_deleting(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    data_dir = tmp_path / "data" / "recollectium"
    cache_dir = tmp_path / "cache" / "recollectium"
    logs_dir = tmp_path / "state" / "recollectium" / "logs"
    runtime_dir = tmp_path / "runtime" / "recollectium"
    for directory in (config_path.parent, data_dir, cache_dir, logs_dir, runtime_dir):
        directory.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    (data_dir / "recollectium.db").write_text("memory", encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge", "--dry-run"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["service"] == {
        "status": "dry_run",
        "note": "service would be stopped",
    }
    assert payload["data"]["preserved"] is False
    assert payload["data"]["purge"]["dry_run"] is True
    assert payload["data"]["purge"]["deleted"] == []
    assert config_path.exists()
    assert (data_dir / "recollectium.db").exists()


def test_cli_uninstall_purge_cancelled_by_confirmation(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "purge cancelled" in stderr


def test_cli_uninstall_purge_accepts_interactive_confirmation(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr("sys.stdin.readline", lambda: "delete all recollectium data\n")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert str(config_path) in stderr
    assert payload["data"]["purge"]["deleted"]


def test_cli_uninstall_purge_deletes_recollectium_owned_paths(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    data_dir = tmp_path / "data" / "recollectium"
    cache_dir = tmp_path / "cache" / "recollectium"
    logs_dir = tmp_path / "state" / "recollectium" / "logs"
    runtime_dir = tmp_path / "runtime" / "recollectium"
    metadata_path = tmp_path / "state" / "recollectium" / "install.json"
    for directory in (config_path.parent, data_dir, cache_dir, logs_dir, runtime_dir):
        directory.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    (data_dir / "recollectium.db").write_text("memory", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recollectium-data"], capsys
    )

    payload = json.loads(stdout)
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert payload["data"]["purge"]["deleted"]
    assert not config_path.parent.exists()
    assert not data_dir.exists()
    assert not cache_dir.exists()
    assert not logs_dir.exists()
    assert not runtime_dir.exists()
    assert (tmp_path / "config").exists()
    assert (tmp_path / "data").exists()


def test_cli_uninstall_purge_reports_delete_errors(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    def _raise_remove(_path: Path) -> None:
        raise OSError("delete failed")

    monkeypatch.setattr("recollectium.cli.shutil.rmtree", _raise_remove)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recollectium-data"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    assert "delete failed" in stderr


def test_cli_uninstall_purge_skips_shared_cache_override(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    shared_cache = tmp_path / "shared-cache"
    shared_cache.mkdir()
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_data = deepcopy(DEFAULTS)
    config_data["directories"] = {"cache": str(shared_cache)}
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recollectium-data"], capsys
    )

    payload = json.loads(stdout)
    skipped = payload["data"]["purge"]["skipped"]
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert shared_cache.exists()
    assert any(
        item["path"] == str(shared_cache) and item["reason"] == "not_recollectium_owned"
        for item in skipped
    )


def test_cli_uninstall_purge_skips_explicit_config_outside_recollectium_dir(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "uninstall",
            "--purge",
            "--yes-delete-all-recollectium-data",
        ],
        capsys,
    )

    payload = json.loads(stdout)
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert config_path.exists()
    assert any(
        item["path"] == str(config_path) and item["reason"] == "not_recollectium_owned"
        for item in payload["data"]["purge"]["skipped"]
    )


def test_cli_uninstall_purge_skips_duplicate_targets(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    duplicate_dir = tmp_path / "data" / "recollectium"
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    duplicate_dir.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    config_data = deepcopy(DEFAULTS)
    config_data["directories"] = {
        "data": str(duplicate_dir),
        "cache": str(duplicate_dir),
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge", "--dry-run"], capsys)

    payload = json.loads(stdout)
    paths = [item["path"] for item in payload["data"]["purge"]["targets"]]
    assert exit_code == 0
    assert stderr == ""
    assert paths.count(str(duplicate_dir)) == 1


def test_cli_uninstall_purge_marks_suspicious_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recollectium.cli import _delete_purge_target

    monkeypatch.setattr(Path, "home", lambda: Path.cwd())

    payload = _delete_purge_target(Path.cwd(), dry_run=True)

    assert payload == {
        "path": str(Path.cwd()),
        "deleted": False,
        "reason": "suspicious_path",
    }


def test_cli_reinstall_after_safe_uninstall_reuses_existing_config_and_database(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr(
        "recollectium.cli.BuiltinFastEmbedProvider.ensure_ready",
        lambda self: None,
    )

    assert _run_cli(["init"], capsys)[0] == 0
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    db_path = tmp_path / "data" / "recollectium" / "recollectium.db"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["service"]["port"] = 9090
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    db_size = db_path.stat().st_size

    assert _run_cli(["uninstall"], capsys)[0] == 0
    assert _run_cli(["init"], capsys)[0] == 0

    reloaded = json.loads(config_path.read_text(encoding="utf-8"))
    assert reloaded["service"]["port"] == 9090
    assert db_path.stat().st_size == db_size


def test_cli_uninstall_dry_run_without_purge_prints_instructions(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recollectium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--dry-run"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "manual_uninstall_required"
    assert payload["data"]["preserved"] is True
    assert payload["service"]["status"] == "dry_run"


def test_cli_uninstall_dry_run_does_not_stop_service(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    stop_calls: list[object] = []

    def _record_stop(config: object) -> int:
        stop_calls.append(config)
        return 123

    monkeypatch.setattr("recollectium.cli.stop_service", _record_stop)

    _run_cli(["uninstall", "--dry-run"], capsys)
    assert stop_calls == []

    _run_cli(["uninstall", "--purge", "--dry-run"], capsys)
    assert stop_calls == []


def test_cli_uninstall_config_is_recollectium_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recollectium.cli import _UninstallConfig
    from recollectium.config import RecollectiumConfig

    conf = _UninstallConfig(
        effective_config={},
        xdg_dirs={},
        config_path=tmp_path / "cfg.json",
        database_path=tmp_path / "db.db",
    )
    assert isinstance(conf, RecollectiumConfig)


class TestMcpStdioErrorPaths:
    def test_mcp_stdio_file_not_found(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        config_data = dict(DEFAULTS)
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        with patch("recollectium.cli.RecollectiumCore") as mock_core:
            mock_core.side_effect = FileNotFoundError("no database found")
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 1
        assert stdout == ""
        assert "no database found" in stderr

    def test_mcp_stdio_validation_error(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        config_data = dict(DEFAULTS)
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        with patch("recollectium.cli.RecollectiumCore") as mock_core:
            mock_core.side_effect = ValidationError("bad config value")
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 2
        assert stdout == ""
        assert "ValidationError: bad config value" in stderr

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (
                EmbeddingReadinessTimeoutError("startup timed out"),
                "EmbeddingReadinessTimeoutError: startup timed out",
            ),
            (
                EmbeddingModelUnavailableError("model not found"),
                "EmbeddingModelUnavailableError: model not found",
            ),
            (
                EmbeddingProviderUnavailableError("provider unavailable"),
                "EmbeddingProviderUnavailableError: provider unavailable",
            ),
        ],
    )
    def test_mcp_stdio_readiness_errors_return_guidance(
        self, tmp_path, capsys, error: Exception, expected: str
    ) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        config_data = dict(DEFAULTS)
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        class FakeCore:
            def _ensure_model_ready(self) -> None:
                raise error

        with patch("recollectium.cli.RecollectiumCore", return_value=FakeCore()):
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 1
        assert stdout == ""
        assert expected in stderr
        assert "recollectium init" in stderr

    def test_mcp_stdio_happy_path_returns_zero(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        config_data = dict(DEFAULTS)
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        class FakeMCP:
            async def run_stdio_async(self) -> None:
                pass

        with (
            patch("recollectium.cli.RecollectiumCore"),
            patch("recollectium.cli.create_mcp_server", return_value=FakeMCP()),
        ):
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 0

    def test_mcp_stdio_runtime_error(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        config_data = dict(DEFAULTS)
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        class FakeMCP:
            def run_stdio_async(self) -> None:
                raise RuntimeError("stdio transport broken")

        with (
            patch("recollectium.cli.RecollectiumCore"),
            patch("recollectium.cli.create_mcp_server", return_value=FakeMCP()),
        ):
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 1
        assert stdout == ""
        assert "stdio transport broken" in stderr


class TestServiceStatusCorruptConfig:
    def test_status_validation_error_on_bad_config(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.json"

        config_data = dict(DEFAULTS)
        config_data["logging"] = {"level": "invalid"}
        config_data["directories"] = {
            "data": str(tmp_path / "data"),
            "cache": str(tmp_path / "cache"),
            "logs": str(tmp_path / "logs"),
            "runtime": str(tmp_path / "run"),
        }
        config_path.write_text(json.dumps(config_data))

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "status"],
            capsys,
        )

        assert exit_code == 2
        assert stdout == ""
        assert "logging.level must be one of" in stderr


# ---------------------------------------------------------------------------
#  shell completion tests
# ---------------------------------------------------------------------------


def test_cli_completion_help_prints_human_readable_instructions(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "bash"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Add this line to your shell rc file" in stdout
    assert 'eval "$(recollectium completion --source bash)"' in stdout
    assert "recollectium completion --install bash" in stdout


def test_cli_completion_default_prints_human_readable_instructions(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "zsh"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Add this line to your shell rc file" in stdout
    assert 'eval "$(recollectium completion --source zsh)"' in stdout
    assert "recollectium completion --install zsh" in stdout


def test_cli_completion_default_prints_human_readable_instructions_fish(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "fish"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Add this line to your shell rc file" in stdout
    assert 'eval "$(recollectium completion --source fish)"' in stdout
    assert "recollectium completion --install fish" in stdout


def test_cli_completion_powershell_prints_human_readable_instructions(
    capsys: CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "powershell"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "$PROFILE.CurrentUserCurrentHost" in stdout
    assert "recollectium completion powershell --source" in stdout
    assert "recollectium completion --install powershell" in stdout
    assert "$PROFILE.CurrentUserAllHosts" in stdout


def test_cli_completion_source_bash_prints_shellcode(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "--source", "bash"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "register-python-argcomplete" in stdout or "complete " in stdout
    assert "recollectium" in stdout


def test_cli_completion_source_zsh_prints_shellcode(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "--source", "zsh"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert len(stdout) > 0


def test_cli_completion_source_fish_prints_shellcode(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "--source", "fish"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert len(stdout) > 0


def test_cli_completion_source_powershell_prints_dynamic_wrapper(
    capsys: CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run_cli(
        ["completion", "--source", "powershell"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    assert "Register-ArgumentCompleter" in stdout
    assert "recollectium completion --complete-line" in stdout
    assert "CompletionResult" in stdout


def test_cli_completion_dynamic_helper_completes_commands(
    capsys: CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run_cli(
        ["completion", "--complete-line", "recollectium conf"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout) == ["config"]


def test_cli_completion_dynamic_helper_completes_config_keys(
    capsys: CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run_cli(
        ["completion", "--complete-line", "recollectium config get log"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout) == [
        "logging.level",
        "logging.format",
        "logging.max_bytes",
        "logging.backup_count",
    ]


def test_cli_completion_auto_detect_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")

    exit_code, stdout, stderr = _run_cli(["completion", "--source"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "recollectium" in stdout


def test_cli_completion_unknown_shell_returns_validation_error(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)

    exit_code, stdout, stderr = _run_cli(["completion"], capsys)

    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "validation_error"
    assert payload["message"] == "Could not detect a supported shell."


def test_cli_completion_auto_detect_non_standard_shell_returns_validation_error(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    monkeypatch.delenv("PSModulePath", raising=False)

    exit_code, stdout, stderr = _run_cli(["completion"], capsys)

    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "validation_error"
    assert payload["message"] == "Could not detect a supported shell."


def test_cli_completion_auto_detect_powershell_from_environment(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setenv("PSModulePath", "C:/Users/example/Documents/PowerShell/Modules")

    exit_code, stdout, stderr = _run_cli(["completion", "--source"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Register-ArgumentCompleter" in stdout


def test_cli_completion_auto_detect_with_source(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    exit_code, stdout, stderr = _run_cli(["completion", "--source"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert len(stdout) > 0


def test_cli_completion_install_yes_writes_rc_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["rc_file"] == str(rc_path)
    assert payload["shell"] == "bash"
    content = rc_path.read_text(encoding="utf-8")
    assert "# >>> recollectium completion >>>" in content
    assert 'eval "$(recollectium completion --source bash)"' in content
    assert "# <<< recollectium completion <<<" in content


def test_cli_completion_install_powershell_uses_current_user_current_host_profile(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    monkeypatch.setenv("RECOLLECTIUM_POWERSHELL_PROFILE", str(profile))

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "powershell", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["shell"] == "powershell"
    assert payload["rc_file"] == str(profile)
    assert payload["profile"] == str(profile)
    assert payload["updated"] is False
    content = profile.read_text(encoding="utf-8")
    assert "Get-Command recollectium" in content
    assert "recollectium completion --source powershell" in content
    assert "Register-ArgumentCompleter" not in content
    assert "recollectium completion --complete-line" not in content


def test_cli_completion_install_powershell_dedups_existing_source_line(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "recollectium completion --source powershell\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RECOLLECTIUM_POWERSHELL_PROFILE", str(profile))

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "powershell", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "already_installed"
    assert payload["profile"] == str(profile)
    assert payload["updated"] is False


def test_cli_completion_install_powershell_reports_current_managed_block(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "# >>> recollectium completion >>>\n"
        "if (Get-Command recollectium -ErrorAction SilentlyContinue) {\n"
        "    Invoke-Expression (& recollectium completion --source powershell)\n"
        "}\n"
        "# <<< recollectium completion <<<\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RECOLLECTIUM_POWERSHELL_PROFILE", str(profile))

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "powershell", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "already_installed"
    assert payload["profile"] == str(profile)
    assert payload["updated"] is False


def test_cli_completion_install_refreshes_existing_managed_block(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.write_text(
        "before\n"
        "# >>> recollectium completion >>>\n"
        "old completion\n"
        "# <<< recollectium completion <<<\n"
        "after\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "updated"
    content = rc_path.read_text(encoding="utf-8")
    assert "old completion" not in content
    assert content.count("# >>> recollectium completion >>>") == 1
    assert 'eval "$(recollectium completion --source bash)"' in content


def test_cli_completion_install_reports_already_installed_for_current_managed_block(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.write_text(
        "# >>> recollectium completion >>>\n"
        'eval "$(recollectium completion --source bash)"\n'
        "# <<< recollectium completion <<<\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "already_installed"
    assert (
        rc_path.read_text(encoding="utf-8").count("# >>> recollectium completion >>>")
        == 1
    )


def test_cli_completion_install_dedup_when_already_present(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.write_text(
        'eval "$(recollectium completion --source bash)"\n', encoding="utf-8"
    )
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "already_installed"
    occurrences = rc_path.read_text(encoding="utf-8").count(
        "recollectium completion --source"
    )
    assert occurrences == 1


def test_cli_completion_install_unknown_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("recollectium.cli._COMPLETION_RC_FILES", {"bash": ".bashrc"})
    monkeypatch.setenv("SHELL", "/bin/zsh")

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "zsh", "--yes"], capsys
    )

    assert exit_code == 1
    assert "No rc file mapping" in stderr


def test_cli_completion_install_refuses_without_confirm_in_non_tty(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")

    exit_code, stdout, stderr = _run_cli(["completion", "--install", "bash"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "operation_failed"
    assert payload["message"] == "Completion installation cancelled."


def test_cli_completion_install_accepts_confirm(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin.readline", lambda: "yes\n")

    exit_code, stdout, stderr = _run_cli(["completion", "--install", "bash"], capsys)

    assert exit_code == 0
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["rc_file"] == str(rc_path)


def test_cli_completion_unreadable_rc_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.mkdir()
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 1
    assert "Could not read rc file" in stderr


def test_cli_completion_unwritable_rc_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)

    original_write_text = Path.write_text

    def _fake_write_text(self: Path, *args: Any, **kwargs: Any) -> int:
        if self == rc_path:
            raise OSError("Permission denied")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _fake_write_text)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 1
    assert "Could not write to" in stderr


def test_cli_completion_help_includes_completion(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    top_level = _run_help(["--help"], capsys)
    assert "completion" in top_level

    completion_help = _run_help(["completion", "--help"], capsys)
    assert "--source" in completion_help
    assert "--install" in completion_help
    assert "--yes" in completion_help
    assert "bash" in completion_help
    assert "zsh" in completion_help
    assert "fish" in completion_help


def test_cli_completion_does_not_interfere_with_normal_commands(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """argcomplete.autocomplete(parser) must be a silent no-op for normal invocations."""
    _set_xdg_home(monkeypatch, tmp_path)
    exit_code, stdout, stderr = _run_cli(["--version"], capsys)
    assert exit_code == 0
    assert "recollectium" in stdout
    assert stderr == ""


def test_cli_completion_config_key_completer_registered(
    capsys: CaptureFixture[str],
) -> None:
    config_get_help = _run_help(["config", "get", "--help"], capsys)
    assert "key" in config_get_help

    config_set_help = _run_help(["config", "set", "--help"], capsys)
    assert "key" in config_set_help

    config_unset_help = _run_help(["config", "unset", "--help"], capsys)
    assert "key" in config_unset_help


# -- workspace CLI --------------------------------------------------------


def test_workspace_list_empty_database(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace list on a fresh database returns an empty array."""
    db_path = tmp_path / "test.db"
    SQLiteMemoryStore(db_path)
    exit_code, out, err = _run_cli(
        ["--db", str(db_path), "workspace", "list"],
        capsys,
    )
    assert exit_code == 0
    assert json.loads(out) == []


def test_workspace_list_returns_sorted_uids(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace list returns distinct workspace UIDs sorted."""

    core = RecollectiumCore(
        db_path=tmp_path / "test.db",
        embedding_provider=FakeEmbeddingProvider(),
    )
    core.add_memory(
        space="workspace", type="fact", content="a", workspace_uid="project-b"
    )
    core.add_memory(
        space="workspace", type="fact", content="b", workspace_uid="project-a"
    )

    exit_code, out, err = _run_cli(
        ["--db", str(tmp_path / "test.db"), "workspace", "list"],
        capsys,
    )
    assert exit_code == 0
    assert json.loads(out) == ["project-a", "project-b"]


def test_workspace_rename_moves_memories(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace rename migrates memories and prints result."""

    core = RecollectiumCore(
        db_path=tmp_path / "test.db",
        embedding_provider=FakeEmbeddingProvider(),
    )
    core.add_memory(space="workspace", type="fact", content="a", workspace_uid="old-ws")
    core.add_memory(space="workspace", type="fact", content="b", workspace_uid="old-ws")

    exit_code, out, err = _run_cli(
        [
            "--db",
            str(tmp_path / "test.db"),
            "workspace",
            "rename",
            "old-ws",
            "new-ws",
        ],
        capsys,
    )
    assert exit_code == 0
    result = json.loads(out)
    assert result["old_uid"] == "old-ws"
    assert result["new_uid"] == "new-ws"
    assert result["memories_updated"] == 2


def test_workspace_rename_nonexistent_fails(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace rename with nonexistent old_uid returns error."""
    db_path = tmp_path / "test.db"
    SQLiteMemoryStore(db_path)

    exit_code, out, err = _run_cli(
        [
            "--db",
            str(db_path),
            "workspace",
            "rename",
            "nonexistent",
            "new",
        ],
        capsys,
    )
    assert exit_code == 1
    assert "no workspace memories found" in err.lower()


def test_workspace_rename_noop_same_uid(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace rename to same UID after normalization is a no-op."""

    core = RecollectiumCore(
        db_path=tmp_path / "test.db",
        embedding_provider=FakeEmbeddingProvider(),
    )
    core.add_memory(space="workspace", type="fact", content="a", workspace_uid="my-ws")

    # "MY-WS" normalizes to "my-ws" — same as stored
    exit_code, out, err = _run_cli(
        [
            "--db",
            str(tmp_path / "test.db"),
            "workspace",
            "rename",
            "MY-WS",
            "my-ws",
        ],
        capsys,
    )
    assert exit_code == 0
    result = json.loads(out)
    assert result["memories_updated"] == 0


def test_config_set_rejects_invalid_value(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """config set with an invalid value fails with validation error."""
    # workspace.uid_normalization only accepts 'normalize' or 'exact'
    exit_code, out, err = _run_cli(
        ["config", "set", "workspace.uid_normalization", "bogus"],
        capsys,
    )
    assert exit_code == 2
    assert "ValidationError" in err or "normalize, exact" in err


def test_workspace_rename_empty_uid_fails(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """workspace rename with whitespace-only UID returns validation error."""
    db_path = tmp_path / "test.db"
    SQLiteMemoryStore(db_path)
    exit_code, out, err = _run_cli(
        ["--db", str(db_path), "workspace", "rename", "   ", "valid"],
        capsys,
    )
    assert exit_code == 2
    assert "empty string" in err.lower() or "validation" in err.lower()


def test_workspace_alias_cli_commands_round_trip(tmp_path, capsys) -> None:
    db_path = tmp_path / "workspace-alias-cli.db"
    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "workspace",
            "--type",
            "fact",
            "--workspace-uid",
            "Canonical",
            "--content",
            "a",
        ],
        capsys,
    )
    assert exit_code == 0
    assert stderr == ""

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "workspace", "alias", "add", "Canonical", "Legacy"],
        capsys,
    )
    assert exit_code == 0
    assert json.loads(stdout)["alias"]["alias_uid"] == "legacy"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "workspace", "resolve", "Legacy"], capsys
    )
    assert exit_code == 0
    assert json.loads(stdout)["canonical_uid"] == "canonical"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "workspace", "list", "--include-aliases"], capsys
    )
    assert exit_code == 0
    assert json.loads(stdout) == [{"workspace_uid": "canonical", "aliases": ["legacy"]}]

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "workspace",
            "alias",
            "list",
            "--workspace",
            "Canonical",
        ],
        capsys,
    )
    assert exit_code == 0
    assert json.loads(stdout)[0]["alias_uid"] == "legacy"

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "workspace", "alias", "remove", "Legacy"], capsys
    )
    assert exit_code == 0
    assert json.loads(stdout)["alias_uid"] == "legacy"


def test_workspace_alias_cli_migrate_existing_conflict(tmp_path, capsys) -> None:
    db_path = tmp_path / "workspace-alias-cli-conflict.db"
    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "add",
            "--space",
            "workspace",
            "--type",
            "fact",
            "--workspace-uid",
            "Legacy",
            "--content",
            "a",
        ],
        capsys,
    )
    assert exit_code == 0

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(db_path), "workspace", "alias", "add", "Canonical", "Legacy"],
        capsys,
    )
    assert exit_code == 1
    assert "Use --migrate-existing" in stderr

    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(db_path),
            "workspace",
            "alias",
            "add",
            "Canonical",
            "Legacy",
            "--migrate-existing",
        ],
        capsys,
    )
    assert exit_code == 0
    assert json.loads(stdout)["migrated_memories"] == 1


def test_cli_update_without_memory_id_points_to_upgrade(capsys) -> None:
    exit_code, stdout, stderr = _run_cli(["update"], capsys)

    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "validation_error"
    assert "recollectium upgrade" in payload["hint"]


def test_cli_upgrade_check_prints_non_mutating_plan(capsys, monkeypatch) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(
        cli_mod,
        "RecollectiumConfig",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("--check must not create or load default config")
        ),
    )

    exit_code, stdout, stderr = _run_cli(["upgrade", "--check"], capsys)

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "dry_run"
    assert payload["install_method"] == "uv_tool"
    assert payload["latest_version"] == "9.9.9"
    assert payload["command"] == ["uv", "tool", "upgrade", "recollectium"]
    assert payload["services_to_restart"] == []


def test_cli_upgrade_applies_and_reports_service_restart_failure(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    fake_config = object()
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: fake_config)
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "check_running_service",
        lambda cfg: {"type": "api", "pid": 123, "process_start_time": 456},
    )
    monkeypatch.setattr(
        cli_mod, "apply_update", lambda *a, **kw: CommandResult(0, "done", "")
    )
    monkeypatch.setattr(cli_mod, "stop_service", lambda cfg: 123)

    def _raise_start(*args, **kwargs):
        raise ServiceError("restart failed")

    monkeypatch.setattr(cli_mod, "start_service", _raise_start)

    exit_code, stdout, stderr = _run_cli(["upgrade", "--force"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "service_error"
    assert payload["service_restart_errors"] == [
        {"type": "api", "error": "restart failed"}
    ]


def test_cli_upgrade_release_lookup_error_with_repo_uses_main_fallback(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseLookupError

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("bootstrap", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "bootstrap")

    def _raise(*args, **kwargs):
        raise ReleaseLookupError("missing", reason="no_latest_release")

    monkeypatch.setattr(cli_mod, "fetch_latest_release", _raise)

    exit_code, stdout, stderr = _run_cli(
        ["upgrade", "--check", "--repo", "owner/repo"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "dry_run"
    assert payload["latest_tag"] == "main"


def test_cli_upgrade_release_lookup_error_returns_json_stderr(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseLookupError

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")

    def _raise(*args, **kwargs):
        raise ReleaseLookupError("offline", reason="release_lookup_failed")

    monkeypatch.setattr(cli_mod, "fetch_latest_release", _raise)

    exit_code, stdout, stderr = _run_cli(["upgrade", "--check"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "network_error"
    assert payload["reason"] == "release_lookup_failed"


def test_cli_upgrade_unknown_install_method_returns_usage_error(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("unknown", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "unknown")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "unsupported_install_method"


def test_cli_upgrade_plan_network_error_returns_json_stderr(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("pip", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "pip")
    monkeypatch.setattr(cli_mod, "fetch_latest_release", lambda client, *, repo: None)

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "network_error"
    assert payload["detail"] == "no_latest_release"


def test_cli_upgrade_apply_failure_returns_command_exit(capsys, monkeypatch) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(
        cli_mod, "apply_update", lambda *a, **kw: CommandResult(126, "", "bad")
    )

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "update_failed"
    assert payload["stderr"] == "bad"


def test_cli_upgrade_success_restarts_running_service(capsys, monkeypatch) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    calls: list[str] = []
    fake_config = object()
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: fake_config)
    monkeypatch.setattr(
        cli_mod, "check_running_service", lambda cfg: {"type": "mcp", "pid": 1}
    )
    monkeypatch.setattr(
        cli_mod, "apply_update", lambda *a, **kw: CommandResult(0, "done", "")
    )
    monkeypatch.setattr(cli_mod, "stop_service", lambda cfg: calls.append("stop") or 1)
    monkeypatch.setattr(
        cli_mod, "start_service", lambda *a, **kw: calls.append("start") or 2
    )

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert calls == ["stop", "start"]
    payload = json.loads(stdout)
    assert payload["status"] == "updated"
    assert payload["services_to_restart"] == ["mcp"]


def test_cli_upgrade_ignores_config_errors_when_checking_services(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: object())

    def _raise_config(*args, **kwargs):
        raise ServiceError("pid file broken")

    monkeypatch.setattr(cli_mod, "check_running_service", _raise_config)

    exit_code, stdout, stderr = _run_cli(["upgrade", "--check"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert json.loads(stdout)["services_to_restart"] == []


def test_cli_upgrade_service_stop_failure_blocks_package_update(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    fake_config = object()
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: fake_config)
    monkeypatch.setattr(
        cli_mod, "check_running_service", lambda cfg: {"type": "api", "pid": 1}
    )

    def _raise_stop(cfg):
        raise ServiceError("stop failed")

    def _unexpected_apply(*args, **kwargs):
        raise AssertionError("package update should not run after stop failure")

    monkeypatch.setattr(cli_mod, "stop_service", _raise_stop)
    monkeypatch.setattr(cli_mod, "apply_update", _unexpected_apply)

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["service_stop_errors"] == [{"type": "api", "error": "stop failed"}]


def test_cli_upgrade_apply_failure_attempts_service_restore(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    calls: list[str] = []
    fake_config = object()
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: fake_config)
    monkeypatch.setattr(
        cli_mod, "check_running_service", lambda cfg: {"type": "api", "pid": 1}
    )
    monkeypatch.setattr(cli_mod, "stop_service", lambda cfg: calls.append("stop") or 1)
    monkeypatch.setattr(
        cli_mod, "apply_update", lambda *a, **kw: CommandResult(7, "", "bad")
    )
    monkeypatch.setattr(
        cli_mod, "start_service", lambda *a, **kw: calls.append("start") or 2
    )

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 7
    assert stdout == ""
    assert calls == ["stop", "start"]
    assert json.loads(stderr)["status"] == "update_failed"


def test_cli_upgrade_apply_failure_reports_service_restore_failure(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    fake_config = object()
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "RecollectiumConfig", lambda *a, **kw: fake_config)
    monkeypatch.setattr(
        cli_mod, "check_running_service", lambda cfg: {"type": "api", "pid": 1}
    )
    monkeypatch.setattr(cli_mod, "stop_service", lambda cfg: 1)
    monkeypatch.setattr(
        cli_mod, "apply_update", lambda *a, **kw: CommandResult(3, "", "bad")
    )

    def _raise_start(*args, **kwargs):
        raise ServiceError("restore failed")

    monkeypatch.setattr(cli_mod, "start_service", _raise_start)

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 3
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "update_failed"
    assert payload["service_restart_errors"] == [
        {"type": "api", "error": "restore failed"}
    ]


def test_workspace_resolve_validation_error(tmp_path, capsys) -> None:
    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "workspace-resolve-error.db"),
            "workspace",
            "resolve",
            "",
        ],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "workspace uid must be a non-empty string" in stderr.lower()


def test_workspace_alias_remove_not_found_error(tmp_path, capsys) -> None:
    exit_code, stdout, stderr = _run_cli(
        [
            "--db",
            str(tmp_path / "workspace-alias-missing.db"),
            "workspace",
            "alias",
            "remove",
            "missing",
        ],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert "workspace alias not found" in stderr.lower()


def test_cli_upgrade_source_without_checkout_returns_structured_failure(
    tmp_path, capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "find_source_checkout_root", lambda start: None)
    monkeypatch.setattr(
        "recollectium.update.find_source_checkout_root", lambda start: None
    )
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("source", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "source")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )

    exit_code, stdout, stderr = _run_cli(
        ["upgrade", "--install-method", "source"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "update_failed"
    assert payload["detail"] == "source_checkout_not_found"
    assert payload["returncode"] == 1


def test_cli_upgrade_apply_failure_includes_structured_error_fields(
    capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import CommandResult, InstallMetadata, ReleaseInfo

    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(cli_mod, "check_running_service", lambda cfg: None)
    monkeypatch.setattr(
        cli_mod,
        "apply_update",
        lambda *a, **kw: CommandResult(9, "", "package manager failed"),
    )

    exit_code, stdout, stderr = _run_cli(["upgrade"], capsys)

    assert exit_code == 9
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "update_failed"
    assert payload["returncode"] == 9
    assert payload["message"] == "Recollectium package upgrade failed."
    assert payload["detail"] == "package manager failed"
    assert payload["hint"]


def test_cli_upgrade_check_existing_config_error_stays_non_mutating(
    tmp_path, capsys, monkeypatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.update import InstallMetadata, ReleaseInfo

    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_setup_cli_logging", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "load_install_metadata",
        lambda: InstallMetadata("uv_tool", None, None, None),
    )
    monkeypatch.setattr(cli_mod, "detect_install_method", lambda metadata: "uv_tool")
    monkeypatch.setattr(
        cli_mod,
        "fetch_latest_release",
        lambda client, *, repo: ReleaseInfo("9.9.9", "v9.9.9", None),
    )
    monkeypatch.setattr(
        cli_mod,
        "RecollectiumConfig",
        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "upgrade", "--check"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "dry_run"
    assert payload["services_to_restart"] == []


def test_write_tty_writes_to_controlling_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import recollectium.cli as cli_mod

    writes: list[str] = []
    flushes: list[bool] = []

    class FakeTty:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def write(self, text: str) -> None:
            writes.append(text)

        def flush(self) -> None:
            flushes.append(True)

    monkeypatch.setattr(cli_mod.Path, "open", lambda *args, **kwargs: FakeTty())

    assert cli_mod._write_tty("prompt") is True
    assert writes == ["prompt"]
    assert flushes == [True]


def test_write_tty_returns_false_when_terminal_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import recollectium.cli as cli_mod

    def _raise(*args, **kwargs):
        raise OSError("no tty")

    monkeypatch.setattr(cli_mod.Path, "open", _raise)

    assert cli_mod._write_tty("prompt") is False


def test_completion_install_interactive_prompt_uses_tty_not_stderr(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod

    prompts: list[str] = []

    monkeypatch.setattr("recollectium.cli.Path.home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")
    monkeypatch.setattr(
        cli_mod, "_write_tty", lambda text: prompts.append(text) or True
    )

    exit_code, stdout, stderr = _run_cli(["completion", "--install", "bash"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "operation_failed"
    assert prompts
    assert "Will append" in prompts[0]


def test_uninstall_purge_interactive_prompt_uses_tty_not_stderr(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod

    prompts: list[str] = []

    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("recollectium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")
    monkeypatch.setattr(
        cli_mod, "_write_tty", lambda text: prompts.append(text) or True
    )

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "purge_cancelled"
    assert prompts == [
        "Type 'delete all recollectium data' to permanently delete Recollectium data: "
    ]


def test_init_migration_error_returns_structured_json(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.errors import MigrationError

    def _raise(*args, **kwargs):
        raise MigrationError("boom")

    monkeypatch.setattr(cli_mod, "SQLiteMemoryStore", _raise)

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "migration_error"
    assert payload["message"] == "Database migration failed."


def test_db_status_migration_error_returns_structured_json(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.errors import MigrationError

    def _raise(*args, **kwargs):
        raise MigrationError("status boom")

    monkeypatch.setattr(cli_mod, "SQLiteMemoryStore", _raise)

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "db-status.db"), "db-status"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "migration_error"
    assert payload["message"] == "Database migration status failed."


def test_core_migration_error_returns_structured_json(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.errors import MigrationError

    def _raise(*args, **kwargs):
        raise MigrationError("core boom")

    monkeypatch.setattr(cli_mod, "RecollectiumCore", _raise)

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "core.db"), "get", "missing"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "migration_error"
    assert payload["message"] == "Database migration failed."


def test_core_recollectium_error_returns_operation_failed_json(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import recollectium.cli as cli_mod
    from recollectium.errors import RecollectiumError

    def _raise(*args, **kwargs):
        raise RecollectiumError("domain boom")

    monkeypatch.setattr(cli_mod, "RecollectiumCore", _raise)

    exit_code, stdout, stderr = _run_cli(
        ["--db", str(tmp_path / "core-error.db"), "get", "missing"], capsys
    )

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "operation_failed"
    assert payload["detail"] == "RecollectiumError: domain boom"


def test_cli_serve_service_error_returns_structured_json(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.errors import ServiceError

    def _fake_run_service(**kwargs: object) -> None:
        raise ServiceError("serve boom")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    exit_code, stdout, stderr = _run_cli(["serve"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "service_error"
    assert payload["detail"] == "ServiceError: serve boom"


def test_cli_serve_embedding_error_returns_structured_json(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.errors import EmbeddingGenerationError

    def _fake_run_service(**kwargs: object) -> None:
        assert kwargs["cli_structured_errors"] is True
        raise EmbeddingGenerationError("model readiness failed")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    exit_code, stdout, stderr = _run_cli(["serve"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "embedding_error"
    assert payload["detail"] == "EmbeddingGenerationError: model readiness failed"


def test_cli_serve_recollectium_error_returns_structured_json(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from recollectium.errors import RecollectiumError

    def _fake_run_service(**kwargs: object) -> None:
        raise RecollectiumError("serve domain boom")

    monkeypatch.setattr("recollectium.cli.run_service", _fake_run_service)

    exit_code, stdout, stderr = _run_cli(["serve"], capsys)

    assert exit_code == 1
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["status"] == "operation_failed"
    assert payload["detail"] == "RecollectiumError: serve domain boom"
