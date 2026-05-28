"""FastAPI local HTTP JSON service for Recallium Core."""

from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from recallium.core import RecalliumCore
from recallium.errors import (
    EmbeddingDimensionMismatchError,
    EmbeddingGenerationError,
    EmbeddingModelUnavailableError,
    EmbeddingProviderUnavailableError,
    EmbeddingReadinessTimeoutError,
    NotFoundError,
    ReembeddingFailedError,
    ReembeddingInProgressError,
    ValidationError,
)
from recallium.mcp_server import create_mcp_server
from recallium.service_contract import (
    SERVICE_API_PREFIX,
    SERVICE_DEFAULT_HOST,
    SERVICE_DEFAULT_PORT,
    capabilities_payload,
    error_payload,
    health_payload,
    serialize_embedding_job,
    serialize_embedding_jobs,
    serialize_embedding_status,
    serialize_memories,
    serialize_memory,
    serialize_search_results,
    success_payload,
    version_payload,
)


_BOUNDARY_ERROR_MAP: tuple[tuple[type[Exception], HTTPStatus, str], ...] = (
    (ValidationError, HTTPStatus.BAD_REQUEST, "validation_error"),
    (NotFoundError, HTTPStatus.NOT_FOUND, "not_found"),
    (
        EmbeddingReadinessTimeoutError,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "embedding_readiness_timeout",
    ),
    (
        EmbeddingProviderUnavailableError,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "embedding_provider_unavailable",
    ),
    (
        EmbeddingModelUnavailableError,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "embedding_model_unavailable",
    ),
    (
        EmbeddingDimensionMismatchError,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "embedding_profile_mismatch",
    ),
    (
        EmbeddingGenerationError,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "embedding_generation_failed",
    ),
    (
        ReembeddingInProgressError,
        HTTPStatus.CONFLICT,
        "reembedding_in_progress",
    ),
    (
        ReembeddingFailedError,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "reembedding_failed",
    ),
    (json.JSONDecodeError, HTTPStatus.BAD_REQUEST, "invalid_json"),
)


class SearchUserRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1)
    include_archived: bool = False


class SearchWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1)
    workspace_uid: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1)
    include_archived: bool = False


class AddMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    space: str = Field(min_length=1)
    type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    workspace_uid: str | None = None
    metadata: dict[str, object] | None = None
    source: str | None = None
    confidence: float | None = None
    sensitivity: str | None = None


class UpdateMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    content: str | None = None
    metadata: dict[str, object] | None = None
    source: str | None = None
    confidence: float | None = None
    sensitivity: str | None = None


class RenameWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    new_uid: str = Field(min_length=1)


def _map_boundary_error(exc: Exception) -> tuple[HTTPStatus, dict[str, Any]]:
    for error_type, status, code in _BOUNDARY_ERROR_MAP:
        if isinstance(exc, error_type):
            if isinstance(exc, json.JSONDecodeError):
                return status, error_payload(code, f"invalid JSON: {exc.msg}")
            if isinstance(exc, ReembeddingInProgressError | ReembeddingFailedError):
                return (
                    status,
                    error_payload(
                        code,
                        str(exc),
                        details={
                            "job_id": exc.job_id,
                            "status_path": exc.status_path,
                        },
                    ),
                )
            return status, error_payload(code, str(exc))
    return (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        error_payload("internal_error", "internal server error"),
    )


def _json_response(status: HTTPStatus, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=int(status), content=payload)


def _parse_optional_bool(raw: str | None, *, field_name: str) -> bool | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValidationError(f"{field_name} must be true or false")


def _parse_optional_positive_int(raw: str | None, *, field_name: str) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be a positive integer") from exc
    if value < 1:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


