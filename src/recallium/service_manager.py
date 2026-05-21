"""Service lifecycle management for Recallium daemon subprocesses.

Provides PID file read/write/cleanup, process liveness checks, stale PID
detection, and daemon-style service start/stop orchestration using
``subprocess.Popen``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from recallium.config import RecalliumConfig
from recallium.errors import ServiceConflictError, ServiceError

# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


def get_pid_file_path(config: RecalliumConfig) -> Path:
    """Return the PID file path: ``runtime_dir / "service.pid"``."""
    return config.xdg_dirs["runtime"] / "service.pid"


def read_pid_file(path: Path) -> dict[str, Any] | None:
    """Read and validate the JSON PID file.

    Returns a dict with ``"pid"`` (int) and ``"type"`` (str, ``"api"`` or
    ``"mcp"``) if the file is valid.  Returns ``None`` if the file does not
    exist.
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
    return data


def write_pid_file(path: Path, pid: int, service_type: str) -> None:
    """Write the PID file as JSON.

    Creates parent directories if they do not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "type": service_type}) + "\n",
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

    return data


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------


def start_service(
    config: RecalliumConfig,
    service_type: str,
    db_path: str | None = None,
) -> int:
    """Start a Recallium daemon subprocess of *service_type* (``"api"`` or ``"mcp"``).

    Returns the child PID.

    Raises ``ServiceConflictError`` if a service of a **different** type is
    already running.  A service of the same type is allowed (restart
    scenario).
    """
    if service_type not in {"api", "mcp"}:
        raise ValueError(f"service_type must be 'api' or 'mcp' (got {service_type!r})")

    existing = check_running_service(config)
    if existing is not None and existing["type"] != service_type:
        raise ServiceConflictError(
            f"a {existing['type']} service is already running (PID {existing['pid']}). "
            f"Stop it before starting a {service_type} service."
        )

    config_path = str(config.config_file_path)

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

    process = subprocess.Popen(cmd)
    pid = process.pid
    pid_path = get_pid_file_path(config)
    write_pid_file(pid_path, pid, service_type)

    # Brief startup grace check: verify the child is still alive.
    # If the child dies quickly (config error, port conflict, etc.),
    # clean up and report failure rather than leaving a stale PID file.
    time.sleep(0.3)
    if not is_pid_alive(pid):
        remove_pid_file(pid_path)
        raise ServiceError(
            f"service process (PID {pid}) exited immediately after start"
        )

    print(f"Service started (PID {pid})")
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
        print("No service running")
        return None

    pid: int = data["pid"]

    print(f"Stopping service (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    # Wait up to 10 seconds for graceful exit
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            print("Service stopped gracefully")
            remove_pid_file(path)
            return pid
        time.sleep(0.1)

    # Force kill
    print("Service did not stop gracefully, sending SIGKILL...")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(0.5)
    remove_pid_file(path)
    print(f"Service forcefully stopped (PID {pid})")
    return pid


# ---------------------------------------------------------------------------
# Child-process entry point
# ---------------------------------------------------------------------------


def _run_server(
    service_type: str,
    db_path: str | None = None,
    config_path: str | None = None,
) -> None:
    """Internal entry point called by the subprocess.

    Builds a ``RecalliumCore`` and starts the appropriate server based on
    *service_type*.  Signal handling (SIGTERM/SIGINT) is delegated to the
    server framework (uvicorn).
    """
    from recallium.service import run_service

    if service_type == "api":
        run_service(db_path=db_path, config_path=config_path)
    elif service_type == "mcp":
        run_service(
            db_path=db_path,
            config_path=config_path,
            service_type="mcp",
        )
    else:
        print(f"Unknown service type: {service_type!r}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Module-level __main__ support for subprocess invocation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # When spawned as: python -m recallium.service_manager _run_server <type> [...]
    if len(sys.argv) < 2 or sys.argv[1] != "_run_server":
        print(
            "usage: python -m recallium.service_manager _run_server <api|mcp> [--db-path PATH] [--config-path PATH]"
        )
        sys.exit(2)

    service_type = sys.argv[2]
    db_path: str | None = None
    config_path: str | None = None

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
        else:
            print(f"Unknown option: {remaining[i]}", file=sys.stderr)
            sys.exit(2)

    _run_server(service_type, db_path=db_path, config_path=config_path)
