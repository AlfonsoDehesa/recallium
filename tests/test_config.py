"""Tests for Recollectium config system."""

from __future__ import annotations

import json
from pathlib import Path
from copy import deepcopy
from typing import Any

import pytest

from recollectium.config import (
    CONFIG_VERSION,
    DEFAULTS,
    RecollectiumConfig,
    _check_type,
    _deep_merge,
    _ensure_config_directories,
    _resolve_xdg_dirs,
    _validate_config_value,
    _write_starter_config,
    get_config_value,
    load_config_file,
    set_config_value,
    unset_config_value,
    validate_config_file,
)
from recollectium.errors import ValidationError


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_merges_flat_overrides(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3}

    def test_merges_nested_dicts(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 4}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 4}, "b": 3}

    def test_none_values_in_override_are_skipped(self) -> None:
        base = {"a": 1}
        override = {"a": None}
        result = _deep_merge(base, override)
        assert result == {"a": 1}

    def test_none_overrides_in_nested_dict_are_skipped(self) -> None:
        base = {"service": {"host": "127.0.0.1", "port": 8765}}
        override = {"service": {"host": None, "port": 9999}}
        result = _deep_merge(base, override)
        assert result == {"service": {"host": "127.0.0.1", "port": 9999}}

    def test_override_replaces_non_dict_with_dict(self) -> None:
        base = {"a": 1}
        override = {"a": {"b": 2}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": 2}}

    def test_does_not_mutate_base(self) -> None:
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"y": 2}})
        assert base == {"a": {"x": 1}}


# ---------------------------------------------------------------------------
# _resolve_xdg_dirs
# ---------------------------------------------------------------------------


class TestResolveXDGDirs:
    def test_resolves_all_directories(self) -> None:
        dirs = _resolve_xdg_dirs({})
        assert "config" in dirs
        assert "data" in dirs
        assert "cache" in dirs
        assert "logs" in dirs
        assert "runtime" in dirs
        for key in dirs:
            assert isinstance(dirs[key], Path)

    def test_respects_override_for_data(self, tmp_path: Path) -> None:
        override: dict[str, str | None] = {"data": str(tmp_path / "my-data")}
        dirs = _resolve_xdg_dirs(override)
        assert dirs["data"] == tmp_path / "my-data"

    def test_respects_override_for_cache(self, tmp_path: Path) -> None:
        override: dict[str, str | None] = {"cache": str(tmp_path / "my-cache")}
        dirs = _resolve_xdg_dirs(override)
        assert dirs["cache"] == tmp_path / "my-cache"

    def test_respects_override_for_logs(self, tmp_path: Path) -> None:
        override: dict[str, str | None] = {"logs": str(tmp_path / "my-logs")}
        dirs = _resolve_xdg_dirs(override)
        assert dirs["logs"] == tmp_path / "my-logs"

    def test_respects_override_for_runtime(self, tmp_path: Path) -> None:
        override: dict[str, str | None] = {"runtime": str(tmp_path / "my-run")}
        dirs = _resolve_xdg_dirs(override)
        assert dirs["runtime"] == tmp_path / "my-run"

    def test_empty_string_override_falls_back_to_default(self) -> None:
        override: dict[str, str | None] = {"data": ""}
        dirs = _resolve_xdg_dirs(override)
        assert isinstance(dirs["data"], Path)


# ---------------------------------------------------------------------------
# _validate_config_value
# ---------------------------------------------------------------------------


