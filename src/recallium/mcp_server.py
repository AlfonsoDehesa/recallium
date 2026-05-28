"""MCP server for Recallium memory operations using FastMCP."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from recallium.core import RecalliumCore
from recallium.errors import RecalliumError


def create_mcp_server(core: RecalliumCore) -> FastMCP:
    """Create a FastMCP server with Recallium memory tools."""

    mcp = FastMCP("Recallium")

    @mcp.tool()
    def search_user_memory(query: str, type: str | None = None, limit: int = 10) -> str:
        """Search user-space memories by semantic similarity to the query."""
        try:
            results = core.search_user_memories(query=query, type=type, limit=limit)
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def search_workspace_memory(
        query: str, workspace_uid: str, type: str | None = None, limit: int = 10
    ) -> str:
        """Search workspace memories by semantic similarity to the query."""
        try:
            results = core.search_workspace_memories(
                query=query, workspace_uid=workspace_uid, type=type, limit=limit
            )
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def add_memory(
        space: str,
        type: str,
        content: str,
        workspace_uid: str | None = None,
    ) -> str:
        """Add a new memory. Returns the created memory as JSON."""
        try:
            memory = core.add_memory(
                space=space,
                type=type,
                content=content,
                workspace_uid=workspace_uid,
            )
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def get_memory(id: str) -> str:
        """Get a single memory by ID. Returns the memory as JSON."""
        try:
            memory = core.get_memory(id)
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def update_memory(
        id: str, type: str | None = None, content: str | None = None
    ) -> str:
        """Update an existing memory. Returns the updated memory as JSON."""
        try:
            memory = core.update_memory(id, type=type, content=content)
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def archive_memory(id: str) -> str:
        """Archive a memory. Returns the archived memory as JSON."""
        try:
            memory = core.archive_memory(id)
            return json.dumps(memory.to_dict(), sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def list_memories(
        space: str | None = None,
        type: str | None = None,
        workspace_uid: str | None = None,
        limit: int | None = None,
    ) -> str:
        """List memories, optionally filtered by space, type, and workspace UID."""
        try:
            results = core.list_memories(
                space=space, type=type, workspace_uid=workspace_uid, limit=limit
            )
            return json.dumps([r.to_dict() for r in results], sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def list_workspaces(include_archived: bool = False) -> str:
        """List known workspace UIDs. Set include_archived to true to include UIDs that only have archived memories."""
        try:
            uids = core.list_workspaces(include_archived=include_archived)
            return json.dumps(uids, sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    @mcp.tool()
    def rename_workspace(old_uid: str, new_uid: str) -> str:
        """Rename a workspace. Migrates all workspace memories from old_uid to new_uid."""
        try:
            result = core.rename_workspace(old_uid=old_uid, new_uid=new_uid)
            return json.dumps(result, sort_keys=True)
        except RecalliumError as e:
            return json.dumps({"error": str(e)}, sort_keys=True)

    return mcp
