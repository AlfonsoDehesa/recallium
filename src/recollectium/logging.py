"""Structured JSON logging infrastructure for Recollectium.

Provides a ``JsonFormatter``, a ``setup_logging`` bootstrap that configures
the ``recollectium.*`` logger hierarchy with size-based rotation and a stderr
fallback, and a ``get_logger`` convenience.
"""

from __future__ import annotations

import logging
import sys
import warnings
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping, Protocol


class LoggingConfig(Protocol):
    @property
    def effective_config(self) -> Mapping[str, Any]: ...

    @property
    def xdg_dirs(self) -> Mapping[str, Path]: ...


def _event_for_record(record: logging.LogRecord) -> str:
    """Return the stable event name for *record*.

    If an explicit event was provided via ``extra={"event": "..."}`` it takes
    priority.  Otherwise the dotted logger name is used as the event.
    """
    custom = getattr(record, "event", None)
    if isinstance(custom, str) and custom:
        return custom
    return record.name


class JsonFormatter(logging.Formatter):
    """A ``logging.Formatter`` that serialises log records as one JSON line.

    Every line contains these fields:

    - ``timestamp`` -- ISO 8601 UTC with microsecond precision
    - ``level`` -- uppercase level name
    - ``logger`` -- dotted module path
    - ``message`` -- human-readable summary
    - ``event`` -- stable machine-readable event name
    - ``context`` -- optional structured data dict (empty dict when absent)
    """

    def format(self, record: logging.LogRecord) -> str:
        import json

        event = _event_for_record(record)
        context = getattr(record, "context", None)
        if not isinstance(context, dict):
            context = {}

        payload = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.upper(),
            "logger": record.name,
            "message": record.getMessage(),
            "event": event,
            "context": context,
        }
        return json.dumps(payload, sort_keys=True)


def setup_logging(config: LoggingConfig) -> None:
    """Bootstrap the ``recollectium`` logger hierarchy.

    Creates the logs directory (mode 0o700), attaches a
    ``RotatingFileHandler`` writing to ``logs/recollectium.log`` (mode 0o600) and
    a ``StreamHandler`` on stderr at WARNING level.  Both use
    ``JsonFormatter``.

    Library loggers ``uvicorn``, ``sqlite3``, and ``httpx`` are captured at
    WARNING and routed to the same handlers.
    """
    log_dir = config.xdg_dirs["logs"]
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_dir.chmod(0o700)

    log_file = log_dir / "recollectium.log"

    logging_config = config.effective_config.get("logging", {})
    log_level_name = str(logging_config.get("level", "info")).upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    max_bytes = int(logging_config.get("max_bytes", 10485760))
    backup_count = int(logging_config.get("backup_count", 5))

    json_formatter = JsonFormatter()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    setattr(file_handler, "_recollectium_managed", True)
    file_handler.setFormatter(json_formatter)
    file_handler.setLevel(log_level)
    if log_file.exists():
        log_file.chmod(0o600)

    stream_handler = logging.StreamHandler(sys.stderr)
    setattr(stream_handler, "_recollectium_managed", True)
    stream_handler.setFormatter(json_formatter)
    stream_handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger("recollectium")
    root_logger.setLevel(log_level)

    def _replace_managed_handlers(logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            if getattr(handler, "_recollectium_managed", False):
                logger.removeHandler(handler)
                handler.close()

    _replace_managed_handlers(root_logger)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    for lib_name in ("uvicorn", "sqlite3", "httpx"):
        lib_logger = logging.getLogger(lib_name)
        lib_logger.setLevel(logging.WARNING)
        lib_logger.propagate = False
        _replace_managed_handlers(lib_logger)
        lib_logger.addHandler(file_handler)
        lib_logger.addHandler(stream_handler)

    _warnings_logger = logging.getLogger("recollectium.warnings")

    def _handle_warning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: object | None = None,
        line: str | None = None,
    ) -> None:
        _warnings_logger.warning(
            str(message),
            extra={
                "event": "warning.captured",
                "context": {
                    "category": category.__name__,
                    "filename": filename,
                    "lineno": lineno,
                },
            },
        )

    warnings.showwarning = _handle_warning


def get_logger(name: str) -> logging.Logger:
    """Return a logger for *name*, typically ``__name__`` of the calling module."""
    return logging.getLogger(name)
