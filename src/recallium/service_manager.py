"""Service lifecycle management for Recallium daemon subprocesses.

Provides PID file read/write/cleanup, process liveness checks, stale PID
detection, and daemon-style service start/stop orchestration using
``subprocess.Popen``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from recallium.config import RecalliumConfig
from recallium.errors import ServiceConflictError, ServiceError

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


def get_pid_file_path(config: RecalliumConfig) -> Path:
    """Return the PID file path: ``runtime_dir / "service.pid"``."""
    return config.xdg_dirs["runtime"] / "service.pid"


def read_pid_file(path: Path) -> dict[str, Any] | None:
    """Read and validate the JSON PID file.

    Returns a dict with ``"pid"`` (int), ``"type"`` (str, ``"api"`` or
    ``"mcp"``), and optional process ownership metadata if the file is valid.
    Returns ``None`` if the file does not exist.
    """
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ServiceError(f"corrupted PID file: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ServiceError(
            f"corrupted PID file: expected JSON object, got {type(data).__name__}"
        )
    if "pid" not in data or not isinstance(data["pid"], int):
        raise ServiceError("corrupted PID file: missing or invalid 'pid' field")
    if data["pid"] <= 0:
        raise ServiceError("corrupted PID file: pid must be a positive integer")
    if "type" not in data or data["type"] not in {"api", "mcp"}:
        raise ServiceError("corrupted PID file: missing or invalid 'type' field")
    if "process_start_time" in data and not isinstance(data["process_start_time"], int):
        raise ServiceError(
            "corrupted PID file: missing or invalid 'process_start_time' field"
        )
    return data


def get_process_start_time(pid: int) -> int | None:
    """Return the Linux process start time ticks for *pid*, if available."""
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError, PermissionError, OSError:
        return None

    try:
        fields_after_name = stat_text[stat_text.rfind(")") + 2 :].split()
        return int(fields_after_name[19])
    except IndexError, ValueError:
        return None


def get_process_cmdline(pid: int) -> list[str] | None:
    """Return the process command line for *pid*, if available."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError, PermissionError, OSError:
        return None
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def is_recallium_service_process(
    pid: int,
    service_type: str,
    process_start_time: int | None,
) -> bool:
    """Return whether *pid* still looks like the daemon this PID file owns."""
    if process_start_time is None:
        return False
    if get_process_start_time(pid) != process_start_time:
        return False

    cmdline = get_process_cmdline(pid)
    if cmdline is None:
        return False
    return (
        "recallium.service_manager" in cmdline
        and "_run_server" in cmdline
        and service_type in cmdline
    )


def write_pid_file(
    path: Path, pid: int, service_type: str, process_start_time: int | None = None
) -> None:
    """Write the PID file as JSON.

    Creates parent directories if they do not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "type": service_type,
                "process_start_time": process_start_time,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def remove_pid_file(path: Path) -> None:
    """Remove the PID file if it exists (no error if missing)."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Process liveness
# ---------------------------------------------------------------------------