def create_app(core: RecalliumCore) -> FastAPI:
    app = FastAPI(
        title="Recallium Core Local Service API",
        version="1",
        description=(
            "Local-only HTTP JSON service contract for Recallium Core. This slice "
            "is localhost-first and intentionally has no authentication. Do not "
            "expose this service publicly."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED}:
            return _json_response(
                HTTPStatus.NOT_FOUND,
                error_payload("unsupported_operation", "unsupported operation"),
            )
        return _json_response(
            HTTPStatus(exc.status_code),
            error_payload("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        for error in exc.errors():
            if error.get("type") == "json_invalid":
                return _json_response(
                    HTTPStatus.BAD_REQUEST,
                    error_payload("invalid_json", "invalid JSON"),
                )
        return _json_response(
            HTTPStatus.BAD_REQUEST,
            error_payload("validation_error", "request validation failed"),
        )

    @app.exception_handler(Exception)
    async def handle_boundary_exception(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        status, payload = _map_boundary_error(exc)
        return _json_response(status, payload)

    @app.get(f"{SERVICE_API_PREFIX}/health", tags=["service"])
    def health() -> dict[str, Any]:
        return health_payload()

    @app.get(f"{SERVICE_API_PREFIX}/version", tags=["service"])
    def version() -> dict[str, Any]:
        return version_payload()

    @app.get(f"{SERVICE_API_PREFIX}/capabilities", tags=["service"])
    def capabilities() -> dict[str, Any]:
        return capabilities_payload()

    @app.post(f"{SERVICE_API_PREFIX}/memories/search_user", tags=["memories"])
    def search_user(body: SearchUserRequest) -> dict[str, Any]:
        results = core.search_user_memories(
            query=body.query,
            limit=body.limit,
            include_archived=body.include_archived,
        )
        return success_payload(serialize_search_results(results))

    @app.post(f"{SERVICE_API_PREFIX}/memories/search_workspace", tags=["memories"])
    def search_workspace(body: SearchWorkspaceRequest) -> dict[str, Any]:
        results = core.search_workspace_memories(
            query=body.query,
            workspace_uid=body.workspace_uid,
            limit=body.limit,
            include_archived=body.include_archived,
        )
        return success_payload(serialize_search_results(results))

    @app.get(f"{SERVICE_API_PREFIX}/embedding/status", tags=["embedding"])
    def embedding_status() -> dict[str, Any]:
        status = core.active_embedding_status()
        return success_payload(serialize_embedding_status(status))

    @app.get(f"{SERVICE_API_PREFIX}/embedding/jobs", tags=["embedding"])
    def list_embedding_jobs(
        state: str | None = None,
        limit: str | None = None,
    ) -> dict[str, Any]:
        jobs = core.list_embedding_jobs(
            state=state,
            limit=_parse_optional_positive_int(limit, field_name="limit"),
        )
        return success_payload(serialize_embedding_jobs(jobs))

    @app.get(f"{SERVICE_API_PREFIX}/embedding/jobs/{{job_id}}", tags=["embedding"])
    def get_embedding_job(job_id: str) -> dict[str, Any]:
        job = core.get_embedding_job(job_id)
        return success_payload(serialize_embedding_job(job))

    @app.post(f"{SERVICE_API_PREFIX}/memories", tags=["memories"])
    def add_memory(body: AddMemoryRequest) -> dict[str, Any]:
        memory = core.add_memory(
            space=body.space,
            type=body.type,
            content=body.content,
            workspace_uid=body.workspace_uid,
            metadata=body.metadata,
            source=body.source,
            confidence=body.confidence,
            sensitivity=body.sensitivity,
        )
        return success_payload(serialize_memory(memory))

    @app.get(f"{SERVICE_API_PREFIX}/memories", tags=["memories"])
    def list_memories(
        space: str | None = None,
        type: str | None = None,
        status: str | None = None,
        workspace_uid: str | None = None,
        include_archived: str | None = None,
        limit: str | None = None,
    ) -> dict[str, Any]:
        parsed_include_archived = _parse_optional_bool(
            include_archived,
            field_name="include_archived",
        )
        memories = core.list_memories(
            space=space,
            type=type,
            status=status,
            workspace_uid=workspace_uid,
            include_archived=parsed_include_archived
            if parsed_include_archived is not None
            else False,
            limit=_parse_optional_positive_int(limit, field_name="limit"),
        )
        return success_payload(serialize_memories(memories))

    @app.get(f"{SERVICE_API_PREFIX}/memories/{{memory_id}}", tags=["memories"])
    def get_memory(memory_id: str) -> dict[str, Any]:
        memory = core.get_memory(memory_id)
        return success_payload(serialize_memory(memory))

    @app.patch(f"{SERVICE_API_PREFIX}/memories/{{memory_id}}", tags=["memories"])
    def update_memory(memory_id: str, body: UpdateMemoryRequest) -> dict[str, Any]:
        memory = core.update_memory(
            memory_id,
            content=body.content,
            type=body.type,
            metadata=body.metadata,
            source=body.source,
            confidence=body.confidence,
            sensitivity=body.sensitivity,
        )
        return success_payload(serialize_memory(memory))

    @app.post(
        f"{SERVICE_API_PREFIX}/memories/{{memory_id}}/archive",
        tags=["memories"],
    )
    def archive_memory(memory_id: str) -> dict[str, Any]:
        memory = core.archive_memory(memory_id)
        return success_payload(serialize_memory(memory))

    # -- workspace endpoints -----------------------------------------------

    @app.get(f"{SERVICE_API_PREFIX}/workspaces", tags=["workspaces"])
    def list_workspaces(
        include_archived: str | None = None,
    ) -> dict[str, Any]:
        parsed_include_archived = _parse_optional_bool(
            include_archived,
            field_name="include_archived",
        )
        uids = core.list_workspaces(
            include_archived=parsed_include_archived
            if parsed_include_archived is not None
            else False,
        )
        return success_payload(uids)

    @app.post(
        f"{SERVICE_API_PREFIX}/workspaces/{{uid}}/rename",
        tags=["workspaces"],
    )
    def rename_workspace(uid: str, body: RenameWorkspaceRequest) -> dict[str, Any]:
        result = core.rename_workspace(old_uid=uid, new_uid=body.new_uid)
        return success_payload(result)

    return app


def create_mcp_app(core: RecalliumCore) -> FastAPI:
    mcp = create_mcp_server(core)
    app = FastAPI(
        title="Recallium MCP Server",
        version="1",
        description="Local-only MCP server for Recallium Core.",
    )
    app.mount("/", mcp.sse_app())
    return app


def run_service(
    host: str = SERVICE_DEFAULT_HOST,
    port: int = SERVICE_DEFAULT_PORT,
    db_path: str | None = None,
    config_path: str | Path | None = None,
    service_type: str | None = None,
    log_level: str | None = None,
) -> None:
    import uvicorn

    core = RecalliumCore(db_path=db_path, config_path=config_path, log_level=log_level)
    log_level = core.config.effective_config["logging"]["level"]

    # Block until the embedding model is ready before accepting connections.
    try:
        core._ensure_model_ready()
    except Exception as exc:
        import sys

        print(f"recallium serve: model readiness failed: {exc}", file=sys.stderr)
        print(
            "Check your internet connection and try 'recallium init' again.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    if service_type == "mcp":
        app = create_mcp_app(core)
    else:
        app = create_app(core)

    uvicorn.run(app, host=host, port=port, log_level=log_level, log_config=None)
