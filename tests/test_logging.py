"""Tests for the structured JSON logging infrastructure."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from unittest.mock import MagicMock
import warnings

import pytest

from recollectium.config import RecollectiumConfig, DEFAULTS, SUPPORTED_LOGGING_FORMATS
from recollectium.logging import JsonFormatter, get_logger, setup_logging


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


def _make_record(
    name: str = "recollectium.test",
    level: int = logging.INFO,
    msg: str = "test message",
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    """Create a LogRecord for testing the formatter."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="/fake/path.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for key, value in extra.items():
            setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_produces_valid_json_with_all_fields(self) -> None:
        formatter = JsonFormatter()
        record = _make_record(
            name="recollectium.core",
            level=logging.INFO,
            msg="RecollectiumCore initialised",
            extra={"event": "core.init", "context": {"db_path": "/tmp/test.db"}},
        )
        line = formatter.format(record)
        parsed = json.loads(line)

        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {
            "context",
            "event",
            "level",
            "logger",
            "message",
            "timestamp",
        }
        # All 6 fields present
        assert parsed["event"] == "core.init"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "recollectium.core"
        assert parsed["message"] == "RecollectiumCore initialised"
        assert parsed["context"] == {"db_path": "/tmp/test.db"}
        # Timestamp is ISO 8601 with microseconds and Z suffix
        ts = parsed["timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts
        assert "." in ts  # microsecond separator

    def test_defaults_event_to_logger_name(self) -> None:
        """When no explicit event is provided, fall back to logger name."""
        formatter = JsonFormatter()
        record = _make_record(name="recollectium.cli", msg="some message")
        line = formatter.format(record)
        parsed = json.loads(line)
        assert parsed["event"] == "recollectium.cli"

    def test_empty_context_when_none_provided(self) -> None:
        formatter = JsonFormatter()
        record = _make_record(msg="plain message")
        line = formatter.format(record)
        parsed = json.loads(line)
        assert parsed["context"] == {}

    def test_non_dict_context_is_treated_as_empty(self) -> None:
        """If context attr is not a dict, it becomes empty dict."""
        formatter = JsonFormatter()
        record = _make_record(
            msg="bad context",
            extra={"context": "not a dict"},
        )
        line = formatter.format(record)
        parsed = json.loads(line)
        assert parsed["context"] == {}

    def test_level_is_uppercase(self) -> None:
        formatter = JsonFormatter()
        for level, name in [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
        ]:
            record = _make_record(level=level)
            line = formatter.format(record)
            parsed = json.loads(line)
            assert parsed["level"] == name

    def test_message_includes_formatted_args(self) -> None:
        """Verify that %-style formatting in the message is applied."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="recollectium.test",
            level=logging.INFO,
            pathname="/f.py",
            lineno=1,
            msg="processed %d items",
            args=(5,),
            exc_info=None,
        )
        line = formatter.format(record)
        parsed = json.loads(line)
        assert parsed["message"] == "processed 5 items"

    def test_json_output_is_one_line(self) -> None:
        formatter = JsonFormatter()
        record = _make_record()
        line = formatter.format(record)
        assert "\n" not in line.strip()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)
        log_file = tmp_path / "logs" / "recollectium.log"
        assert log_file.exists()
        assert log_file.is_file()

    def test_rotating_handler_config(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)

        root_logger = logging.getLogger("recollectium")
        file_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        handler: logging.handlers.RotatingFileHandler = file_handlers[0]
        assert handler.maxBytes == 10485760
        assert handler.backupCount == 5

    def test_stream_handler_is_warning_level(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)

        root_logger = logging.getLogger("recollectium")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(stream_handlers) >= 1
        for h in stream_handlers:
            if not isinstance(h, logging.handlers.RotatingFileHandler):
                assert h.level == logging.WARNING

    def test_logger_emits_to_file(self, tmp_path: Path) -> None:
        # Save and clear existing handlers so test setup takes full control
        recollectium_logger = logging.getLogger("recollectium")
        saved_handlers = list(recollectium_logger.handlers)
        recollectium_logger.handlers.clear()

        config = _make_test_config(tmp_path)
        setup_logging(config)

        logger = get_logger("recollectium.test")
        logger.info(
            "event logged",
            extra={"event": "test.event", "context": {"key": "value"}},
        )

        # Flush all handlers so content is written to disk
        for handler in logging.getLogger("recollectium").handlers:
            handler.flush()

        log_file = tmp_path / "logs" / "recollectium.log"
        content = log_file.read_text()
        assert "event logged" in content
        parsed = json.loads(content.strip().split("\n")[-1])
        assert parsed["event"] == "test.event"
        assert parsed["context"] == {"key": "value"}

        # Restore original handlers
        recollectium_logger.handlers.clear()
        recollectium_logger.handlers.extend(saved_handlers)

    def test_library_loggers_are_captured(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)

        uvicorn = logging.getLogger("uvicorn")
        assert len(uvicorn.handlers) > 0
        sqlite3_logger = logging.getLogger("sqlite3")
        assert len(sqlite3_logger.handlers) > 0
        httpx_logger = logging.getLogger("httpx")
        assert len(httpx_logger.handlers) > 0

    def test_uvicorn_log_config_none_preserves_structured_file_logging(
        self, tmp_path: Path
    ) -> None:
        import uvicorn

        config = _make_test_config(tmp_path)
        setup_logging(config)

        async def app(scope: object, receive: object, send: object) -> None:
            return None

        uvicorn_config = uvicorn.Config(app, log_config=None)
        uvicorn_config.configure_logging()
        logging.getLogger("uvicorn.error").warning("uvicorn warning reached file")

        for handler in logging.getLogger("uvicorn").handlers:
            handler.flush()

        log_file = tmp_path / "logs" / "recollectium.log"
        payloads = [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
        ]
        assert any(
            payload["logger"] == "uvicorn.error"
            and payload["message"] == "uvicorn warning reached file"
            for payload in payloads
        )

    def test_warning_capture_writes_structured_event(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)

        warnings.showwarning("connection leaked", ResourceWarning, "db.py", 7)

        for handler in logging.getLogger("recollectium").handlers:
            handler.flush()

        log_file = tmp_path / "logs" / "recollectium.log"
        payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
        assert payload["event"] == "warning.captured"
        assert payload["logger"] == "recollectium.warnings"
        assert payload["message"] == "connection leaked"
        assert payload["context"] == {
            "category": "ResourceWarning",
            "filename": "db.py",
            "lineno": 7,
        }

    def test_handlers_not_duplicated_on_repeated_setup(self, tmp_path: Path) -> None:
        config = _make_test_config(tmp_path)
        setup_logging(config)
        handler_count_before = len(logging.getLogger("recollectium").handlers)
        setup_logging(config)
        handler_count_after = len(logging.getLogger("recollectium").handlers)
        assert handler_count_after == handler_count_before


# ---------------------------------------------------------------------------
# Config validation for logging fields
# ---------------------------------------------------------------------------


class TestLoggingConfigValidation:
    def test_rejects_invalid_format(self, tmp_path: Path) -> None:
        config_data = _make_logging_config(format="yaml")
        with pytest.raises(Exception) as exc_info:
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config_data))
            RecollectiumConfig(config_path)
        assert "logging.format" in str(exc_info.value)

    def test_rejects_non_positive_max_bytes(self, tmp_path: Path) -> None:
        config_data = _make_logging_config(max_bytes=0)
        with pytest.raises(Exception) as exc_info:
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config_data))
            RecollectiumConfig(config_path)
        assert "logging.max_bytes" in str(exc_info.value)

    def test_rejects_negative_max_bytes(self, tmp_path: Path) -> None:
        config_data = _make_logging_config(max_bytes=-1)
        with pytest.raises(Exception) as exc_info:
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config_data))
            RecollectiumConfig(config_path)
        assert "logging.max_bytes" in str(exc_info.value)

    def test_rejects_zero_backup_count(self, tmp_path: Path) -> None:
        config_data = _make_logging_config(backup_count=0)
        with pytest.raises(Exception) as exc_info:
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config_data))
            RecollectiumConfig(config_path)
        assert "logging.backup_count" in str(exc_info.value)

    def test_rejects_negative_backup_count(self, tmp_path: Path) -> None:
        config_data = _make_logging_config(backup_count=-1)
        with pytest.raises(Exception) as exc_info:
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config_data))
            RecollectiumConfig(config_path)
        assert "logging.backup_count" in str(exc_info.value)

    def test_defaults_include_all_logging_fields(self) -> None:
        logging_defaults = DEFAULTS["logging"]
        assert "level" in logging_defaults
        assert "format" in logging_defaults
        assert "max_bytes" in logging_defaults
        assert "backup_count" in logging_defaults
        assert logging_defaults["format"] == "json"
        assert logging_defaults["max_bytes"] == 10485760
        assert logging_defaults["backup_count"] == 5

    def test_supported_logging_formats_contains_json(self) -> None:
        assert "json" in SUPPORTED_LOGGING_FORMATS


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger_with_given_name(self) -> None:
        logger = get_logger("recollectium.something")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "recollectium.something"

    def test_returns_child_of_recollectium_hierarchy(self) -> None:
        logger = get_logger("recollectium.child")
        assert logger.name.startswith("recollectium.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_test_config(tmp_path: Path) -> RecollectiumConfig:
    """Create a minimal mock config for logging setup tests."""
    config = MagicMock(spec=RecollectiumConfig)
    config.xdg_dirs = {"logs": tmp_path / "logs"}
    config.effective_config = {
        "logging": {
            "level": "info",
            "format": "json",
            "max_bytes": 10485760,
            "backup_count": 5,
        }
    }
    return config


def _make_logging_config(
    format: str = "json",
    max_bytes: int = 10485760,
    backup_count: int = 5,
) -> dict[str, object]:
    """Build a minimal config dict focused on logging fields."""
    return {
        "version": 1,
        "database": {"path": "recollectium.db"},
        "embedding": {
            "provider": "builtin-fastembed",
            "model": "jinaai/jina-embeddings-v2-small-en",
        },
        "service": {"host": "127.0.0.1", "port": 8765},
        "logging": {
            "level": "info",
            "format": format,
            "max_bytes": max_bytes,
            "backup_count": backup_count,
        },
    }
