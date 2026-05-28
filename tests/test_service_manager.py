"""Tests for service lifecycle management (PID files, process liveness, start/stop)."""

from __future__ import annotations

import io
import json
import logging
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest import CaptureFixture, LogCaptureFixture

from recollectium.errors import ServiceConflictError, ServiceError
from recollectium.service_manager import (
    _run_server,
    check_running_service,
    discover_service,
    get_discovery_file_path,
    get_process_cmdline,
    get_process_start_time,
    get_pid_file_path,
    is_pid_alive,
    is_recollectium_service_process,
    read_pid_file,
    remove_discovery_file,
    remove_pid_file,
    service_discovery_payload,
    start_service,
    stop_service,
    write_discovery_file,
    write_pid_file,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mock_config(
    runtime_dir: Path, config_path: str = "/mock/config.json"
) -> MagicMock:
    config = MagicMock()
    config.xdg_dirs = {"runtime": runtime_dir, "logs": runtime_dir / "logs"}
    config.config_file_path = Path(config_path)
    config.effective_config = {"service": {"host": "127.0.0.9", "port": 9876}}
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
    write_pid_file(path, pid=12345, service_type="api", process_start_time=777)
    data = read_pid_file(path)
    assert data == {"pid": 12345, "type": "api", "process_start_time": 777}


def test_write_and_read_mcp_pid_file(tmp_path: Path) -> None:
    path = tmp_path / "service.pid"
    write_pid_file(path, pid=42, service_type="mcp", process_start_time=888)
    data = read_pid_file(path)
    assert data == {"pid": 42, "type": "mcp", "process_start_time": 888}


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


def test_read_corrupt_pid_file_invalid_process_start_time(tmp_path: Path) -> None:
    path = tmp_path / "bad_start_time.pid"
    path.write_text(
        json.dumps({"pid": 12345, "type": "api", "process_start_time": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(ServiceError, match="process_start_time"):
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


def test_get_discovery_file_path(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime")

    assert (
        get_discovery_file_path(config)
        == tmp_path / "runtime" / "service-discovery.json"
    )


def test_remove_discovery_file(tmp_path: Path) -> None:
    path = tmp_path / "service-discovery.json"
    path.write_text("{}", encoding="utf-8")

    remove_discovery_file(path)

    assert not path.exists()


def test_remove_discovery_file_missing(tmp_path: Path) -> None:
    remove_discovery_file(tmp_path / "missing.json")


def test_service_discovery_payload_not_running(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime", config_path="/tmp/config.json")

    payload = service_discovery_payload(config, None)

    assert payload["status"] == "not_running"
    assert payload["service"] is None
    assert payload["paths"] == {
        "config": "/tmp/config.json",
        "runtime_dir": str(tmp_path / "runtime"),
        "pid_file": str(tmp_path / "runtime" / "service.pid"),
        "discovery_file": str(tmp_path / "runtime" / "service-discovery.json"),
    }
    assert payload["versions"]["service_api_version"] == "1"
    assert "service start api" in payload["next_step"]


def test_service_discovery_payload_running_api(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime")

    payload = service_discovery_payload(
        config,
        {"pid": 12345, "type": "api", "process_start_time": 77},
    )

    assert payload["status"] == "running"
    assert payload["service"] == {
        "type": "api",
        "pid": 12345,
        "process_start_time": 77,
        "endpoint": "http://127.0.0.9:9876",
        "api_prefix": "/v1",
        "health_url": "http://127.0.0.9:9876/v1/health",
        "version_url": "http://127.0.0.9:9876/v1/version",
        "capabilities_url": "http://127.0.0.9:9876/v1/capabilities",
    }


def test_write_discovery_file_atomically(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime")

    write_discovery_file(
        config,
        {"pid": 12345, "type": "mcp", "process_start_time": 77},
    )

    discovery_path = tmp_path / "runtime" / "service-discovery.json"
    payload = json.loads(discovery_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["service"]["type"] == "mcp"
    assert not (tmp_path / "runtime" / ".service-discovery.json.tmp").exists()


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


def test_get_process_start_time_current_process() -> None:
    assert get_process_start_time(os.getpid()) is not None


def test_get_process_start_time_missing_process() -> None:
    assert get_process_start_time(999999) is None


def test_get_process_start_time_malformed_stat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda self, encoding=None: "bad stat")
    assert get_process_start_time(123) is None


def test_get_process_cmdline_current_process() -> None:
    cmdline = get_process_cmdline(os.getpid())
    assert cmdline is not None
    assert len(cmdline) > 0


def test_get_process_cmdline_missing_process() -> None:
    assert get_process_cmdline(999999) is None


def test_is_recollectium_service_process_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_cmdline",
        lambda pid: [
            sys.executable,
            "-m",
            "recollectium.service_manager",
            "_run_server",
            "api",
        ],
    )
    assert is_recollectium_service_process(123, "api", 5) is True


def test_is_recollectium_service_process_missing_start_time() -> None:
    assert is_recollectium_service_process(123, "api", None) is False


def test_is_recollectium_service_process_start_time_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 6
    )
    assert is_recollectium_service_process(123, "api", 5) is False


def test_is_recollectium_service_process_wrong_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_cmdline", lambda pid: ["sleep", "60"]
    )
    assert is_recollectium_service_process(123, "api", 5) is False


def test_is_recollectium_service_process_missing_cmdline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_cmdline", lambda pid: None
    )
    assert is_recollectium_service_process(123, "api", 5) is False


# ---------------------------------------------------------------------------
# write_pid_file parent dir creation
# ---------------------------------------------------------------------------


def test_write_pid_file_parent_dir_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "service.pid"
    write_pid_file(path, pid=42, service_type="mcp", process_start_time=999)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"pid": 42, "type": "mcp", "process_start_time": 999}


# ---------------------------------------------------------------------------
# check_running_service
# ---------------------------------------------------------------------------


def test_check_running_service_no_file(tmp_path: Path) -> None:
    config = _make_mock_config(tmp_path / "runtime")
    result = check_running_service(config)
    assert result is None


def test_check_running_service_no_pid_removes_stale_discovery_file(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    discovery_path = runtime / "service-discovery.json"
    discovery_path.write_text("{}", encoding="utf-8")
    config = _make_mock_config(runtime)

    result = check_running_service(config)

    assert result is None
    assert not discovery_path.exists()


def test_check_running_service_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=99999, service_type="api", process_start_time=5)

    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: False)
    caplog.set_level(logging.ERROR, logger="recollectium.service_manager")

    result = check_running_service(config)
    assert result is None
    assert not pid_path.exists()
    crashed_records = [
        record
        for record in caplog.records
        if record.__dict__.get("event") == "service.crashed"
    ]
    assert len(crashed_records) == 1
    assert crashed_records[0].__dict__["context"] == {
        "pid": 99999,
        "type": "api",
        "exit_code": None,
        "reason": "process_not_running",
    }


def test_check_running_service_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=12345, service_type="api", process_start_time=5)

    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.is_recollectium_service_process",
        lambda pid, service_type, process_start_time: True,
    )

    result = check_running_service(config)
    assert result == {"pid": 12345, "type": "api", "process_start_time": 5}


