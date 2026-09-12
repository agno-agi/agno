"""Bounded ASGI admission in front of the existing AgentOS routes."""

from __future__ import annotations

import asyncio
import inspect
import json
import zlib
from ipaddress import IPv6Address, ip_address, ip_network
from pathlib import PurePath
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette._utils import get_route_path
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse

from agno.os.auth import require_verified_public_workflow, verify_internal_service_request
from agno.os.public import _client_id
from agno.os.public._execution import _authorize, _resolutions
from agno.os.public._policy import RUN_ROUTE, PublicRoutePolicy
from agno.utils.bounded import BoundedWorkers
from agno.utils.log import log_warning

IDENTITY_WORKERS = BoundedWorkers(8, "public-identity")
MAX_PENDING_WEBSOCKETS = 32


class Rejected(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def _uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value.lower():
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise Rejected(400, "invalid_handle") from exc


class PublicMiddleware:
    def __init__(self, app: Any, *, surface: Any, agent_os: Any, policy: Optional[PublicRoutePolicy] = None):
        self.app, self.surface, self.agent_os = app, surface, agent_os
        self.policy = policy or PublicRoutePolicy(surface, agent_os)
        self.active_runs = self.active_mcp = 0
        self.pending_websockets = 0
        self.selected = self.policy.selected
        self.registered = {
            kind: {component.id for component in getattr(agent_os, kind) or []} for kind in self.selected
        }
        self.oauth_paths = self.policy.oauth_paths
        self.interface_routes = set(getattr(agent_os, "_public_interface_routes", []))

    async def _admit_execution(self, action: str, identity: str) -> None:
        decision = await self.surface.limiter.aconsume("cancel" if action == "cancel" else "run", client_id=identity)
        if not decision.allowed:
            raise HTTPException(429, "rate_limited", headers={"Retry-After": str(decision.retry_after)})
        if action != "cancel":
            if self.active_runs >= self.surface.max_active_runs:
                raise HTTPException(503, "run_capacity")
            self.active_runs += 1

    async def _identity(self, request: Request) -> str:
        if self.surface.client_id is not None:
            if inspect.iscoroutinefunction(self.surface.client_id):
                result = self.surface.client_id(request)
            else:

                def resolve(*, budget):
                    budget.remaining()
                    return self.surface.client_id(request)

                result = await IDENTITY_WORKERS.run(resolve, seconds=3)
            result = await result if inspect.isawaitable(result) else result
            if result is None:
                return "unknown"
            if not isinstance(result, str) or len(result.encode()) > 256:
                raise Rejected(503, "identity_unavailable")
            return result or "unknown"
        try:
            address = ip_address(request.client.host if request.client else "")
            if isinstance(address, IPv6Address):
                return str(address.ipv4_mapped or ip_network(str(address) + "/64", strict=False))
            return str(address)
        except ValueError:
            return "unknown"

    async def _body(self, receive: Any, maximum: int, seconds: float) -> bytes:
        body = bytearray()

        async def read():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    raise asyncio.CancelledError()
                if message["type"] != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > maximum:
                    raise Rejected(413, "body_too_large")
                if not message.get("more_body", False):
                    return bytes(body)

        try:
            return await asyncio.wait_for(read(), timeout=seconds)
        except asyncio.TimeoutError as exc:
            raise Rejected(408, "body_timeout") from exc

    async def _validate_form(
        self, scope: Any, body: bytes, *, workflow: bool, cancel: bool, continuing: bool = False, kind: str = "agents"
    ) -> dict:
        used = False

        async def receive():
            nonlocal used
            if used:
                return {"type": "http.disconnect"}
            used = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(scope, receive)
        uploads = self.surface.uploads
        try:
            form = await request.form(
                max_files=uploads.max_files if uploads and not workflow else 0,
                max_fields=8,
                max_part_size=uploads.max_file_bytes if uploads else 32768,
            )
            scalar = {}
            try:
                allowed = {"message", "stream", "session_id", "background"}
                if cancel:
                    allowed = {"session_id"}
                requirement_field = {"agents": "tools", "teams": "requirements", "workflows": "step_requirements"}[kind]
                if continuing:
                    allowed = {"session_id", "stream", requirement_field}
                for key, value in form.multi_items():
                    if isinstance(value, UploadFile):
                        if workflow or cancel or continuing or uploads is None or key != "files":
                            raise Rejected(400, "uploads_not_allowed")
                        pair = (PurePath(value.filename or "").suffix.lower(), (value.content_type or "").lower())
                        if (
                            pair not in uploads.allowed_types
                            or value.size is None
                            or value.size > uploads.max_file_bytes
                        ):
                            raise Rejected(400, "invalid_upload")
                    else:
                        if key not in allowed or key in scalar:
                            raise Rejected(400, "invalid_form_fields")
                        scalar[key] = value
                if "session_id" in scalar:
                    _uuid(scalar["session_id"])
                if continuing:
                    if not scalar.get("session_id"):
                        raise Rejected(400, "invalid_handle")
                    if scalar.get("stream", "true").lower() not in ("true", "false"):
                        raise Rejected(400, "invalid_run_mode")
                    raw = scalar.get(requirement_field, "")
                    if raw:
                        requirements = json.loads(raw)
                        if (
                            not isinstance(requirements, list)
                            or len(requirements) > 128
                            or any(not isinstance(r, dict) for r in requirements)
                        ):
                            raise Rejected(400, "invalid_requirements")
                elif not cancel:
                    message = scalar.get("message", "")
                    if not isinstance(message, str) or not message.strip() or len(message.encode()) > 32768:
                        raise Rejected(400, "invalid_message")
                    if scalar.get("stream", "true").lower() not in ("true", "false") or scalar.get(
                        "background", "false"
                    ).lower() not in ("true", "false"):
                        raise Rejected(400, "invalid_run_mode")
                    if not workflow and scalar.get("background", "false").lower() != "false":
                        raise Rejected(400, "background_not_allowed")
                    if workflow:
                        try:
                            json.loads(message)
                        except ValueError as exc:
                            raise Rejected(400, "invalid_workflow_input") from exc
                return scalar
            finally:
                await form.close()
        except Rejected:
            raise
        except Exception as exc:
            raise Rejected(400, "invalid_request_body") from exc

    async def _websocket(self, scope: Any, receive: Any, send: Any) -> None:
        if self.pending_websockets >= MAX_PENDING_WEBSOCKETS:
            await send({"type": "websocket.close", "code": 1008})
            return
        self.pending_websockets += 1
        pending = True

        def release():
            nonlocal pending
            if pending:
                pending = False
                self.pending_websockets -= 1

        try:
            try:
                # Preserve the Request contract of application-owned identity callbacks
                # while resolving the identity of the HTTP upgrade request.
                request = Request({**scope, "type": "http", "method": "GET"})
                identity = await asyncio.wait_for(self._identity(request), timeout=3)
                decision = await self.surface.limiter.aconsume("socket", client_id=identity)
            except Exception:
                log_warning("Public WebSocket admission unavailable")
                await send({"type": "websocket.close", "code": 1008})
                return
            if not decision.allowed:
                await send({"type": "websocket.close", "code": 1008})
                return
            # Only the native authenticated handler receives this callback. Release
            # pending capacity after verification, or on any disconnect/failure below.
            scope["_agno_public_ws_authenticated"] = release
            await self.app(scope, receive, send)
        finally:
            release()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if (
                scope["type"] == "websocket"
                and self.policy.authenticated_api
                and get_route_path(scope) == "/workflows/ws"
                and self.policy.allows_authenticated_websocket(scope)
            ):
                # The native workflow socket authenticates its first message and
                # enforces scopes before any execution or subscription.
                await self._websocket(scope, receive, send)
                return
            await send({"type": "websocket.close", "code": 1008})
            return
        path, method = get_route_path(scope), scope["method"]
        request = Request(scope, receive)
        correlation = uuid4().hex
        started = False
        is_sse = False
        output_bytes = 0
        stream_buffer = b""
        response_start = None
        response_buffer = bytearray()
        error_status = None
        error_headers = {}
        capacity = None
        identity_token = None
        active_binding = None
        mcp = False
        public_run = False
        decoder = None

        async def error(status: int, code: str, headers=None):
            await JSONResponse(
                {"error": {"code": code, "message": code.replace("_", " "), "correlation_id": correlation}},
                status_code=status,
                headers=headers,
            )(scope, receive, send)

        async def bounded_send(message):
            nonlocal started, output_bytes, is_sse, stream_buffer, error_status, error_headers, response_start, decoder
            if message["type"] == "http.response.start":
                status = message["status"]
                if status >= 400:
                    error_status = status
                    error_headers = {
                        k.decode("latin-1"): v.decode("latin-1")
                        for k, v in message.get("headers", [])
                        if k.lower() in (b"www-authenticate", b"retry-after")
                    }
                    return
                is_sse = any(
                    k.lower() == b"content-type" and b"text/event-stream" in v for k, v in message.get("headers", [])
                )
                encoding = next(
                    (v.lower() for k, v in message.get("headers", []) if k.lower() == b"content-encoding"),
                    b"identity",
                )
                if is_sse and encoding != b"identity":
                    # Encoded frames cannot be inspected safely. Refuse them before
                    # headers are sent; outer compression can still encode inspected SSE.
                    raise Rejected(503, "unsupported_response_encoding")
                if not is_sse:
                    # Validate the complete bounded body before committing success
                    # headers, so overflow can still return a valid error response.
                    if encoding == b"gzip":
                        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    elif encoding != b"identity":
                        raise Rejected(503, "unsupported_response_encoding")
                    response_start = message
                    return
                started = True
            elif message["type"] == "http.response.body":
                if error_status is not None:
                    if not message.get("more_body", False):
                        await error(error_status, "request_failed", error_headers)
                    return
                body = message.get("body", b"")
                output_bytes += len(body)
                if output_bytes > self.surface.max_output_bytes:
                    raise Rejected(503, "output_limit")
                if not is_sse:
                    response_buffer.extend(body)
                    if message.get("more_body", False):
                        return
                    logical_body = bytes(response_buffer)
                    if decoder is not None:
                        logical_body = decoder.decompress(logical_body, self.surface.max_output_bytes + 1)
                        if len(logical_body) > self.surface.max_output_bytes or decoder.unconsumed_tail:
                            raise Rejected(503, "output_limit")
                        if not decoder.eof or decoder.unused_data:
                            raise Rejected(503, "invalid_response_encoding")
                    if public_run:
                        payload = json.loads(logical_body)
                        if isinstance(payload, dict) and payload.get("status") == "ERROR":
                            # Native runs encode model failures in HTTP 200 JSON.
                            # Replace the entire failed run so nested diagnostics
                            # cannot bypass the public error representation.
                            raise Rejected(503, "run_failed")
                    assert response_start is not None
                    started = True
                    await send(response_start)
                    await send({**message, "body": bytes(response_buffer)})
                    response_buffer.clear()
                    return
                if is_sse and not mcp:
                    stream_buffer += body
                    frames = stream_buffer.split(b"\n\n")
                    stream_buffer = frames.pop()
                    clean = []
                    for frame in frames:
                        data_lines = [line[5:].lstrip() for line in frame.splitlines() if line.startswith(b"data:")]
                        try:
                            event = json.loads(b"\n".join(data_lines))
                        except ValueError:
                            event = {}
                        if isinstance(event, dict) and event.get("event") in (
                            "RunStarted",
                            "TeamRunStarted",
                            "WorkflowStarted",
                        ):
                            nonlocal active_binding
                            if active_binding is None and event.get("run_id") and event.get("session_id"):
                                expected = {"agents": "agent_id", "teams": "team_id", "workflows": "workflow_id"}[
                                    component_kind
                                ]
                                if event.get(expected) == component_id:
                                    _uuid(event["run_id"])
                                    _uuid(event["session_id"])
                                    lease = await self.surface._bindings._claim(
                                        component_kind,
                                        component_id,
                                        event["session_id"],
                                        event["run_id"],
                                        getattr(request.state, "user_id", None),
                                        self.surface.max_run_seconds,
                                    )
                                    active_binding = (event["run_id"], lease)
                        if isinstance(event, dict) and event.get("event") in (
                            "RunError",
                            "TeamRunError",
                            "WorkflowRunError",
                        ):
                            frame = (
                                b"event: "
                                + event["event"].encode()
                                + b"\ndata: "
                                + json.dumps(
                                    {
                                        "event": event["event"],
                                        "content": "Run unavailable",
                                        "error_code": "run_failed",
                                        "correlation_id": correlation,
                                    }
                                ).encode()
                            )
                        clean.append(frame + b"\n\n")
                    if not message.get("more_body", False):
                        clean.append(stream_buffer)
                        stream_buffer = b""
                    message = {**message, "body": b"".join(clean)}
            await send(message)

        try:
            if len(request.headers.getlist("authorization")) > 1:
                raise Rejected(401, "ambiguous_authorization")
            internal = verify_internal_service_request(request)
            match = RUN_ROUTE.fullmatch(path)
            component_kind = component_id = run_id = operation = ""
            if match:
                component_kind, component_id, run_id, operation = match.groups()
            cancellation, continuing = operation == "/cancel", operation == "/continue"
            if internal and match and component_id in self.registered[component_kind]:
                # Verification, not bearer-header presence, grants scheduler schemas and quota bypass.
                await self.app(scope, receive, send)
                return
            from agno.os.middleware.jwt import _VERIFIED_API_JWT

            if (
                self.policy.authenticated_api
                and getattr(request.state, "_agno_verified_api_jwt", None) is _VERIFIED_API_JWT
                and not self.policy.is_mcp(path)
                and path not in ("/", "/health", "/readyz")
            ):

                async def private_send(message):
                    if message["type"] == "http.response.start":
                        headers = [
                            (key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"
                        ]
                        headers.append((b"cache-control", b"private, no-store"))
                        message = {**message, "headers": headers}
                    await send(message)

                await self.app(scope, receive, private_send)
                return
            if (method, path) in self.interface_routes:
                await self.app(scope, receive, send)
                return
            if self.policy.authenticated_api and path == "/info" and method == "GET":
                await self.app(scope, receive, send)
                return
            if path in ("/", "/health") and method in ("GET", "HEAD"):

                async def head_send(message):
                    await send({**message, "body": b""} if message["type"] == "http.response.body" else message)

                await self.app({**scope, "method": "GET"}, receive, head_send if method == "HEAD" else send)
                return
            if path == "/readyz" and method == "GET":
                limiter = self.surface.limiter

                def ready(*, budget):
                    with limiter.engine.begin() as conn:
                        from sqlalchemy import text

                        conn.execute(text("SET LOCAL statement_timeout='2500ms'"))
                        conn.execute(text("SELECT 1 FROM public.agno_public_limits LIMIT 1"))

                from agno.os.public._limits import WORKERS

                await WORKERS.run(ready, seconds=3)
                await JSONResponse({"status": "ok", "database": "ok", "request_limits": "ok"})(scope, receive, send)
                return
            if path in ("/agents", "/teams") and method == "GET":
                await JSONResponse(
                    [
                        {"id": item.id, "name": item.name, "description": (item.description or "")[:2048]}
                        for item in getattr(self.surface, path[1:])
                    ],
                    headers={"Vary": "Authorization"} if self.policy.authenticated_api else None,
                )(scope, receive, send)
                return
            mcp = self.surface.mcp and path in ("/mcp", "/mcp/server-card")
            if self.surface.mcp and path in self.oauth_paths and path not in ("/mcp", "/mcp/server-card"):
                # The configured provider owns its discovery and OAuth endpoint validation.
                await self.app(scope, receive, send)
                return
            if mcp and method in ("GET", "HEAD", "OPTIONS", "DELETE"):
                await self.app(scope, receive, send)
                return
            if not mcp:
                if not match or component_id not in self.selected[component_kind]:
                    raise Rejected(404, "not_found")
                workflow = component_kind == "workflows"
                if workflow:
                    await require_verified_public_workflow(request, self.agent_os.settings, component_id)
                if run_id:
                    _uuid(run_id)
                if method == "GET" and workflow and run_id and not cancellation:
                    params = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
                    if len(params) != 1 or params[0][0] != "session_id":
                        raise Rejected(400, "invalid_query")
                    _uuid(params[0][1])
                    await asyncio.wait_for(self.app(scope, receive, bounded_send), timeout=10)
                    return
                if method != "POST" or (run_id and not (cancellation or continuing)):
                    raise Rejected(404, "not_found")
                if scope.get("query_string") and not cancellation:
                    raise Rejected(400, "query_overrides_not_allowed")
            else:
                workflow = False
                if method != "POST" or path != "/mcp":
                    raise Rejected(404, "not_found")
            identity = await asyncio.wait_for(self._identity(request), timeout=3)
            scope.setdefault("state", {})["public_client_id"] = identity
            identity_token = _client_id.set(identity)
            if mcp:
                scope["state"]["_agno_public_execution"] = SimpleNamespace(
                    middleware=self, identity=identity, request=Request(dict(scope))
                )
                decision = await self.surface.limiter.aconsume("mcp", client_id=identity)
                if not decision.allowed:
                    await error(429, "rate_limited", {"Retry-After": str(decision.retry_after)})
                    return
                if self.active_mcp >= 32:
                    raise Rejected(503, "request_capacity")
                self.active_mcp += 1
                capacity = "mcp"
            else:
                await self._admit_execution("cancel" if cancellation else "run", identity)
                if not cancellation:
                    capacity = "run"
            maximum = 128 * 1024 if mcp or continuing else 16 * 1024 if workflow else self.surface.max_body_bytes
            body = await self._body(receive, maximum, 10 if mcp else 15)
            if mcp:
                try:
                    payload = json.loads(body)
                except ValueError as exc:
                    raise Rejected(400, "invalid_mcp_request") from exc
                # The pinned stateless transport does not support JSON-RPC batches.
                if not isinstance(payload, dict):
                    raise Rejected(400, "mcp_batch_not_supported")
                rpc_params = payload.get("params")
                run_tool = (
                    payload.get("method") == "tools/call"
                    and isinstance(rpc_params, dict)
                    and isinstance(rpc_params.get("name"), str)
                    and rpc_params["name"] in self.surface._mcp_run_tools
                )
            else:
                scalar = await self._validate_form(
                    scope, body, workflow=workflow, cancel=cancellation, continuing=continuing, kind=component_kind
                )
                if cancellation:
                    params = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
                    if params:
                        if len(params) != 1 or params[0][0] != "session_id" or "session_id" in scalar:
                            raise Rejected(400, "invalid_query")
                        scalar["session_id"] = params[0][1]
                    if not scalar.get("session_id"):
                        raise Rejected(400, "invalid_handle")
                    _uuid(scalar["session_id"])
                    scope["query_string"] = ("session_id=" + scalar["session_id"]).encode()
                action = "cancel" if cancellation else "continue" if continuing else "run"
                run = await _authorize(
                    self.agent_os, request, component_kind, component_id, action, scalar.get("session_id"), run_id
                )
                if continuing:
                    field = {"agents": "tools", "teams": "requirements", "workflows": "step_requirements"}[
                        component_kind
                    ]
                    resolutions = _resolutions(
                        run,
                        json.loads(scalar.get(field) or "[]"),
                        workflow=workflow,
                        legacy_tools=component_kind == "agents",
                    )
                    scalar[field] = json.dumps(resolutions)
                    body = urlencode(scalar).encode()
                    scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"] + [
                        (b"content-length", str(len(body)).encode())
                    ]
                    lease = await self.surface._bindings._claim(
                        component_kind,
                        component_id,
                        scalar["session_id"],
                        run_id,
                        getattr(request.state, "user_id", None),
                        self.surface.max_run_seconds,
                    )
                    active_binding = (run_id, lease)
                if cancellation or continuing:
                    request.state._agno_public_lifecycle = (component_kind, component_id, scalar["session_id"], run_id)
                public_run = component_kind in ("agents", "teams") and not cancellation
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await asyncio.wait_for(
                self.app(scope, replay, bounded_send),
                timeout=(max(60, self.surface.max_run_seconds) if run_tool else 60)
                if mcp
                else self.surface.max_run_seconds,
            )
        except HTTPException as exc:
            await error(
                exc.status_code,
                exc.detail
                if isinstance(exc.detail, str)
                and exc.detail
                in {
                    "not_found",
                    "invalid_handle",
                    "invalid_requirements",
                    "run_not_paused",
                    "run_in_progress",
                    "rate_limited",
                    "run_capacity",
                }
                else "authentication_unavailable"
                if exc.status_code == 503
                else "access_denied",
                exc.headers,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = exc.status if isinstance(exc, Rejected) else 503
            code = exc.code if isinstance(exc, Rejected) else "service_unavailable"
            log_warning(f"Public request {correlation}: {type(exc).__name__}")
            if not started:
                await error(status, code)
            elif is_sse:
                event_name = "TeamRunError" if component_kind == "teams" else "RunError"
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"event: "
                        + event_name.encode()
                        + b"\ndata: "
                        + json.dumps(
                            {
                                "event": event_name,
                                "content": "Run unavailable",
                                "error_code": code,
                                "correlation_id": correlation,
                            }
                        ).encode()
                        + b"\n\n",
                        "more_body": False,
                    }
                )
        finally:
            response_buffer.clear()
            if capacity == "mcp":
                self.active_mcp -= 1
            elif capacity == "run":
                self.active_runs -= 1
            if identity_token is not None:
                _client_id.reset(identity_token)
            if active_binding is not None:
                try:
                    await self.surface._bindings._release(*active_binding)
                except Exception:
                    log_warning("Public run binding cleanup failed; the binding will expire")