class TestValidateConfigValue:
    def test_check_type_allows_none_when_expected_is_none(self) -> None:
        """_check_type returns early when expected is type(None) and value is None."""
        data = {"a": None}
        _check_type(data, "a", type(None), "")  # should not raise

    def test_check_type_raises_for_none_when_expected_is_str(self) -> None:
        data = {"a": None}
        with pytest.raises(ValidationError, match="must be str"):
            _check_type(data, "a", str, "")

    def test_valid_default_config_passes(self) -> None:
        _validate_config_value(deepcopy(DEFAULTS))

    def test_invalid_version_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["version"] = "1"
        with pytest.raises(ValidationError, match="version must be int"):
            _validate_config_value(data)

    def test_version_below_1_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["version"] = 0
        with pytest.raises(ValidationError, match="version must be >= 1"):
            _validate_config_value(data)

    def test_invalid_database_path_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["database"] = {"path": 123}
        with pytest.raises(ValidationError, match="database.path must be str"):
            _validate_config_value(data)

    def test_invalid_embedding_provider_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["embedding"] = {"provider": 123, "model": "test"}
        with pytest.raises(ValidationError, match="embedding.provider must be str"):
            _validate_config_value(data)

    def test_unsupported_embedding_provider_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["embedding"]["provider"] = "ollama"
        with pytest.raises(ValidationError, match="embedding.provider only supports"):
            _validate_config_value(data)

    def test_unsupported_embedding_model_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["embedding"]["model"] = "other-model"
        with pytest.raises(ValidationError, match="embedding.model only supports"):
            _validate_config_value(data)

    def test_invalid_service_port_range_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["service"]["port"] = 99999
        with pytest.raises(
            ValidationError, match="service.port must be between 1 and 65535"
        ):
            _validate_config_value(data)

    def test_port_zero_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["service"]["port"] = 0
        with pytest.raises(
            ValidationError, match="service.port must be between 1 and 65535"
        ):
            _validate_config_value(data)

    def test_port_negative_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["service"]["port"] = -1
        with pytest.raises(
            ValidationError, match="service.port must be between 1 and 65535"
        ):
            _validate_config_value(data)

    def test_invalid_logging_level_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["logging"] = {"level": 42}
        with pytest.raises(ValidationError, match="logging.level must be str"):
            _validate_config_value(data)

    def test_unknown_logging_level_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["logging"]["level"] = "verbose"
        with pytest.raises(ValidationError, match="logging.level must be one of"):
            _validate_config_value(data)

    def test_logging_level_is_normalized(self) -> None:
        data = deepcopy(DEFAULTS)
        data["logging"]["level"] = "WARNING"
        _validate_config_value(data)
        assert data["logging"]["level"] == "warning"

    def test_invalid_directories_subkey_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["directories"] = {"data": 123}
        with pytest.raises(
            ValidationError, match="directories.data must be a string or null"
        ):
            _validate_config_value(data)

    def test_missing_section_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        del data["database"]
        with pytest.raises(ValidationError, match="database.path must be str"):
            _validate_config_value(data)

    def test_wrong_section_type_raises(self) -> None:
        data = deepcopy(DEFAULTS)
        data["database"] = "not-a-dict"
        with pytest.raises(ValidationError, match="database must be an object"):
            _validate_config_value(data)


# ---------------------------------------------------------------------------
# _write_starter_config / load_config_file
# ---------------------------------------------------------------------------


class TestWriteAndLoadConfigFile:
    def test_write_starter_creates_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)
        assert config_path.exists()
        loaded = json.loads(config_path.read_text())
        assert loaded == DEFAULTS

    def test_write_starter_creates_parent_dirs(self, tmp_path: Path) -> None:
        config_path = tmp_path / "deep" / "nested" / "config.json"
        _write_starter_config(config_path)
        assert config_path.exists()
        assert config_path.parent.is_dir()

    def test_write_starter_sets_permissions(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)
        stat = config_path.stat()
        assert stat.st_mode & 0o777 == 0o600
        assert config_path.parent.stat().st_mode & 0o777 == 0o700

    def test_ensure_config_directories_creates_private_dirs(
        self, tmp_path: Path
    ) -> None:
        paths = {
            "config": tmp_path / "config" / "recollectium",
            "data": tmp_path / "data" / "recollectium",
            "cache": tmp_path / "cache" / "recollectium",
            "logs": tmp_path / "state" / "recollectium" / "logs",
            "runtime": tmp_path / "runtime" / "recollectium",
        }

        _ensure_config_directories(paths)

        for directory in paths.values():
            assert directory.is_dir()
            assert directory.stat().st_mode & 0o777 == 0o700

    def test_load_config_file_reads_valid_json(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text('{"version": 1}', encoding="utf-8")
        result = load_config_file(config_path)
        assert result == {"version": 1}

    def test_load_config_file_missing_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="config file not found"):
            load_config_file(config_path)

    def test_load_config_file_malformed_json_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.json"
        config_path.write_text("{invalid", encoding="utf-8")
        with pytest.raises(ValidationError, match="invalid JSON"):
            load_config_file(config_path)


# ---------------------------------------------------------------------------
# validate_config_file
# ---------------------------------------------------------------------------


class TestValidateConfigFile:
    def test_valid_config_passes(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)
        validate_config_file(config_path)  # no raise

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("{bad", encoding="utf-8")
        with pytest.raises(ValidationError, match="invalid JSON"):
            validate_config_file(config_path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            validate_config_file(config_path)

    def test_invalid_value_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            '{"version": 1, "service": {"port": "bad"}}', encoding="utf-8"
        )
        with pytest.raises(ValidationError, match="service.port must be int"):
            validate_config_file(config_path)


