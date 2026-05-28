"""CLI tests for Recallium Core."""

from __future__ import annotations

import io
import json
import logging
from copy import deepcopy
from importlib.metadata import PackageNotFoundError
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pytest import CaptureFixture

from recallium.config import DEFAULTS
from recallium.cli import main
from recallium.errors import (
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
    ServiceError,
    ValidationError,
)
from recallium.storage import SQLiteMemoryStore
from recallium.core import RecalliumCore


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


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    log_buf = io.StringIO()
    log_handler = logging.StreamHandler(log_buf)
    log_handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(log_handler)
    try:
        exit_code = main(args)
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err + log_buf.getvalue()
    finally:
        root.removeHandler(log_handler)


def _run_help(args: list[str], capsys: CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out


def test_cli_help_documents_commands_and_flags(capsys) -> None:
    top_level_help = _run_help(["--help"], capsys)
    assert "Recallium Core local memory CLI" in top_level_help
    assert "--version" in top_level_help
    assert "initialize Recallium config" in top_level_help
    assert "add a user or workspace memory" in top_level_help
    assert "search memories for one workspace UID" in top_level_help
    assert "embedding-status" in top_level_help
    assert "embedding-jobs" in top_level_help
    assert "db-status" in top_level_help
    assert "uninstall" in top_level_help
    assert "completion" in top_level_help

    add_help = _run_help(["add", "--help"], capsys)
    assert "User memories must not include" in add_help
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

    archive_help = _run_help(["archive", "--help"], capsys)
    assert "not hard-deleted" in archive_help

    serve_help = _run_help(["serve", "--help"], capsys)
    assert "blocking" in serve_help
    assert "local-only" in serve_help
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
    assert "--yes-delete-all-recallium-data" in uninstall_help
    assert "--dry-run" in uninstall_help

    service_discover_help = _run_help(["service", "discover", "--help"], capsys)
    assert "machine-readable connection details" in service_discover_help
    assert "without creating a config file" in service_discover_help


def test_cli_no_args_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Recallium Core local memory CLI" in captured.out
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

    monkeypatch.setattr("recallium.cli._build_parser", lambda: FakeParser())

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

    monkeypatch.setattr("recallium.cli.setup_logging", _fake_setup_logging)

    from recallium.cli import _setup_cli_logging

    _setup_cli_logging(tmp_path / "missing.json", log_level="debug")

    assert len(calls) == 2


def test_module_entrypoint_delegates_to_cli_main(monkeypatch) -> None:
    calls: list[object] = []

    def fake_main() -> int:
        calls.append(None)
        return 7

    monkeypatch.setattr("recallium.cli.main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recallium.__main__", run_name="__main__")

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
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path
        call["log_level"] = log_level

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

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
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path
        call["log_level"] = log_level

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)
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
    assert (tmp_path / "config" / "recallium" / "config.json").exists()


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
    ) -> None:
        raise AssertionError("run_service should not run with a missing config")

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)
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
    ) -> None:
        raise AssertionError("run_service should not run with invalid config")

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)
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
    ) -> None:
        raise FileNotFoundError(f"config file not found: {config_path}")

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

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
    ) -> None:
        raise ValidationError("invalid JSON in config file")

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

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

    config_path = config_home / "recallium" / "config.json"
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
    assert payload["current_version"] == 2
    assert payload["latest_version"] == 2
    assert payload["pending_versions"] == []
    assert payload["up_to_date"] is True


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
    config_path = config_home / "recallium" / "config.json"
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
    assert "metadata must be valid JSON" in stderr

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
    assert "metadata must be a JSON object" in stderr


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

    monkeypatch.setattr("recallium.cli.RecalliumCore", UnavailableCore)

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

    monkeypatch.setattr("recallium.cli.RecalliumCore", UnavailableCore)

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
    assert "recallium init" in stderr


def test_cli_readiness_timeout_error_returns_guidance(
    tmp_path, capsys, monkeypatch
) -> None:
    class TimeoutCore:
        def __init__(self, *args, **kwargs) -> None:
            raise EmbeddingReadinessTimeoutError("startup timed out")

    monkeypatch.setattr("recallium.cli.RecalliumCore", TimeoutCore)

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
    assert "recallium init" in stderr


