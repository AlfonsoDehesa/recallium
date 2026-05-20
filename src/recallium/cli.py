"""CLI entrypoint for Recallium Core."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from recallium import NotFoundError, RecalliumCore, RecalliumError, ValidationError
from recallium.config import (
    DEFAULTS,
    RecalliumConfig,
    get_config_value,
    load_config_file,
    set_config_value,
    unset_config_value,
    validate_config_file,
)
from recallium.models import SearchResult
from recallium.service import run_service
from recallium.service_contract import SERVICE_DEFAULT_HOST, SERVICE_DEFAULT_PORT
from recallium.storage import SQLiteMemoryStore


def _parse_metadata(raw_metadata: str | None) -> dict[str, object] | None:
    if raw_metadata is None:
        return None

    payload = raw_metadata
    if raw_metadata.startswith("@"):
        metadata_path = Path(raw_metadata[1:])
        payload = metadata_path.read_text(encoding="utf-8")

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"metadata must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValidationError("metadata must be a JSON object")
    return parsed


def _to_payload(data: Any) -> Any:
    if isinstance(data, SearchResult):
        return data.to_dict()
    if hasattr(data, "to_dict"):
        return data.to_dict()
    if isinstance(data, list):
        return [_to_payload(item) for item in data]
    return data


def _parse_config_value(raw: str) -> Any:
    """Parse a CLI-provided config value as JSON; fall back to string on failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError, ValueError:
        return raw


def _resolve_config_path(explicit_path: str | None) -> Path:
    """Resolve the config file path from --config flag or default XDG location."""
    from platformdirs import user_config_dir

    if explicit_path is not None:
        return Path(explicit_path)
    return Path(user_config_dir("recallium")) / "config.json"


def _core_config_path(explicit_path: str | None) -> Path | None:
    """Return only explicit config paths for core/service initialization."""
    if explicit_path is None:
        return None
    return Path(explicit_path)


def _load_effective_config(config_path: Path, *, explicit: bool) -> RecalliumConfig:
    """Load effective config with first-run default creation semantics."""
    if explicit:
        return RecalliumConfig(config_path)
    return RecalliumConfig()


