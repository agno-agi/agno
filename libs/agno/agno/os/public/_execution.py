"""Public run ownership and admission shared by HTTP and MCP."""

from __future__ import annotations

import asyncio
import functools
import inspect
from copy import deepcopy
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from agno.os.public._limits import WORKERS


def _handle(value: Any) -> str:
    if not isinstance(value, str):
        raise HTTPException(400, "invalid_handle")
    try:
        if str(UUID(value)) != value.lower():
            raise ValueError()
    except ValueError:
        raise HTTPException(400, "invalid_handle") from None
    return value


class _RunBindings:
    """Short-lived, shared ownership records for runs that have not persisted yet."""

    def __init__(self, engine: Any, namespace: str):
        from agno.db.postgres._bounded import bounded_engine

        self.engine = bounded_engine(engine, capacity=8)
        self.namespace = namespace

    @staticmethod
    def _prepare(conn: Any) -> None:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS public.agno_public_runs ("
                "namespace text NOT NULL, run_id text NOT NULL, session_id text NOT NULL, "
                "kind text NOT NULL, component_id text NOT NULL, user_id text, "
                "lease text NOT NULL, expires_at timestamptz NOT NULL, PRIMARY KEY(namespace, run_id))"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS agno_public_runs_expiry ON public.agno_public_runs(expires_at)"))

    async def _claim(
        self, kind: str, component_id: str, session_id: str, run_id: str, user_id: Any, seconds: float
    ) -> str:
        lease = uuid4().hex

        def write(*, budget):
            with self.engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout='2500ms'"))
                conn.execute(
                    text(
                        "DELETE FROM public.agno_public_runs WHERE (namespace, run_id) IN "
                        "(SELECT namespace, run_id FROM public.agno_public_runs WHERE expires_at < now() "
                        "LIMIT 100 FOR UPDATE SKIP LOCKED)"
                    )
                )
                return conn.execute(
                    text(
                        "INSERT INTO public.agno_public_runs "
                        "(namespace, run_id, session_id, kind, component_id, user_id, lease, expires_at) "
                        "VALUES (:namespace, :run, :session, :kind, :component, :user, :lease, "
                        "now() + :seconds * interval '1 second') ON CONFLICT DO NOTHING RETURNING lease"
                    ),
                    dict(
                        namespace=self.namespace,
                        run=run_id,
                        session=session_id,
                        kind=kind,
                        component=component_id,
                        user=user_id,
                        lease=lease,
                        seconds=seconds + 30,
                    ),
                ).scalar()

        if await WORKERS.run(write, seconds=3) is None:
            raise HTTPException(409, "run_in_progress")
        return lease

    async def _matches(self, kind: str, component_id: str, session_id: str, run_id: str, user_id: Any) -> bool:
        def read(*, budget):
            with self.engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout='2500ms'"))
                return (
                    conn.execute(
                        text(
                            "SELECT 1 FROM public.agno_public_runs WHERE namespace=:namespace AND run_id=:run "
                            "AND session_id=:session AND kind=:kind AND component_id=:component "
                            "AND user_id IS NOT DISTINCT FROM :user AND expires_at > now()"
                        ),
                        dict(
                            namespace=self.namespace,
                            run=run_id,
                            session=session_id,
                            kind=kind,
                            component=component_id,
                            user=user_id,
                        ),
                    ).scalar()
                    is not None
                )

        return await WORKERS.run(read, seconds=3)

    async def _release(self, run_id: str, lease: str) -> None:
        def delete(*, budget):
            with self.engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout='2500ms'"))
                conn.execute(
                    text(
                        "DELETE FROM public.agno_public_runs WHERE namespace=:namespace AND run_id=:run AND lease=:lease"
                    ),
                    dict(namespace=self.namespace, run=run_id, lease=lease),
                )

        await WORKERS.run(delete, seconds=3)


async def _authorize(
    os: Any,
    request: Any,
    kind: str,
    component_id: str,
    action: str,
    session_id: Any = None,
    run_id: Any = None,
    *,
    mcp: bool = False,
) -> Any:
    from agno.os.auth import require_verified_public_workflow
    from agno.os.middleware.user_scope import run_matches_component, session_matches_component

    components = (
        os.public._mcp_components
        if mcp
        else {(k, c.id): c for k in ("agents", "teams", "workflows") for c in getattr(os.public, k)}
    )
    component = components.get((kind, component_id))
    if component is None:
        raise HTTPException(404, "not_found")
    component_kind = cast(Literal["agents", "teams", "workflows"], kind)
    if kind == "workflows":
        await require_verified_public_workflow(request, os.settings, component_id)
    if session_id is None and action == "run":
        return None
    _handle(session_id)
    user_id = getattr(request.state, "user_id", None)
    session = await component.aget_session(session_id=session_id)
    if session is not None:
        if not session_matches_component(session, component_kind, component_id) or session.user_id != user_id:
            raise HTTPException(404, "not_found")
    if action == "run":
        return None
    _handle(run_id)
    run = session.get_run(run_id=run_id) if session is not None else None
    if run is not None and run_matches_component(run, component_kind, component_id):
        if action == "continue" and not run.is_paused:
            raise HTTPException(409, "run_not_paused")
        if action == "continue":
            from agno.os.auth import run_continuation_blocked_reason

            reason = await run_continuation_blocked_reason(
                os.db,
                run_id,
                authorization_enabled=True,
                user_scopes=list(getattr(request.state, "scopes", None) or []),
                fail_closed=True,
            )
            if reason:
                raise HTTPException(403, "access_denied")
        return run
    if action == "cancel" and await os.public._bindings._matches(kind, component_id, session_id, run_id, user_id):
        return None
    raise HTTPException(404, "not_found")


def _lifecycle_verified(request: Any, kind: str, component_id: str, session_id: Any, run_id: str) -> bool:
    """A public gate already verified this exact operation, including active runs."""
    return getattr(getattr(request, "state", None), "_agno_public_lifecycle", None) == (
        kind,
        component_id,
        session_id,
        run_id,
    )


def _resolutions(run: Any, submitted: Any, *, workflow: bool = False, legacy_tools: bool = False) -> list:
    """Keep saved tool/step identity and policy; accept only resolution fields."""
    if submitted is None:
        return []
    if not isinstance(submitted, list) or len(submitted) > 128:
        raise HTTPException(400, "invalid_requirements")
    saved = [req.to_dict() for req in (getattr(run, "step_requirements" if workflow else "requirements", None) or [])]
    if legacy_tools:
        saved = [req["tool_execution"] for req in saved]

    def identity(req):
        return req.get("step_id") if workflow else req.get("tool_call_id") if legacy_tools else req.get("id")

    def merge(base, update):
        if not isinstance(update, dict):
            raise HTTPException(400, "invalid_requirements")
        result = deepcopy(base)
        mutable = {
            "confirmed",
            "confirmation",
            "confirmation_note",
            "user_input",
            "selected_choices",
            "rejection_feedback",
            "edited_output",
            "external_execution_result",
            "answered",
        }
        if base.get("external_execution_required"):
            mutable.add("result")
        for key, value in update.items():
            if key in mutable:
                if (
                    key in {"confirmed", "confirmation", "answered"}
                    and value is not None
                    and not isinstance(value, bool)
                ):
                    raise HTTPException(400, "invalid_requirements")
                result[key] = value
            elif key == "tool_execution" and isinstance(base.get(key), dict):
                result[key] = merge(base[key], value)
            elif key in ("user_input_schema", "user_feedback_schema") and isinstance(value, list):
                original = base.get(key) or []
                if len(original) != len(value):
                    raise HTTPException(400, "invalid_requirements")
                result[key] = []
                for old, new in zip(original, value):
                    if not isinstance(new, dict) or any(
                        v != old.get(k)
                        for k, v in new.items()
                        if k not in {"value", "selected_options", "free_text_response"}
                    ):
                        raise HTTPException(400, "invalid_requirements")
                    result[key].append({**old, **new})
            elif key == "executor_requirements" and isinstance(value, list):
                original = base.get(key) or []
                if len(original) != len(value):
                    raise HTTPException(400, "invalid_requirements")
                result[key] = [merge(old, new) for old, new in zip(original, value)]
            elif value != base.get(key):
                raise HTTPException(400, "invalid_requirements")
        return result

    resolved, seen = [], set()
    for item in submitted:
        if not isinstance(item, dict):
            raise HTTPException(400, "invalid_requirements")
        key = identity(item)
        matches = [req for req in saved if identity(req) == key]
        if not isinstance(key, str) or key in seen or len(matches) != 1:
            raise HTTPException(400, "invalid_requirements")
        seen.add(key)
        resolved.append(merge(matches[0], item))
    return resolved


def _public_mcp_tool(os: Any, kind: Any = None, component_id: Any = None, action: str = "run"):
    """Apply public policy at invocation, after the MCP authentication bridge."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            from agno.os.mcp import _http_request_or_none

            request = _http_request_or_none()
            execution = getattr(getattr(request, "state", None), "_agno_public_execution", None)
            if request is None or execution is None:
                return await fn(*args, **kwargs)
            bound = signature.bind(*args, **kwargs)
            values = bound.arguments
            target_kind, target_id = kind, component_id
            if target_kind is None:
                from agno.os.mcp import _classify_lifecycle_target

                target_kind, target_id = _classify_lifecycle_target(
                    values.get("agent_id"), values.get("team_id"), values.get("workflow_id")
                )
            lease = None
            admitted = False
            run_id, session_id = values.get("run_id"), values.get("session_id")
            try:
                actor = getattr(request.state, "user_id", None)
                from agno.os.mcp import _require_tool_scopes

                route = f"/{target_kind}/{target_id}/runs"
                if action != "run":
                    route += f"/{run_id}/{action}"
                _require_tool_scopes("POST", route)
                if values.get("user_id") is not None and values["user_id"] != actor:
                    raise HTTPException(400, "identity_override_not_allowed")
                if action == "run":
                    message = values.get("message")
                    if not isinstance(message, str) or not message.strip() or len(message.encode()) > 32768:
                        raise HTTPException(400, "invalid_message")
                    if target_kind == "workflows":
                        import json

                        try:
                            json.loads(message)
                        except ValueError:
                            raise HTTPException(400, "invalid_message") from None
                run = await _authorize(
                    os, execution.request, target_kind, target_id, action, session_id, run_id, mcp=True
                )
                if action == "continue":
                    values["requirements"] = _resolutions(
                        run, values.get("requirements"), workflow=target_kind == "workflows"
                    )
                if action != "run":
                    request.state._agno_public_lifecycle = (target_kind, target_id, session_id, run_id)
                await execution.middleware._admit_execution(action, execution.identity)
                admitted = action != "cancel"
                if action == "continue":
                    lease = await os.public._bindings._claim(
                        target_kind, target_id, session_id, run_id, actor, os.public.max_run_seconds
                    )
                result = await asyncio.wait_for(fn(*bound.args, **bound.kwargs), timeout=os.public.max_run_seconds)
                structured = getattr(result, "structured_content", None)
                if isinstance(structured, dict) and structured.get("status") == "ERROR":
                    raise HTTPException(503, "run_failed")
                return result
            except Exception as exc:
                from fastmcp.exceptions import ToolError

                code = (
                    exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "run_unavailable"
                )
                if code not in {
                    "not_found",
                    "invalid_handle",
                    "run_not_paused",
                    "run_in_progress",
                    "rate_limited",
                    "run_capacity",
                    "invalid_message",
                    "invalid_requirements",
                    "identity_override_not_allowed",
                    "run_failed",
                }:
                    code = (
                        "access_denied"
                        if isinstance(exc, HTTPException) and exc.status_code in (401, 403)
                        else "run_unavailable"
                    )
                raise ToolError(str(code)) from None
            finally:
                if admitted:
                    execution.middleware.active_runs -= 1
                if lease is not None:
                    try:
                        await os.public._bindings._release(run_id, lease)
                    except Exception:
                        from agno.utils.log import log_warning

                        log_warning("Public run binding cleanup failed; the binding will expire")

        return wrapped

    return decorate