def test_cli_update_with_content_gates_model_readiness(
    tmp_path, capsys, monkeypatch
) -> None:
    """Update --content triggers embedding readiness gate."""
    import recallium.cli as cli_mod

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

    monkeypatch.setattr(cli_mod, "RecalliumCore", TrackingCore)

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
    import recallium.cli as cli_mod

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

    monkeypatch.setattr(cli_mod, "RecalliumCore", TrackingCore)

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

    monkeypatch.setattr("recallium.cli.RecalliumCore", FailingCore)

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

    monkeypatch.setattr("recallium.cli._build_parser", lambda: FakeParser())
    monkeypatch.setattr("recallium.cli.RecalliumCore", FakeCore)

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
        from recallium.cli import _directory_writable

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
        assert exit_code == 1
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

        config_path = config_home / "recallium" / "config.json"
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

        config_path = config_home / "recallium" / "config.json"
        log_file = state_home / "recallium" / "logs" / "recallium.log"
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
        config_path = tmp_path / "recallium" / "config.json"
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

        config_path = config_home / "recallium" / "config.json"
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

        config_path = config_home / "recallium" / "config.json"
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

        config_path = config_home / "recallium" / "config.json"
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

        config_path = config_home / "recallium" / "config.json"
        assert exit_code == 0
        assert stderr == ""
        assert config_path.exists()
        assert "OK config:" in stdout
        assert "OK data:" in stdout
        assert "OK cache:" in stdout
        assert "OK logs:" in stdout
        assert "OK runtime:" in stdout
        assert "Config doctor checks passed" in stdout

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
        monkeypatch.setattr("recallium.cli._directory_writable", lambda _path: False)

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "doctor"], capsys
        )

        assert exit_code == 1
        assert "OK config:" in stdout
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
            resolved_database_path=(tmp_path / "missing-db-parent" / "recallium.db"),
        )
        monkeypatch.setattr(
            "recallium.cli._load_effective_config", lambda _path, explicit: fake_cfg
        )

        exit_code, stdout, stderr = _run_cli(["config", "doctor"], capsys)

        assert exit_code == 1
        assert "OK config:" in stdout
        assert "FAIL data directory missing:" in stderr
        assert "FAIL cache path is not a directory:" in stderr
        assert "FAIL database parent directory missing:" in stderr
        log_file = state_home / "recallium" / "logs" / "recallium.log"
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
            resolved_database_path=db_parent_file / "recallium.db",
        )
        monkeypatch.setattr(
            "recallium.cli._load_effective_config", lambda _path, explicit: fake_cfg
        )

        exit_code, stdout, stderr = _run_cli(["config", "doctor"], capsys)

        assert exit_code == 1
        assert "FAIL database parent path is not a directory:" in stderr

    # -- edit ---------------------------------------------------------------

    def test_config_edit_creates_file_and_opens_editor(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        config_path = tmp_path / "recallium" / "config.json"
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
        config_path = tmp_path / "recallium" / "config.json"

        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "config", "reset"], capsys
        )

        assert exit_code == 0
        assert stderr == ""
        assert f"Config reset to defaults: {config_path}" in stdout
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
        assert f"Config reset to defaults: {config_path}" in stdout
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
        assert str(config_path) in stdout
        assert "Config reset to defaults:" in stdout

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
    monkeypatch.setattr("recallium.cli.package_version", lambda _name: "1.2.3")

    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout == "recallium 1.2.3\n"
    assert stderr == ""


