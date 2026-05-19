"""Local HTTP JSON service route dispatch for Recallium Core."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from recallium.core import RecalliumCore
from recallium.errors import NotFoundError, ValidationError
from recallium.service_contract import (
    SERVICE_API_PREFIX,
    SERVICE_DEFAULT_HOST,
    SERVICE_DEFAULT_PORT,
    capabilities_payload,
    error_payload,
    health_payload,
    serialize_memories,
    serialize_memory,
    serialize_search_results,
    success_payload,
    version_payload,
)


_BOUNDARY_ERROR_MAP: tuple[tuple[type[Exception], HTTPStatus, str], ...] = (
    (ValidationError, HTTPStatus.BAD_REQUEST, "validation_error"),
    (NotFoundError, HTTPStatus.NOT_FOUND, "not_found"),
    (json.JSONDecodeError, HTTPStatus.BAD_REQUEST, "invalid_json"),
)


def _map_boundary_error(exc: Exception) -> tuple[HTTPStatus, dict[str, Any]]:
    for error_type, status, code in _BOUNDARY_ERROR_MAP:
        if isinstance(exc, error_type):
            if isinstance(exc, json.JSONDecodeError):
                return status, error_payload(code, f"invalid JSON: {exc.msg}")
            return status, error_payload(code, str(exc))
    return (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        error_payload("internal_error", "internal server error"),
    )


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


def _query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _require_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value


def create_request_handler(
    core: RecalliumCore,
) -> type[BaseHTTPRequestHandler]:
    class RecalliumServiceHandler(BaseHTTPRequestHandler):
        _core = core

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def _dispatch(self, method: str) -> None:
            try:
                self._handle_request(method)
            except Exception as exc:
                status, payload = _map_boundary_error(exc)
                self._send_json(status, payload)

        def _handle_request(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if method == "GET" and path == f"{SERVICE_API_PREFIX}/health":
                self._send_json(HTTPStatus.OK, health_payload())
                return
            if method == "GET" and path == f"{SERVICE_API_PREFIX}/version":
                self._send_json(HTTPStatus.OK, version_payload())
                return
            if method == "GET" and path == f"{SERVICE_API_PREFIX}/capabilities":
                self._send_json(HTTPStatus.OK, capabilities_payload())
                return
            if (
                method == "POST"
                and path == f"{SERVICE_API_PREFIX}/memories/search_user"
            ):
                self._handle_search_user()
                return
            if (
                method == "POST"
                and path == f"{SERVICE_API_PREFIX}/memories/search_workspace"
            ):
                self._handle_search_workspace()
                return
            if method == "POST" and path == f"{SERVICE_API_PREFIX}/memories":
                self._handle_add_memory()
                return
            if method == "GET" and path == f"{SERVICE_API_PREFIX}/memories":
                self._handle_list_memories(parsed.query)
                return

            path_parts = [part for part in path.split("/") if part]
            if len(path_parts) == 3 and path_parts[:2] == ["v1", "memories"]:
                memory_id = path_parts[2]
                if method == "GET":
                    memory = self._core.get_memory(memory_id)
                    self._send_json(
                        HTTPStatus.OK, success_payload(serialize_memory(memory))
                    )
                    return
                if method == "PATCH":
                    self._handle_update_memory(memory_id)
                    return

            if len(path_parts) == 4 and path_parts[:2] == ["v1", "memories"]:
                memory_id = path_parts[2]
                if method == "POST" and path_parts[3] == "archive":
                    memory = self._core.archive_memory(memory_id)
                    self._send_json(
                        HTTPStatus.OK, success_payload(serialize_memory(memory))
                    )
                    return

            self._send_json(
                HTTPStatus.NOT_FOUND,
                error_payload("unsupported_operation", "unsupported operation"),
            )

        def _read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                raise ValidationError("JSON body is required")
            payload = self.rfile.read(content_length)
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValidationError("JSON body must be an object")
            return body

        def _handle_search_user(self) -> None:
            body = self._read_json_body()
            results = self._core.search_user_memories(
                query=_require_string(body, "query"),
                limit=body.get("limit", 10),
                include_archived=body.get("include_archived", False),
            )
            self._send_json(
                HTTPStatus.OK,
                success_payload(serialize_search_results(results)),
            )

        def _handle_search_workspace(self) -> None:
            body = self._read_json_body()
            results = self._core.search_workspace_memories(
                query=_require_string(body, "query"),
                workspace_uid=body.get("workspace_uid"),
                limit=body.get("limit", 10),
                include_archived=body.get("include_archived", False),
            )
            self._send_json(
                HTTPStatus.OK,
                success_payload(serialize_search_results(results)),
            )

        def _handle_add_memory(self) -> None:
            body = self._read_json_body()
            memory = self._core.add_memory(
                space=_require_string(body, "space"),
                type=_require_string(body, "type"),
                content=_require_string(body, "content"),
                workspace_uid=body.get("workspace_uid"),
                metadata=body.get("metadata"),
                source=body.get("source"),
                confidence=body.get("confidence"),
                sensitivity=body.get("sensitivity"),
            )
            self._send_json(HTTPStatus.OK, success_payload(serialize_memory(memory)))

        def _handle_update_memory(self, memory_id: str) -> None:
            body = self._read_json_body()
            memory = self._core.update_memory(
                memory_id,
                content=body.get("content"),
                type=body.get("type"),
                metadata=body.get("metadata"),
                source=body.get("source"),
                confidence=body.get("confidence"),
                sensitivity=body.get("sensitivity"),
            )
            self._send_json(HTTPStatus.OK, success_payload(serialize_memory(memory)))

        def _handle_list_memories(self, query_text: str) -> None:
            query = parse_qs(query_text)
            include_archived = _parse_optional_bool(
                _query_value(query, "include_archived"),
                field_name="include_archived",
            )
            memories = self._core.list_memories(
                space=_query_value(query, "space"),
                type=_query_value(query, "type"),
                status=_query_value(query, "status"),
                workspace_uid=_query_value(query, "workspace_uid"),
                include_archived=include_archived
                if include_archived is not None
                else False,
                limit=_parse_optional_positive_int(
                    _query_value(query, "limit"),
                    field_name="limit",
                ),
            )
            self._send_json(
                HTTPStatus.OK, success_payload(serialize_memories(memories))
            )

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RecalliumServiceHandler


def create_service_server(
    core: RecalliumCore, host: str, port: int
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), create_request_handler(core))


def run_service(
    host: str = SERVICE_DEFAULT_HOST,
    port: int = SERVICE_DEFAULT_PORT,
    db_path: str | None = None,
) -> None:
    core = RecalliumCore(db_path=db_path)
    server = create_service_server(core, host, port)
    with server:
        server.serve_forever()