def _handle_config_command(
    args: argparse.Namespace,
    config_path: Path,
    *,
    explicit: bool,
) -> int:
    """Handle the `recallium config` command and its subcommands."""
    if args.config_action == "get":
        try:
            cfg = _load_effective_config(config_path, explicit=explicit)
            value = get_config_value(cfg.effective_config, args.key)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except ValidationError as exc:
            print(f"ValidationError: {exc}", file=sys.stderr)
            return 2
        except KeyError as exc:
            print(f"key not found: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(value, sort_keys=True))
        return 0

    if args.config_action == "set":
        value = _parse_config_value(args.value)
        if not config_path.exists():
            config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
            )
            config_path.chmod(0o600)
        raw = load_config_file(config_path)
        set_config_value(raw, args.key, value)
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.config_action == "unset":
        if not config_path.exists():
            print(f"config file not found: {config_path}", file=sys.stderr)
            return 1
        raw = load_config_file(config_path)
        try:
            unset_config_value(raw, args.key)
        except KeyError as exc:
            print(f"key not found: {exc}", file=sys.stderr)
            return 1
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.config_action == "init":
        if config_path.exists() and not args.force:
            print(
                f"config file already exists: {config_path}\nuse --force to overwrite",
                file=sys.stderr,
            )
            return 1
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        return 0

    if args.validate:
        try:
            if explicit:
                validate_config_file(config_path)
            else:
                _load_effective_config(config_path, explicit=False)
        except ValidationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.path:
        print(str(config_path))
        return 0

    if args.defaults:
        print(json.dumps(DEFAULTS, indent=2, sort_keys=True))
        return 0

    # No subcommand or flag: print effective config
    try:
        cfg = _load_effective_config(config_path, explicit=explicit)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"ValidationError: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(cfg.effective_config, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recallium",
        description=(
            "Recallium Core local memory CLI. Commands print JSON on success and "
            "write validation or not-found errors to stderr."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help=(
            "Path to Recallium JSON config file. Defaults to the XDG config "
            "location and auto-creates there on first use. Explicit missing "
            "paths fail except config creation commands."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        help=(
            "SQLite database path. Overrides the database.path config value. "
            "Defaults to ~/.local/share/recallium/recallium.db."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="COMMAND",
    )

    # -- config ----------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config",
        help="inspect, validate, and edit Recallium configuration",
        description=(
            "Inspect, validate, and edit the Recallium JSON config file. "
            "Without arguments, prints the effective configuration (defaults "
            "merged with explicit overrides) as formatted JSON."
        ),
    )
    config_parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the config file and exit 0 on success or 1 on error.",
    )
    config_parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved config file path without creating a file.",
    )
    config_parser.add_argument(
        "--defaults",
        action="store_true",
        help="Print built-in default values as formatted JSON without creating a file.",
    )

    config_sub = config_parser.add_subparsers(
        dest="config_action",
        title="config actions",
        metavar="ACTION",
    )

    get_parser = config_sub.add_parser(
        "get",
        help="get a single config value by dot-notation key",
        description="Print the effective config value for a dot-notation key.",
    )
    get_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    )

    set_parser = config_sub.add_parser(
        "set",
        help="set a config value by dot-notation key",
        description="Write a value to the config file, auto-creating it if needed.",
    )
    set_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    )
    set_parser.add_argument(
        "value",
        help="Value to write. Parsed as JSON when possible; stored as string otherwise.",
    )

    unset_parser = config_sub.add_parser(
        "unset",
        help="remove a key from the config file",
        description="Remove a key from the config file so the built-in default applies.",
    )
    unset_parser.add_argument(
        "key",
        help='Dot-notation config key, e.g. "service.port".',
    )

    init_parser = config_sub.add_parser(
        "init",
        help="create or overwrite the starter config file",
        description="Create a starter config file with all built-in default values.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the config file if it already exists.",
    )

    # -- add --------------------------------------------------------------
    add_parser = subparsers.add_parser(
        "add",
        help="add a user or workspace memory",
        description=(
            "Add a memory to the local Recallium database. User memories must not "
            "include --workspace-uid. Workspace memories require --workspace-uid."
        ),
    )
    add_parser.add_argument(
        "--space",
        required=True,
        help="Memory space: 'user' for global user memory or 'workspace' for workspace memory.",
    )
    add_parser.add_argument(
        "--type",
        required=True,
        help="Free-form memory type, such as preference, fact, note, decision, or task_context.",
    )
    add_parser.add_argument(
        "--content",
        required=True,
        help="Memory text to store and embed for search.",
    )
    add_parser.add_argument(
        "--workspace-uid",
        help="Stable workspace UID. Required when --space workspace; forbidden when --space user.",
    )
    add_parser.add_argument(
        "--metadata",
        help="Optional JSON object metadata, either inline JSON or @path/to/file.json.",
    )
    add_parser.add_argument(
        "--source",
        help="Optional source label describing where the memory came from.",
    )
    add_parser.add_argument(
        "--confidence",
        type=float,
        help="Optional confidence score from 0.0 to 1.0.",
    )
    add_parser.add_argument(
        "--sensitivity",
        help="Optional sensitivity label for privacy-aware handling later.",
    )

    # -- search-user ------------------------------------------------------
    search_user_parser = subparsers.add_parser(
        "search-user",
        help="search global user memories",
        description="Search active user memories semantically and return ranked JSON results.",
    )
    search_user_parser.add_argument(
        "query", help="Search text to match against user memories."
    )
    search_user_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of ranked results to return. Must be positive. Defaults to 10.",
    )
    search_user_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in search candidates.",
    )

    # -- search-workspace -------------------------------------------------
    search_workspace_parser = subparsers.add_parser(
        "search-workspace",
        help="search memories for one workspace UID",
        description=(
            "Search active memories for a specific workspace UID and return ranked "
            "JSON results."
        ),
    )
    search_workspace_parser.add_argument(
        "query", help="Search text to match against workspace memories."
    )
    search_workspace_parser.add_argument(
        "--workspace-uid",
        required=True,
        help="Stable workspace UID whose memories should be searched.",
    )
    search_workspace_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of ranked results to return. Must be positive. Defaults to 10.",
    )
    search_workspace_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in search candidates.",
    )

    # -- list --------------------------------------------------------------
    list_parser = subparsers.add_parser(
        "list",
        help="list memories with optional filters",
        description=(
            "List memories as JSON, optionally filtered by space, type, status, "
            "workspace UID, or result limit. Archived memories are hidden unless "
            "requested."
        ),
    )
    list_parser.add_argument(
        "--space", help="Filter by memory space, usually 'user' or 'workspace'."
    )
    list_parser.add_argument("--type", help="Filter by memory type.")
    list_parser.add_argument(
        "--status", help="Filter by memory status, such as active or archived."
    )
    list_parser.add_argument(
        "--workspace-uid", help="Filter to memories for one stable workspace UID."
    )
    list_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived memories in list results.",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of memories to return. Must be positive.",
    )

    # -- get ---------------------------------------------------------------
    get_parser = subparsers.add_parser(
        "get",
        help="retrieve one memory by ID",
        description="Retrieve one memory by its ID and print it as JSON.",
    )
    get_parser.add_argument("memory_id", help="Memory ID to retrieve.")

    # -- update ------------------------------------------------------------
    update_parser = subparsers.add_parser(
        "update",
        help="update editable memory fields",
        description=(
            "Update one or more editable fields on a memory. Updating --content "
            "also regenerates that memory's embedding."
        ),
    )
    update_parser.add_argument("memory_id", help="Memory ID to update.")
    update_parser.add_argument("--type", help="Replacement memory type.")
    update_parser.add_argument(
        "--content", help="Replacement memory text. Regenerates the stored embedding."
    )
    update_parser.add_argument(
        "--metadata",
        help="Replacement JSON object metadata, either inline JSON or @path/to/file.json.",
    )
    update_parser.add_argument(
        "--source",
        help="Replacement source label describing where the memory came from.",
    )
    update_parser.add_argument(
        "--confidence",
        type=float,
        help="Replacement confidence score from 0.0 to 1.0.",
    )
    update_parser.add_argument(
        "--sensitivity",
        help="Replacement sensitivity label for privacy-aware handling later.",
    )

    # -- archive -----------------------------------------------------------
    archive_parser = subparsers.add_parser(
        "archive",
        help="archive one memory by ID",
        description=(
            "Archive a memory by ID. Archived memories are hidden from default list "
            "and search results but are not hard-deleted."
        ),
    )
    archive_parser.add_argument("memory_id", help="Memory ID to archive.")

    # -- serve -------------------------------------------------------------
    serve_parser = subparsers.add_parser(
        "serve",
        help="run the local Recallium HTTP service",
        description=(
            "Start a blocking local-only HTTP JSON service for Recallium Core. "
            "By default it binds to localhost (127.0.0.1), exposes the /v1 "
            "service API, and keeps running until interrupted. Host and port "
            "can be set via config file or CLI flags. CLI flags override config."
        ),
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help=(
            "Host interface to bind. Overrides service.host from config. "
            "Defaults to 127.0.0.1."
        ),
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "TCP port for the local service API. Overrides service.port from config. "
            "Defaults to 8765."
        ),
    )

    # -- db-status ---------------------------------------------------------
    subparsers.add_parser(
        "db-status",
        help="show database schema migration status",
        description=(
            "Show SQLite migration status as JSON for the selected database path. "
            "This command initializes the database if needed and reports current "
            "and pending schema versions."
        ),
    )

    # -- embedding-status --------------------------------------------------
    subparsers.add_parser(
        "embedding-status",
        help="show active local FastEmbed profile and startup job",
        description=(
            "Show the active built-in local FastEmbed embedding profile plus startup "
            "re-embedding job metadata. Recallium uses the local model cache for "
            "jinaai/jina-embeddings-v2-small-en."
        ),
    )

    # -- embedding-jobs ----------------------------------------------------
    embedding_jobs_parser = subparsers.add_parser(
        "embedding-jobs",
        help="list embedding jobs or fetch one job by id",
        description=(
            "List embedding jobs by default or fetch one job with --job-id. "
            "Jobs track local FastEmbed model download and re-embedding progress."
        ),
    )
    embedding_jobs_parser.add_argument(
        "--job-id",
        help="If provided, return exactly one embedding job by ID.",
    )
    embedding_jobs_parser.add_argument(
        "--state",
        help="Optional list filter by job state, such as pending, in_progress, completed, or failed.",
    )
    embedding_jobs_parser.add_argument(
        "--limit",
        type=int,
        help="Optional positive integer limit for list mode.",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Recallium CLI."""
    parser = _build_parser()
    if argv == [] or (argv is None and len(sys.argv) == 1):
        parser.print_help()
        return 0
    args = parser.parse_args(argv)

    # Resolve config path
    config_path = _resolve_config_path(args.config_path)
    core_config_path = _core_config_path(args.config_path)

    # -- config command ---------------------------------------------------
    if args.command == "config":
        return _handle_config_command(
            args,
            config_path,
            explicit=args.config_path is not None,
        )

    # -- serve command ----------------------------------------------------
    if args.command == "serve":
        # Resolve host/port from config or defaults
        host = args.host
        port = args.port
        if host is None or port is None:
            try:
                cfg = RecalliumConfig(core_config_path)
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except ValidationError as exc:
                print(f"ValidationError: {exc}", file=sys.stderr)
                return 2
            if host is None:
                host = (
                    cfg.effective_config["service"]["host"]
                    if cfg
                    else SERVICE_DEFAULT_HOST
                )
            if port is None:
                port = (
                    cfg.effective_config["service"]["port"]
                    if cfg
                    else SERVICE_DEFAULT_PORT
                )
        try:
            run_service(
                host=host,
                port=port,
                db_path=args.db_path,
                config_path=core_config_path,
            )
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except ValidationError as exc:
            print(f"ValidationError: {exc}", file=sys.stderr)
            return 2
        return 0

    # -- db-status command ------------------------------------------------
    if args.command == "db-status":
        if args.db_path:
            db_path = Path(args.db_path)
        else:
            try:
                cfg = RecalliumConfig(core_config_path)
                db_path = cfg.resolved_database_path
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except ValidationError as exc:
                print(f"ValidationError: {exc}", file=sys.stderr)
                return 2
        store = SQLiteMemoryStore(db_path)
        print(json.dumps(store.migration_status(), sort_keys=True))
        return 0

    # -- all other commands use RecalliumCore ------------------------------
    try:
        core = RecalliumCore(db_path=args.db_path, config_path=core_config_path)

        if args.command == "add":
            result = core.add_memory(
                space=args.space,
                type=args.type,
                content=args.content,
                workspace_uid=args.workspace_uid,
                metadata=_parse_metadata(args.metadata),
                source=args.source,
                confidence=args.confidence,
                sensitivity=args.sensitivity,
            )
        elif args.command == "search-user":
            result = core.search_user_memories(
                query=args.query,
                limit=args.limit,
                include_archived=args.include_archived,
            )
        elif args.command == "search-workspace":
            result = core.search_workspace_memories(
                query=args.query,
                workspace_uid=args.workspace_uid,
                limit=args.limit,
                include_archived=args.include_archived,
            )
        elif args.command == "list":
            result = core.list_memories(
                space=args.space,
                type=args.type,
                status=args.status,
                workspace_uid=args.workspace_uid,
                include_archived=args.include_archived,
                limit=args.limit,
            )
        elif args.command == "get":
            result = core.get_memory(args.memory_id)
        elif args.command == "update":
            result = core.update_memory(
                args.memory_id,
                type=args.type,
                content=args.content,
                metadata=_parse_metadata(args.metadata),
                source=args.source,
                confidence=args.confidence,
                sensitivity=args.sensitivity,
            )
        elif args.command == "archive":
            result = core.archive_memory(args.memory_id)
        elif args.command == "embedding-status":
            result = core.active_embedding_status()
        elif args.command == "embedding-jobs":
            if args.job_id:
                result = core.get_embedding_job(args.job_id)
            else:
                result = core.list_embedding_jobs(state=args.state, limit=args.limit)
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
    except ValidationError as exc:
        print(f"ValidationError: {exc}", file=sys.stderr)
        return 2
    except NotFoundError as exc:
        print(f"NotFoundError: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RecalliumError as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_payload(result), sort_keys=True))
    return 0