def test_cli_version_uses_source_fallback(capsys, monkeypatch) -> None:
    def _missing_package(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("recallium.cli.package_version", _missing_package)
    monkeypatch.setattr("recallium.cli.__version__", "0.1.0-dev")

    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout == "recallium 0.1.0-dev\n"
    assert stderr == ""


def test_cli_version_without_command_does_not_require_subcommand(capsys) -> None:
    exit_code, stdout, stderr = _run_cli(["--version"], capsys)

    assert exit_code == 0
    assert stdout.startswith("recallium ")
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
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _fake_ensure_ready,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    payload = json.loads(stdout)
    config_path = tmp_path / "config" / "recallium" / "config.json"
    db_path = tmp_path / "data" / "recallium" / "recallium.db"
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "initialized"
    assert payload["config"] == str(config_path)
    assert payload["database"] == str(db_path)
    assert payload["embedding_model"] == "jinaai/jina-embeddings-v2-small-en"
    assert config_path.exists()
    assert db_path.exists()
    assert (tmp_path / "cache" / "recallium").is_dir()
    assert (tmp_path / "state" / "recallium" / "logs").is_dir()
    assert ready_calls


def test_cli_init_explicit_missing_config_creates_file(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "custom" / "config.json"
    ready_calls: list[object] = []

    monkeypatch.setattr(
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
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
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
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

    monkeypatch.setattr("recallium.cli._handle_init_command", _raise_file_not_found)

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
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
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
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _raise_timeout,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingReadinessTimeoutError: startup timed out" in stderr
    assert "recallium init" in stderr


def test_cli_init_reports_model_unavailable_error(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def _raise_model_error(self) -> None:
        raise EmbeddingModelUnavailableError("model not found")

    monkeypatch.setattr(
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
        _raise_model_error,
    )

    exit_code, stdout, stderr = _run_cli(["init"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "EmbeddingModelUnavailableError: model not found" in stderr
    assert "recallium init" in stderr


def test_cli_update_without_memory_id_prints_package_update_instructions(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unexpected_core(*args, **kwargs):
        raise AssertionError("package update should not initialise RecalliumCore")

    monkeypatch.setattr("recallium.cli.RecalliumCore", _unexpected_core)

    exit_code, stdout, stderr = _run_cli(["update"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "manual_update_required"
    assert "install.sh" in payload["commands"]["bootstrap"]
    assert payload["commands"]["pip"] == "pip install --upgrade recallium"


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
    assert not (tmp_path / "config" / "recallium" / "config.json").exists()


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

    monkeypatch.setattr("recallium.cli.discover_service", _fake_discover)

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

    monkeypatch.setattr("recallium.cli.discover_service", _raise_service_error)

    exit_code, stdout, stderr = _run_cli(["service", "discover"], capsys)

    assert exit_code == 2
    assert stdout == ""
    assert "corrupted PID file" in stderr


def test_cli_uninstall_preserves_data_and_uses_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recallium" / "config.json"
    db_path = tmp_path / "data" / "recallium" / "recallium.db"
    metadata_path = tmp_path / "state" / "recallium" / "install.json"
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

    monkeypatch.setattr("recallium.cli.RecalliumCore", lambda *args, **kwargs: None)
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["status"] == "manual_uninstall_required"
    assert payload["data"]["preserved"] is True
    assert payload["data"]["paths"]["database"] == str(db_path)
    assert payload["package"]["install_method"] == "bootstrap"
    assert payload["package"]["source_ref"] == "main"
    assert payload["package"]["recommended"] == "uv tool uninstall recallium"
    assert payload["package"]["managed_path_edits"] == ["profile path edit"]
    assert config_path.exists()
    assert db_path.read_text(encoding="utf-8") == "preserved"


def test_cli_uninstall_removes_managed_completion_block(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(
        "before\n"
        "# >>> recallium completion >>>\n"
        'eval "$(recallium completion --source bash)"\n'
        "# <<< recallium completion <<<\n"
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
        "# >>> recallium completion >>>\n"
        'eval "$(recallium completion --source bash)"\n'
        "# <<< recallium completion <<<\n"
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
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)
    metadata_path = tmp_path / "state" / "recallium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    custom_rc = tmp_path / "custom" / "recallium-shell-setup"
    custom_rc.parent.mkdir()
    custom_rc.write_text(
        "# >>> recallium completion >>>\n"
        'eval "$(recallium completion --source bash)"\n'
        "# <<< recallium completion <<<\n",
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "managed_path_edits": [
                    f'{custom_rc}: eval "$(recallium completion --source bash)"'
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


def test_cli_uninstall_completion_cleanup_skips_duplicate_metadata_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recallium.cli import _remove_completion_blocks

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("", encoding="utf-8")

    payload = _remove_completion_blocks(
        {
            "managed_path_edits": [
                123,
                f'{bashrc}: eval "$(recallium completion --source bash)"',
            ]
        },
        dry_run=True,
    )

    paths = [item["path"] for item in payload["targets"]]
    assert paths.count(str(bashrc)) == 1


def test_cli_uninstall_completion_cleanup_reports_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recallium.cli import _remove_completion_blocks

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
    from recallium.cli import _remove_completion_blocks

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(
        "# >>> recallium completion >>>\n"
        'eval "$(recallium completion --source bash)"\n'
        "# <<< recallium completion <<<\n",
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

    monkeypatch.setattr("recallium.cli.stop_service", _fake_stop)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["service"] == {"status": "stopped", "pid": 123}
    assert stopped_configs


def test_cli_uninstall_rejects_destructive_yes_without_purge(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--yes-delete-all-recallium-data"], capsys
    )

    assert exit_code == 2
    assert stdout == ""
    assert "requires --purge" in stderr


def test_cli_uninstall_reports_explicit_missing_config(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

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
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

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

    monkeypatch.setattr("recallium.cli.stop_service", _raise_service_error)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "service stop failed" in stderr


def test_cli_uninstall_ignores_unreadable_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    metadata_path = tmp_path / "state" / "recallium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "unknown"


def test_cli_uninstall_ignores_non_object_install_metadata(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    metadata_path = tmp_path / "state" / "recallium" / "install.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(["bootstrap"]), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert stderr == ""
    assert payload["package"]["install_method"] == "unknown"


def test_cli_uninstall_purge_dry_run_lists_targets_without_deleting(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recallium" / "config.json"
    data_dir = tmp_path / "data" / "recallium"
    cache_dir = tmp_path / "cache" / "recallium"
    logs_dir = tmp_path / "state" / "recallium" / "logs"
    runtime_dir = tmp_path / "runtime" / "recallium"
    for directory in (config_path.parent, data_dir, cache_dir, logs_dir, runtime_dir):
        directory.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    (data_dir / "recallium.db").write_text("memory", encoding="utf-8")

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
    assert (data_dir / "recallium.db").exists()


def test_cli_uninstall_purge_cancelled_by_confirmation(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge"], capsys)

    assert exit_code == 1
    assert stdout == ""
    assert "purge cancelled" in stderr


def test_cli_uninstall_purge_accepts_interactive_confirmation(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recallium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr("sys.stdin.readline", lambda: "delete all recallium data\n")

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge"], capsys)

    payload = json.loads(stdout)
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert str(config_path) in stderr
    assert payload["data"]["purge"]["deleted"]


def test_cli_uninstall_purge_deletes_recallium_owned_paths(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "recallium" / "config.json"
    data_dir = tmp_path / "data" / "recallium"
    cache_dir = tmp_path / "cache" / "recallium"
    logs_dir = tmp_path / "state" / "recallium" / "logs"
    runtime_dir = tmp_path / "runtime" / "recallium"
    metadata_path = tmp_path / "state" / "recallium" / "install.json"
    for directory in (config_path.parent, data_dir, cache_dir, logs_dir, runtime_dir):
        directory.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    (data_dir / "recallium.db").write_text("memory", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recallium-data"], capsys
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
    config_path = tmp_path / "config" / "recallium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    def _raise_remove(_path: Path) -> None:
        raise OSError("delete failed")

    monkeypatch.setattr("recallium.cli.shutil.rmtree", _raise_remove)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recallium-data"], capsys
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
    config_path = tmp_path / "config" / "recallium" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_data = deepcopy(DEFAULTS)
    config_data["directories"] = {"cache": str(shared_cache)}
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        ["uninstall", "--purge", "--yes-delete-all-recallium-data"], capsys
    )

    payload = json.loads(stdout)
    skipped = payload["data"]["purge"]["skipped"]
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert shared_cache.exists()
    assert any(
        item["path"] == str(shared_cache) and item["reason"] == "not_recallium_owned"
        for item in skipped
    )


def test_cli_uninstall_purge_skips_explicit_config_outside_recallium_dir(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(
        [
            "--config",
            str(config_path),
            "uninstall",
            "--purge",
            "--yes-delete-all-recallium-data",
        ],
        capsys,
    )

    payload = json.loads(stdout)
    assert exit_code == 0
    assert "permanently deleted" in stderr
    assert config_path.exists()
    assert any(
        item["path"] == str(config_path) and item["reason"] == "not_recallium_owned"
        for item in payload["data"]["purge"]["skipped"]
    )


def test_cli_uninstall_purge_skips_duplicate_targets(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_xdg_home(monkeypatch, tmp_path)
    duplicate_dir = tmp_path / "data" / "recallium"
    config_path = tmp_path / "config" / "recallium" / "config.json"
    duplicate_dir.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    config_data = deepcopy(DEFAULTS)
    config_data["directories"] = {
        "data": str(duplicate_dir),
        "cache": str(duplicate_dir),
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)

    exit_code, stdout, stderr = _run_cli(["uninstall", "--purge", "--dry-run"], capsys)

    payload = json.loads(stdout)
    paths = [item["path"] for item in payload["data"]["purge"]["targets"]]
    assert exit_code == 0
    assert stderr == ""
    assert paths.count(str(duplicate_dir)) == 1


def test_cli_uninstall_purge_marks_suspicious_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recallium.cli import _delete_purge_target

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
    monkeypatch.setattr("recallium.cli.stop_service", lambda _config: None)
    monkeypatch.setattr(
        "recallium.cli.BuiltinFastEmbedProvider.ensure_ready",
        lambda self: None,
    )

    assert _run_cli(["init"], capsys)[0] == 0
    config_path = tmp_path / "config" / "recallium" / "config.json"
    db_path = tmp_path / "data" / "recallium" / "recallium.db"
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
    config_path = tmp_path / "config" / "recallium" / "config.json"
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

    monkeypatch.setattr("recallium.cli.stop_service", _record_stop)

    _run_cli(["uninstall", "--dry-run"], capsys)
    assert stop_calls == []

    _run_cli(["uninstall", "--purge", "--dry-run"], capsys)
    assert stop_calls == []


def test_cli_uninstall_config_is_recallium_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recallium.cli import _UninstallConfig
    from recallium.config import RecalliumConfig

    conf = _UninstallConfig(
        effective_config={},
        xdg_dirs={},
        config_path=tmp_path / "cfg.json",
        database_path=tmp_path / "db.db",
    )
    assert isinstance(conf, RecalliumConfig)


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

        with patch("recallium.cli.RecalliumCore") as mock_core:
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

        with patch("recallium.cli.RecalliumCore") as mock_core:
            mock_core.side_effect = ValidationError("bad config value")
            exit_code, stdout, stderr = _run_cli(
                ["--config", str(config_path), "mcp-stdio"],
                capsys,
            )

        assert exit_code == 2
        assert stdout == ""
        assert "ValidationError: bad config value" in stderr

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
            patch("recallium.cli.RecalliumCore"),
            patch("recallium.cli.create_mcp_server", return_value=FakeMCP()),
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
            patch("recallium.cli.RecalliumCore"),
            patch("recallium.cli.create_mcp_server", return_value=FakeMCP()),
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
    assert 'eval "$(recallium completion --source bash)"' in stdout
    assert "recallium completion --install bash" in stdout


def test_cli_completion_default_prints_human_readable_instructions(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "zsh"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Add this line to your shell rc file" in stdout
    assert 'eval "$(recallium completion --source zsh)"' in stdout
    assert "recallium completion --install zsh" in stdout


def test_cli_completion_default_prints_human_readable_instructions_fish(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "fish"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "Add this line to your shell rc file" in stdout
    assert 'eval "$(recallium completion --source fish)"' in stdout
    assert "recallium completion --install fish" in stdout


def test_cli_completion_source_bash_prints_shellcode(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code, stdout, stderr = _run_cli(["completion", "--source", "bash"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "register-python-argcomplete" in stdout or "complete " in stdout
    assert "recallium" in stdout


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


def test_cli_completion_auto_detect_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")

    exit_code, stdout, stderr = _run_cli(["completion", "--source"], capsys)

    assert exit_code == 0
    assert stderr == ""
    assert "recallium" in stdout


def test_cli_completion_unknown_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHELL", raising=False)

    exit_code, stdout, stderr = _run_cli(["completion"], capsys)

    assert exit_code == 2
    assert stderr != ""
    assert "Could not detect shell" in stderr


def test_cli_completion_auto_detect_non_standard_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/tcsh")

    exit_code, stdout, stderr = _run_cli(["completion"], capsys)

    assert exit_code == 2
    assert "Could not detect shell" in stderr


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
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["rc_file"] == str(rc_path)
    content = rc_path.read_text(encoding="utf-8")
    assert "# >>> recallium completion >>>" in content
    assert 'eval "$(recallium completion --source bash)"' in content
    assert "# <<< recallium completion <<<" in content


def test_cli_completion_install_dedup_when_already_present(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    rc_path.write_text(
        'eval "$(recallium completion --source bash)"\n', encoding="utf-8"
    )
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)

    exit_code, stdout, stderr = _run_cli(
        ["completion", "--install", "bash", "--yes"], capsys
    )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "already_installed"
    occurrences = rc_path.read_text(encoding="utf-8").count(
        "recallium completion --source"
    )
    assert occurrences == 1


def test_cli_completion_install_unknown_shell(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("recallium.cli._COMPLETION_RC_FILES", {"bash": ".bashrc"})
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
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin.readline", lambda: "no\n")

    exit_code, stdout, stderr = _run_cli(["completion", "--install", "bash"], capsys)

    assert exit_code == 1
    assert "Cancelled" in stderr or "cancelled" in stderr


def test_cli_completion_install_accepts_confirm(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc_path = tmp_path / ".bashrc"
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)
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
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)

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
    monkeypatch.setattr("recallium.cli.Path.home", lambda: tmp_path)

    original_open = Path.open

    def _fake_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == rc_path and args == ("a",):
            raise OSError("Permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _fake_open)

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
    assert "recallium" in stdout
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

    core = RecalliumCore(
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

    core = RecalliumCore(
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

    core = RecalliumCore(
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
    assert exit_code == 1
    assert "empty string" in err.lower() or "validation" in err.lower()
