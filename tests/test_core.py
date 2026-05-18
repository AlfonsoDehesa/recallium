from pathlib import Path

import pytest

from recallium.core import RecalliumCore
from recallium.errors import NotFoundError, ValidationError
from recallium.models import SPACE_WORKSPACE, STATUS_ARCHIVED


def test_core_user_memory_flow_add_get_search_list_update_archive(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "core.db")

    created = core.add_memory(
        space="user",
        type="note",
        content="Need to fix bug before release",
        metadata={"source": "chat"},
    )

    assert created.id
    assert created.created_at
    assert created.updated_at

    fetched = core.get_memory(created.id)
    assert fetched.id == created.id
    assert fetched.last_accessed_at is not None

    search_results = core.search_user_memories("repair defect")
    assert [result.memory.id for result in search_results] == [created.id]

    listed = core.list_memories(space="user")
    assert [memory.id for memory in listed] == [created.id]

    updated = core.update_memory(created.id, content="Need to write release notes")
    assert updated.content == "Need to write release notes"
    assert updated.updated_at != created.updated_at

    refreshed_results = core.search_user_memories("release notes")
    assert refreshed_results[0].memory.id == created.id

    archived = core.archive_memory(created.id)
    assert archived.status == STATUS_ARCHIVED

    active_results = core.search_user_memories("release notes")
    assert active_results == []

    archived_results = core.search_user_memories("release notes", include_archived=True)
    assert [result.memory.id for result in archived_results] == [created.id]


def test_core_workspace_search_isolation_and_canonical_workspace_path(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "workspace.db")

    workspace_a_path = tmp_path / "projects" / "alpha"
    workspace_b_path = tmp_path / "projects" / "beta"

    workspace_a = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase milk",
        workspace_path=str(workspace_a_path),
    )
    workspace_b = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase bread",
        workspace_path=str(workspace_b_path),
    )

    assert workspace_a.workspace_path == str(workspace_a_path.resolve())

    search_a = core.search_workspace_memories(
        "buy milk", workspace_path=str(workspace_a_path)
    )
    assert [result.memory.id for result in search_a] == [workspace_a.id]

    search_b = core.search_workspace_memories(
        "buy milk", workspace_path=str(workspace_b_path)
    )
    assert [result.memory.id for result in search_b] == [workspace_b.id]

    combined = core.search_workspace_memories("buy")
    assert {result.memory.id for result in combined} == {workspace_a.id, workspace_b.id}

    user_results = core.search_user_memories("buy")
    assert user_results == []


def test_core_persistence_across_instances_and_not_found(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    first_core = RecalliumCore(db_path=db_path)
    created = first_core.add_memory(
        space="user", type="fact", content="Kaylee likes tea"
    )

    second_core = RecalliumCore(db_path=db_path)
    loaded = second_core.get_memory(created.id)
    assert loaded.content == "Kaylee likes tea"

    with pytest.raises(NotFoundError):
        second_core.get_memory("missing-id")


def test_workspace_methods_reject_mixed_workspace_id_and_workspace_path(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "mixed-workspace.db")

    with pytest.raises(ValidationError, match="both workspace_id and workspace_path"):
        core.add_memory(
            space=SPACE_WORKSPACE,
            type="task",
            content="Need to purchase milk",
            workspace_id="workspace-alpha",
            workspace_path=str(tmp_path / "alpha"),
        )

    with pytest.raises(ValidationError, match="both workspace_id and workspace_path"):
        core.search_workspace_memories(
            "buy milk",
            workspace_id="workspace-alpha",
            workspace_path=str(tmp_path / "alpha"),
        )

    with pytest.raises(ValidationError, match="both workspace_id and workspace_path"):
        core.list_memories(
            space=SPACE_WORKSPACE,
            workspace_id="workspace-alpha",
            workspace_path=str(tmp_path / "alpha"),
        )


def test_core_rejects_invalid_list_limit(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "limit.db")

    with pytest.raises(ValidationError, match="positive integer"):
        core.list_memories(limit=0)
