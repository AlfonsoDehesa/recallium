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


def test_core_workspace_search_isolation_by_workspace_uid(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "workspace.db")

    workspace_a = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase milk",
        workspace_uid="workspace-alpha",
    )
    workspace_b = core.add_memory(
        space=SPACE_WORKSPACE,
        type="task",
        content="Need to purchase bread",
        workspace_uid="workspace-beta",
    )

    assert workspace_a.workspace_uid == "workspace-alpha"

    search_a = core.search_workspace_memories(
        "buy milk", workspace_uid="workspace-alpha"
    )
    assert [result.memory.id for result in search_a] == [workspace_a.id]

    search_b = core.search_workspace_memories(
        "buy milk", workspace_uid="workspace-beta"
    )
    assert [result.memory.id for result in search_b] == [workspace_b.id]

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


def test_workspace_identity_validation(
    tmp_path: Path,
) -> None:
    core = RecalliumCore(db_path=tmp_path / "workspace-uid.db")

    with pytest.raises(ValidationError, match="workspace_uid is required"):
        core.add_memory(
            space=SPACE_WORKSPACE,
            type="task",
            content="Need to purchase milk",
        )

    with pytest.raises(ValidationError, match="user memories must not include"):
        core.add_memory(
            space="user",
            type="preference",
            content="I like short answers",
            workspace_uid="workspace-alpha",
        )

    with pytest.raises(ValidationError, match="workspace_uid"):
        core.search_workspace_memories("buy milk", workspace_uid=" ")


def test_core_rejects_invalid_list_limit(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "limit.db")

    with pytest.raises(ValidationError, match="positive integer"):
        core.list_memories(limit=0)
