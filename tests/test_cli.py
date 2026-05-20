"""CLI tests for Recallium Core."""

from __future__ import annotations

import json

import pytest
from pytest import CaptureFixture

from recallium.cli import main
from recallium.errors import EmbeddingProviderUnavailableError


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
    assert "--db" in serve_help
    assert "database path" in serve_help
    assert "--host" in serve_help
    assert "--port" in serve_help

    embedding_status_help = _run_help(["embedding-status", "--help"], capsys)
    assert "built-in local FastEmbed" in embedding_status_help
    assert "jinaai/jina-" in embedding_status_help
    assert "embeddings-v2-small-en" in embedding_status_help

    embedding_jobs_help = _run_help(["embedding-jobs", "--help"], capsys)
    assert "--job-id" in embedding_jobs_help
    assert "--state" in embedding_jobs_help
    assert "--limit" in embedding_jobs_help


def test_cli_serve_passes_flags_to_service_runner(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "serve.db"
    call: dict[str, object] = {}

    def _fake_run_service(*, host: str, port: int, db_path: str | None) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

    exit_code = main(
        [
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
    assert call == {
        "host": "127.0.0.2",
        "port": 9001,
        "db_path": str(db_path),
    }


def test_cli_serve_uses_default_host_and_port(monkeypatch) -> None:
    call: dict[str, object] = {}

    def _fake_run_service(*, host: str, port: int, db_path: str | None) -> None:
        call["host"] = host
        call["port"] = port
        call["db_path"] = db_path

    monkeypatch.setattr("recallium.cli.run_service", _fake_run_service)

    exit_code = main(["serve"])

    assert exit_code == 0
    assert call == {
        "host": "127.0.0.1",
        "port": 8765,
        "db_path": None,
    }


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
    assert len(state_payload) <= 1