def test_discover_service_running_writes_discovery_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=12345, service_type="api", process_start_time=5)
    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.is_recollectium_service_process",
        lambda pid, service_type, process_start_time: True,
    )

    payload = discover_service(config)

    discovery_path = runtime / "service-discovery.json"
    file_payload = json.loads(discovery_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload == file_payload


def test_discover_service_not_running_reports_stale_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    write_pid_file(
        runtime / "service.pid", pid=12345, service_type="api", process_start_time=5
    )
    (runtime / "service-discovery.json").write_text("{}", encoding="utf-8")
    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: False)

    payload = discover_service(config)

    assert payload["status"] == "not_running"
    assert payload["stale"] == {
        "pid_file_removed": True,
        "discovery_file_removed": True,
    }
    assert not (runtime / "service.pid").exists()
    assert not (runtime / "service-discovery.json").exists()


def test_discover_service_removes_discovery_file_without_pid(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "service-discovery.json").write_text("{}", encoding="utf-8")
    config = _make_mock_config(runtime)

    payload = discover_service(config)

    assert payload["status"] == "not_running"
    assert payload["stale"] == {
        "pid_file_removed": False,
        "discovery_file_removed": True,
    }
    assert not (runtime / "service-discovery.json").exists()


def test_discover_service_uses_custom_host_port_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "custom-runtime"
    runtime.mkdir()
    write_pid_file(
        runtime / "service.pid", pid=12345, service_type="mcp", process_start_time=5
    )
    config = _make_mock_config(runtime)
    config.effective_config = {"service": {"host": "127.0.0.7", "port": 9010}}
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.is_recollectium_service_process",
        lambda pid, service_type, process_start_time: True,
    )

    payload = discover_service(config)

    assert payload["service"]["type"] == "mcp"
    assert payload["service"]["endpoint"] == "http://127.0.0.7:9010"
    assert payload["paths"]["runtime_dir"] == str(runtime)


