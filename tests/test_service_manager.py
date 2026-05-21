"""Tests for service lifecycle management (PID files, process liveness, start/stop)."""

from __future__ import annotations

import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recallium.errors import ServiceConflictError, ServiceError
from recallium.service_manager import (
    _run_server,
    check_running_service,
    get_pid_file_path,
    is_pid_alive,
    read_pid_file,
    remove_pid_file,
    start_service,
    stop_service,
    write_pid_file,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mock_config(
    runtime_dir: Path, config_path: str = "/mock/config.json"
) -> MagicMock:
    config = MagicMock()
    config.xdg_dirs = {"runtime": runtime_dir}
    config.config_file_path = Path(config_path)
    return config


# ---------------------------------------------------------------------------
# get_pid_file_path
# ---------------------------------------------------------------------------


def test_get_pid_file_path(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    config = _make_mock_config(runtime)
    result = get_pid_file_path(config)
    assert result == runtime / "service.pid"


# ---------------------------------------------------------------------------
# write_pid_file + read_pid_file
# ---------------------------------------------------------------------------


def test_write_and_read_pid_file(tmp_path: Path) -> None:
    path = tmp_path / "service.pid"
    write_pid_file(path, pid=12345, service_type="api")
    data = read_pid_file(path)
    assert data == {"pid": 12345, "type": "api"}


def test_write_and_read_mcp_pid_file(tmp_path: Path) -> None:
    path = tmp_path / "service.pid"
    write_pid_file(path, pid=42, service_type="mcp")
    data = read_pid_file(path)
    assert data == {"pid": 42, "type": "mcp"}


def test_read_missing_pid_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.pid"
    assert read_pid_file(path) is None


def test_read_corrupt_pid_file_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pid"
    path.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ServiceError, match="invalid JSON"):
        read_pid_file(path)


def test_read_corrupt_pid_file_wrong_structure(tmp_path: Path) -> None:
    path = tmp_path / "bad_structure.pid"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ServiceError, match="expected JSON object"):
        read_pid_file(path)


def test_read_corrupt_pid_file_non_positive_pid_zero(tmp_path: Path) -> None:
    path = tmp_path / "bad_pid.pid"
    path.write_text(json.dumps({"pid": 0, "type": "api"}), encoding="utf-8")
    with pytest.raises(ServiceError, match="pid must be a positive integer"):
        read_pid_file(path)


def test_read_corrupt_pid_file_non_positive_pid_negative(tmp_path: Path) -> None:
    path = tmp_path / "bad_pid.pid"
    path.write_text(json.dumps({"pid": -1, "type": "api"}), encoding="utf-8")
    with pytest.raises(ServiceError, match="pid must be a positive integer"):
        read_pid_file(path)


def test_read_corrupt_pid_file_missing_pid_field(tmp_path: Path) -> None:
    path = tmp_path / "no_pid.pid"
    path.write_text(json.dumps({"type": "api"}), encoding="utf-8")
    with pytest.raises(ServiceError, match="missing or invalid 'pid'"):
        read_pid_file(path)


def test_read_corrupt_pid_file_pid_not_int(tmp_path: Path) -> None:
    path = tmp_path / "bad_pid_type.pid"
    path.write_text(
        json.dumps({"pid": "not-a-number", "type": "api"}), encoding="utf-8"
    )
    with pytest.raises(ServiceError, match="missing or invalid 'pid'"):
        read_pid_file(path)


def test_read_corrupt_pid_file_missing_type_field(tmp_path: Path) -> None:
    path = tmp_path / "no_type.pid"
    path.write_text(json.dumps({"pid": 12345}), encoding="utf-8")
    with pytest.raises(ServiceError, match="missing or invalid 'type'"):
        read_pid_file(path)


def test_read_corrupt_pid_file_invalid_type_value(tmp_path: Path) -> None:
    path = tmp_path / "bad_type.pid"
    path.write_text(json.dumps({"pid": 12345, "type": "grpc"}), encoding="utf-8")
    with pytest.raises(ServiceError, match="missing or invalid 'type'"):
        read_pid_file(path)


# ---------------------------------------------------------------------------
# remove_pid_file
# ---------------------------------------------------------------------------


def test_remove_pid_file(tmp_path: Path) -> None:
    path = tmp_path / "service.pid"
    path.write_text(json.dumps({"pid": 12345, "type": "api"}))
    remove_pid_file(path)
    assert not path.exists()


def test_remove_pid_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.pid"
    remove_pid_file(path)  # should not raise


