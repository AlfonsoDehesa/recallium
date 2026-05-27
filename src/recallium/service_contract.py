"""Local service contract metadata and JSON-ready payload helpers."""

from __future__ import annotations

from typing import Any

from recallium import __version__
from recallium.models import Memory, SearchResult

SERVICE_API_VERSION = "1"
SERVICE_API_PREFIX = f"/v{SERVICE_API_VERSION}"
SERVICE_DEFAULT_HOST = "127.0.0.1"
SERVICE_DEFAULT_PORT = 8765

OPERATION_HEALTH_READ = "health.read"
OPERATION_VERSION_READ = "version.read"
OPERATION_CAPABILITIES_READ = "capabilities.read"
OPERATION_MEMORIES_SEARCH_USER = "memories.search_user"
OPERATION_MEMORIES_SEARCH_WORKSPACE = "memories.search_workspace"
OPERATION_MEMORIES_ADD = "memories.add"
OPERATION_MEMORIES_UPDATE = "memories.update"
OPERATION_MEMORIES_ARCHIVE = "memories.archive"
OPERATION_MEMORIES_LIST = "memories.list"
OPERATION_MEMORIES_GET = "memories.get"
OPERATION_EMBEDDING_STATUS = "embedding.status"
OPERATION_EMBEDDING_JOBS_LIST = "embedding.jobs.list"
OPERATION_EMBEDDING_JOBS_GET = "embedding.jobs.get"
OPERATION_WORKSPACES_LIST = "workspaces.list"
OPERATION_WORKSPACES_RENAME = "workspaces.rename"

SERVICE_CAPABILITIES = (
    OPERATION_HEALTH_READ,
    OPERATION_VERSION_READ,
    OPERATION_CAPABILITIES_READ,
    OPERATION_MEMORIES_SEARCH_USER,
    OPERATION_MEMORIES_SEARCH_WORKSPACE,
    OPERATION_MEMORIES_ADD,
    OPERATION_MEMORIES_UPDATE,
    OPERATION_MEMORIES_ARCHIVE,
    OPERATION_MEMORIES_LIST,
    OPERATION_MEMORIES_GET,
    OPERATION_EMBEDDING_STATUS,
    OPERATION_EMBEDDING_JOBS_LIST,
    OPERATION_EMBEDDING_JOBS_GET,
    OPERATION_WORKSPACES_LIST,
    OPERATION_WORKSPACES_RENAME,
)


def serialize_memory(memory: Memory) -> dict[str, Any]:
    return memory.to_dict()


def serialize_search_result(result: SearchResult) -> dict[str, Any]:
    return result.to_dict()


def serialize_memories(memories: list[Memory]) -> list[dict[str, Any]]:
    return [serialize_memory(memory) for memory in memories]


def serialize_search_results(results: list[SearchResult]) -> list[dict[str, Any]]:
    return [serialize_search_result(result) for result in results]


def serialize_embedding_status(status: dict[str, Any]) -> dict[str, Any]:
    return status


def serialize_embedding_job(job: dict[str, Any]) -> dict[str, Any]:
    return job


def serialize_embedding_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_embedding_job(job) for job in jobs]


def success_payload(data: Any) -> dict[str, Any]:
    return {"data": data}


def health_payload() -> dict[str, Any]:
    return success_payload({"status": "ok"})


def version_payload() -> dict[str, Any]:
    return success_payload(
        {
            "service_api_version": SERVICE_API_VERSION,
            "recallium_version": __version__,
        }
    )


def capabilities_payload() -> dict[str, Any]:
    return success_payload(
        {
            "service_api_version": SERVICE_API_VERSION,
            "capabilities": list(SERVICE_CAPABILITIES),
        }
    )


def error_payload(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