# ---------------------------------------------------------------------------
# get_config_value / set_config_value / unset_config_value
# ---------------------------------------------------------------------------


class TestConfigValueAccessors:
    def test_get_top_level_key(self) -> None:
        value = get_config_value(DEFAULTS, "version")
        assert value == CONFIG_VERSION

    def test_get_nested_key(self) -> None:
        value = get_config_value(DEFAULTS, "service.port")
        assert value == 8765

    def test_get_deeply_nested_key(self) -> None:
        value = get_config_value(DEFAULTS, "embedding.model")
        assert value == "jinaai/jina-embeddings-v2-small-en"

    def test_get_missing_top_level_raises(self) -> None:
        with pytest.raises(KeyError, match="not found"):
            get_config_value(DEFAULTS, "nonexistent")

    def test_get_missing_nested_raises(self) -> None:
        with pytest.raises(KeyError, match="not found"):
            get_config_value(DEFAULTS, "service.nonexistent")

    def test_get_on_non_dict_raises(self) -> None:
        with pytest.raises(KeyError, match="cannot traverse"):
            get_config_value(DEFAULTS, "version.nope")

    def test_set_top_level_key(self) -> None:
        config = deepcopy(DEFAULTS)
        set_config_value(config, "newkey", "value")
        assert config["newkey"] == "value"

    def test_set_nested_key(self) -> None:
        config = deepcopy(DEFAULTS)
        set_config_value(config, "service.port", 9999)
        assert config["service"]["port"] == 9999

    def test_set_auto_creates_intermediate_dicts(self) -> None:
        config: dict[str, Any] = {}
        set_config_value(config, "a.b.c", 42)
        assert config == {"a": {"b": {"c": 42}}}

    def test_unset_removes_key(self) -> None:
        config = deepcopy(DEFAULTS)
        removed = unset_config_value(config, "service.port")
        assert removed == 8765
        assert "port" not in config["service"]

    def test_unset_top_level_raises_for_missing(self) -> None:
        config = deepcopy(DEFAULTS)
        with pytest.raises(KeyError, match="not found"):
            unset_config_value(config, "nonexistent")

    def test_unset_nested_raises_for_missing(self) -> None:
        config = deepcopy(DEFAULTS)
        with pytest.raises(KeyError, match="not found"):
            unset_config_value(config, "service.nonexistent")


# ---------------------------------------------------------------------------
# RecollectiumConfig
# ---------------------------------------------------------------------------