# ---------------------------------------------------------------------------
# is_pid_alive
# ---------------------------------------------------------------------------


def test_is_pid_alive_current_process() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_nonexistent() -> None:
    assert is_pid_alive(999999) is False


def test_is_pid_alive_permission_error_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_kill(pid: int, sig: int) -> None:
        raise PermissionError("nope")

    monkeypatch.setattr(os, "kill", mock_kill)
    assert is_pid_alive(1) is True


# ---------------------------------------------------------------------------
# write_pid_file parent dir creation
# ---------------------------------------------------------------------------


def test_write_pid_file_parent_dir_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "service.pid"
    write_pid_file(path, pid=42, service_type="mcp")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"pid": 42, "type": "mcp"}


# ---------------------------------------------------------------------------
# check_running_service
# ---------------------------------------------------------------------------


def test_check_running_service_no_file(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime")
    result = check_running_service(config)
    assert result is None


def test_check_running_service_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=99999, service_type="api")

    config = _make_mock_config(runtime)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: False)

    result = check_running_service(config)
    assert result is None
    assert not pid_path.exists()


def test_check_running_service_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=12345, service_type="api")

    config = _make_mock_config(runtime)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: True)

    result = check_running_service(config)
    assert result == {"pid": 12345, "type": "api"}


def test_check_running_service_corrupt_pid_file(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    pid_path.write_text("{invalid", encoding="utf-8")

    config = _make_mock_config(runtime)
    with pytest.raises(ServiceError, match="invalid JSON"):
        check_running_service(config)


# ---------------------------------------------------------------------------
# start_service
# ---------------------------------------------------------------------------


def test_start_service_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))

    def mock_check_running(cfg: object) -> dict[str, str | int]:
        return {"pid": 42, "type": "api"}

    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", mock_check_running
    )

    with pytest.raises(ServiceConflictError, match="api service is already running"):
        start_service(config, "mcp")


def test_start_service_same_type_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))

    def mock_check_running(cfg: object) -> dict[str, str | int]:
        return {"pid": 42, "type": "api"}

    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", mock_check_running
    )

    fake_process = MagicMock()
    fake_process.pid = 12345
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: fake_process)

    write_calls: list[tuple[Path, int, str]] = []
    monkeypatch.setattr(
        "recallium.service_manager.write_pid_file",
        lambda path, pid, st: write_calls.append((path, pid, st)),
    )

    pid = start_service(config, "api")
    assert pid == 12345
    assert len(write_calls) == 1
    assert write_calls[0][1] == 12345


def test_start_service_invalid_service_type() -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    with pytest.raises(ValueError, match="service_type must be"):
        start_service(config, "grpc")


def test_start_service_no_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 5555
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: fake_process)
    monkeypatch.setattr(
        "recallium.service_manager.write_pid_file", lambda path, pid, st: None
    )

    pid = start_service(config, "mcp")
    assert pid == 5555


def test_start_service_without_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", lambda cfg: None
    )

    popen_args: list[list[str]] = []

    def fake_popen(cmd: list[str]) -> MagicMock:
        popen_args.append(cmd)
        fake = MagicMock()
        fake.pid = 7777
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "recallium.service_manager.write_pid_file", lambda p, pid, st: None
    )

    pid = start_service(config, "api")
    assert pid == 7777
    assert len(popen_args) == 1
    assert "--db-path" not in popen_args[0]
    assert "--config-path" in popen_args[0]
    assert "/mock/config.json" in popen_args[0]


def test_start_service_with_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", lambda cfg: None
    )

    popen_args: list[list[str]] = []

    def fake_popen(cmd: list[str]) -> MagicMock:
        popen_args.append(cmd)
        fake = MagicMock()
        fake.pid = 7777
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "recallium.service_manager.write_pid_file", lambda p, pid, st: None
    )

    pid = start_service(config, "api", db_path="/custom/db.sqlite")
    assert pid == 7777
    assert len(popen_args) == 1
    assert "--db-path" in popen_args[0]
    assert "/custom/db.sqlite" in popen_args[0]


# ---------------------------------------------------------------------------
# stop_service
# ---------------------------------------------------------------------------


def test_stop_service_no_service(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service", lambda cfg: None
    )

    result = stop_service(config)
    assert result is None


def test_stop_service_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: False)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recallium.service_manager.remove_pid_file",
        lambda path: remove_calls.append(path),
    )
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 42
    assert kill_calls == [(42, signal.SIGTERM)]
    assert len(remove_calls) == 1