def test_discover_service_wraps_discovery_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    write_pid_file(
        runtime / "service.pid", pid=12345, service_type="api", process_start_time=5
    )
    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.is_recollectium_service_process",
        lambda pid, service_type, process_start_time: True,
    )

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(
        "recollectium.service_manager.write_discovery_file", raise_os_error
    )

    with pytest.raises(ServiceError, match="could not write discovery file"):
        discover_service(config)
    assert (runtime / "service.pid").exists()


def test_check_running_service_wrong_process_removes_pid_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_path = runtime / "service.pid"
    write_pid_file(pid_path, pid=12345, service_type="api", process_start_time=5)

    config = _make_mock_config(runtime)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.is_recollectium_service_process",
        lambda pid, service_type, process_start_time: False,
    )
    caplog.set_level(logging.ERROR, logger="recollectium.service_manager")

    result = check_running_service(config)
    assert result is None
    assert not pid_path.exists()
    crashed_records = [
        record
        for record in caplog.records
        if record.__dict__.get("event") == "service.crashed"
    ]
    assert len(crashed_records) == 1
    assert crashed_records[0].__dict__["context"] == {
        "pid": 12345,
        "type": "api",
        "exit_code": None,
        "reason": "process_mismatch",
    }


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
        "recollectium.service_manager.check_running_service", mock_check_running
    )

    with pytest.raises(ServiceConflictError, match="api service is already running"):
        start_service(config, "mcp")


def test_start_service_same_type_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))

    def mock_check_running(cfg: object) -> dict[str, str | int]:
        return {"pid": 42, "type": "api"}

    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", mock_check_running
    )

    popen_calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: popen_calls.append(cmd))

    with pytest.raises(ServiceConflictError, match="api service is already running"):
        start_service(config, "api")

    assert popen_calls == []


def test_start_service_invalid_service_type() -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    with pytest.raises(ValueError, match="service_type must be"):
        start_service(config, "grpc")


def test_start_service_child_dies_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """start_service must clean up and raise ServiceError if the child exits immediately."""
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9999
    fake_process.poll.return_value = 1
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )

    monkeypatch.setattr(
        "recollectium.service_manager.write_pid_file", lambda path, pid, st, pst: None
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file", lambda path: None
    )

    with pytest.raises(ServiceError, match="exited immediately after start"):
        start_service(config, "api")


def test_start_service_process_ownership_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9999
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: None
    )

    with pytest.raises(
        ServiceError, match="could not verify service process ownership"
    ):
        start_service(config, "api")
    fake_process.terminate.assert_called_once_with()


def test_start_service_cleans_pid_file_when_discovery_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = _make_mock_config(runtime)
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9999
    fake_process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(
        "recollectium.service_manager.write_discovery_file", raise_os_error
    )

    with pytest.raises(ServiceError, match="could not write discovery file"):
        start_service(config, "api")

    fake_process.terminate.assert_called_once_with()
    assert not (runtime / "service.pid").exists()


def test_start_service_ignores_missing_process_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = _make_mock_config(runtime)
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9998
    fake_process.poll.return_value = None
    fake_process.terminate.side_effect = ProcessLookupError("gone")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(
        "recollectium.service_manager.write_discovery_file", raise_os_error
    )

    with pytest.raises(ServiceError, match="could not write discovery file"):
        start_service(config, "api")

    assert not (runtime / "service.pid").exists()


def test_start_service_escalates_to_kill_when_terminate_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = _make_mock_config(runtime)
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9997
    fake_process.poll.return_value = None
    fake_process.wait.side_effect = [
        subprocess.TimeoutExpired("wait", 5),
        subprocess.TimeoutExpired("wait", 5),
    ]
    fake_process.kill.side_effect = ProcessLookupError("gone")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(
        "recollectium.service_manager.write_discovery_file", raise_os_error
    )

    with pytest.raises(ServiceError, match="could not write discovery file"):
        start_service(config, "api")

    fake_process.terminate.assert_called_once_with()
    fake_process.kill.assert_called_once_with()
    assert not (runtime / "service.pid").exists()


def test_start_service_ignores_second_wait_timeout_after_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = _make_mock_config(runtime)
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 9996
    fake_process.poll.return_value = None
    fake_process.wait.side_effect = [
        subprocess.TimeoutExpired("wait", 5),
        subprocess.TimeoutExpired("wait", 5),
    ]
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(
        "recollectium.service_manager.write_discovery_file", raise_os_error
    )

    with pytest.raises(ServiceError, match="could not write discovery file"):
        start_service(config, "api")

    fake_process.terminate.assert_called_once_with()
    fake_process.kill.assert_called_once_with()
    assert not (runtime / "service.pid").exists()


