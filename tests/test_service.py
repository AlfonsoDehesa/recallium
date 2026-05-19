from pathlib import Path
import json
import re
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from recallium.core import RecalliumCore
from recallium.service import create_service_server
from recallium.service_contract import (
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

    assert "Documented known client-visible codes" in docs_text
    for error_code in (
        "unsupported_capability",
        "incompatible_version",
        "service_unavailable",
    ):
        assert error_code in docs_text

    assert "POST /v1/memories/{memory_id}/archive` is body-less." in docs_text


def test_local_service_openapi_contract_is_valid_and_covers_routes() -> None:
    openapi_path = (
        Path(__file__).resolve().parents[1] / "docs" / "local-service-openapi.json"
    )
    assert openapi_path.exists()

    contract = json.loads(openapi_path.read_text(encoding="utf-8"))
    assert contract["openapi"] == "3.1.0"

    info_description = contract["info"]["description"].lower()
    assert "localhost" in info_description or "local" in info_description
    assert "no authentication" in info_description or "no auth" in info_description
    assert contract["security"] == []

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
    }
    for path, methods in required_paths.items():
        assert path in paths
        for method in methods:
            assert method in paths[path]

    archive_operation = paths["/v1/memories/{memory_id}/archive"]["post"]
    assert "requestBody" not in archive_operation

    schemas = contract["components"]["schemas"]
    for schema_name in (
        "Memory",
        "SearchResult",
        "SuccessEnvelope",
        "ErrorEnvelope",
    ):
        assert schema_name in schemas


def _service_docs_section_for_route(docs_text: str, route: str) -> str:
    route_index = docs_text.index(route)
    next_heading_match = re.search(r"\n### ", docs_text[route_index + 1 :])
    if next_heading_match is None:
        return docs_text[route_index:]

    next_heading_index = route_index + 1 + next_heading_match.start()
    return docs_text[route_index:next_heading_index]


def _start_service(core: RecalliumCore) -> tuple[ThreadingHTTPServer, str, Thread]:
    server = create_service_server(core=core, host="127.0.0.1", port=0)
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    thread = Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, f"http://{host}:{port}", thread


def _request_json(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = None
    headers = {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", method=method, data=payload, headers=headers)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _request_raw(
    base_url: str,
    method: str,
    path: str,
    body: bytes,
) -> tuple[int, dict[str, Any]]:
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_metadata_routes_return_json(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-metadata.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_json(base_url, "GET", "/v1/health")
        assert status == 200
        assert payload == {"data": {"status": "ok"}}

        status, payload = _request_json(base_url, "GET", "/v1/version")
        assert status == 200
        assert payload["data"]["service_api_version"] == "1"

        status, payload = _request_json(base_url, "GET", "/v1/capabilities")
        assert status == 200
        assert payload["data"]["capabilities"] == list(SERVICE_CAPABILITIES)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_local_service_smoke_end_to_end(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-smoke.db")
    server, base_url, thread = _start_service(core)
    try:
        status, health = _request_json(base_url, "GET", "/v1/health")
        assert status == 200
        assert health == {"data": {"status": "ok"}}

        status, added = _request_json(
            base_url,
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
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_memory_routes_delegate_to_core(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-memory-routes.db")
    server, base_url, thread = _start_service(core)
    try:
        status, added_user = _request_json(
            base_url,
            "POST",
            "/v1/memories",
            {"space": "user", "type": "fact", "content": "Alfonso likes tea"},
        )
        assert status == 200
        user_id = str(added_user["data"]["id"])

        status, added_workspace = _request_json(
            base_url,
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

        status, list_payload = _request_json(base_url, "GET", "/v1/memories")
        assert status == 200
        assert {item["id"] for item in list_payload["data"]} == {user_id, workspace_id}

        status, search_user = _request_json(
            base_url,
            "POST",
            "/v1/memories/search_user",
            {"query": "likes tea"},
        )
        assert status == 200
        assert search_user["data"][0]["memory"]["id"] == user_id

        status, search_workspace = _request_json(
            base_url,
            "POST",
            "/v1/memories/search_workspace",
            {"query": "sqlite", "workspace_uid": "ws-1"},
        )
        assert status == 200
        assert search_workspace["data"][0]["memory"]["id"] == workspace_id

        status, got_memory = _request_json(base_url, "GET", f"/v1/memories/{user_id}")
        assert status == 200
        assert got_memory["data"]["id"] == user_id

        status, updated = _request_json(
            base_url,
            "PATCH",
            f"/v1/memories/{user_id}",
            {"content": "Alfonso likes green tea"},
        )
        assert status == 200
        assert updated["data"]["content"] == "Alfonso likes green tea"

        status, archived = _request_json(
            base_url,
            "POST",
            f"/v1/memories/{user_id}/archive",
        )
        assert status == 200
        assert archived["data"]["status"] == "archived"

        status, list_default = _request_json(base_url, "GET", "/v1/memories")
        assert status == 200
        listed_ids_default = {item["id"] for item in list_default["data"]}
        assert user_id not in listed_ids_default
        assert workspace_id in listed_ids_default

        status, list_with_archived = _request_json(
            base_url,
            "GET",
            "/v1/memories?include_archived=true",
        )
        assert status == 200
        listed_ids_all = {item["id"] for item in list_with_archived["data"]}
        assert user_id in listed_ids_all
        assert workspace_id in listed_ids_all
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_workspace_search_requires_workspace_uid(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-workspace-validation.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_json(
            base_url,
            "POST",
            "/v1/memories/search_workspace",
            {"query": "hello"},
        )
        assert status == 400
        assert payload["error"]["code"] == "validation_error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_unknown_route_returns_unsupported_operation(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-unknown-route.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_json(base_url, "GET", "/v1/nope")
        assert status == 404
        assert payload["error"]["code"] == "unsupported_operation"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_get_missing_memory_returns_not_found(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-missing-memory.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_json(base_url, "GET", "/v1/memories/missing-id")
        assert status == 404
        assert payload["error"]["code"] == "not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_invalid_json_returns_invalid_json_error(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-invalid-json.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_raw(
            base_url,
            "POST",
            "/v1/memories",
            b'{"space": "user",',
        )
        assert status == 400
        assert payload["error"]["code"] == "invalid_json"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_unsupported_method_returns_unsupported_operation(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-unsupported-method.db")
    server, base_url, thread = _start_service(core)
    try:
        status, payload = _request_json(base_url, "POST", "/v1/health")
        assert status == 404
        assert payload["error"]["code"] == "unsupported_operation"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_internal_error_is_mapped_without_traceback(tmp_path: Path) -> None:
    core = RecalliumCore(db_path=tmp_path / "service-internal-error.db")
    server, base_url, thread = _start_service(core)
    original = core.list_memories

    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("db blew up with private details")

    core.list_memories = boom
    try:
        status, payload = _request_json(base_url, "GET", "/v1/memories")
        assert status == 500
        assert payload["error"]["code"] == "internal_error"
        assert payload["error"]["message"] == "internal server error"
    finally:
        core.list_memories = original
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
