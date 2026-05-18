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
    parser = argparse.ArgumentParser(prog="recallium")
    parser.add_argument("--db", dest="db_path", help="SQLite database path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--space", required=True)
    add_parser.add_argument("--type", required=True)
    add_parser.add_argument("--content", required=True)
    add_parser.add_argument("--workspace-id")
    add_parser.add_argument("--workspace-path")
    add_parser.add_argument("--metadata")
    add_parser.add_argument("--source")
    add_parser.add_argument("--confidence", type=float)
    add_parser.add_argument("--sensitivity")

    search_user_parser = subparsers.add_parser("search-user")
    search_user_parser.add_argument("query")
    search_user_parser.add_argument("--limit", type=int, default=10)
    search_user_parser.add_argument("--include-archived", action="store_true")

    search_workspace_parser = subparsers.add_parser("search-workspace")
    search_workspace_parser.add_argument("query")
    search_workspace_parser.add_argument("--workspace-id")
    search_workspace_parser.add_argument("--workspace-path")
    search_workspace_parser.add_argument("--limit", type=int, default=10)
    search_workspace_parser.add_argument("--include-archived", action="store_true")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--space")
    list_parser.add_argument("--type")
    list_parser.add_argument("--status")
    list_parser.add_argument("--workspace-id")
    list_parser.add_argument("--workspace-path")
    list_parser.add_argument("--include-archived", action="store_true")
    list_parser.add_argument("--limit", type=int)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("memory_id")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("memory_id")
    update_parser.add_argument("--type")
    update_parser.add_argument("--content")
    update_parser.add_argument("--metadata")
    update_parser.add_argument("--source")
    update_parser.add_argument("--confidence", type=float)
    update_parser.add_argument("--sensitivity")

    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("memory_id")

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
                workspace_id=args.workspace_id,
                workspace_path=args.workspace_path,
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
                workspace_id=args.workspace_id,
                workspace_path=args.workspace_path,
                limit=args.limit,
                include_archived=args.include_archived,
            )
        elif args.command == "list":
            result = core.list_memories(
                space=args.space,
                type=args.type,
                status=args.status,
                workspace_id=args.workspace_id,
                workspace_path=args.workspace_path,
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
