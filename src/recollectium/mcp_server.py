"""MCP server for Recollectium memory operations using FastMCP."""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from recollectium.core import RecollectiumCore
from recollectium.errors import RecollectiumError

_log = logging.getLogger(__name__)


def create_mcp_server(core: RecollectiumCore) -> FastMCP:
    """Create a FastMCP server with Recollectium memory tools."""

    mcp = FastMCP("Recollectium")

    @mcp.tool()
    def search_user_memory(
        query: str,
        type: str | None = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> str:
        """Search user-space memories by semantic similarity to the query."""
        try:
            results = core.search_user_memories(
                query=query,
                type=type,
                limit=limit,
                include_archived=include_archived,
            )
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "search_user_memory",
                extra={
                    "event": "mcp.search_user_memory_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def search_workspace_memory(
        query: str,
        workspace_uid: str,
        type: str | None = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> str:
        """Search workspace memories by semantic similarity to the query."""
        try:
            results = core.search_workspace_memories(
                query=query,
                workspace_uid=workspace_uid,
                type=type,
                limit=limit,
                include_archived=include_archived,
            )
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "search_workspace_memory",
                extra={
                    "event": "mcp.search_workspace_memory_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def add_memory(
        space: str,
        type: str,
        content: str,
        workspace_uid: str | None = None,
        metadata: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> str:
        """Add a new memory. Returns the created memory as JSON."""
        try:
            parsed_metadata: dict[str, object] | None = None
            if metadata is not None:
                try:
                    parsed_metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    return json.dumps(
                        {"error": "metadata must be valid JSON"}, sort_keys=True
                    )
                if not isinstance(parsed_metadata, dict):
                    return json.dumps(
                        {"error": "metadata must be a JSON object"}, sort_keys=True
                    )

            memory = core.add_memory(
                space=space,
                type=type,
                content=content,
                workspace_uid=workspace_uid,
                metadata=parsed_metadata,
                source=source,
                confidence=confidence,
                sensitivity=sensitivity,
            )
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "add_memory",
                extra={"event": "mcp.add_memory_failed", "context": {"error": str(e)}},
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def get_memory(id: str) -> str:
        """Get a single memory by ID. Returns the memory as JSON."""
        try:
            memory = core.get_memory(id)
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "get_memory",
                extra={"event": "mcp.get_memory_failed", "context": {"error": str(e)}},
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def update_memory(
        id: str,
        type: str | None = None,
        content: str | None = None,
        metadata: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> str:
        """Update an existing memory. Returns the updated memory as JSON."""
        try:
            parsed_metadata: dict[str, object] | None = None
            if metadata is not None:
                try:
                    parsed_metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    return json.dumps(
                        {"error": "metadata must be valid JSON"}, sort_keys=True
                    )
                if not isinstance(parsed_metadata, dict):
                    return json.dumps(
                        {"error": "metadata must be a JSON object"}, sort_keys=True
                    )

            memory = core.update_memory(
                id,
                type=type,
                content=content,
                metadata=parsed_metadata,
                source=source,
                confidence=confidence,
                sensitivity=sensitivity,
            )
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "update_memory",
                extra={
                    "event": "mcp.update_memory_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def archive_memory(id: str) -> str:
        """Archive a memory. Returns the archived memory as JSON."""
        try:
            memory = core.archive_memory(id)
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "archive_memory",
                extra={
                    "event": "mcp.archive_memory_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def list_memories(
        space: str | None = None,
        type: str | None = None,
        status: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> str:
        """List memories, optionally filtered by space, type, status, workspace UID, and limit."""
        try:
            results = core.list_memories(
                space=space,
                type=type,
                status=status,
                workspace_uid=workspace_uid,
                include_archived=include_archived,
                limit=limit,
            )
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "list_memories",
                extra={
                    "event": "mcp.list_memories_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def list_workspaces(
        include_archived: bool = False, include_aliases: bool = False
    ) -> str:
        """List known workspace UIDs, optionally with aliases."""
        try:
            uids = core.list_workspaces(
                include_archived=include_archived, include_aliases=include_aliases
            )
            return json.dumps(uids, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "list_workspaces",
                extra={
                    "event": "mcp.list_workspaces_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def resolve_workspace(uid: str) -> str:
        """Resolve a workspace UID candidate to its canonical UID."""
        try:
            return json.dumps(core.resolve_workspace(uid), sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "resolve_workspace",
                extra={
                    "event": "mcp.resolve_workspace_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def add_workspace_alias(
        canonical_uid: str, alias_uid: str, migrate_existing: bool = False
    ) -> str:
        """Create an alias for a canonical workspace UID."""
        try:
            result = core.add_workspace_alias(
                canonical_uid=canonical_uid,
                alias_uid=alias_uid,
                migrate_existing=migrate_existing,
            )
            return json.dumps(result, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "add_workspace_alias",
                extra={
                    "event": "mcp.add_workspace_alias_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def list_workspace_aliases(canonical_uid: str | None = None) -> str:
        """List workspace alias mappings, optionally filtered by canonical UID."""
        try:
            aliases = core.list_workspace_aliases(canonical_uid=canonical_uid)
            return json.dumps(aliases, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "list_workspace_aliases",
                extra={
                    "event": "mcp.list_workspace_aliases_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def remove_workspace_alias(alias_uid: str) -> str:
        """Remove a workspace alias mapping."""
        try:
            alias = core.remove_workspace_alias(alias_uid)
            return json.dumps(alias, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "remove_workspace_alias",
                extra={
                    "event": "mcp.remove_workspace_alias_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def rename_workspace(old_uid: str, new_uid: str) -> str:
        """Rename a workspace. Migrates all workspace memories from old_uid to new_uid."""
        try:
            result = core.rename_workspace(old_uid=old_uid, new_uid=new_uid)
            return json.dumps(result, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "rename_workspace",
                extra={
                    "event": "mcp.rename_workspace_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def embedding_status() -> str:
        """Get active local FastEmbed profile and startup job status."""
        try:
            status = core.active_embedding_status()
            return json.dumps(status, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "embedding_status",
                extra={
                    "event": "mcp.embedding_status_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def embedding_jobs(
        state: str | None = None,
        limit: int | None = None,
    ) -> str:
        """List embedding jobs, optionally filtered by state."""
        try:
            jobs = core.list_embedding_jobs(state=state, limit=limit)
            return json.dumps(jobs, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "embedding_jobs",
                extra={
                    "event": "mcp.embedding_jobs_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def get_embedding_job(job_id: str) -> str:
        """Get a single embedding job by ID."""
        try:
            job = core.get_embedding_job(job_id)
            return json.dumps(job, sort_keys=True)
        except RecollectiumError as e:
            _log.error(
                "MCP tool %s failed",
                "get_embedding_job",
                extra={
                    "event": "mcp.get_embedding_job_failed",
                    "context": {"error": str(e)},
                },
            )
            return json.dumps({"error": str(e)}, sort_keys=True)

    return mcp