def is_pid_alive(pid: int) -> bool:
    """Return ``True`` if a process with *pid* is currently alive.

    Uses ``os.kill(pid, 0)`` which sends signal 0 — a no-op that only checks
    whether the process exists and we have permission to signal it.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, we just can't signal it


# ---------------------------------------------------------------------------
# Running service check
# ---------------------------------------------------------------------------


def check_running_service(config: RecalliumConfig) -> dict[str, Any] | None:
    """Return PID file data if a service is alive, or ``None``.

    If the PID file exists but the process is dead the stale file is cleaned
    up and ``None`` is returned.  Raises ``ServiceError`` if the PID file
    exists but is corrupted.
    """
    path = get_pid_file_path(config)
    data = read_pid_file(path)
    if data is None:
        return None

    if not is_pid_alive(data["pid"]):
        remove_pid_file(path)
        return None

    if not is_recallium_service_process(
        data["pid"], data["type"], data.get("process_start_time")
    ):
        remove_pid_file(path)
        return None

    return data


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------


def start_service(
    config: RecalliumConfig,
    service_type: str,
    db_path: str | None = None,
    log_level: str | None = None,
) -> int:
    """Start a Recallium daemon subprocess of *service_type* (``"api"`` or ``"mcp"``).

    Returns the child PID.

    Raises ``ServiceConflictError`` if any service is already running. Use
    ``service restart`` for restart semantics so the PID file always tracks
    the process that is actually serving requests.
    """
    if service_type not in {"api", "mcp"}:
        raise ValueError(f"service_type must be 'api' or 'mcp' (got {service_type!r})")

    existing = check_running_service(config)
    if existing is not None:
        raise ServiceConflictError(
            f"a {existing['type']} service is already running (PID {existing['pid']}). "
            f"Stop it before starting a {service_type} service."
        )

    config_path = str(config.config_file_path)
    host = str(config.effective_config["service"]["host"])
    port = int(config.effective_config["service"]["port"])

    cmd: list[str] = [
        sys.executable,
        "-m",
        "recallium.service_manager",
        "_run_server",
        service_type,
    ]
    if db_path is not None:
        cmd.extend(["--db-path", db_path])
    cmd.extend(["--config-path", config_path])
    if log_level is not None:
        cmd.extend(["--log-level", log_level])
    cmd.extend(["--host", host, "--port", str(port)])

    log_dir = config.xdg_dirs["logs"]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"service-{service_type}.log"

    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    pid = process.pid
    pid_path = get_pid_file_path(config)
    process_start_time = get_process_start_time(pid)
    if process_start_time is None:
        process.terminate()
        _log.error(
            f"could not verify service ownership for PID {pid}",
            extra={"event": "service.startup_failed", "context": {"pid": pid}},
        )
        raise ServiceError(f"could not verify service process ownership for PID {pid}")
    write_pid_file(pid_path, pid, service_type, process_start_time)

    # Brief startup grace check: verify the child is still alive.
    # If the child dies quickly (config error, port conflict, etc.),
    # clean up and report failure rather than leaving a stale PID file.
    time.sleep(0.3)
    if process.poll() is not None or not is_pid_alive(pid):
        remove_pid_file(pid_path)
        _log.error(
            "service exited immediately after start",
            extra={
                "event": "service.startup_failed",
                "context": {"pid": pid, "type": service_type},
            },
        )
        raise ServiceError(
            f"service process (PID {pid}) exited immediately after start"
        )

    _log.info(
        "service started",
        extra={
            "event": "service.startup",
            "context": {
                "type": service_type,
                "host": host,
                "port": port,
                "pid": pid,
            },
        },
    )
    return pid


def stop_service(config: RecalliumConfig) -> int | None:
    """Stop the running Recallium service.

    Sends ``SIGTERM``, waits up to 10 seconds (polling every 0.1 seconds),
    then sends ``SIGKILL`` if the process is still alive.  Removes the PID
    file.

    Returns the PID that was stopped, or ``None`` if no service was running.
    """
    path = get_pid_file_path(config)
    data = check_running_service(config)
    if data is None:
        _log.info(
            "no service running to stop",
            extra={"event": "service.no_service"},
        )
        return None

    pid: int = data["pid"]

    _log.info(
        f"Stopping service (PID {pid})...",
        extra={
            "event": "service.stop",
            "context": {"pid": pid, "type": data["type"]},
        },
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    # Wait up to 10 seconds for graceful exit
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            _log.info(
                "Service stopped gracefully",
                extra={
                    "event": "service.shutdown",
                    "context": {"pid": pid, "type": data["type"]},
                },
            )
            remove_pid_file(path)
            return pid
        time.sleep(0.1)

    # Force kill
    _log.warning(
        f"service did not stop gracefully, sending SIGKILL (PID {pid})",
        extra={
            "event": "service.force_stopped",
            "context": {"pid": pid, "type": data["type"]},
        },
    )
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(0.5)
    remove_pid_file(path)
    return pid


# ---------------------------------------------------------------------------
# Child-process entry point
# ---------------------------------------------------------------------------


def _run_server(
    service_type: str,
    db_path: str | None = None,
    config_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
) -> None:
    """Internal entry point called by the subprocess.

    Builds a ``RecalliumCore`` and starts the appropriate server based on
    *service_type*.  Signal handling (SIGTERM/SIGINT) is delegated to the
    server framework (uvicorn).
    """
    from recallium.service import run_service

    service_kwargs: dict[str, Any] = {
        "db_path": db_path,
        "config_path": config_path,
        "log_level": log_level,
    }
    if host is not None:
        service_kwargs["host"] = host
    if port is not None:
        service_kwargs["port"] = port

    if service_type == "api":
        run_service(**service_kwargs)
    elif service_type == "mcp":
        run_service(**service_kwargs, service_type="mcp")
    else:
        _log.error(
            f"unknown service type: {service_type!r}",
            extra={
                "event": "service.startup_failed",
                "context": {"type": service_type},
            },
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Module-level __main__ support for subprocess invocation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # When spawned as: python -m recallium.service_manager _run_server <type> [...]
    if len(sys.argv) < 2 or sys.argv[1] != "_run_server":
        _log.error(
            "usage: python -m recallium.service_manager _run_server <api|mcp> [--db-path PATH] [--config-path PATH] [--host HOST] [--port PORT]"
        )
        sys.exit(2)

    service_type = sys.argv[2]
    db_path: str | None = None
    config_path: str | None = None
    host: str | None = None
    port: int | None = None
    log_level: str | None = None

    # Simple argument parsing for the remaining args
    remaining = sys.argv[3:]
    i = 0
    while i < len(remaining):
        if remaining[i] == "--db-path" and i + 1 < len(remaining):
            db_path = remaining[i + 1]
            i += 2
        elif remaining[i] == "--config-path" and i + 1 < len(remaining):
            config_path = remaining[i + 1]
            i += 2
        elif remaining[i] == "--host" and i + 1 < len(remaining):
            host = remaining[i + 1]
            i += 2
        elif remaining[i] == "--port" and i + 1 < len(remaining):
            try:
                port = int(remaining[i + 1])
            except ValueError:
                _log.error(
                    f"invalid port: {remaining[i + 1]!r}",
                    extra={"event": "config.invalid"},
                )
                sys.exit(2)
            i += 2
        elif remaining[i] == "--log-level" and i + 1 < len(remaining):
            log_level = remaining[i + 1]
            i += 2
        else:
            _log.error(
                f"unknown option: {remaining[i]}",
                extra={"event": "config.invalid"},
            )
            sys.exit(2)

    _run_server(
        service_type,
        db_path=db_path,
        config_path=config_path,
        host=host,
        port=port,
        log_level=log_level,
    )
