"""Bounded ASGI admission in front of the existing AgentOS routes."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import zlib
from ipaddress import IPv6Address, ip_address, ip_network
from pathlib import PurePath
from typing import Any
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette._utils import get_route_path
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse

from agno.os.auth import require_verified_public_workflow, verify_internal_service_request
from agno.os.public import _client_id
from agno.utils.bounded import BoundedWorkers
from agno.utils.log import log_warning

ROUTE = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs(?:/([^/]+)(/cancel)?)?$")
IDENTITY_WORKERS = BoundedWorkers(8, "public-identity")


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
    def __init__(self, app: Any, *, surface: Any, agent_os: Any):
        self.app, self.surface, self.agent_os = app, surface, agent_os
        self.active_runs = self.active_mcp = 0
        self.selected = {
            kind: {component.id for component in getattr(surface, kind)} for kind in ("agents", "teams", "workflows")
        }
        self.registered = {
            kind: {component.id for component in getattr(agent_os, kind) or []} for kind in self.selected
        }
        self.oauth_paths = agent_os.mcp_auth_exempt_paths() if surface.mcp else []
        self.interface_routes = set(getattr(agent_os, "_public_interface_routes", []))

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

    async def _validate_form(self, scope: Any, body: bytes, *, workflow: bool, cancel: bool) -> None:
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
                for key, value in form.multi_items():
                    if isinstance(value, UploadFile):
                        if workflow or uploads is None or key != "files":
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
                if not cancel:
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
            finally:
                await form.close()
        except Rejected:
            raise
        except Exception as exc:
            raise Rejected(400, "invalid_request_body") from exc

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
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
            match = ROUTE.fullmatch(path)
            component_kind = component_id = run_id = cancellation = ""
            if match:
                component_kind, component_id, run_id, cancellation = match.groups()
            if internal and match and component_id in self.registered[component_kind]:
                # Verification, not bearer-header presence, grants scheduler schemas and quota bypass.
                await self.app(scope, receive, send)
                return
            if (method, path) in self.interface_routes:
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
                    ]
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
                if method != "POST" or (run_id and not cancellation) or (workflow and cancellation):
                    raise Rejected(404, "not_found")
                if scope.get("query_string"):
                    raise Rejected(400, "query_overrides_not_allowed")
            else:
                workflow = False
                if method != "POST" or path != "/mcp":
                    raise Rejected(404, "not_found")
            identity = await asyncio.wait_for(self._identity(request), timeout=3)
            scope.setdefault("state", {})["public_client_id"] = identity
            identity_token = _client_id.set(identity)
            bucket = "mcp" if mcp else "cancel" if cancellation else "run"
            decision = await self.surface.limiter.aconsume(bucket, client_id=identity)
            if not decision.allowed:
                await error(429, "rate_limited", {"Retry-After": str(decision.retry_after)})
                return
            if mcp:
                if self.active_mcp >= 32:
                    raise Rejected(503, "request_capacity")
                self.active_mcp += 1
                capacity = "mcp"
            elif not cancellation:
                if self.active_runs >= self.surface.max_active_runs:
                    raise Rejected(503, "run_capacity")
                self.active_runs += 1
                capacity = "run"
            maximum = 128 * 1024 if mcp else 16 * 1024 if workflow else self.surface.max_body_bytes
            body = await self._body(receive, maximum, 10 if mcp else 15)
            if mcp:
                try:
                    payload = json.loads(body)
                except ValueError as exc:
                    raise Rejected(400, "invalid_mcp_request") from exc
                # The pinned stateless transport does not support JSON-RPC batches.
                if not isinstance(payload, dict):
                    raise Rejected(400, "mcp_batch_not_supported")
            else:
                await self._validate_form(scope, body, workflow=workflow, cancel=bool(cancellation))
                public_run = component_kind in ("agents", "teams") and not cancellation
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await asyncio.wait_for(
                self.app(scope, replay, bounded_send), timeout=60 if mcp else self.surface.max_run_seconds
            )
        except HTTPException as exc:
            await error(
                exc.status_code,
                "authentication_unavailable" if exc.status_code == 503 else "access_denied",
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
