from pathlib import Path
import json
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

from recallium.core import RecalliumCore
from recallium.errors import ValidationError
from recallium.service import (
    _map_boundary_error,
    _parse_optional_bool,
    _parse_optional_positive_int,
    create_app,
    run_service,
)
from recallium.service_contract import (
    OPERATION_EMBEDDING_JOBS_GET,
    OPERATION_EMBEDDING_JOBS_LIST,
    OPERATION_EMBEDDING_STATUS,
    OPERATION_CAPABILITIES_READ,
    OPERATION_HEALTH_READ,
    OPERATION_MEMORIES_ADD,
    OPERATION_MEMORIES_ARCHIVE,
    OPERATION_MEMORIES_GET,
    OPERATION_MEMORIES_LIST,
    OPERATION_MEMORIES_SEARCH_USER,
    OPERATION_MEMORIES_SEARCH_WORKSPACE,
    OPERATION_MEMORIES_UPDATE,
    OPERATION_VERSION_READ,
    SERVICE_API_VERSION,
    SERVICE_CAPABILITIES,
    capabilities_payload,
    error_payload,
    health_payload,
    serialize_embedding_job,
    serialize_embedding_jobs,
    serialize_embedding_status,
    serialize_memories,
    serialize_memory,
    serialize_search_result,
    serialize_search_results,
    success_payload,
    version_payload,
)


def test_service_capabilities_cover_required_operations() -> None:
    assert SERVICE_CAPABILITIES == (
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
    )


def test_metadata_payload_helpers_are_stable() -> None:
    assert health_payload() == {"data": {"status": "ok"}}

    version = version_payload()
    assert version["data"]["service_api_version"] == SERVICE_API_VERSION
    assert isinstance(version["data"]["recallium_version"], str)

    capabilities = capabilities_payload()
    assert capabilities["data"] == {
        "service_api_version": SERVICE_API_VERSION,
        "capabilities": list(SERVICE_CAPABILITIES),
    }


def test_error_payload_shape_is_stable() -> None:
    assert error_payload("validation_error", "bad request") == {
        "error": {
            "code": "validation_error",
            "message": "bad request",
            "details": {},
        }
    }
    assert error_payload(
        "validation_error",
        "bad request",
        details={"field": "workspace_uid"},
    ) == {
        "error": {
            "code": "validation_error",
            "message": "bad request",
            "details": {"field": "workspace_uid"},
        }
    }