def test_stop_service_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: True)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recallium.service_manager.remove_pid_file",
        lambda path: remove_calls.append(path),
    )

    # monotonic: 0.0 (deadline calc) → 0.0 (loop entry) → 100.0 (loop exit)
    monotonic_values = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 42
    assert kill_calls == [(42, signal.SIGTERM), (42, signal.SIGKILL)]
    assert len(remove_calls) == 1


def test_stop_service_sigterm_processlookuperror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    def mock_kill(pid: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            raise ProcessLookupError("already gone")

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: False)
    monkeypatch.setattr("recallium.service_manager.remove_pid_file", lambda path: None)
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 42


def test_stop_service_sigkill_processlookuperror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        if sig == signal.SIGKILL:
            raise ProcessLookupError("gone")

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: True)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recallium.service_manager.remove_pid_file",
        lambda path: remove_calls.append(path),
    )

    monotonic_values = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 42
    assert kill_calls == [(42, signal.SIGTERM), (42, signal.SIGKILL)]
    assert len(remove_calls) == 1


def test_stop_service_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recallium.service_manager.check_running_service",
        lambda cfg: {"pid": 7, "type": "mcp"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recallium.service_manager.is_pid_alive", lambda pid: False)

    monkeypatch.setattr("recallium.service_manager.remove_pid_file", lambda path: None)
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 7
    assert kill_calls == [(7, signal.SIGTERM)]


# ---------------------------------------------------------------------------
# _run_server
# ---------------------------------------------------------------------------


def test_run_server_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, str | None] = {}

    def fake_run_service(
        *, db_path: str | None = None, config_path: str | None = None
    ) -> None:
        calls["db_path"] = db_path
        calls["config_path"] = config_path

    monkeypatch.setattr("recallium.service.run_service", fake_run_service)
    monkeypatch.setattr(sys, "exit", lambda code: None)

    _run_server("api", db_path="/tmp/db", config_path="/tmp/config.json")
    assert calls == {"db_path": "/tmp/db", "config_path": "/tmp/config.json"}


def test_run_server_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    _run_server("mcp")
    assert exit_codes == [1]


def test_run_server_unknown_type(monkeypatch: pytest.MonkeyPatch) -> None:
    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    _run_server("grpc")
    assert exit_codes == [1]


# ---------------------------------------------------------------------------
# __main__ block
# ---------------------------------------------------------------------------
#
# runpy.run_module re-executes the module in a fresh namespace with
# __name__ == "__main__".  In that namespace, all functions (including
# _run_server) are redefined from the source.  Monkeypatching
# recallium.service_manager._run_server does NOT affect the exec'd copy.
# Instead we mock the things that the exec'd code will reach: sys.exit
# (same sys module object) and recallium.service.run_service (lazy-imported
# inside _run_server).  We always mock sys.exit to raise SystemExit so
# that the arg-parsing loop and exit paths don't get stuck.


def _fake_exit(code: object = 0) -> None:
    raise SystemExit(code)


def test_main_entry_point_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recallium.service_manager",
            "_run_server",
            "api",
            "--db-path",
            "/tmp/db",
            "--config-path",
            "/tmp/config.json",
        ],
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    run_service_calls: list[tuple[str | None, str | None]] = []

    def fake_run_service(
        *, db_path: str | None = None, config_path: str | None = None
    ) -> None:
        run_service_calls.append((db_path, config_path))

    monkeypatch.setattr("recallium.service.run_service", fake_run_service)

    runpy.run_module("recallium.service_manager", run_name="__main__")
    assert run_service_calls == [("/tmp/db", "/tmp/config.json")]


def test_main_entry_point_api_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["recallium.service_manager", "_run_server", "api"]
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    run_service_calls: list[tuple[str | None, str | None]] = []

    def fake_run_service(
        *, db_path: str | None = None, config_path: str | None = None
    ) -> None:
        run_service_calls.append((db_path, config_path))

    monkeypatch.setattr("recallium.service.run_service", fake_run_service)

    runpy.run_module("recallium.service_manager", run_name="__main__")
    assert run_service_calls == [(None, None)]


def test_main_entry_point_insufficient_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["recallium.service_manager"])
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recallium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2


def test_main_entry_point_unknown_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["recallium.service_manager", "_run_server", "api", "--bad-flag"]
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recallium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2


def test_main_entry_point_not_run_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["recallium.service_manager", "not_run_server"])
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recallium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2
