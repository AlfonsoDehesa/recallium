"""CLI tests for Recallium Core."""

from __future__ import annotations

import json

import pytest
from pytest import CaptureFixture

from recallium.cli import main


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
