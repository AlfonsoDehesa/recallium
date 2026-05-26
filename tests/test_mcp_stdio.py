"""Integration tests for MCP stdio server tool registration and round-trips."""

from __future__ import annotations

import json
from pathlib import Path

from recallium.core import RecalliumCore
from recallium.mcp_server import create_mcp_server


def test_create_mcp_server_registers_tools(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    tools = mcp._tool_manager._tools
    expected = {
        "search_user_memory",
        "search_workspace_memory",
        "add_memory",
        "get_memory",
        "update_memory",
        "archive_memory",
        "list_memories",
    }
    assert set(tools.keys()) == expected


def test_mcp_tool_add_memory_round_trip(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    add_fn = mcp._tool_manager._tools["add_memory"].fn
    result_json = add_fn(space="user", type="preference", content="I prefer dark mode")
    memory = json.loads(result_json)
    assert memory["space"] == "user"
    assert memory["type"] == "preference"
    assert memory["content"] == "I prefer dark mode"
    assert "id" in memory

    list_fn = mcp._tool_manager._tools["list_memories"].fn
    list_json = list_fn(space="user")
    memories = json.loads(list_json)
    assert len(memories) >= 1
    assert memories[0]["content"] == "I prefer dark mode"


def test_mcp_tool_search_user_memory(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    added = core.add_memory(
        space="user", type="fact", content="Recallium stores memories locally"
    )
    mcp = create_mcp_server(core)

    search_fn = mcp._tool_manager._tools["search_user_memory"].fn
    result_json = search_fn(query="local memory storage")
    results = json.loads(result_json)
    assert len(results) >= 1
    assert results[0]["memory"]["id"] == added.id
    assert results[0]["memory"]["content"] == "Recallium stores memories locally"


def test_mcp_tool_get_memory(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    added = core.add_memory(space="user", type="fact", content="Get this memory")
    mcp = create_mcp_server(core)

    get_fn = mcp._tool_manager._tools["get_memory"].fn
    result_json = get_fn(id=added.id)
    memory = json.loads(result_json)
    assert memory["id"] == added.id
    assert memory["content"] == "Get this memory"
    assert memory["space"] == "user"


def test_mcp_tool_archive_memory(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    added = core.add_memory(space="user", type="note", content="Old idea to archive")
    mcp = create_mcp_server(core)

    archive_fn = mcp._tool_manager._tools["archive_memory"].fn
    result_json = archive_fn(id=added.id)
    archived = json.loads(result_json)
    assert archived["id"] == added.id
    assert archived["status"] == "archived"

    list_fn = mcp._tool_manager._tools["list_memories"].fn
    list_json = list_fn(space="user")
    memories = json.loads(list_json)
    assert all(m["id"] != added.id for m in memories)


def test_mcp_tool_update_memory(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    added = core.add_memory(space="user", type="fact", content="Original content")
    mcp = create_mcp_server(core)

    update_fn = mcp._tool_manager._tools["update_memory"].fn
    result_json = update_fn(id=added.id, content="Updated content")
    updated = json.loads(result_json)
    assert updated["id"] == added.id
    assert updated["content"] == "Updated content"


def test_mcp_tool_errors(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    add_fn = mcp._tool_manager._tools["add_memory"].fn
    result_json = add_fn(space="invalid", type="test", content="test content")
    data = json.loads(result_json)
    assert "error" in data
    assert "space must be one of" in data["error"]


def test_search_user_memory_validation_error(tmp_path: Path) -> None:
    """search_user_memory with an empty query returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    search_fn = mcp._tool_manager._tools["search_user_memory"].fn
    result_json = search_fn(query="", limit=5)
    data = json.loads(result_json)
    assert "error" in data


def test_search_workspace_memory_missing_workspace_uid(tmp_path: Path) -> None:
    """search_workspace_memory with an empty workspace UID returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    search_fn = mcp._tool_manager._tools["search_workspace_memory"].fn
    result_json = search_fn(query="test query", workspace_uid="", limit=5)
    data = json.loads(result_json)
    assert "error" in data


def test_update_memory_not_found_error(tmp_path: Path) -> None:
    """update_memory with a non-existent ID returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    update_fn = mcp._tool_manager._tools["update_memory"].fn
    result_json = update_fn(id="nonexistent-id", content="new content")
    data = json.loads(result_json)
    assert "error" in data


def test_archive_memory_not_found_error(tmp_path: Path) -> None:
    """archive_memory with a non-existent ID returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    archive_fn = mcp._tool_manager._tools["archive_memory"].fn
    result_json = archive_fn(id="nonexistent-id")
    data = json.loads(result_json)
    assert "error" in data


def test_get_memory_not_found_error(tmp_path: Path) -> None:
    """get_memory with a non-existent ID returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    get_fn = mcp._tool_manager._tools["get_memory"].fn
    result_json = get_fn(id="nonexistent-id")
    data = json.loads(result_json)
    assert "error" in data


def test_add_memory_workspace_space_mismatch(tmp_path: Path) -> None:
    """add_memory with workspace space but no workspace_uid returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    add_fn = mcp._tool_manager._tools["add_memory"].fn
    result_json = add_fn(space="workspace", type="test", content="test content")
    data = json.loads(result_json)
    assert "error" in data
    assert "workspace_uid is required" in data["error"]


def test_list_memories_invalid_limit(tmp_path: Path) -> None:
    """list_memories with an invalid limit returns an error JSON."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    mcp = create_mcp_server(core)

    list_fn = mcp._tool_manager._tools["list_memories"].fn
    result_json = list_fn(limit=0)
    data = json.loads(result_json)
    assert "error" in data
    assert "limit must be" in data["error"]


def test_search_workspace_memory_round_trip(tmp_path: Path) -> None:
    """search_workspace_memory returns an added workspace memory."""
    db_path = str(tmp_path / "test.db")
    core = RecalliumCore(db_path=db_path)
    added = core.add_memory(
        space="workspace",
        type="fact",
        content="This project uses SQLite",
        workspace_uid="test-ws",
    )
    mcp = create_mcp_server(core)

    search_fn = mcp._tool_manager._tools["search_workspace_memory"].fn
    result_json = search_fn(query="SQLite database", workspace_uid="test-ws")
    results = json.loads(result_json)
    assert len(results) >= 1
    assert results[0]["memory"]["id"] == added.id