class TestRecollectiumConfig:
    def test_default_constructor_with_existing_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)
        cfg = RecollectiumConfig(config_path)
        assert cfg.config_file_path == config_path
        assert cfg.effective_config == DEFAULTS

    def test_explicit_path_missing_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nonexistent" / "config.json"
        with pytest.raises(FileNotFoundError, match="config file not found"):
            RecollectiumConfig(config_path)

    def test_malformed_config_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.json"
        config_path.write_text("{bad", encoding="utf-8")
        with pytest.raises(ValidationError, match="invalid JSON"):
            RecollectiumConfig(config_path)

    def test_effective_config_merges_overrides(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"service": {"port": 9999}}),
            encoding="utf-8",
        )
        cfg = RecollectiumConfig(config_path)
        assert cfg.effective_config["service"]["port"] == 9999
        assert cfg.effective_config["service"]["host"] == "127.0.0.1"

    def test_resolved_database_path_relative(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "database": {"path": "mydb.db"}}),
            encoding="utf-8",
        )
        cfg = RecollectiumConfig(config_path)
        # Relative path resolved against data dir
        assert cfg.resolved_database_path.name == "mydb.db"
        assert cfg.resolved_database_path.is_absolute()

    def test_resolved_database_path_absolute(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        abs_db = tmp_path / "absolute" / "mydb.db"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "database": {"path": str(abs_db)}}),
            encoding="utf-8",
        )
        cfg = RecollectiumConfig(config_path)
        assert cfg.resolved_database_path == abs_db

    def test_config_file_path_property(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)
        cfg = RecollectiumConfig(config_path)
        assert cfg.config_file_path == config_path

    def test_xdg_dirs_respects_overrides(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        custom_data = tmp_path / "custom-data"
        config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "directories": {"data": str(custom_data)},
                }
            ),
            encoding="utf-8",
        )
        cfg = RecollectiumConfig(config_path)
        assert cfg.xdg_dirs["data"] == custom_data

    def test_invalid_values_in_config_raise(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"version": 1, "service": {"port": "not-a-number"}}),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="service.port must be int"):
            RecollectiumConfig(config_path)

    def test_no_config_flag_auto_creates(self, monkeypatch, tmp_path: Path) -> None:
        # Simulate the no-explicit-path case by monkeypatching user_config_dir
        import recollectium.config as config_mod

        fake_config_dir = tmp_path / "xdg-config"
        monkeypatch.setattr(
            config_mod, "user_config_dir", lambda appname: str(fake_config_dir)
        )

        cfg = RecollectiumConfig()
        assert cfg.config_file_path == fake_config_dir / "config.json"
        assert cfg.config_file_path.exists()
        assert cfg.effective_config == DEFAULTS

    def test_default_config_load_creates_all_xdg_directories(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import recollectium.config as config_mod

        xdg_config = tmp_path / "config" / "recollectium"
        xdg_data = tmp_path / "data" / "recollectium"
        xdg_cache = tmp_path / "cache" / "recollectium"
        xdg_state = tmp_path / "state" / "recollectium"
        xdg_runtime = tmp_path / "runtime" / "recollectium"

        monkeypatch.setattr(
            config_mod, "user_config_dir", lambda appname: str(xdg_config)
        )
        monkeypatch.setattr(config_mod, "user_data_dir", lambda appname: str(xdg_data))
        monkeypatch.setattr(
            config_mod, "user_cache_dir", lambda appname: str(xdg_cache)
        )
        monkeypatch.setattr(
            config_mod, "user_state_dir", lambda appname: str(xdg_state)
        )
        monkeypatch.setattr(
            config_mod, "user_runtime_dir", lambda appname: str(xdg_runtime)
        )

        cfg = RecollectiumConfig()

        expected_dirs = {
            "config": xdg_config,
            "data": xdg_data,
            "cache": xdg_cache,
            "logs": xdg_state / "logs",
            "runtime": xdg_runtime,
        }
        assert cfg.xdg_dirs == expected_dirs
        for directory in expected_dirs.values():
            assert directory.is_dir()
            assert directory.stat().st_mode & 0o777 == 0o700

    def test_runtime_dir_fallback_when_user_runtime_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import recollectium.config as config_mod

        config_path = tmp_path / "config.json"
        _write_starter_config(config_path)

        monkeypatch.setattr(
            config_mod,
            "user_runtime_dir",
            lambda appname: None,
        )

        cfg = RecollectiumConfig(config_path)
        assert cfg.xdg_dirs["runtime"] is not None

    def test_unset_intermediate_key_missing(self) -> None:
        from recollectium.config import unset_config_value

        config = {"a": {}}
        with pytest.raises(KeyError, match="not found"):
            unset_config_value(config, "a.b.c")


# -- workspace.uid_normalization config -----------------------------------


def test_workspace_uid_normalization_default_in_defaults() -> None:
    from recollectium.config import DEFAULTS

    assert DEFAULTS["workspace"]["uid_normalization"] == "normalize"


def test_workspace_uid_normalization_rejects_invalid_value() -> None:
    from recollectium.config import _validate_config_value, _deep_merge, DEFAULTS
    from copy import deepcopy

    merged = _deep_merge(
        deepcopy(DEFAULTS), {"workspace": {"uid_normalization": "bogus"}}
    )
    with pytest.raises(ValidationError, match="workspace.uid_normalization"):
        _validate_config_value(merged)


def test_workspace_uid_normalization_accepts_exact() -> None:
    from recollectium.config import _validate_config_value, _deep_merge, DEFAULTS
    from copy import deepcopy

    merged = _deep_merge(
        deepcopy(DEFAULTS), {"workspace": {"uid_normalization": "exact"}}
    )
    _validate_config_value(merged)  # should not raise


def test_workspace_uid_normalization_accepts_normalize() -> None:
    from recollectium.config import _validate_config_value, _deep_merge, DEFAULTS
    from copy import deepcopy

    merged = _deep_merge(
        deepcopy(DEFAULTS), {"workspace": {"uid_normalization": "normalize"}}
    )
    _validate_config_value(merged)  # should not raise


def test_completable_config_keys_includes_workspace_uid_normalization() -> None:
    from recollectium.cli import _COMPLETABLE_CONFIG_KEYS

    assert "workspace.uid_normalization" in _COMPLETABLE_CONFIG_KEYS
