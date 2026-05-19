"""CLI entrypoint for Recallium Core."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from recallium import NotFoundError, RecalliumCore, ValidationError
from recallium.models import SearchResult


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recallium",
        description=(
            "Recallium Core local memory CLI. Commands print JSON on success and "
            "write validation or not-found errors to stderr."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        help=(
            "SQLite database path. Defaults to ~/.local/share/recallium/recallium.db."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="COMMAND",
    )

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

    get_parser = subparsers.add_parser(
        "get",
        help="retrieve one memory by ID",
        description="Retrieve one memory by its ID and print it as JSON.",
    )
    get_parser.add_argument("memory_id", help="Memory ID to retrieve.")

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

    archive_parser = subparsers.add_parser(
        "archive",
        help="archive one memory by ID",
        description=(
            "Archive a memory by ID. Archived memories are hidden from default list "
            "and search results but are not hard-deleted."
        ),
    )
    archive_parser.add_argument("memory_id", help="Memory ID to archive.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Recallium CLI."""
    parser = _build_parser()
    if argv == [] or (argv is None and len(sys.argv) == 1):
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    core = RecalliumCore(db_path=args.db_path)

    try:
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
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
    except ValidationError as exc:
        print(f"ValidationError: {exc}", file=sys.stderr)
        return 2
    except NotFoundError as exc:
        print(f"NotFoundError: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_payload(result), sort_keys=True))
    return 0