def test_start_service_no_conflict(
    monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    fake_process = MagicMock()
    fake_process.pid = 5555
    fake_process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.write_pid_file", lambda path, pid, st, pst: None
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    pid = start_service(config, "mcp")
    assert pid == 5555
    captured = capsys.readouterr()
    assert captured.out == ""


def test_start_service_without_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    popen_args: list[list[str]] = []

    def fake_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        popen_args.append(cmd)
        popen_kwargs.append(kwargs)
        fake = MagicMock()
        fake.pid = 7777
        fake.poll.return_value = None
        return fake

    popen_kwargs: list[dict[str, object]] = []
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.write_pid_file", lambda p, pid, st, pst: None
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    pid = start_service(config, "api")
    assert pid == 7777
    assert len(popen_args) == 1
    assert "--db-path" not in popen_args[0]
    assert "--config-path" in popen_args[0]
    assert "/mock/config.json" in popen_args[0]
    assert "--host" in popen_args[0]
    assert "127.0.0.9" in popen_args[0]
    assert "--port" in popen_args[0]
    assert "9876" in popen_args[0]
    assert popen_kwargs[0]["stdin"] == subprocess.DEVNULL
    assert popen_kwargs[0]["stderr"] == subprocess.STDOUT
    assert popen_kwargs[0]["close_fds"] is True
    assert popen_kwargs[0]["start_new_session"] is True
    assert popen_kwargs[0]["stdout"] is not None


def test_start_service_with_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    popen_args: list[list[str]] = []

    def fake_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        popen_args.append(cmd)
        fake = MagicMock()
        fake.pid = 7777
        fake.poll.return_value = None
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.write_pid_file", lambda p, pid, st, pst: None
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    pid = start_service(config, "api", db_path="/custom/db.sqlite")
    assert pid == 7777
    assert len(popen_args) == 1
    assert "--db-path" in popen_args[0]
    assert "/custom/db.sqlite" in popen_args[0]


def test_start_service_with_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    popen_args: list[list[str]] = []

    def fake_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        popen_args.append(cmd)
        fake = MagicMock()
        fake.pid = 7777
        fake.poll.return_value = None
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "recollectium.service_manager.get_process_start_time", lambda pid: 5
    )
    monkeypatch.setattr(
        "recollectium.service_manager.write_pid_file", lambda p, pid, st, pst: None
    )
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    pid = start_service(config, "api", log_level="debug")

    assert pid == 7777
    assert "--log-level" in popen_args[0]
    assert "debug" in popen_args[0]


# ---------------------------------------------------------------------------
# stop_service
# ---------------------------------------------------------------------------


def test_stop_service_no_service(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service", lambda cfg: None
    )

    result = stop_service(config)
    assert result is None


def test_stop_service_graceful(
    monkeypatch: pytest.MonkeyPatch,
    capsys: CaptureFixture[str],
    caplog: LogCaptureFixture,
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: False)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file",
        lambda path: remove_calls.append(path),
    )
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    log_buf = io.StringIO()
    log_handler = logging.StreamHandler(log_buf)
    log_handler.setLevel(logging.INFO)
    root = logging.getLogger()
    root.addHandler(log_handler)
    caplog.set_level(logging.INFO, logger="recollectium.service_manager")
    try:
        result = stop_service(config)
        assert result == 42
        assert kill_calls == [(42, signal.SIGTERM)]
        assert len(remove_calls) == 1
        captured = capsys.readouterr()
        combined = captured.err + log_buf.getvalue()
        assert captured.out == ""
        assert "Stopping service" in combined
        assert "stopped gracefully" in combined
        assert any(
            record.__dict__.get("event") == "service.shutdown"
            for record in caplog.records
        )
    finally:
        root.removeHandler(log_handler)


def test_stop_service_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file",
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
        "recollectium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    def mock_kill(pid: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            raise ProcessLookupError("already gone")

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: False)
    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file", lambda path: None
    )
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 42


def test_stop_service_sigkill_processlookuperror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_mock_config(Path("/tmp/runtime"))
    monkeypatch.setattr(
        "recollectium.service_manager.check_running_service",
        lambda cfg: {"pid": 42, "type": "api"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        if sig == signal.SIGKILL:
            raise ProcessLookupError("gone")

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: True)

    remove_calls: list[Path] = []
    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file",
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
        "recollectium.service_manager.check_running_service",
        lambda cfg: {"pid": 7, "type": "mcp"},
    )

    kill_calls: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr(os, "kill", mock_kill)
    monkeypatch.setattr("recollectium.service_manager.is_pid_alive", lambda pid: False)

    monkeypatch.setattr(
        "recollectium.service_manager.remove_pid_file", lambda path: None
    )
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = stop_service(config)
    assert result == 7
    assert kill_calls == [(7, signal.SIGTERM)]


