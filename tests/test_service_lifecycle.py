"""Integration tests for service lifecycle CLI commands."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import TextContent
import pytest
from pytest import CaptureFixture

from recallium.cli import main
from recallium.config import DEFAULTS
from recallium.errors import ServiceConflictError, ServiceError
from recallium.service_manager import is_pid_alive

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _make_config(tmp_path: Path) -> Path:
    """Create a minimal valid config and return its path."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.json"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    logs_dir = tmp_path / "logs"
    runtime_dir = tmp_path / "run"
    config_data = dict(DEFAULTS)
    config_data["directories"] = {
        "data": str(data_dir),
        "cache": str(cache_dir),
        "logs": str(logs_dir),
        "runtime": str(runtime_dir),
    }
    config_path.write_text(json.dumps(config_data))
    return config_path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_real_service_config(tmp_path: Path) -> Path:
    config_path = _make_config(tmp_path)
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["service"] = {"host": "127.0.0.1", "port": _free_port()}
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    return config_path


def _run_real_service_command(
    config_path: Path,
    *args: str,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "recallium", "--config", str(config_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _service_endpoint(config_path: Path) -> str:
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    service = config_data["service"]
    return f"http://{service['host']}:{service['port']}"


def _request_service_json(
    endpoint: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    encoded_body = None
    headers = {"Accept": "application/json"}
    if body is not None:
        encoded_body = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{endpoint}{path}",
        data=encoded_body,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_http_service(endpoint: str) -> None:
    last_error: Exception | None = None
    for _ in range(40):
        try:
            _request_service_json(endpoint, "GET", "/v1/health")
            return
        except (TimeoutError, URLError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.25)

    raise AssertionError(f"service did not become ready: {last_error!r}")


def _stop_real_service(config_path: Path, pid: int | None) -> None:
    stop_result = _run_real_service_command(config_path, "service", "stop")
    assert stop_result.returncode == 0, stop_result.stderr
    if pid is not None:
        assert not is_pid_alive(pid)


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


def test_service_help_shows_subcommands(capsys: CaptureFixture[str]) -> None:
    help_text = _run_help(["service", "--help"], capsys)
    assert "start" in help_text
    assert "stop" in help_text
    assert "status" in help_text
    assert "restart" in help_text


def test_service_start_help(capsys: CaptureFixture[str]) -> None:
    help_text = _run_help(["service", "start", "--help"], capsys)
    assert "api" in help_text
    assert "mcp" in help_text
    assert "REST API" in help_text


def test_service_stop_help(capsys: CaptureFixture[str]) -> None:
    help_text = _run_help(["service", "stop", "--help"], capsys)
    assert "stop" in help_text


def test_service_status_help(capsys: CaptureFixture[str]) -> None:
    help_text = _run_help(["service", "status", "--help"], capsys)
    assert "status" in help_text


def test_service_restart_help(capsys: CaptureFixture[str]) -> None:
    help_text = _run_help(["service", "restart", "--help"], capsys)
    assert "--type" in help_text


# ---------------------------------------------------------------------------
# start command — happy path
# ---------------------------------------------------------------------------


def test_start_service_api(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with patch("recallium.cli.start_service", return_value=12345):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "start", "api"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {
        "endpoint": "http://127.0.0.1:8765",
        "pid": 12345,
        "status": "started",
        "type": "api",
    }


def test_start_service_mcp(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with patch("recallium.cli.start_service", return_value=9999):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "start", "mcp"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "started"
    assert payload["type"] == "mcp"
    assert payload["pid"] == 9999


# ---------------------------------------------------------------------------
# start command — error paths
# ---------------------------------------------------------------------------


def test_start_service_conflict(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    def _raise_conflict(*args, **kwargs) -> int:
        raise ServiceConflictError("a mcp service is already running (PID 9999)")

    with patch("recallium.cli.start_service", _raise_conflict):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "start", "api"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "a mcp service is already running" in stderr


def test_start_service_invalid_type(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Argparse rejects unknown service type before reaching the handler."""
    with pytest.raises(SystemExit) as exc_info:
        main(["service", "start", "grpc"])
    assert exc_info.value.code == 2


def test_start_service_value_error(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """start_service raises ValueError — handler prints to stderr and returns 2."""
    config_path = _make_config(tmp_path)

    def _raise_value_error(*args, **kwargs) -> int:
        raise ValueError("unknown service type: xyz")

    with patch("recallium.cli.start_service", _raise_value_error):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "start", "api"],
            capsys,
        )

    assert exit_code == 2
    assert stdout == ""
    assert "unknown service type: xyz" in stderr


def test_start_service_service_error(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = _make_config(tmp_path)

    def _raise_service_error(*args, **kwargs) -> int:
        raise ServiceError("service process exited immediately after start")

    with patch("recallium.cli.start_service", _raise_service_error):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "start", "api"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "service process exited immediately" in stderr


def test_start_service_real_process_returns_json_without_inherited_output(
    tmp_path: Path,
) -> None:
    config_path = _make_real_service_config(tmp_path)
    pid: int | None = None

    result = _run_real_service_command(
        config_path,
        "service",
        "start",
        "api",
        timeout=5,
    )

    try:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["status"] == "started"
        assert payload["type"] == "api"
        pid = payload["pid"]
        assert isinstance(pid, int)
    finally:
        _stop_real_service(config_path, pid)


def test_api_service_real_process_handles_memory_round_trip(tmp_path: Path) -> None:
    config_path = _make_real_service_config(tmp_path)
    endpoint = _service_endpoint(config_path)
    pid: int | None = None

    result = _run_real_service_command(config_path, "service", "start", "api")

    try:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        start_payload = json.loads(result.stdout)
        assert start_payload["status"] == "started"
        assert start_payload["type"] == "api"
        pid = start_payload["pid"]
        assert isinstance(pid, int)

        _wait_for_http_service(endpoint)

        added = _request_service_json(
            endpoint,
            "POST",
            "/v1/memories",
            {"space": "user", "type": "fact", "content": "api daemon memory"},
        )
        memory = added["data"]
        assert isinstance(memory, dict)
        assert memory["content"] == "api daemon memory"

        search = _request_service_json(
            endpoint,
            "POST",
            "/v1/memories/search_user",
            {"query": "api daemon"},
        )
        results = search["data"]
        assert isinstance(results, list)
        assert results[0]["memory"]["id"] == memory["id"]
    finally:
        _stop_real_service(config_path, pid)


def test_mcp_service_real_process_handles_tool_round_trip(tmp_path: Path) -> None:
    asyncio.run(_assert_mcp_service_round_trip(tmp_path))


async def _assert_mcp_service_round_trip(tmp_path: Path) -> None:
    config_path = _make_real_service_config(tmp_path)
    endpoint = _service_endpoint(config_path)
    pid: int | None = None

    result = _run_real_service_command(config_path, "service", "start", "mcp")

    try:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        start_payload = json.loads(result.stdout)
        assert start_payload["status"] == "started"
        assert start_payload["type"] == "mcp"
        pid = start_payload["pid"]
        assert isinstance(pid, int)

        await _exercise_mcp_service_when_ready(endpoint)
    finally:
        _stop_real_service(config_path, pid)


async def _exercise_mcp_service_when_ready(endpoint: str) -> None:
    last_error: Exception | None = None
    for _ in range(40):
        try:
            await _exercise_mcp_service(endpoint)
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.25)

    raise AssertionError(f"MCP service did not become ready: {last_error!r}")


async def _exercise_mcp_service(endpoint: str) -> None:
    async with sse_client(
        f"{endpoint}/sse",
        timeout=5,
        sse_read_timeout=5,
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert tool_names >= {
                "add_memory",
                "get_memory",
                "search_user_memory",
            }

            added = await session.call_tool(
                "add_memory",
                {
                    "space": "user",
                    "type": "fact",
                    "content": "mcp daemon memory",
                },
            )
            assert not added.isError
            added_content = added.content[0]
            assert isinstance(added_content, TextContent)
            added_memory = json.loads(added_content.text)
            assert added_memory["content"] == "mcp daemon memory"

            search = await session.call_tool(
                "search_user_memory",
                {"query": "mcp daemon"},
            )
            assert not search.isError
            search_content = search.content[0]
            assert isinstance(search_content, TextContent)
            results = json.loads(search_content.text)
            assert results[0]["memory"]["id"] == added_memory["id"]

            got = await session.call_tool(
                "get_memory",
                {"id": added_memory["id"]},
            )
            assert not got.isError
            got_content = got.content[0]
            assert isinstance(got_content, TextContent)
            got_memory = json.loads(got_content.text)
            assert got_memory["id"] == added_memory["id"]
            assert got_memory["content"] == "mcp daemon memory"


# ---------------------------------------------------------------------------
# stop command
# ---------------------------------------------------------------------------


def test_stop_service_running(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with patch("recallium.cli.stop_service", return_value=12345):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "stop"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {"status": "stopped", "pid": 12345}


def test_stop_service_not_running(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with patch("recallium.cli.stop_service", return_value=None):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "stop"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {"status": "no_service_running"}


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_running(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch(
            "recallium.cli.check_running_service",
            return_value={"pid": 12345, "type": "api"},
        ),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch(
            "recallium.cli.read_pid_file", return_value={"pid": 12345, "type": "api"}
        ),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "status"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["running"] is True
    assert payload["type"] == "api"
    assert payload["pid"] == 12345
    assert payload["endpoint"] == "http://127.0.0.1:8765"


def test_status_not_running(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.read_pid_file", return_value=None),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "status"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {"running": False}


def test_status_stale_pid(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch(
            "recallium.cli.read_pid_file",
            return_value={"pid": 99999, "type": "api"},
        ),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "status"],
            capsys,
        )

    assert exit_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["running"] is False
    assert payload["last_service"] == {"type": "api", "pid": 99999}


# ---------------------------------------------------------------------------
# restart command
# ---------------------------------------------------------------------------


def test_restart_running_service(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    stop_calls: list = []
    start_calls: list = []

    def _mock_stop(config) -> int:
        stop_calls.append(config)
        return 12345

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append((service_type, db_path))
        return 12346

    with (
        patch(
            "recallium.cli.check_running_service",
            return_value={"pid": 12345, "type": "api"},
        ),
        patch(
            "recallium.cli.read_pid_file",
            return_value={"pid": 12345, "type": "api"},
        ),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.stop_service", _mock_stop),
        patch("recallium.cli.start_service", _mock_start),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart"],
            capsys,
        )

    assert exit_code == 0
    assert "Stopping existing api service..." in stderr
    payload = json.loads(stdout)
    assert payload["status"] == "restarted"
    assert payload["type"] == "api"
    assert payload["pid"] == 12346
    assert len(stop_calls) == 1
    assert start_calls == [("api", None)]


def test_restart_stale_pid(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    start_calls: list = []

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append((service_type, db_path))
        return 12345

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch(
            "recallium.cli.read_pid_file",
            return_value={"pid": 99999, "type": "mcp"},
        ),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _mock_start),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart"],
            capsys,
        )

    assert exit_code == 0
    assert start_calls == [("mcp", None)]
    payload = json.loads(stdout)
    assert payload["status"] == "restarted"
    assert payload["type"] == "mcp"
    assert payload["pid"] == 12345


def test_restart_no_service_no_type(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "No running service found" in stderr
    assert "--type" in stderr


def test_restart_with_type_flag(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    start_calls: list = []

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append((service_type, db_path))
        return 12345

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _mock_start),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart", "--type", "api"],
            capsys,
        )

    assert exit_code == 0
    assert start_calls == [("api", None)]
    payload = json.loads(stdout)
    assert payload["status"] == "restarted"
    assert payload["type"] == "api"


def test_restart_value_error_on_start(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """start_service raises ValueError during restart — handler returns 2."""
    config_path = _make_config(tmp_path)

    def _raise_value_error(config, service_type, db_path=None) -> int:
        raise ValueError("unknown service type: xyz")

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _raise_value_error),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart", "--type", "mcp"],
            capsys,
        )

    assert exit_code == 2
    assert stdout == ""
    assert "unknown service type: xyz" in stderr


def test_restart_conflict_error_on_start(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """start_service raises ServiceConflictError during restart — handler returns 1."""
    config_path = _make_config(tmp_path)

    def _raise_conflict(config, service_type, db_path=None) -> int:
        raise ServiceConflictError("a mcp service is already running")

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _raise_conflict),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart", "--type", "api"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "a mcp service is already running" in stderr


def test_restart_service_error_on_start(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = _make_config(tmp_path)

    def _raise_service_error(config, service_type, db_path=None) -> int:
        raise ServiceError("service process exited immediately after start")

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _raise_service_error),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart", "--type", "api"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "service process exited immediately" in stderr


# ---------------------------------------------------------------------------
# config error paths
# ---------------------------------------------------------------------------


def test_service_config_file_not_found(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "nonexistent" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "start", "api"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_service_config_validation_error(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "service": {"port": "bad"}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "start", "api"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "service.port must be int" in stderr


def test_service_config_file_not_found_on_stop(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "nonexistent" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "stop"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_service_config_validation_error_on_stop(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "service": {"port": "bad"}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "stop"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr
    assert "service.port must be int" in stderr


def test_service_config_file_not_found_on_status(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "nonexistent" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "status"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


def test_service_config_file_not_found_on_restart(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "nonexistent" / "config.json"

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "restart", "--type", "api"],
        capsys,
    )

    assert exit_code == 1
    assert stdout == ""
    assert f"config file not found: {config_path}" in stderr


# ---------------------------------------------------------------------------
# stop / status / restart covered by all config error paths
# ---------------------------------------------------------------------------


def test_stop_config_validation_error(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """ValidationError in stop command returns exit code 2."""
    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "logging": {"level": ["invalid"]}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "stop"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr


def test_restart_config_validation_error(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """ValidationError in restart command returns exit code 2."""
    config_path = tmp_path / "config.json"
    config_path.write_text('{"version": 1, "logging": {"level": 42}}')

    exit_code, stdout, stderr = _run_cli(
        ["--config", str(config_path), "service", "restart", "--type", "mcp"],
        capsys,
    )

    assert exit_code == 2
    assert stdout == ""
    assert "ValidationError:" in stderr


# ---------------------------------------------------------------------------
# db_path propagation
# ---------------------------------------------------------------------------


def test_start_service_passes_db_path(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    config_path = _make_config(tmp_path)
    db_path = tmp_path / "custom.db"

    start_calls: list = []

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append((service_type, db_path))
        return 42

    with patch("recallium.cli.start_service", _mock_start):
        exit_code, stdout, stderr = _run_cli(
            [
                "--config",
                str(config_path),
                "--db",
                str(db_path),
                "service",
                "start",
                "api",
            ],
            capsys,
        )

    assert exit_code == 0
    assert len(start_calls) == 1
    assert start_calls[0] == ("api", str(db_path))


def test_restart_passes_db_path(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)
    db_path = tmp_path / "custom.db"

    start_calls: list = []

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append((service_type, db_path))
        return 42

    with (
        patch("recallium.cli.check_running_service", return_value=None),
        patch("recallium.cli.read_pid_file", return_value=None),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.start_service", _mock_start),
    ):
        exit_code, stdout, stderr = _run_cli(
            [
                "--config",
                str(config_path),
                "--db",
                str(db_path),
                "service",
                "restart",
                "--type",
                "mcp",
            ],
            capsys,
        )

    assert exit_code == 0
    assert len(start_calls) == 1
    assert start_calls[0] == ("mcp", str(db_path))


# ---------------------------------------------------------------------------
# restart: stop_service propagates error (edge case)
# ---------------------------------------------------------------------------


def test_restart_running_stop_fails_with_conflict(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """If stop_service raises during restart of a running service, the error
    propagates (CLI does not catch exceptions from stop_service)."""
    config_path = _make_config(tmp_path)

    start_calls: list = []

    def _mock_stop(config) -> None:
        raise ServiceConflictError("cannot stop: another process holds lock")

    def _mock_start(config, service_type, db_path=None) -> int:
        start_calls.append(service_type)
        return 12346

    with (
        patch(
            "recallium.cli.check_running_service",
            return_value={"pid": 12345, "type": "api"},
        ),
        patch(
            "recallium.cli.read_pid_file",
            return_value={"pid": 12345, "type": "api"},
        ),
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch("recallium.cli.stop_service", _mock_stop),
        patch("recallium.cli.start_service", _mock_start),
    ):
        with pytest.raises(ServiceConflictError, match="cannot stop"):
            main(
                [
                    "--config",
                    str(config_path),
                    "service",
                    "restart",
                ]
            )


def test_status_corrupt_pid_file(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch(
            "recallium.cli.read_pid_file",
            side_effect=ServiceError("corrupted PID file"),
        ),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "status"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "corrupted PID file" in stderr


def test_restart_corrupt_pid_file(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    config_path = _make_config(tmp_path)

    with (
        patch("recallium.cli.get_pid_file_path", return_value=Path("/fake/pid")),
        patch(
            "recallium.cli.read_pid_file",
            side_effect=ServiceError("corrupted PID file"),
        ),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["--config", str(config_path), "service", "restart"],
            capsys,
        )

    assert exit_code == 1
    assert stdout == ""
    assert "corrupted PID file" in stderr