def test_serializers_use_existing_models(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-contract.db")
    memory = core.add_memory(
        space="user",
        type="fact",
        content="Kaylee likes tea",
        metadata={"source": "chat"},
    )
    results = core.search_user_memories("likes tea")

    serialized_memory = serialize_memory(memory)
    assert serialized_memory["id"] == memory.id
    assert serialized_memory["metadata"] == {"source": "chat"}

    serialized_memories = serialize_memories([memory])
    assert serialized_memories == [memory.to_dict()]

    serialized_result = serialize_search_result(results[0])
    assert serialized_result["memory"]["id"] == memory.id
    assert serialized_result["rank"] == 1

    serialized_results = serialize_search_results(results)
    assert serialized_results == [result.to_dict() for result in results]

    status = {"provider_status": "configured"}
    assert serialize_embedding_status(status) is status

    job = {"id": "job-1"}
    assert serialize_embedding_job(job) is job
    assert serialize_embedding_jobs([job]) == [job]


def test_success_payload_wraps_data_without_mutation() -> None:
    data = [{"id": "m-1"}, {"id": "m-2"}]
    assert success_payload(data) == {"data": data}


def test_local_service_docs_cover_request_and_response_behavior_for_all_routes() -> (
    None
):
    docs_path = Path(__file__).resolve().parents[1] / "docs" / "local-service-api.md"
    assert docs_path.exists()

    docs_text = docs_path.read_text(encoding="utf-8")
    routes = {
        "GET /v1/health": {"require_request": False},
        "GET /v1/version": {"require_request": False},
        "GET /v1/capabilities": {"require_request": False},
        "POST /v1/memories/search_user": {"require_request": True},
        "POST /v1/memories/search_workspace": {"require_request": True},
        "POST /v1/memories": {"require_request": True},
        "PATCH /v1/memories/{memory_id}": {"require_request": True},
        "POST /v1/memories/{memory_id}/archive": {"require_request": True},
        "GET /v1/memories": {"require_request": True},
        "GET /v1/memories/{memory_id}": {"require_request": True},
        "GET /v1/embedding/status": {"require_request": False},
        "GET /v1/embedding/jobs": {"require_request": False},
        "GET /v1/embedding/jobs/{job_id}": {"require_request": False},
    }

    for route, constraints in routes.items():
        assert route in docs_text
        section = _service_docs_section_for_route(docs_text, route)
        assert "Purpose:" in section
        if constraints["require_request"]:
            assert "Example request:" in section
            assert "curl" in section
        assert "Example response:" in section or "Response example:" in section
        assert '"data":' in section

    for error_code in (
        "embedding_provider_unavailable",
        "embedding_model_unavailable",
        "embedding_generation_failed",
        "embedding_profile_mismatch",
        "embedding_readiness_timeout",
        "reembedding_in_progress",
        "reembedding_failed",
    ):
        assert error_code in docs_text

    assert "POST /v1/memories/{memory_id}/archive` is body-less." in docs_text


def test_local_service_openapi_contract_is_valid_and_covers_routes(
    tmp_path: Path,
) -> None:
    openapi_path = (
        Path(__file__).resolve().parents[1] / "docs" / "local-service-openapi.json"
    )
    assert openapi_path.exists()

    contract = json.loads(openapi_path.read_text(encoding="utf-8"))
    app = create_app(RecalliumCore(db_path=tmp_path / "openapi.db"))
    assert contract == app.openapi()
    assert contract["openapi"] == "3.1.0"

    info_description = contract["info"]["description"].lower()
    assert "localhost" in info_description or "local" in info_description
    assert "no authentication" in info_description or "no auth" in info_description

    paths = contract["paths"]
    required_paths = {
        "/v1/health": ["get"],
        "/v1/version": ["get"],
        "/v1/capabilities": ["get"],
        "/v1/memories/search_user": ["post"],
        "/v1/memories/search_workspace": ["post"],
        "/v1/memories": ["post", "get"],
        "/v1/memories/{memory_id}": ["patch", "get"],
        "/v1/memories/{memory_id}/archive": ["post"],
        "/v1/embedding/status": ["get"],
        "/v1/embedding/jobs": ["get"],
        "/v1/embedding/jobs/{job_id}": ["get"],
    }
    for path, methods in required_paths.items():
        assert path in paths
        for method in methods:
            assert method in paths[path]

    archive_operation = paths["/v1/memories/{memory_id}/archive"]["post"]
    assert "requestBody" not in archive_operation

    schemas = contract["components"]["schemas"]
    for schema_name in (
        "AddMemoryRequest",
        "SearchUserRequest",
        "SearchWorkspaceRequest",
        "UpdateMemoryRequest",
    ):
        assert schema_name in schemas


def _service_docs_section_for_route(docs_text: str, route: str) -> str:
    route_index = docs_text.index(route)
    next_heading_match = re.search(r"\n### ", docs_text[route_index + 1 :])
    if next_heading_match is None:
        return docs_text[route_index:]

    next_heading_index = route_index + 1 + next_heading_match.start()
    return docs_text[route_index:next_heading_index]


def _client(core: RecalliumCore) -> TestClient:
    return TestClient(create_app(core), raise_server_exceptions=False)


def _request_json(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    response = client.request(method, path, json=body)
    return response.status_code, response.json()


def _request_raw(
    client: TestClient,
    method: str,
    path: str,
    body: bytes,
) -> tuple[int, dict[str, Any]]:
    response = client.request(
        method,
        path,
        content=body,
        headers={"Content-Type": "application/json"},
    )
    return response.status_code, response.json()


def test_http_metadata_routes_return_json(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-metadata.db")
    client = _client(core)

    status, payload = _request_json(client, "GET", "/v1/health")
    assert status == 200
    assert payload == {"data": {"status": "ok"}}

    status, payload = _request_json(client, "GET", "/v1/version")
    assert status == 200
    assert payload["data"]["service_api_version"] == "1"

    status, payload = _request_json(client, "GET", "/v1/capabilities")
    assert status == 200
    assert payload["data"]["capabilities"] == list(SERVICE_CAPABILITIES)


def test_http_local_service_smoke_end_to_end(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-smoke.db")
    client = _client(core)

    status, health = _request_json(client, "GET", "/v1/health")
    assert status == 200
    assert health == {"data": {"status": "ok"}}

    status, added = _request_json(
        client,
        "POST",
        "/v1/memories",
        {
            "space": "user",
            "type": "fact",
            "content": "smoke test memory",
        },
    )
    assert status == 200
    assert added["data"]["content"] == "smoke test memory"
    assert added["data"]["space"] == "user"


def test_http_memory_routes_delegate_to_core(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-memory-routes.db")
    client = _client(core)

    status, added_user = _request_json(
        client,
        "POST",
        "/v1/memories",
        {"space": "user", "type": "fact", "content": "Alfonso likes tea"},
    )
    assert status == 200
    user_id = str(added_user["data"]["id"])

    status, added_workspace = _request_json(
        client,
        "POST",
        "/v1/memories",
        {
            "space": "workspace",
            "type": "decision",
            "content": "Use sqlite for local db",
            "workspace_uid": "ws-1",
        },
    )
    assert status == 200
    workspace_id = str(added_workspace["data"]["id"])

    status, list_payload = _request_json(client, "GET", "/v1/memories")
    assert status == 200
    assert {item["id"] for item in list_payload["data"]} == {user_id, workspace_id}

    status, search_user = _request_json(
        client,
        "POST",
        "/v1/memories/search_user",
        {"query": "likes tea"},
    )
    assert status == 200
    assert search_user["data"][0]["memory"]["id"] == user_id

    status, search_workspace = _request_json(
        client,
        "POST",
        "/v1/memories/search_workspace",
        {"query": "sqlite", "workspace_uid": "ws-1"},
    )
    assert status == 200
    assert search_workspace["data"][0]["memory"]["id"] == workspace_id

    status, got_memory = _request_json(client, "GET", f"/v1/memories/{user_id}")
    assert status == 200
    assert got_memory["data"]["id"] == user_id

    status, updated = _request_json(
        client,
        "PATCH",
        f"/v1/memories/{user_id}",
        {"content": "Alfonso likes green tea"},
    )
    assert status == 200
    assert updated["data"]["content"] == "Alfonso likes green tea"

    status, archived = _request_json(
        client,
        "POST",
        f"/v1/memories/{user_id}/archive",
    )
    assert status == 200
    assert archived["data"]["status"] == "archived"

    status, list_default = _request_json(client, "GET", "/v1/memories")
    assert status == 200
    listed_ids_default = {item["id"] for item in list_default["data"]}
    assert user_id not in listed_ids_default
    assert workspace_id in listed_ids_default

    status, list_with_archived = _request_json(
        client,
        "GET",
        "/v1/memories?include_archived=true",
    )
    assert status == 200
    listed_ids_all = {item["id"] for item in list_with_archived["data"]}
    assert user_id in listed_ids_all
    assert workspace_id in listed_ids_all

    status, embedding_status = _request_json(client, "GET", "/v1/embedding/status")
    assert status == 200
    assert (
        embedding_status["data"]["embedding_profile"]["provider"] == "builtin-fastembed"
    )
    assert embedding_status["data"]["provider_status"] == "configured"
    assert embedding_status["data"]["model_status"] == "managed_by_fastembed_cache"
    assert embedding_status["data"]["runtime"] == {
        "name": "fastembed",
        "threads": 1,
        "parallel": None,
    }

    status, jobs_payload = _request_json(client, "GET", "/v1/embedding/jobs")
    assert status == 200
    jobs = jobs_payload["data"]
    assert isinstance(jobs, list)
    if jobs:
        job_id = jobs[0]["id"]
        status, one_job = _request_json(client, "GET", f"/v1/embedding/jobs/{job_id}")
        assert status == 200
        assert one_job["data"]["id"] == job_id

    status, limited_jobs = _request_json(client, "GET", "/v1/embedding/jobs?limit=1")
    assert status == 200
    assert len(limited_jobs["data"]) <= 1


def test_http_query_parsers_accept_valid_values_and_reject_bad_values() -> None:
    assert _parse_optional_bool(None, field_name="include_archived") is None
    assert _parse_optional_bool(" TRUE ", field_name="include_archived") is True
    assert _parse_optional_bool("false", field_name="include_archived") is False

    with pytest.raises(ValidationError, match="include_archived"):
        _parse_optional_bool("yes", field_name="include_archived")

    assert _parse_optional_positive_int(None, field_name="limit") is None
    assert _parse_optional_positive_int("3", field_name="limit") == 3

    with pytest.raises(ValidationError, match="positive integer"):
        _parse_optional_positive_int("nope", field_name="limit")

    with pytest.raises(ValidationError, match="positive integer"):
        _parse_optional_positive_int("0", field_name="limit")


def test_http_invalid_query_params_return_validation_errors(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-query-validation.db")
    client = _client(core)

    status, payload = _request_json(client, "GET", "/v1/memories?include_archived=yes")
    assert status == 400
    assert payload["error"]["code"] == "validation_error"

    status, payload = _request_json(client, "GET", "/v1/embedding/jobs?limit=0")
    assert status == 400
    assert payload["error"]["code"] == "validation_error"


def test_http_workspace_search_requires_workspace_uid(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-workspace-validation.db")
    client = _client(core)

    status, payload = _request_json(
        client,
        "POST",
        "/v1/memories/search_workspace",
        {"query": "hello"},
    )
    assert status == 400
    assert payload["error"]["code"] == "validation_error"


def test_http_unknown_route_returns_unsupported_operation(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-unknown-route.db")
    client = _client(core)

    status, payload = _request_json(client, "GET", "/v1/nope")
    assert status == 404
    assert payload["error"]["code"] == "unsupported_operation"


def test_http_exception_handler_preserves_other_http_errors(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-http-error.db")
    app = create_app(core)

    from fastapi import HTTPException

    @app.get("/boom")
    def boom() -> None:
        raise HTTPException(status_code=418, detail="short and stout")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")
    assert response.status_code == 418
    assert response.json()["error"] == {
        "code": "http_error",
        "message": "short and stout",
        "details": {},
    }


def test_http_get_missing_memory_returns_not_found(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-missing-memory.db")
    client = _client(core)

    status, payload = _request_json(client, "GET", "/v1/memories/missing-id")
    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_http_get_missing_embedding_job_returns_not_found(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-missing-job.db")
    client = _client(core)

    status, payload = _request_json(client, "GET", "/v1/embedding/jobs/missing-job")

    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_http_get_embedding_job_returns_existing_job(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-existing-job.db")
    job = core.store.create_embedding_job(
        job_id="job-1",
        state="completed",
        total_count=1,
        processed_count=1,
        succeeded_count=1,
        failed_count=0,
        provider="test",
        model="fake",
        embedding_profile={"provider": "test", "model": "fake", "dimensions": 3},
    )
    client = _client(core)

    status, payload = _request_json(client, "GET", f"/v1/embedding/jobs/{job['id']}")

    assert status == 200
    assert payload["data"]["id"] == "job-1"


def test_http_invalid_json_returns_invalid_json_error(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-invalid-json.db")
    client = _client(core)

    status, payload = _request_raw(
        client,
        "POST",
        "/v1/memories",
        b'{"space": "user",',
    )
    assert status == 400
    assert payload["error"]["code"] == "invalid_json"


def test_http_unsupported_method_returns_unsupported_operation(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-unsupported-method.db")
    client = _client(core)

    status, payload = _request_json(client, "POST", "/v1/health")
    assert status == 404
    assert payload["error"]["code"] == "unsupported_operation"


def test_http_internal_error_is_mapped_without_traceback(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-internal-error.db")
    client = _client(core)
    original = core.list_memories

    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("db blew up with private details")

    core.list_memories = boom
    try:
        status, payload = _request_json(client, "GET", "/v1/memories")
        assert status == 500
        assert payload["error"]["code"] == "internal_error"
        assert payload["error"]["message"] == "internal server error"
    finally:
        core.list_memories = original


def test_http_embedding_errors_map_to_stable_boundary_codes(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-embedding-errors.db")
    client = _client(core)
    original = core.search_user_memories

    from recallium.errors import (
        EmbeddingDimensionMismatchError,
        EmbeddingGenerationError,
        EmbeddingModelUnavailableError,
        EmbeddingProviderUnavailableError,
        EmbeddingReadinessTimeoutError,
        ReembeddingFailedError,
        ReembeddingInProgressError,
    )

    error_cases = [
        (
            EmbeddingReadinessTimeoutError("FastEmbed provider startup timed out"),
            503,
            "embedding_readiness_timeout",
        ),
        (
            EmbeddingProviderUnavailableError("FastEmbed is unavailable"),
            503,
            "embedding_provider_unavailable",
        ),
        (
            EmbeddingModelUnavailableError("failed to load embedding model"),
            503,
            "embedding_model_unavailable",
        ),
        (
            EmbeddingDimensionMismatchError("unexpected embedding dimension"),
            500,
            "embedding_profile_mismatch",
        ),
        (
            EmbeddingGenerationError("failed to generate embedding"),
            500,
            "embedding_generation_failed",
        ),
        (
            ReembeddingFailedError(
                "runtime re-embedding failed",
                job_id="job-failed",
                status_path="/v1/embedding/jobs/job-failed",
            ),
            503,
            "reembedding_failed",
        ),
    ]

    def reembedding_in_progress(*args: Any, **kwargs: Any) -> list[Any]:
        raise ReembeddingInProgressError(
            "re-embedding is in progress for the active profile",
            job_id="job-123",
            status_path="/v1/embedding/jobs/job-123",
        )

    core.search_user_memories = reembedding_in_progress
    try:
        status, payload = _request_json(
            client,
            "POST",
            "/v1/memories/search_user",
            {"query": "test"},
        )
        assert status == 409
        assert payload["error"]["code"] == "reembedding_in_progress"
        assert payload["error"]["details"] == {
            "job_id": "job-123",
            "status_path": "/v1/embedding/jobs/job-123",
        }

        for error, expected_status, expected_code in error_cases:

            def raise_error(*args: Any, **kwargs: Any) -> list[Any]:
                raise error

            core.search_user_memories = raise_error
            status, payload = _request_json(
                client,
                "POST",
                "/v1/memories/search_user",
                {"query": "test"},
            )
            assert status == expected_status
            assert payload["error"]["code"] == expected_code

            if expected_code == "reembedding_failed":
                assert payload["error"]["details"] == {
                    "job_id": "job-failed",
                    "status_path": "/v1/embedding/jobs/job-failed",
                }
    finally:
        core.search_user_memories = original


def test_boundary_error_maps_json_decode_error_message() -> None:
    error = json.JSONDecodeError("missing value", "{", 1)

    status, payload = _map_boundary_error(error)

    assert status == 400
    assert payload["error"]["code"] == "invalid_json"
    assert payload["error"]["message"] == "invalid JSON: missing value"


def test_run_service_builds_core_and_starts_uvicorn(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeCore:
        def __init__(
            self, *, db_path: str | None, config_path: str | None = None
        ) -> None:
            calls["db_path"] = db_path
            self.config = type(
                "FakeConfig",
                (),
                {"effective_config": {"logging": {"level": "debug"}}},
            )()

    def fake_create_app(core: object) -> str:
        calls["core"] = core
        return "fake-app"

    def fake_run(app: object, *, host: str, port: int, log_level: str) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port
        calls["log_level"] = log_level

    monkeypatch.setattr("recallium.service.RecalliumCore", FakeCore)
    monkeypatch.setattr("recallium.service.create_app", fake_create_app)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    run_service(host="127.0.0.2", port=9002, db_path="service.db")

    assert calls["db_path"] == "service.db"
    assert calls["app"] == "fake-app"
    assert calls["host"] == "127.0.0.2"
    assert calls["port"] == 9002
    assert calls["log_level"] == "debug"
