"""CLI tests for Recallium Core."""

from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest
from pytest import CaptureFixture

from recallium.config import DEFAULTS
from recallium.cli import main
from recallium.errors import (
    EmbeddingGenerationError,
    EmbeddingProviderUnavailableError,
    ValidationError,
)
from recallium.storage import SQLiteMemoryStore


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
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
    assert "Recallium Core local memory CLI" in top_level_help
    assert "add a user or workspace memory" in top_level_help
    assert "search memories for one workspace UID" in top_level_help
    assert "embedding-status" in top_level_help
    assert "embedding-jobs" in top_level_help
    assert "db-status" in top_level_help

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


def test_cli_no_args_prints_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Recallium Core local memory CLI" in captured.out
    assert captured.err == ""


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
        *, host: str, port: int, db_path: str | None, config_path: str | None
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    exit_code = main(
        [
            "--config",
            str(config_path),
            "--db",
            str(db_path),
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


def test_cli_serve_uses_default_host_and_port_without_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call: dict[str, object] = {}

    def _fake_run_service(
        *, host: str, port: int, db_path: str | None, config_path: str | None
    ) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path
        call["config_path"] = config_path

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
    assert (tmp_path / "config" / "recallium" / "config.json").exists()


def test_cli_serve_explicit_missing_config_fails_clearly(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run_service(
        *, host: str, port: int, db_path: str | None, config_path: str | None
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
        *, host: str, port: int, db_path: str | None, config_path: str | None
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
        *, host: str, port: int, db_path: str | None, config_path: str | None
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
        *, host: str, port: int, db_path: str | None, config_path: str | None
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

    class FakeParser:
        def parse_args(self, argv: object) -> FakeArgs:
            return FakeArgs()

        def error(self, message: str) -> None:
            assert message == "unknown command: mystery"

    class FakeCore:
        def __init__(self, *, db_path: object, config_path: object = None) -> None:
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

    def test_config_help_shows_actions(self, capsys) -> None:
        help_text = _run_help(["config", "--help"], capsys)
        assert "inspect, validate, and edit" in help_text.lower()
        assert "get" in help_text
        assert "set" in help_text
        assert "unset" in help_text
        assert "init" in help_text
        assert "--validate" in help_text
        assert "--path" in help_text
        assert "--defaults" in help_text