# ---------------------------------------------------------------------------
# _run_server
# ---------------------------------------------------------------------------


def test_run_server_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, str | int | None] = {}

    def fake_run_service(
        *,
        db_path: str | None = None,
        config_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        log_level: str | None = None,
    ) -> None:
        calls["db_path"] = db_path
        calls["config_path"] = config_path
        calls["host"] = host
        calls["port"] = port
        calls["log_level"] = log_level

    monkeypatch.setattr("recollectium.service.run_service", fake_run_service)
    monkeypatch.setattr(sys, "exit", lambda code: None)

    _run_server(
        "api",
        db_path="/tmp/db",
        config_path="/tmp/config.json",
        host="127.0.0.9",
        port=9876,
    )
    assert calls == {
        "db_path": "/tmp/db",
        "config_path": "/tmp/config.json",
        "host": "127.0.0.9",
        "port": 9876,
        "log_level": None,
    }


def test_run_server_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, str | int | None] = {}

    def fake_run_service(
        *,
        db_path: str | None = None,
        config_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        service_type: str | None = None,
        log_level: str | None = None,
    ) -> None:
        calls["db_path"] = db_path
        calls["config_path"] = config_path
        calls["host"] = host
        calls["port"] = port
        calls["service_type"] = service_type

    monkeypatch.setattr("recollectium.service.run_service", fake_run_service)
    monkeypatch.setattr(sys, "exit", lambda code: None)

    _run_server(
        "mcp",
        db_path="/tmp/db",
        config_path="/tmp/cfg.json",
        host="127.0.0.9",
        port=9876,
    )
    assert calls == {
        "db_path": "/tmp/db",
        "config_path": "/tmp/cfg.json",
        "host": "127.0.0.9",
        "port": 9876,
        "service_type": "mcp",
    }


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
# recollectium.service_manager._run_server does NOT affect the exec'd copy.
# Instead we mock the things that the exec'd code will reach: sys.exit
# (same sys module object) and recollectium.service.run_service (lazy-imported
# inside _run_server).  We always mock sys.exit to raise SystemExit so
# that the arg-parsing loop and exit paths don't get stuck.


def _fake_exit(code: object = 0) -> None:
    raise SystemExit(code)


def test_main_entry_point_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recollectium.service_manager",
            "_run_server",
            "api",
            "--db-path",
            "/tmp/db",
            "--config-path",
            "/tmp/config.json",
            "--host",
            "127.0.0.9",
            "--port",
            "9876",
        ],
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    run_service_calls: list[tuple[str | None, str | None, str | None, int | None]] = []

    def fake_run_service(
        *,
        db_path: str | None = None,
        config_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        log_level: str | None = None,
    ) -> None:
        run_service_calls.append((db_path, config_path, host, port))

    monkeypatch.setattr("recollectium.service.run_service", fake_run_service)

    runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert run_service_calls == [("/tmp/db", "/tmp/config.json", "127.0.0.9", 9876)]


def test_main_entry_point_api_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["recollectium.service_manager", "_run_server", "api"]
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    run_service_calls: list[tuple[str | None, str | None]] = []

    def fake_run_service(
        *,
        db_path: str | None = None,
        config_path: str | None = None,
        log_level: str | None = None,
    ) -> None:
        run_service_calls.append((db_path, config_path))

    monkeypatch.setattr("recollectium.service.run_service", fake_run_service)

    runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert run_service_calls == [(None, None)]


def test_main_entry_point_insufficient_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["recollectium.service_manager"])
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2


def test_main_entry_point_unknown_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["recollectium.service_manager", "_run_server", "api", "--bad-flag"],
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2


def test_main_entry_point_invalid_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["recollectium.service_manager", "_run_server", "api", "--port", "bad"],
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2


def test_main_entry_point_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["recollectium.service_manager", "_run_server", "api", "--log-level", "debug"],
    )
    monkeypatch.setattr(sys, "exit", _fake_exit)

    run_service_calls: list[str | None] = []

    def fake_run_service(
        *,
        db_path: str | None = None,
        config_path: str | None = None,
        log_level: str | None = None,
    ) -> None:
        run_service_calls.append(log_level)

    monkeypatch.setattr("recollectium.service.run_service", fake_run_service)

    runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert run_service_calls == ["debug"]


def test_main_entry_point_not_run_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["recollectium.service_manager", "not_run_server"])
    monkeypatch.setattr(sys, "exit", _fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("recollectium.service_manager", run_name="__main__")
    assert exc_info.value.code == 2
