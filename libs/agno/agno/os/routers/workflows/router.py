import asyncio
import contextlib
import json
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agno.db.base import BaseDb, SessionType
from agno.db.schemas.jobs import QueuedJob
from agno.exceptions import (
    ComponentRehydrationError,
    InputCheckError,
    OutputCheckError,
    RunNotContinuableError,
    RunNotFoundError,
)
from agno.factory import FactoryContextRequired
from agno.os.auth import (
    INTERNAL_SCHEDULER_USER_ID,
    get_auth_token_from_request,
    get_authentication_dependency,
    require_resource_access,
)
from agno.os.event_streams import get_event_stream
from agno.os.job_queue import (
    acontinue_via_queue,
    aprepare_accepted_or_abort,
    araise_if_ticket_owns_continue,
    aticket_poll_fallback,
    ensure_duplicate_matches_component,
    normalize_idempotency_key,
    payload_is_queueable,
    ticket_status_to_api,
    validate_seam_input,
)
from agno.os.middleware.user_scope import (
    MISSING_USER_IDENTITY,
    SESSION_ID_REQUIRED,
    SESSION_ID_REQUIRED_RECONNECT,
    WORKFLOW_ID_REQUIRED_RECONNECT,
    assert_session_matches_component,
    assert_session_writable,
    caller_is_admin,
    get_scoped_user_id,
    get_scoped_user_id_for_ws,
    run_matches_component,
    verify_run_in_session,
    verify_run_in_session_via_db,
)
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
    WorkflowSummaryResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    afinalize_continue_stream,
    allow_draft_preview,
    amark_continue_stream_running,
    draft_preview_identity,
    find_factory_by_id,
    format_sse_event,
    get_request_kwargs,
    get_workflow_by_id,
    get_workflow_by_id_async,
    queued_run_tail_streamer,
    replayed_payload_to_sse,
    resolve_workflow,
    sse_error_frame,
    stamp_component_version,
    stamped_component_version,
    stored_event_replay_dicts,
)
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowErrorEvent, WorkflowRunOutput
from agno.utils.log import log_debug, log_error, log_warning, logger
from agno.utils.serialize import json_serializer
from agno.workflow.factory import WorkflowFactory
from agno.workflow.remote import RemoteWorkflow
from agno.workflow.workflow import Workflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


_ws_tail_pumps: "weakref.WeakKeyDictionary[WebSocket, asyncio.Task]" = weakref.WeakKeyDictionary()


def _stream_payload_to_dict(payload: Any, ev_index: int, run_id: str) -> Dict[str, Any]:
    """Normalize an event-stream payload to the WS wire dict.

    In-memory streams hand back structured events; distributed streams hand
    back SSE-formatted strings whose data JSON already embeds event_index and
    run_id. Either way the socket sends one flat JSON object."""
    if isinstance(payload, str):
        for line in payload.split("\n"):
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    d.setdefault("event_index", ev_index)
                    d.setdefault("run_id", run_id)
                    return d
                except Exception:
                    break
        return {"event": "unknown", "raw": payload, "event_index": ev_index, "run_id": run_id}
    d = payload.model_dump() if hasattr(payload, "model_dump") else payload.to_dict()
    d["event_index"] = ev_index
    if "run_id" not in d:
        d["run_id"] = run_id
    return d


async def _pump_event_stream_to_websocket(websocket: WebSocket, run_id: str, from_index: Optional[int]) -> None:
    """Forward live events from the event stream to a subscribed socket.

    This is what makes WS reconnects replica-independent: the socket lives
    wherever the client connected, the events come from wherever the run
    executes, and tail() bridges the two."""
    event_stream = get_event_stream()
    try:
        async for ev_index, sse_data in event_stream.tail(run_id, last_event_index=from_index):
            await websocket.send_text(
                json.dumps(_stream_payload_to_dict(sse_data, ev_index, run_id), default=json_serializer)
            )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Socket closed mid-pump (normal on client disconnect) or stream
        # failed. Best-effort error frame: a dead pump must not look like a
        # completed run to a client whose socket is still open.
        log_debug(f"WS tail pump for run {run_id} ended: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_text(
                json.dumps({"event": "error", "run_id": run_id, "error": f"stream tail failed: {str(e)[:200]}"})
            )


# NOTE on execute-socket wire format: the non-durable execute path sends
# SSE-wrapped frames (WebSocketHandler.format_sse_event) while the reconnect
# pump sends flat JSON dicts. Durable tails standardize on the FLAT format:
# the FE parser accepts both, and one pump beats two formats diverging.


async def cancel_subscription_pump(websocket: WebSocket) -> None:
    """Cancel the tail pump attached to this socket, if any (called on
    disconnect by the WS dispatcher, and on re-subscribe)."""
    task = _ws_tail_pumps.pop(websocket, None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def handle_workflow_via_websocket(
    websocket: WebSocket,
    message: dict,
    os: "AgentOS",
    ws_user_context: Optional[Dict[str, Any]] = None,
    ws_auth: Optional["WebSocketAuthContext"] = None,
):
    """Handle workflow execution directly via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        user_message = message.get("message", "")
        user_id = message.get("user_id")
        version = message.get("version")
        factory_input = message.get("factory_input")

        # Defense-in-depth: an authenticated caller's identity is the token,
        # never the client frame. The WS dispatcher in router.py already forces
        # this, but the handler must not trust a client-supplied user_id if
        # called from any other code path. Mirrors the HTTP route's rule
        # (request.state.user_id, i.e. the JWT sub): a non-admin token pins
        # user_id to its sub EVEN WHEN THE SUB IS ABSENT - a sub-less token
        # under isolation-off must not keep a client-chosen value, or the
        # client could claim a draft owner's identity at the preview gate
        # below (which the HTTP route denies with actor=None).
        if ws_user_context:
            jwt_user_id = ws_user_context.get("user_id")
            # The admin decision belongs to the WS dispatcher, which evaluates the
            # deployment's CONFIGURED admin scope. Re-deriving it here from the
            # default scope name diverges as soon as a deployment configures a
            # custom admin scope, and it diverges in the attacker's favour: a
            # token carrying the literal default scope name as an ordinary scope
            # would take the admin branch and keep the client frame's user_id.
            is_admin = bool(ws_auth and ws_auth.is_admin)
            if is_admin:
                user_id = user_id or jwt_user_id
            else:
                user_id = jwt_user_id

        # Owner scope for DB-backed workflow components; ``None`` for admins and unscoped callers.
        # Fails closed (403) for an identity-less token under isolation, like the REST routes.
        try:
            scoped_user_id = get_scoped_user_id_for_ws(
                user_id,
                jwt_enabled=bool(ws_auth and ws_auth.jwt_enabled),
                is_admin=bool(ws_auth and ws_auth.is_admin),
                user_isolation_enabled=bool(ws_auth and ws_auth.user_isolation_enabled),
            )
        except HTTPException:
            await websocket.send_text(json.dumps({"event": "error", "error": MISSING_USER_IDENTITY}))
            return

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return

        # An explicit draft version is a control-plane preview: owner/admin only.
        # Published pins were always reachable. Privilege means admin or auth
        # off; a plain authenticated caller keeps its raw identity even when
        # isolation is off (scoped_user_id None must not read as admin).
        preview_privileged = bool(ws_auth and ws_auth.is_admin) or not bool(ws_auth and ws_auth.jwt_enabled)
        if not allow_draft_preview(
            os.db, workflow_id, version, user_id if isinstance(user_id, str) else None, privileged=preview_privileged
        ):
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return

        # Get workflow from OS — supports both static and factory components
        is_factory = os.workflows and any(
            isinstance(w, WorkflowFactory) and w.id == workflow_id for w in (os.workflows or [])
        )
        if is_factory:
            from agno.factory import RequestContext, TrustedContext

            # Build trusted context from JWT claims if available (via websocket auth)
            trusted = TrustedContext()
            if ws_user_context:
                claims = ws_user_context.get("payload", {})
                scopes = ws_user_context.get("scopes", frozenset())
                if isinstance(scopes, (list, set)):
                    scopes = frozenset(scopes)
                trusted = TrustedContext(claims=claims, scopes=scopes)

            ctx = RequestContext(
                user_id=user_id,
                session_id=session_id,
                input=factory_input,
                trusted=trusted,
            )
            try:
                workflow = await get_workflow_by_id_async(
                    workflow_id=workflow_id,
                    workflows=os.workflows,
                    db=os.db,
                    version=version,
                    registry=os.registry,
                    create_fresh=True,
                    ctx=ctx,
                    user_id=scoped_user_id,
                )
            except Exception as e:
                await websocket.send_text(json.dumps({"event": "error", "error": f"Factory error: {e}"}))
                return
        else:
            try:
                workflow = get_workflow_by_id(
                    workflow_id=workflow_id,
                    workflows=os.workflows,
                    db=os.db,
                    version=version,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=scoped_user_id,
                )
            except Exception as e:
                await websocket.send_text(json.dumps({"event": "error", "error": f"Error resolving workflow: {e}"}))
                return
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return

        if isinstance(workflow, RemoteWorkflow):
            await websocket.send_text(
                json.dumps({"event": "error", "error": "Remote workflows are not supported via WebSocket"})
            )
            return

        # Generate session_id if not provided
        # Use workflow's default session_id if not provided in message
        if not session_id:
            if workflow.session_id:
                session_id = workflow.session_id
            else:
                session_id = str(uuid4())

        # Durable WS submission: the queue row is the acceptance, execution
        # happens on whichever worker claims it, and this socket becomes a
        # tail view of the event stream - the run survives this replica.
        # Wire format: flat JSON dicts (the reconnect/subscribe format; the
        # FE parser handles both, confirmed) with a leading "queued" ack
        # frame so the client sees accepted/waiting instead of a silent
        # socket while the job waits for a claim.
        queue_worker = getattr(websocket.app.state, "queue_worker", None)
        queued_ws_payload: Dict[str, Any] = {"input": user_message, "kwargs": {}, "stream": True}
        ws_submit_queueable = (
            queue_worker is not None
            and not is_factory
            and getattr(workflow, "db", None) is not None
            and payload_is_queueable(queued_ws_payload)
            and any(
                getattr(candidate, "id", None) == workflow_id and not isinstance(candidate, WorkflowFactory)
                for candidate in (os.workflows or [])
            )
        )
        if ws_submit_queueable:
            # Accept must honor input_schema exactly like the inline path
            try:
                validate_seam_input(workflow, user_message)
            except HTTPException as e:
                await websocket.send_text(json.dumps({"event": "error", "error": str(e.detail)}))
                return
            assert queue_worker is not None  # narrowed by ws_submit_queueable
            queued_run_id = str(uuid4())
            job = QueuedJob(
                id=queued_run_id,
                component_type="workflow",
                component_id=getattr(workflow, "id", None) or workflow_id,
                session_id=session_id,
                user_id=user_id,
                payload=queued_ws_payload,
                max_attempts=queue_worker.config.max_attempts,
                deployment_id=queue_worker.config.deployment_id,
            ).to_dict()
            enqueue_result = await queue_worker.store.enqueue_job(job, max_depth=queue_worker.config.max_queue_depth)
            if not enqueue_result["accepted"]:
                # No Idempotency-Key over WS, so "duplicate" cannot legitimately
                # happen on a fresh uuid - either way nothing was enqueued and
                # the client must know the submission was NOT accepted
                reason = enqueue_result.get("reason") or "rejected"
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "error": "Job queue is full; retry later"
                            if reason == "queue_full"
                            else f"Submission was not accepted ({reason})",
                        }
                    )
                )
                return
            with contextlib.suppress(Exception):
                # Fail-open: the queue row is already committed - a Redis blip
                # must not kill an accepted submission (tails degrade gracefully)
                await get_event_stream().register_run(queued_run_id, RunStatus.pending)
            try:
                await aprepare_accepted_or_abort(
                    queue_worker, workflow, "workflow", queued_run_id, session_id, user_id, user_message
                )
            except HTTPException as he:
                await websocket.send_text(json.dumps({"event": "error", "error": str(he.detail)}))
                return
            await websocket.send_text(
                json.dumps({"event": "queued", "run_id": queued_run_id, "session_id": session_id})
            )
            # Tail the whole stream from the start (this socket is the primary
            # view). One pump per socket; the dispatcher cancels it on
            # disconnect/re-subscribe via the shared registry.
            await cancel_subscription_pump(websocket)
            _ws_tail_pumps[websocket] = asyncio.create_task(
                _pump_event_stream_to_websocket(websocket, queued_run_id, None)
            )
            return
        if queue_worker is not None:
            log_warning(
                "WS workflow submission bypasses the durable queue (factory/off-registry/no-db "
                "workflows are not queueable): bounded and observable, but NOT durable."
            )

        # Version-stable preview: an explicitly pinned version is recorded on
        # the run itself (run metadata), so the continue paths can reload the
        # SAME version later instead of whatever is current by then.
        ws_run_kwargs: Dict[str, Any] = {}
        stamp_component_version(ws_run_kwargs, version)

        # Execute workflow in background with streaming via WebSocket
        await workflow.arun(  # type: ignore
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background=True,
            websocket=websocket,
            enable_websocket=True,
            **ws_run_kwargs,
        )

        # NOTE: Don't register the original websocket in the manager
        # It's already handled by the WebSocketHandler passed to the workflow
        # The manager is ONLY for reconnected clients (see handle_workflow_subscription)

    except (InputCheckError, OutputCheckError) as e:
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": str(e),
                    "error_type": e.type,
                    "error_id": e.error_id,
                    "additional_data": e.additional_data,
                }
            )
        )
    except Exception as e:
        logger.exception("Error executing workflow via WebSocket")
        error_payload = {
            "event": "error",
            "error": str(e),
            "error_type": e.type if hasattr(e, "type") else None,
            "error_id": e.error_id if hasattr(e, "error_id") else None,
        }
        error_payload = {k: v for k, v in error_payload.items() if v is not None}
        await websocket.send_text(json.dumps(error_payload))


@dataclass
class WebSocketAuthContext:
    """Per-connection auth state derived once when the WebSocket opens.

    Passed to handler functions alongside the (untrusted) client message so
    handlers don't need to read internal flags out of the client payload.
    """

    jwt_enabled: bool = False
    is_admin: bool = False
    # Opt-in per-user isolation. When False (default), ownership checks added
    # by the user-scoped-DB work stay dormant — RBAC still applies but the
    # handler treats reconnect as session-id-optional.
    user_isolation_enabled: bool = False


async def handle_workflow_subscription(
    websocket: WebSocket,
    message: dict,
    os: "AgentOS",
    ws_auth: Optional[WebSocketAuthContext] = None,
):
    """
    Handle subscription/reconnection to an existing workflow run.

    Allows clients to reconnect after page refresh or disconnection and catch up on missed events.
    """
    try:
        run_id = message.get("run_id")
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        user_id = message.get("user_id")
        last_event_index = message.get("last_event_index")  # 0-based index of last received event
        # Auth context is set by the WS dispatcher in router.py; default to
        # "no JWT, no isolation" for callers that bypass the dispatcher.
        ctx = ws_auth or WebSocketAuthContext()
        jwt_enabled = ctx.jwt_enabled
        is_admin = ctx.is_admin
        user_isolation_enabled = ctx.user_isolation_enabled
        # Owner scope for DB-backed workflow components on reconnect.
        # Fails closed (403) for an identity-less token under isolation, like the REST routes.
        try:
            scoped_user_id = get_scoped_user_id_for_ws(
                user_id, jwt_enabled=jwt_enabled, is_admin=is_admin, user_isolation_enabled=user_isolation_enabled
            )
        except HTTPException:
            await websocket.send_text(json.dumps({"event": "error", "error": MISSING_USER_IDENTITY}))
            return

        if not run_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "run_id is required for subscription"}))
            return

        # Non-admin JWT callers must prove session ownership before any replay or
        # live-event subscription — but only when per-user isolation is enabled.
        # The buffer path is keyed solely on run_id, so without this check (when
        # isolation is on) a caller with workflows:run could read another user's
        # run events by guessing the run_id. With isolation off, RBAC alone
        # governs reconnect access.
        if scoped_user_id is not None:
            if not session_id:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "error": SESSION_ID_REQUIRED_RECONNECT,
                        }
                    )
                )
                return
            # workflow_id is required so the session/run component check has
            # something to validate against. Defense-in-depth: the WS dispatch
            # in router.py already rejects missing workflow_id at reconnect
            # for JWT callers, but the handler must not silently fall back to
            # an unconstrained check if a future caller skips that path.
            if not workflow_id:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "error": WORKFLOW_ID_REQUIRED_RECONNECT,
                        }
                    )
                )
                return

            try:
                await verify_run_in_session_via_db(
                    os.db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="workflows",
                    component_id=workflow_id,
                )
            except HTTPException:
                # Mask existence of another user's run.
                await websocket.send_text(json.dumps({"event": "error", "error": f"Run {run_id} not found"}))
                return

        # Check if the run is known to the event stream (any replica)
        event_stream = get_event_stream()
        try:
            buffer_status = await event_stream.get_run_status(run_id)
        except Exception as e:
            log_error(f"WS subscription: event stream status probe failed for run {run_id}: {e}")
            await websocket.send_text(
                json.dumps({"event": "error", "error": f"event stream unavailable: {str(e)[:200]}"})
            )
            return

        if buffer_status is None:
            # Run not in buffer - check database
            if workflow_id and session_id:
                try:
                    # Lenient: replay only reads stored events through the
                    # workflow's db handle, never its resolved references.
                    workflow = get_workflow_by_id(
                        workflow_id=workflow_id,
                        workflows=os.workflows,
                        db=os.db,
                        registry=os.registry,
                        create_fresh=True,
                        user_id=scoped_user_id,
                        strict=False,
                        published_only=False,
                    )
                except FactoryContextRequired:
                    workflow = None
                if workflow and isinstance(workflow, Workflow):
                    workflow_run = await workflow.aget_run_output(run_id, session_id, user_id=user_id)

                    if workflow_run:
                        # Run exists in DB - replay through the shared
                        # floor-honoring helper (same contract as the SSE
                        # resume routes): stamped events are filtered under
                        # the client's last_event_index and keep their REAL
                        # stream indices - positional renumbering re-sent the
                        # full history and destroyed index continuity for
                        # partially-caught-up clients.
                        replay_dicts = stored_event_replay_dicts(workflow_run, run_id, last_event_index)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "replay",
                                    "run_id": run_id,
                                    "status": workflow_run.status.value if workflow_run.status else "unknown",
                                    "total_events": len(replay_dicts),
                                    "message": "Run completed. Replaying stored events from database."
                                    if replay_dicts
                                    else "Run completed but no events stored past the requested index.",
                                }
                            )
                        )
                        for event_dict in replay_dicts:
                            await websocket.send_text(json.dumps(event_dict, default=json_serializer))
                        return

            # Run not found anywhere
            await websocket.send_text(
                json.dumps({"event": "error", "error": f"Run {run_id} not found in buffer or database"})
            )
            return

        # Run is known to the stream (still active or recently completed).
        # PAUSED belongs here too: a paused run's stream is settled until the
        # continue-run, so subscribers get the replay (ending in the paused
        # snapshot) rather than an open live tail claiming RUNNING.
        if buffer_status in [RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused]:
            # Run finished - replay everything still buffered
            all_events = await event_stream.replay(run_id, last_event_index=None)

            await websocket.send_text(
                json.dumps(
                    {
                        "event": "replay",
                        "run_id": run_id,
                        "status": buffer_status.value,
                        "total_events": len(all_events),
                        "message": f"Run {buffer_status.value}. Replaying all events.",
                    }
                )
            )

            for ev_index, buffered_event in all_events:
                await websocket.send_text(
                    json.dumps(_stream_payload_to_dict(buffered_event, ev_index, run_id), default=json_serializer)
                )
            return

        # Run is still active - replay missed events, then follow live via a
        # tail pump (works regardless of which replica executes the run)
        missed_events = await event_stream.replay(run_id, last_event_index)
        current_event_count = await event_stream.get_event_count(run_id)

        last_replayed_index = last_event_index
        if missed_events:
            # Send catch-up notification
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "catch_up",
                        "run_id": run_id,
                        "status": "running",
                        "missed_events": len(missed_events),
                        "current_event_count": current_event_count,
                        "message": f"Catching up on {len(missed_events)} missed events.",
                    }
                )
            )

            for ev_index, buffered_event in missed_events:
                await websocket.send_text(
                    json.dumps(_stream_payload_to_dict(buffered_event, ev_index, run_id), default=json_serializer)
                )
                last_replayed_index = ev_index

        # Send subscription confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "subscribed",
                    "run_id": run_id,
                    "status": "running",
                    "current_event_count": current_event_count,
                    "message": "Subscribed to workflow run. You will receive new events as they occur.",
                }
            )
        )

        # Live phase: tail() handles the replay/subscribe race internally, so
        # events landing between our replay and the pump start are not lost.
        # One pump per socket: a re-subscribe replaces the previous pump.
        await cancel_subscription_pump(websocket)
        _ws_tail_pumps[websocket] = asyncio.create_task(
            _pump_event_stream_to_websocket(websocket, run_id, last_replayed_index)
        )

        log_debug(f"Client subscribed to workflow run {run_id} (last_event_index: {last_event_index})")

    except Exception as e:
        logger.exception("Error handling workflow subscription")
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": f"Subscription failed: {str(e)}",
                }
            )
        )


async def handle_workflow_continue_via_websocket(
    websocket: WebSocket,
    message: dict,
    os: "AgentOS",
    ws_user_context: Optional[Dict[str, Any]] = None,
    ws_auth: Optional[WebSocketAuthContext] = None,
):
    """Handle continuing a paused workflow run via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        run_id = message.get("run_id")
        session_id = message.get("session_id")
        user_id = message.get("user_id")
        step_requirements_data = message.get("step_requirements")

        # Defense-in-depth: an authenticated caller's identity is the token,
        # never the client frame. The WS dispatcher in router.py already forces
        # this, but the handler must not trust a client-supplied user_id if
        # called from any other code path. Mirrors the HTTP route's rule
        # (request.state.user_id, i.e. the JWT sub): a non-admin token pins
        # user_id to its sub EVEN WHEN THE SUB IS ABSENT - a sub-less token
        # under isolation-off must not keep a client-chosen value, or the
        # client could claim a draft owner's identity at the stamped-version
        # preview gate below (which the HTTP route denies with actor=None).
        if ws_user_context:
            jwt_user_id = ws_user_context.get("user_id")
            # The admin decision belongs to the WS dispatcher, which evaluates the
            # deployment's CONFIGURED admin scope. Re-deriving it here from the
            # default scope name diverges as soon as a deployment configures a
            # custom admin scope, and it diverges in the attacker's favour: a
            # token carrying the literal default scope name as an ordinary scope
            # would take the admin branch and keep the client frame's user_id.
            is_admin = bool(ws_auth and ws_auth.is_admin)
            if is_admin:
                user_id = user_id or jwt_user_id
            else:
                user_id = jwt_user_id

        # Owner scope for DB-backed workflow components on continue.
        # Fails closed (403) for an identity-less token under isolation, like the REST routes.
        try:
            scoped_user_id = get_scoped_user_id_for_ws(
                user_id,
                jwt_enabled=bool(ws_auth and ws_auth.jwt_enabled),
                is_admin=bool(ws_auth and ws_auth.is_admin),
                user_isolation_enabled=bool(ws_auth and ws_auth.user_isolation_enabled),
            )
        except HTTPException:
            await websocket.send_text(json.dumps({"event": "error", "error": MISSING_USER_IDENTITY}))
            return

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return
        if not run_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "run_id is required"}))
            return

        # Enforce ownership for non-admin callers when user isolation is enabled.
        # Mirrors the HTTP cancel/resume routes: a non-admin caller must own
        # both the session and the run before we even fetch the paused state.
        if scoped_user_id is not None:
            if not session_id:
                await websocket.send_text(json.dumps({"event": "error", "error": SESSION_ID_REQUIRED}))
                return
            # Prefer the factory's db when this workflow_id is a factory entry;
            # only fall back to os.db when no factory-specific db is configured.
            # This matches the pattern the HTTP cancel/resume routes use.
            factory = find_factory_by_id(workflow_id, os.workflows)
            check_db = getattr(factory, "db", None) or os.db
            try:
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="workflows",
                    component_id=workflow_id,
                )
            except HTTPException:
                await websocket.send_text(json.dumps({"event": "error", "error": f"Run {run_id} not found"}))
                return

        workflow = get_workflow_by_id(
            workflow_id=workflow_id,
            workflows=os.workflows,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
            user_id=scoped_user_id,
            published_only=False,
        )
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return
        if isinstance(workflow, RemoteWorkflow):
            await websocket.send_text(
                json.dumps({"event": "error", "error": "Continue is not supported for remote workflows via WebSocket"})
            )
            return

        # Load the paused run
        existing_run = await workflow.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
        if existing_run is None:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Run {run_id} not found"}))
            return
        if not getattr(existing_run, "is_paused", False):
            status = getattr(existing_run, "status", None)
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "error",
                        "error": f"Run is not paused (status={getattr(status, 'value', status)})",
                    }
                )
            )
            return

        # Version-stable continuation (see the HTTP continue route): a run
        # started with an explicitly pinned version (draft preview) recorded
        # it in its run metadata; continue on THAT version, not whatever is
        # published/current now. No stamp (legacy or unpinned runs) keeps
        # today's resolution. Factories build per-request, so they are exempt.
        stamped_version = stamped_component_version(existing_run)
        if stamped_version is not None and not find_factory_by_id(workflow_id, os.workflows):
            # Re-run the run-start preview gate before trusting the stamp: a
            # stamp naming a draft version this caller may not preview must not
            # resolve (defense against a forged/leaked stamp). Same not-found
            # message the WS start path emits, so a denial is indistinguishable
            # from the component being absent.
            preview_privileged = bool(ws_auth and ws_auth.is_admin) or not bool(ws_auth and ws_auth.jwt_enabled)
            preview_actor = user_id if isinstance(user_id, str) else None
            if not allow_draft_preview(
                os.db, workflow_id, stamped_version, preview_actor, privileged=preview_privileged
            ):
                await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
                return
            stamped_workflow = get_workflow_by_id(
                workflow_id=workflow_id,
                workflows=os.workflows,
                db=os.db,
                registry=os.registry,
                version=stamped_version,
                create_fresh=True,
                user_id=scoped_user_id,
                published_only=False,
            )
            if not stamped_workflow or isinstance(stamped_workflow, RemoteWorkflow):
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "error": f"Workflow version {stamped_version} recorded on run {run_id} "
                            "is no longer available",
                        }
                    )
                )
                return
            workflow = stamped_workflow

        # Apply step requirements if provided
        if step_requirements_data:
            from agno.workflow.types import StepRequirement

            try:
                parsed_requirements = [StepRequirement.from_dict(req) for req in step_requirements_data]
                existing_run.step_requirements = parsed_requirements
            except Exception as e:
                await websocket.send_text(
                    json.dumps({"event": "error", "error": f"Invalid step_requirements: {str(e)}"})
                )
                return

        # Durable continue: CAS the run's EXISTING paused ticket back to
        # queued so the continuation leg survives crashes and executes on
        # whichever worker claims it; this socket becomes a tail view
        # speaking the flat-JSON tail format (the same
        # _pump_event_stream_to_websocket frames the reconnect/subscription
        # surface sends - the FE parser handles both, per the 2026-08-02
        # resolution that removed the SSE-wrapped execute pump).
        queue_worker = getattr(websocket.app.state, "queue_worker", None)
        continue_payload = {"step_requirements": step_requirements_data}
        workflow_is_queueable = any(
            getattr(candidate, "id", None) == workflow_id and not isinstance(candidate, WorkflowFactory)
            for candidate in (os.workflows or [])
        )
        if queue_worker is not None and workflow_is_queueable and payload_is_queueable(continue_payload):
            # existing_run.is_paused was proven above. stream_requested: this
            # socket IS a stream - a non-streaming submission's ticket must be
            # refused before the CAS, not silently pumped from an empty stream
            continue_outcome = await acontinue_via_queue(
                queue_worker,
                run_id,
                continue_payload,
                stream_requested=True,
                component_type="workflow",
                component_id=getattr(workflow, "id", None) or workflow_id,
            )
            if continue_outcome is not None:
                outcome = continue_outcome["outcome"]
                if outcome == "stream_mismatch":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "error",
                                "run_id": run_id,
                                "error": "Run was submitted non-streaming; continue it over HTTP "
                                "and poll for the result instead of a WebSocket",
                            }
                        )
                    )
                    return
                if outcome == "settling":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "error",
                                "run_id": run_id,
                                "error": "Run is settling between execution legs; retry in a moment",
                            }
                        )
                    )
                    return
                if outcome == "conflict":
                    ticket_status = (continue_outcome.get("job") or {}).get("status", "unknown")
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "error",
                                "run_id": run_id,
                                "error": f"Run is not continuable (ticket status: {ticket_status})",
                            }
                        )
                    )
                    return
                # queued (accepted) or attach (double-click): pump the event
                # stream to this socket. Tail from the PRE-ACCEPT index
                # (captured by the helper before the CAS) - the execute
                # socket gets post-approval events only, exactly like the
                # detached continue producer; earlier history belongs to the
                # subscription/replay surface. One pump per socket, cancelled
                # on disconnect/re-subscribe by the dispatcher (same registry
                # the subscription pump uses).
                # Also send the "queued" ack here: the continue socket has the
                # same claim-delay window as a submission, and the FE ignores
                # unknown frames until it wires this one up
                with contextlib.suppress(Exception):
                    await websocket.send_text(
                        json.dumps({"event": "queued", "run_id": run_id, "session_id": session_id})
                    )
                await cancel_subscription_pump(websocket)
                _ws_tail_pumps[websocket] = asyncio.create_task(
                    _pump_event_stream_to_websocket(websocket, run_id, continue_outcome.get("tail_from"))
                )
                return
            # DELIBERATE transport asymmetry with the HTTP continue door
            # (which refuses this cell): the socket is itself the live event
            # channel the detached machinery streams into, so falling back
            # delivers exactly what the caller attached for - minus
            # durability, hence the warning.
            log_warning(
                "WS background continue bypasses the durable queue (no paused ticket for this "
                "run): executing on the accepting replica instead - bounded and observable, "
                "but NOT durable."
            )

        # Inline-door admission gate: a paused/queued/running durable ticket
        # OWNS this run's continuation - the detached WS door must refuse or
        # the cross-door double-execution race reopens (as an error frame,
        # this being a socket)
        try:
            await araise_if_ticket_owns_continue(
                getattr(websocket.app.state, "queue_worker", None),
                run_id,
                component_type="workflow",
                component_id=getattr(workflow, "id", None) or workflow_id,
            )
        except HTTPException as gate_exc:
            await websocket.send_text(json.dumps({"event": "error", "run_id": run_id, "error": str(gate_exc.detail)}))
            return

        # Continue workflow in background with WebSocket streaming.
        # Events are broadcast via WebSocketHandler through _handle_event calls,
        # which also handles event buffering and websocket manager broadcasting.
        await workflow.acontinue_run(  # type: ignore
            run_response=existing_run,
            session_id=session_id,
            stream=True,
            stream_events=True,
            background=True,
            websocket=websocket,
            enable_websocket=True,
        )

    except (InputCheckError, OutputCheckError) as e:
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": str(e),
                    "error_type": e.type,
                    "error_id": e.error_id,
                    "additional_data": e.additional_data,
                }
            )
        )
    except Exception as e:
        logger.error(f"Error continuing workflow via WebSocket: {e}")
        error_payload = {
            "event": "error",
            "error": str(e),
            "error_type": e.type if hasattr(e, "type") else None,
            "error_id": e.error_id if hasattr(e, "error_id") else None,
        }
        error_payload = {k: v for k, v in error_payload.items() if v is not None}
        await websocket.send_text(json.dumps(error_payload))


async def workflow_response_streamer(
    workflow: Union[Workflow, RemoteWorkflow],
    input: Union[str, Dict[str, Any], List[Any], BaseModel],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        # Pass auth_token for remote workflows
        if auth_token and isinstance(workflow, RemoteWorkflow):
            kwargs["auth_token"] = auth_token

        run_response = workflow.arun(  # type: ignore
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            **kwargs,
        )

        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore

        # If the workflow paused, yield WorkflowPausedEvent as the new clean
        # snapshot event. Also yield the legacy "WorkflowRunOutput" event for
        # backwards compatibility with older clients.
        if isinstance(workflow, RemoteWorkflow):
            return
        _session = await workflow.aget_session(session_id=session_id)
        if _session and _session.runs:
            _last_run = _session.runs[-1]
            if getattr(_last_run, "is_paused", False):
                from agno.run.workflow import WorkflowPausedEvent

                paused_event = WorkflowPausedEvent(
                    run_id=_last_run.run_id or "",
                    workflow_id=_last_run.workflow_id,
                    workflow_name=_last_run.workflow_name,
                    session_id=_last_run.session_id,
                    status=_last_run.status.value if hasattr(_last_run.status, "value") else _last_run.status,
                    paused_step_index=_last_run.paused_step_index,
                    paused_step_name=_last_run.paused_step_name,
                    pause_kind=_last_run.pause_kind,
                    step_requirements=_last_run.step_requirements,
                    step_results=_last_run.step_results,
                    step_executor_runs=_last_run.step_executor_runs,
                    content=_last_run.content,
                    metadata=_last_run.metadata,
                )
                yield format_sse_event(paused_event)

                # Legacy WorkflowRunOutput event for backwards compatibility
                run_dict = _last_run.to_dict()
                run_json = json.dumps(run_dict, default=json_serializer, separators=(",", ":"))
                yield f"event: WorkflowRunOutput\ndata: {run_json}\n\n"

    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def workflow_resumable_response_streamer(
    workflow: Union[Workflow, RemoteWorkflow],
    input: Union[str, Dict[str, Any], List[Any], BaseModel],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Resumable SSE generator for background=True, stream=True.

    Delegates to workflow.arun(background=True, stream=True) which handles:
    - Persisting RUNNING status in DB
    - Running workflow in a detached asyncio.Task (survives client disconnect)
    - Buffering events for reconnection via /resume
    - Publishing to SSE subscribers for resumed clients
    - Yielding SSE-formatted strings via a queue
    """
    if background_tasks is not None:
        kwargs["background_tasks"] = background_tasks

    if "stream_events" in kwargs:
        stream_events = kwargs.pop("stream_events")
    else:
        stream_events = True

    if auth_token and isinstance(workflow, RemoteWorkflow):
        kwargs["auth_token"] = auth_token

    try:
        async for sse_data in workflow.arun(  # type: ignore
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            background=True,
            **kwargs,
        ):
            yield sse_data
    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def workflow_continue_response_streamer(
    workflow: Workflow,
    run_id: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    step_requirements: Optional[List[Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    queue_worker: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        run_response = await workflow.acontinue_run(  # type: ignore
            run_id=run_id,
            session_id=session_id,
            step_requirements=step_requirements,
            stream=True,
            stream_events=True,
            **kwargs,
        )

        # Post-approval events must reach the event stream too: with
        # _handle_event transport-free, this response is otherwise their only
        # copy, and a later /resume or WS reconnect would replay just the
        # pre-pause prefix. Re-register (idempotent, cross-replica continue),
        # mark RUNNING, publish per event, and complete with the final status.
        await amark_continue_stream_running(run_id, component=workflow, session_id=session_id, user_id=user_id)

        try:
            async for run_response_chunk in run_response:
                if not isinstance(run_response_chunk, WorkflowRunOutput):
                    await workflow._apublish_stream_event(run_response_chunk, run_id)
                yield format_sse_event(run_response_chunk)  # type: ignore
        finally:
            # Stream close + paused-ticket settle as one cancellation-proof
            # unit; under cancellation the final status is KNOWN - see the
            # agents twin for both hazards. Otherwise it resolves from THIS
            # run's row, never session.runs[-1]
            import sys

            _exc = sys.exc_info()[0]
            _cancelled = _exc is not None and issubclass(_exc, (asyncio.CancelledError, GeneratorExit))
            await afinalize_continue_stream(
                workflow,
                run_id,
                session_id,
                queue_worker=queue_worker,
                final_status=RunStatus.cancelled if _cancelled else None,
            )

        # If the workflow re-paused, yield WorkflowPausedEvent as the new clean
        # snapshot event. Also yield the legacy "WorkflowRunOutput" event for
        # backwards compatibility with older clients.
        _session = await workflow.aget_session(session_id=session_id)
        if _session is not None:
            _last_run = _session.get_run(run_id)
            if _last_run is not None and getattr(_last_run, "is_paused", False):
                from agno.run.workflow import WorkflowPausedEvent

                paused_event = WorkflowPausedEvent(
                    run_id=_last_run.run_id or "",
                    workflow_id=_last_run.workflow_id,
                    workflow_name=_last_run.workflow_name,
                    session_id=_last_run.session_id,
                    status=_last_run.status.value if hasattr(_last_run.status, "value") else _last_run.status,
                    paused_step_index=_last_run.paused_step_index,
                    paused_step_name=_last_run.paused_step_name,
                    pause_kind=_last_run.pause_kind,
                    step_requirements=_last_run.step_requirements,
                    step_results=_last_run.step_results,
                    step_executor_runs=_last_run.step_executor_runs,
                    content=_last_run.content,
                    metadata=_last_run.metadata,
                )
                with contextlib.suppress(Exception):
                    await workflow._apublish_stream_event(paused_event, run_id)
                yield format_sse_event(paused_event)

                # Legacy WorkflowRunOutput event for backwards compatibility
                run_dict = _last_run.to_dict()
                run_json = json.dumps(run_dict, default=json_serializer, separators=(",", ":"))
                yield f"event: WorkflowRunOutput\ndata: {run_json}\n\n"

    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def _resume_stream_generator(
    workflow: Union[Workflow, RemoteWorkflow],
    run_id: str,
    last_event_index: Optional[int],
    session_id: Optional[str],
    user_id: Optional[str] = None,
) -> AsyncGenerator:
    """SSE generator for the /resume endpoint.

    Three reconnection paths:
    1. Run still active (in buffer): replay missed events + subscribe for live events via Queue
    2. Run completed (in buffer): replay all events since last_event_index
    3. Not in buffer: fall back to database replay
    """
    event_stream = get_event_stream()
    try:
        buffer_status = await event_stream.get_run_status(run_id)
    except Exception as e:
        # Network-backed streams can fail here; headers are already sent, so
        # the only honest signal is an SSE error frame (never a silent close,
        # and never a quiet fall-through to the DB path)
        log_error(f"Resume: event stream status probe failed for run {run_id}: {e}")
        yield sse_error_frame(f"event stream unavailable: {str(e)[:200]}")
        return

    if buffer_status is None:
        # PATH 3: Not in buffer -- fall back to database
        if session_id and not isinstance(workflow, RemoteWorkflow):
            try:
                run_output = await workflow.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
            except Exception as e:
                error = {"event": "error", "error": f"Failed to fetch run from database: {str(e)}"}
                yield f"event: error\ndata: {json.dumps(error)}\n\n"
                return
            if run_output and run_output.events:
                from agno.os.utils import stored_event_replay_frames

                for frame in stored_event_replay_frames(run_output, run_id, last_event_index):
                    yield frame
                return
            elif run_output:
                meta = {
                    "event": "replay",
                    "run_id": run_id,
                    "status": run_output.status.value
                    if hasattr(run_output.status, "value")
                    else (run_output.status or "unknown"),
                    "total_events": 0,
                    "message": "Run completed but no events stored.",
                }
                yield f"event: replay\ndata: {json.dumps(meta)}\n\n"
                return

        # Run not found anywhere
        error = {"event": "error", "error": f"Run {run_id} not found in buffer or database"}
        yield f"event: error\ndata: {json.dumps(error)}\n\n"
        return

    if buffer_status in (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused):
        # PATH 2: Run finished -- replay missed events from the event stream
        total_buffered = await event_stream.get_event_count(run_id)
        missed_events = await event_stream.replay(run_id, last_event_index=last_event_index)
        log_debug(
            f"Workflow resume PATH 2: run_id={run_id}, status={buffer_status.value}, "
            f"last_event_index={last_event_index}, total_buffered={total_buffered}, "
            f"missed_events={len(missed_events)}"
        )

        meta = {
            "event": "replay",
            "run_id": run_id,
            "status": buffer_status.value,
            "total_events": len(missed_events),
            "total_buffered": total_buffered,
            "last_event_index_requested": last_event_index if last_event_index is not None else -1,
            "message": f"Run {buffer_status.value}. Replaying {len(missed_events)} missed events (of {total_buffered} total).",
        }
        yield f"event: replay\ndata: {json.dumps(meta)}\n\n"

        for ev_index, payload in missed_events:
            yield replayed_payload_to_sse(payload, ev_index, run_id)
        return

    # PATH 1: Run still active (RUNNING, or PENDING while queued for a
    # concurrency slot) -- replay missed events, then tail live events. The
    # event stream's tail() owns the replay/subscribe race, dedup by
    # event_index, and terminal detection (including a producer that died
    # without writing a sentinel).
    missed_events = await event_stream.replay(run_id, last_event_index=last_event_index)
    current_count = await event_stream.get_event_count(run_id)

    last_replayed_index = last_event_index if last_event_index is not None else -1

    if missed_events:
        meta = {
            "event": "catch_up",
            "run_id": run_id,
            "status": "running",
            "missed_events": len(missed_events),
            "current_event_count": current_count,
            "message": f"Catching up on {len(missed_events)} missed events.",
        }
        yield f"event: catch_up\ndata: {json.dumps(meta)}\n\n"

        for ev_index, payload in missed_events:
            yield replayed_payload_to_sse(payload, ev_index, run_id)
            last_replayed_index = max(last_replayed_index, ev_index)

    # Confirm subscription for live events
    subscribed = {
        "event": "subscribed",
        "run_id": run_id,
        "status": "running",
        "current_event_count": current_count,
        "message": "Subscribed to workflow run. Receiving live events.",
    }
    yield f"event: subscribed\ndata: {json.dumps(subscribed)}\n\n"

    log_debug(f"SSE client subscribed to workflow run {run_id} (last_event_index: {last_event_index})")

    # Pump the tail through a queue so we can heartbeat on idle without
    # cancelling the tail generator (cancelling its __anext__ would kill it).
    tail_queue: asyncio.Queue = asyncio.Queue()

    async def _pump_tail() -> None:
        try:
            async for tail_item in event_stream.tail(run_id, last_event_index=last_replayed_index):
                await tail_queue.put(tail_item)
        except Exception as e:
            # A tail that DIES must not look like a tail that FINISHED: emit an
            # error frame so the client can distinguish and reconnect
            log_error(f"Resume tail failed for run {run_id}: {e}")
            with contextlib.suppress(Exception):
                await tail_queue.put((-1, sse_error_frame(f"stream tail failed: {str(e)[:200]}")))
        finally:
            await tail_queue.put(None)

    pump_task = asyncio.create_task(_pump_tail())
    try:
        while True:
            try:
                item = await asyncio.wait_for(tail_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Tail is idle (queued or silent run) - keep the connection alive
                yield ": heartbeat\n\n"
                continue
            if item is None:
                # Tail finished: run reached a terminal state
                break
            _ev_index, sse_data = item
            yield sse_data
    finally:
        pump_task.cancel()
        # Suppress everything, not just CancelledError: an exception re-raised
        # here reaches the ASGI layer on a response whose headers are already
        # sent (the pump has already surfaced it as an error frame)
        with contextlib.suppress(BaseException):
            await pump_task


def get_workflow_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """Create the workflow router with comprehensive OpenAPI documentation."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/workflows",
        response_model=List[WorkflowSummaryResponse],
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflows",
        summary="List All Workflows",
        description=(
            "Retrieve a comprehensive list of all workflows configured in this OS instance.\n\n"
            "**Return Information:**\n"
            "- Workflow metadata (ID, name, description)\n"
            "- Input schema requirements\n"
            "- Step sequence and execution flow\n"
            "- Associated agents and teams"
        ),
        responses={
            200: {
                "description": "List of workflows retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "content-creation-workflow",
                                "name": "Content Creation Workflow",
                                "description": "Automated content creation from blog posts to social media",
                                "db_id": "123",
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_workflows(request: Request) -> List[WorkflowSummaryResponse]:
        # Filter workflows based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import (
                build_insufficient_permissions_detail,
                filter_resources_by_access,
                get_accessible_resources,
            )

            # Check if user has any workflow scopes at all
            accessible_ids = get_accessible_resources(request, "workflows")
            if not accessible_ids:
                required_scopes = getattr(request.state, "required_scopes", None)
                raise HTTPException(
                    status_code=403,
                    detail=build_insufficient_permissions_detail(required_scopes),
                )

            accessible_workflows = filter_resources_by_access(request, os.workflows or [], "workflows")
        else:
            accessible_workflows = os.workflows or []

        workflows: List[WorkflowSummaryResponse] = []
        if accessible_workflows:
            for workflow in accessible_workflows:
                workflows.append(WorkflowSummaryResponse.from_workflow(workflow=workflow, is_component=False))

        if os.db and isinstance(os.db, BaseDb):
            from agno.workflow.workflow import get_workflows

            # Exclude the ids this OS actually serves, which is exactly what
            # the code objects above render: a stored row sharing one of them
            # would list the same workflow twice. The registry is a superset -
            # it also carries rehydration context this route never lists - so
            # subtracting it instead would drop a stored workflow with nothing
            # left to list it back.
            exclude_ids = {wid for w in os.workflows or [] if (wid := getattr(w, "id", None)) is not None}
            db_workflows = get_workflows(
                db=os.db,
                registry=os.registry,
                exclude_component_ids=exclude_ids or None,
                user_id=get_scoped_user_id(request),
            )
            if db_workflows:
                # Apply the same RBAC filtering to DB-loaded workflows:
                # without it, a caller whose scope excludes a workflow
                # still saw its config here (the agents endpoint already
                # filters)
                if getattr(request.state, "authorization_enabled", False):
                    db_workflows = filter_resources_by_access(request, db_workflows, "workflows")
            for db_workflow in db_workflows or []:
                try:
                    workflows.append(WorkflowSummaryResponse.from_workflow(workflow=db_workflow, is_component=True))
                except Exception:
                    workflow_id = getattr(db_workflow, "id", "unknown")
                    logger.exception(f"Error converting workflow {workflow_id} to response")
                    continue

        return workflows

    @router.get(
        "/workflows/{workflow_id}",
        response_model=WorkflowResponse,
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflow",
        summary="Get Workflow Details",
        description=("Retrieve detailed configuration and step information for a specific workflow."),
        responses={
            200: {
                "description": "Workflow details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "content-creation-workflow",
                            "name": "Content Creation Workflow",
                            "description": "Automated content creation from blog posts to social media",
                            "db_id": "123",
                        }
                    }
                },
            },
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "read", "workflow_id"))],
    )
    async def get_workflow(
        workflow_id: str,
        request: Request,
        version: Optional[int] = Query(None, description="Workflow version to retrieve"),
    ) -> WorkflowResponse:
        # Factory workflows: return factory metadata directly
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            return WorkflowResponse.from_factory(factory)

        # An explicit version is a control-plane preview, and this is the one
        # read route that takes one: publishing shares a component for reading,
        # so without this gate any actor who can see it could pin - and read -
        # the owner's unpublished drafts. Same 404 the run routes raise, so a
        # denial is indistinguishable from the component being absent.
        if not allow_draft_preview(os.db, workflow_id, version, *draft_preview_identity(request)):
            raise HTTPException(status_code=404, detail="Workflow not found")

        try:
            workflow = get_workflow_by_id(
                workflow_id=workflow_id,
                workflows=os.workflows,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                version=version,
                user_id=get_scoped_user_id(request),
                published_only=False,
            )  # type: ignore[assignment]
        except ComponentRehydrationError as rehydration_error:
            raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resolving workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if isinstance(workflow, RemoteWorkflow):
            return await workflow.get_workflow_config()
        else:
            return await WorkflowResponse.from_workflow(workflow=workflow)

    @router.post(
        "/workflows/{workflow_id}/runs",
        tags=["Workflows"],
        operation_id="create_workflow_run",
        response_model_exclude_none=True,
        summary="Execute Workflow",
        description=(
            "Execute a workflow with the provided input data. Workflows can run in streaming or batch mode.\n\n"
            "**Execution Modes:**\n"
            "- **Streaming (`stream=true`)**: Real-time step-by-step execution updates via SSE\n"
            "- **Non-Streaming (`stream=false`)**: Complete workflow execution with final result\n\n"
            "**Workflow Execution Process:**\n"
            "1. Input validation against workflow schema\n"
            "2. Sequential or parallel step execution based on workflow design\n"
            "3. Data flow between steps with transformation\n"
            "4. Error handling and automatic retries where configured\n"
            "5. Final result compilation and response\n\n"
            "**Session Management:**\n"
            "Workflows support session continuity for stateful execution across multiple runs."
        ),
        responses={
            200: {
                "description": "Workflow executed successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid input data or workflow configuration", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
            500: {"description": "Workflow execution error", "model": InternalServerErrorResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def create_workflow_run(
        workflow_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(..., description="The input message or prompt to send to the workflow"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        background: bool = Form(
            False,
            description="Run workflow in background (survives client disconnect). Requires database. Use /resume to reconnect.",
        ),
        session_id: Optional[str] = Form(
            None, description="Session ID for conversation continuity. If not provided, a new session is created"
        ),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        version: Optional[int] = Form(None, description="Workflow version to use for this run"),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow construction",
        ),
    ):
        kwargs = await get_request_kwargs(request, create_workflow_run)

        # Scoped non-admin callers always get their JWT sub as user_id.
        # Admins and unscoped callers fall through to middleware/form values.
        scoped_user_id = get_scoped_user_id(request)
        state_user_id = getattr(request.state, "user_id", None)
        if scoped_user_id is not None:
            user_id = scoped_user_id
        elif state_user_id == INTERNAL_SCHEDULER_USER_ID:
            # The sentinel identifies the caller, not the owner: keep the form-field ``user_id``
            # the executor wrote, which is None for an unowned schedule.
            pass
        elif state_user_id is not None:
            if user_id and user_id != state_user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = state_user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state") and request.state.session_state is not None:
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies") and request.state.dependencies is not None:
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata") and request.state.metadata is not None:
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        # Retrieve the workflow by ID (supports both static and factory components)
        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            version=version,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )

        # Version-stable preview: an explicitly pinned version is recorded on
        # the run itself (run metadata), so the lifecycle routes can reload
        # the SAME version later instead of whatever is current by then.
        stamp_component_version(kwargs, version)

        # A run must not enter a session owned by someone else: the runs table has no
        # ownership predicate, so an unguarded write is replayed into the owner's history.
        # ``effective_user_id`` is what will actually stamp the session row - the route's
        # user_id, else the component's own default. Passing the raw ``user_id`` here would
        # 404 every second run of a component that sets one.
        effective_user_id = user_id or getattr(workflow, "user_id", None)
        await assert_session_writable(
            getattr(workflow, "db", None) or os.db,
            session_id,
            effective_user_id,
            session_type=SessionType.WORKFLOW,
            is_admin=caller_is_admin(request),
        )

        if session_id:
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        # Extract auth token for remote workflows
        auth_token = get_auth_token_from_request(request)

        # Background execution
        if background:
            if isinstance(workflow, RemoteWorkflow):
                raise HTTPException(
                    status_code=400, detail="Background execution is not supported for remote workflows"
                )
            # The db requirement gates BOTH shapes here: the non-stream
            # branch always 400ed, while the stream branch used to enter the
            # detached streamer and let arun(background=True) raise - the
            # same misconfiguration answered 200 + SSE error frame,
            # indistinguishable from a runtime failure.
            if not workflow.db:
                raise HTTPException(
                    status_code=400,
                    detail="Background execution requires a database to be configured on the workflow",
                )

            if stream:
                # Durable queued streaming: the queue row is the acceptance,
                # execution happens on whichever worker claims it, and this
                # response tails the event stream. Durability attaches to the
                # RUN (complete output guaranteed via the run row); the live
                # stream is the best-effort view.
                queue_worker = getattr(request.app.state, "queue_worker", None)
                queued_stream_payload = {"input": message, "kwargs": kwargs, "stream": True}
                stream_queueable = (
                    queue_worker is not None
                    and getattr(workflow, "db", None) is not None
                    and version is None
                    and payload_is_queueable(queued_stream_payload)
                    and any(
                        getattr(candidate, "id", None) == workflow_id and not isinstance(candidate, WorkflowFactory)
                        for candidate in (os.workflows or [])
                    )
                )
                if stream_queueable:
                    # 202/stream-accept must honor input_schema like the inline path (400)
                    validate_seam_input(workflow, message)
                    assert queue_worker is not None  # narrowed by stream_queueable
                    from agno.run.base import RunStatus as _RS

                    queued_run_id = str(uuid4())
                    queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                    job = QueuedJob(
                        id=queued_run_id,
                        component_type="workflow",
                        component_id=getattr(workflow, "id", None) or workflow_id,
                        session_id=queued_session_id,
                        user_id=user_id,
                        payload=queued_stream_payload,
                        max_attempts=queue_worker.config.max_attempts,
                        deployment_id=queue_worker.config.deployment_id,
                        idempotency_key=normalize_idempotency_key(request.headers.get("idempotency-key")),
                    ).to_dict()
                    enqueue_result = await queue_worker.store.enqueue_job(
                        job, max_depth=queue_worker.config.max_queue_depth
                    )
                    if enqueue_result["reason"] == "queue_full":
                        raise HTTPException(status_code=429, detail="Job queue is full")
                    if enqueue_result["reason"] == "duplicate":
                        existing = enqueue_result["job"]
                        if existing is None:
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency-Key was already used but the original run could not be retrieved",
                            )
                        ensure_duplicate_matches_component(existing, "workflow", job["component_id"])
                        if not (existing.get("payload") or {}).get("stream"):
                            # The key was used by a NON-stream submission: its
                            # run never registers in the event stream, so a
                            # tail would close instantly and silently. Refuse
                            # honestly instead.
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency-Key was used by a non-streaming submission; "
                                f"poll run {existing['id']} instead of attaching a stream",
                            )
                        # Attach to the ORIGINAL run's stream. A terminal
                        # original (or one whose stream keys already expired)
                        # gets the full resume path - buffer or DB replay -
                        # instead of a blind tail that would close silently
                        # with zero events.
                        if existing.get("status") in ("queued", "running"):
                            return StreamingResponse(
                                queued_run_tail_streamer(existing["id"]), media_type="text/event-stream"
                            )
                        return StreamingResponse(
                            _resume_stream_generator(
                                workflow, existing["id"], None, existing.get("session_id"), user_id
                            ),
                            media_type="text/event-stream",
                        )
                    with contextlib.suppress(Exception):
                        # Fail-open: the queue row is already committed - a Redis blip
                        # must not 500 an accepted submission (tails degrade gracefully)
                        await get_event_stream().register_run(queued_run_id, _RS.pending)
                    await aprepare_accepted_or_abort(
                        queue_worker, workflow, "workflow", queued_run_id, queued_session_id, user_id, message
                    )
                    return StreamingResponse(queued_run_tail_streamer(queued_run_id), media_type="text/event-stream")
                if queue_worker is not None:
                    log_warning(
                        "Streaming background workflow run bypasses the durable queue "
                        "(remote/factory/version-pinned submissions are not queueable): "
                        "bounded and observable, but NOT durable."
                    )
                # background=True, stream=True: resumable SSE streaming
                # Workflow runs in a detached asyncio.Task that survives client disconnections.
                # Events are buffered for reconnection via /resume endpoint.
                return StreamingResponse(
                    workflow_resumable_response_streamer(
                        workflow,
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )

            # background=True, stream=False: return 202 immediately with run
            # metadata (the db requirement was enforced at the top of the
            # background branch, for both shapes)
            # Durable queue path: acceptance is a committed row; whichever
            # replica's worker claims the job executes it, surviving crashes
            # and deploys. Client contract identical: 202 + poll.
            queue_worker = getattr(request.app.state, "queue_worker", None)
            # Queueable only if this is a plain registry instance: the worker
            # resolves from the registry, so factory-backed or off-registry
            # (db-resolved / version-pinned) components would be accepted here
            # and then fail or run differently in the worker.
            component_is_queueable = any(
                getattr(candidate, "id", None) == workflow_id and not isinstance(candidate, WorkflowFactory)
                for candidate in (os.workflows or [])
            )
            queued_payload = {"input": message, "kwargs": kwargs}
            if (
                queue_worker is not None
                and component_is_queueable
                and version is None  # version-pinned resolution differs from the worker's registry instance
                and payload_is_queueable(queued_payload)
            ):
                # 202 must honor input_schema exactly like the inline path (400)
                validate_seam_input(workflow, message)
                queued_run_id = str(uuid4())
                queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                job = QueuedJob(
                    id=queued_run_id,
                    component_type="workflow",
                    component_id=getattr(workflow, "id", None) or workflow_id,
                    session_id=queued_session_id,
                    user_id=user_id,
                    payload=queued_payload,
                    max_attempts=queue_worker.config.max_attempts,
                    deployment_id=queue_worker.config.deployment_id,
                    idempotency_key=normalize_idempotency_key(request.headers.get("idempotency-key")),
                ).to_dict()

                # Enqueue FIRST: the committed queue row is the acceptance.
                # Rejected or duplicate submissions must leave no phantom
                # PENDING run behind in the session.
                enqueue_result = await queue_worker.store.enqueue_job(
                    job, max_depth=queue_worker.config.max_queue_depth
                )
                if enqueue_result["reason"] == "queue_full":
                    raise HTTPException(status_code=429, detail="Job queue is full")
                if enqueue_result["reason"] == "duplicate" and enqueue_result["job"] is not None:
                    existing = enqueue_result["job"]
                    ensure_duplicate_matches_component(existing, "workflow", job["component_id"])
                    return JSONResponse(
                        status_code=202,
                        content={
                            "run_id": existing["id"],
                            "session_id": existing["session_id"],
                            # Same vocabulary as the run poll: a duplicate of a
                            # failed run says ERROR (not an invented "FAILED"),
                            # and a running one says RUNNING (not PENDING).
                            "status": ticket_status_to_api(existing["status"]) or existing["status"].upper(),
                        },
                    )
                if enqueue_result["reason"] == "duplicate":
                    # Duplicate but the original row could not be retrieved:
                    # NEVER fall through to a 202 for a run that was not
                    # enqueued - that acceptance would be a lie
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key was already used but the original run could not be retrieved",
                    )
                # Accepted: persist the PENDING run row so pollers find it.
                # Idempotent - a worker that already claimed the job wins.
                await aprepare_accepted_or_abort(
                    queue_worker, workflow, "workflow", queued_run_id, queued_session_id, user_id, message
                )
                return JSONResponse(
                    status_code=202,
                    content={"run_id": queued_run_id, "session_id": queued_session_id, "status": "PENDING"},
                )
            elif queue_worker is not None:
                # EVERY bypass reason warns - a client gets its 202 either way
                # and must never silently believe acceptance was durable.
                if not payload_is_queueable(queued_payload):
                    log_warning(
                        "Background run bypasses the durable queue: the submission carries values plain "
                        "JSON cannot store (e.g. output_schema classes or media objects). Executing on the "
                        "accepting replica instead - bounded and observable, but NOT durable."
                    )
                else:
                    # Off-registry, factory-backed, or version-pinned: the
                    # worker resolves from the registry, so these cannot ride
                    # the queue - previously this dropped to the non-durable
                    # path with no log line at all.
                    log_warning(
                        "Background run bypasses the durable queue: the workflow is not a plain "
                        "registry instance (remote, factory-backed, db-resolved, or version-pinned "
                        "resolution differs from the worker's registry instance). Executing on the "
                        "accepting replica instead - bounded and observable, but NOT durable."
                    )

            # Same input-error contract as the inline path: schema violations
            # are refused up front (the dispatch's own schema ValueError is
            # indistinguishable from an internal one, so it is not caught -
            # internal failures keep their generic 500), and guardrail
            # refusals from the dispatch answer 400.
            validate_seam_input(workflow, message)
            try:
                run_response = await workflow.arun(
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                    background=True,
                    background_tasks=background_tasks,
                    **kwargs,
                )
            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return JSONResponse(
                status_code=202,
                content={
                    "run_id": run_response.run_id,
                    "session_id": run_response.session_id,
                    "status": run_response.status.value if run_response.status else "PENDING",
                },
            )

        # Return based on stream parameter
        try:
            if stream:
                return StreamingResponse(
                    workflow_response_streamer(
                        workflow,
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                # Pass auth_token for remote workflows
                if auth_token and isinstance(workflow, RemoteWorkflow):
                    kwargs["auth_token"] = auth_token

                # Schema violations are refused up front with the seams'
                # shared check: the dispatch's own schema ValueError is
                # indistinguishable from an internal one, so it is not
                # caught - internal failures keep their generic 500.
                validate_seam_input(workflow, message)
                run_response = await workflow.arun(
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                    background_tasks=background_tasks,
                    **kwargs,
                )
                return run_response.to_dict()

        except InputCheckError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # No blanket 500 (agents parity): the old except Exception swallowed
        # every typed error - including HTTPException itself, converting 4xx
        # into 500 - and echoed raw internals in the detail. Uncaught
        # exceptions propagate to FastAPI's generic 500.

    @router.post(
        "/workflows/{workflow_id}/runs/{run_id}/continue",
        tags=["Workflows"],
        operation_id="continue_workflow_run",
        response_model_exclude_none=True,
        summary="Continue Workflow Run",
        description=(
            "Continue a paused workflow run with resolved requirements.\n\n"
            "**Use Cases:**\n"
            "- Resume after step-level HITL (confirmation, user input, router selection)\n"
            "- Resume after executor-level HITL (agent/team tool confirmation within a step)\n\n"
            "**Requirements Parameter:**\n"
            "JSON string containing the resolved step requirements."
        ),
        responses={
            200: {
                "description": "Workflow run continued successfully",
                "content": {
                    "text/event-stream": {"example": 'event: StepCompleted\ndata: {"step_name": "step1"}\n\n'},
                },
            },
            400: {"description": "Invalid JSON in requirements field", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
            409: {
                "description": "Run is not paused. Only PAUSED runs can be continued.",
            },
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def continue_workflow_run(
        workflow_id: str,
        run_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        step_requirements: str = Form("", description="JSON string of step requirement objects with resolution status"),
        session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        background: bool = Form(
            False,
            description="Continue in background (survives client disconnect). Requires database. Use /resume to reconnect.",
        ),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            session_id = request.state.session_id

        # Parse step requirements JSON
        try:
            step_requirements_data = json.loads(step_requirements) if step_requirements else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in step_requirements field")

        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
            published_only=False,
        )

        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Continue is not supported for remote workflows")

        # Ownership check before status validation — see continue_agent_run.
        # Non-admin callers must own the session AND the run must belong to
        # this workflow (per-resource RBAC).
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                workflow,
                session_id,
                run_id,
                scoped_user_id,
                component_type="workflows",
                component_id=workflow_id,
            )

        # Load existing run and validate it's paused
        existing_run = await workflow.aget_run_output(
            run_id=run_id, session_id=session_id, user_id=scoped_user_id or user_id
        )
        if existing_run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        if not getattr(existing_run, "is_paused", False):
            status = getattr(existing_run, "status", None)
            _status_to_detail = {
                RunStatus.pending: "run is already pending",
                RunStatus.running: "run is already running",
                RunStatus.completed: "run is already completed",
                RunStatus.error: "run has errored",
                RunStatus.cancelled: "run is already cancelled",
            }
            detail = _status_to_detail.get(
                status,  # type: ignore[arg-type]
                f"run is not paused (status={getattr(status, 'value', status)})",
            )
            raise HTTPException(status_code=409, detail=detail)

        # Version-stable continuation: a run started with an explicitly pinned
        # version (draft preview) recorded it in its run metadata; continue on
        # THAT version, not whatever is published/current now. No stamp
        # (legacy or unpinned runs) keeps today's resolution. Factories build
        # per-request, so they are exempt.
        stamped_version = stamped_component_version(existing_run)
        if stamped_version is not None and not find_factory_by_id(workflow_id, os.workflows):
            # Re-run the run-start preview gate before trusting the stamp: a
            # stamp naming a draft version this caller may not preview must not
            # resolve (defense against a forged/leaked stamp). Same 404 the
            # run-start route raises, so a denial is indistinguishable from the
            # component being absent.
            if not allow_draft_preview(os.db, workflow_id, stamped_version, *draft_preview_identity(request)):
                raise HTTPException(status_code=404, detail="Workflow not found")
            try:
                stamped_workflow = get_workflow_by_id(
                    workflow_id=workflow_id,
                    workflows=os.workflows,
                    db=os.db,
                    registry=os.registry,
                    version=stamped_version,
                    create_fresh=True,
                    user_id=scoped_user_id,
                    published_only=False,
                )
            except ComponentRehydrationError as rehydration_error:
                raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
            if stamped_workflow is None or isinstance(stamped_workflow, RemoteWorkflow):
                raise HTTPException(
                    status_code=404,
                    detail=f"Workflow version {stamped_version} recorded on run {run_id} is no longer available",
                )
            workflow = stamped_workflow

        # Convert step requirements dicts to StepRequirement objects
        from agno.workflow.types import StepRequirement

        parsed_requirements: Optional[List[StepRequirement]] = None
        if step_requirements_data:
            try:
                parsed_requirements = [StepRequirement.from_dict(req) for req in step_requirements_data]
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Invalid structure or content for step_requirements: {str(e)}"
                )

        # Force JWT user_id for non-admin callers so a spoofed user_id cannot
        # attribute the continued run to another user.
        effective_user_id = scoped_user_id if scoped_user_id is not None else user_id

        if background:
            # Durable continue: CAS the run's EXISTING paused ticket back to
            # queued (same row, same run_id) so the continuation leg survives
            # crashes and executes on whichever worker claims it. Runs that
            # never rode the queue have no ticket to transition and keep the
            # non-background path below.
            queue_worker = getattr(request.app.state, "queue_worker", None)
            continue_payload = {"step_requirements": step_requirements_data}
            workflow_is_queueable = any(
                getattr(candidate, "id", None) == workflow_id and not isinstance(candidate, WorkflowFactory)
                for candidate in (os.workflows or [])
            )
            if queue_worker is not None and workflow_is_queueable and payload_is_queueable(continue_payload):
                # The endpoint already proved the run row is PAUSED above
                continue_outcome = await acontinue_via_queue(
                    queue_worker,
                    run_id,
                    continue_payload,
                    stream_requested=stream,
                    component_type="workflow",
                    component_id=getattr(workflow, "id", None) or workflow_id,
                )
                if continue_outcome is not None:
                    outcome, ticket = continue_outcome["outcome"], continue_outcome.get("job")
                    if outcome == "stream_mismatch":
                        # Pre-CAS refusal: nothing was accepted behind this
                        # 409 (submit-seam duplicate parity)
                        raise HTTPException(
                            status_code=409,
                            detail=f"Run was submitted non-streaming; poll run {run_id} instead of attaching a stream",
                        )
                    if outcome == "settling":
                        raise HTTPException(
                            status_code=409,
                            detail="Run is settling between execution legs; retry in a moment",
                            headers={"Retry-After": "1"},
                        )
                    if outcome == "conflict":
                        ticket_status = (ticket or {}).get("status", "unknown")
                        raise HTTPException(
                            status_code=409,
                            detail=f"Run is not continuable (ticket status: {ticket_status})",
                        )
                    # queued (accepted) or attach (double-click): same
                    # response shape as the submit seam
                    if stream:
                        # Tail from the PRE-ACCEPT index (captured by the
                        # helper before the CAS): the continue response
                        # carries post-approval events only, exactly like the
                        # detached continue streamer; earlier history belongs
                        # to /resume
                        return StreamingResponse(
                            queued_run_tail_streamer(run_id, from_index=continue_outcome.get("tail_from")),
                            media_type="text/event-stream",
                        )
                    return JSONResponse(
                        status_code=202,
                        content={"run_id": run_id, "session_id": session_id, "status": "PENDING"},
                    )
            # No durable path (no worker, factory/remote workflow, or no
            # paused ticket): refuse. The background param on this HTTP
            # endpoint arrived with the durable queue, so no pre-queue
            # clients depend on a fallthrough (unlike agents/teams, whose
            # inline non-stream fallthrough is kept for back-compat), and
            # HTTP has no workflow detached-continue machinery to serve
            # instead - a replica-bound foreground response would silently
            # fake the semantics the caller asked for.
            #
            # DELIBERATE transport asymmetry: the workflow WebSocket
            # continue door falls back to detached execution with a warning
            # for this same cell, because the socket is itself the live
            # event channel the detached machinery streams into. HTTP has
            # no equivalent until workflows grow the resumable-continue
            # streamer agents/teams have.
            raise HTTPException(
                status_code=409,
                detail="background=true continuation is only available for durably-submitted "
                "workflow runs (a paused queue ticket); this run has none. Retry without "
                "background, or submit the workflow with background=true and a durable queue.",
            )

        # Inline-door admission gate: a paused/queued/running durable ticket
        # OWNS this run's continuation; non-queue doors must refuse or the
        # cross-door double-execution race reopens. 409/503 raise here.
        await araise_if_ticket_owns_continue(
            getattr(request.app.state, "queue_worker", None),
            run_id,
            component_type="workflow",
            component_id=getattr(workflow, "id", None) or workflow_id,
        )

        if stream:
            return StreamingResponse(
                workflow_continue_response_streamer(
                    workflow,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=effective_user_id,
                    step_requirements=parsed_requirements,
                    background_tasks=background_tasks,
                    queue_worker=getattr(request.app.state, "queue_worker", None),
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                # Ownership already verified above; acontinue_run loads the run
                # via {session_id, run_id} which we've proven the caller owns.
                run_response = await workflow.acontinue_run(  # type: ignore[call-overload]
                    run_id=run_id,
                    session_id=session_id,
                    step_requirements=parsed_requirements,
                    stream=False,
                    background_tasks=background_tasks,
                )
                # Status-only stream sync (deliberate scope): a non-stream
                # continue has no events to publish, but a formerly-queued/
                # streamed run's stream view must stop saying PAUSED once the
                # continue settles - only_if_tracked leaves never-streamed
                # runs alone.
                # Stream close + paused-ticket settle as one
                # cancellation-proof unit (see the streaming twin)
                await afinalize_continue_stream(
                    workflow,
                    run_id,
                    session_id,
                    queue_worker=getattr(request.app.state, "queue_worker", None),
                    only_if_tracked=True,
                    final_status=getattr(run_response, "status", None),
                )
                return run_response.to_dict()
            # Same typed mapping as the agents continue endpoint: a
            # race-losing continue (the run moved past PAUSED between the
            # pre-check and dispatch) must answer 404/409/400 like the
            # pre-check would have, never a blanket 500. Anything untyped
            # propagates (FastAPI's 500, without echoing internals).
            except RunNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except RunNotContinuableError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except (InputCheckError, ValueError) as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/workflows/{workflow_id}/runs/{run_id}/cancel",
        tags=["Workflows"],
        operation_id="cancel_workflow_run",
        summary="Cancel Workflow Run",
        description=(
            "Cancel a currently executing workflow run, stopping all active steps and cleanup.\n"
            "**Note:** Complex workflows with multiple parallel steps may take time to fully cancel."
        ),
        responses={
            200: {},
            404: {"description": "Workflow or run not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel workflow run", "model": InternalServerErrorResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def cancel_workflow_run(
        request: Request,
        workflow_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ):
        # Factory workflows: cancel is static, no workflow instance needed.
        # Non-admin callers must still prove session ownership before we apply
        # a global cancellation intent keyed solely on run_id.
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            from agno.run.cancel import acancel_run

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None:
                if not session_id:
                    raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="workflows",
                    component_id=workflow_id,
                )

            # Tombstone a still-queued durable ticket first: intent alone
            # does not stop a job no task is executing yet
            queue_worker = getattr(request.app.state, "queue_worker", None)
            if queue_worker is not None:
                await queue_worker.acancel_queued(run_id)
            await acancel_run(run_id)
            return JSONResponse(content={}, status_code=200)

        try:
            workflow = get_workflow_by_id(
                workflow_id=workflow_id,
                workflows=os.workflows,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                strict=False,
                published_only=False,
            )  # type: ignore[assignment]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resolving workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Ownership check: non-admin JWT callers must supply a session_id and the
        # run must live in a session they own. Admins / unauthenticated bypass.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                workflow,
                session_id,
                run_id,
                scoped_user_id,
                component_type="workflows",
                component_id=workflow_id,
            )

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        # Tombstone a still-queued durable ticket first: intent alone
        # does not stop a job no task is executing yet
        queue_worker = getattr(request.app.state, "queue_worker", None)
        if queue_worker is not None:
            await queue_worker.acancel_queued(run_id)
        await workflow.acancel_run(run_id=run_id)
        return JSONResponse(content={}, status_code=200)

    @router.post(
        "/workflows/{workflow_id}/runs/{run_id}/resume",
        tags=["Workflows"],
        operation_id="resume_workflow_run_stream",
        summary="Resume Workflow Run Stream",
        description=(
            "Resume an SSE stream for a workflow run after disconnection.\n\n"
            "Sends missed events since `last_event_index`, then continues streaming "
            "live events if the run is still active.\n\n"
            "**Three reconnection paths:**\n"
            "1. **Run still active**: Sends catch-up events + continues live streaming\n"
            "2. **Run completed (in buffer)**: Replays missed buffered events\n"
            "3. **Run completed (in database)**: Replays events from database\n\n"
            "**Client usage:**\n"
            "Track `event_index` from each SSE event. On reconnection, pass the last "
            "received `event_index` as `last_event_index`."
        ),
        responses={
            200: {
                "description": "SSE stream of catch-up and/or live events",
                "content": {"text/event-stream": {}},
            },
            400: {"description": "Not supported for remote workflows", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def resume_workflow_run_stream(
        request: Request,
        workflow_id: str,
        run_id: str,
        last_event_index: Optional[int] = Form(None, description="Index of last event received by client (0-based)"),
        session_id: Optional[str] = Form(None, description="Session ID for database fallback"),
    ):
        # Ownership check up-front (see resume_agent_run_stream for rationale).
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)

        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            if scoped_user_id is not None:
                assert session_id is not None
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="workflows",
                    component_id=workflow_id,
                )
            raise HTTPException(
                status_code=400,
                detail="Stream resumption is not supported for factory workflows",
            )

        workflow = get_workflow_by_id(
            workflow_id=workflow_id,
            workflows=os.workflows,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
            user_id=scoped_user_id,
            strict=False,
            published_only=False,
        )
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Stream resumption is not supported for remote workflows")

        if scoped_user_id is not None:
            assert session_id is not None
            await verify_run_in_session(
                workflow,
                session_id,
                run_id,
                scoped_user_id,
                component_type="workflows",
                component_id=workflow_id,
            )

        return StreamingResponse(
            _resume_stream_generator(workflow, run_id, last_event_index, session_id, user_id=scoped_user_id),
            media_type="text/event-stream",
        )

    @router.get(
        "/workflows/{workflow_id}/runs/{run_id}",
        tags=["Workflows"],
        operation_id="get_workflow_run",
        summary="Get Workflow Run",
        description=(
            "Retrieve the status and output of a workflow run. Use this to poll for run completion.\n\n"
            "Requires the `session_id` that was returned when the run was created."
        ),
        responses={
            200: {"description": "Run output retrieved successfully"},
            404: {"description": "Workflow or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def get_workflow_run(
        request: Request,
        workflow_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
        factory_input: Optional[str] = Query(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        user_id = getattr(request.state, "user_id", None)
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and query params, using request state")
            session_id = request.state.session_id

        # Factory workflows: resolve to get a real workflow for session lookup
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            workflow = await resolve_workflow(  # type: ignore[assignment]
                workflow_id,
                os.workflows,
                factory.db,
                request=request,
                user_id=user_id,
                session_id=session_id,
                factory_input=factory_input,
                published_only=False,
            )
        else:
            try:
                workflow = get_workflow_by_id(
                    workflow_id=workflow_id,
                    workflows=os.workflows,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving workflow '{workflow_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if workflow is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Run polling is not supported for remote workflows")

        user_id = get_scoped_user_id(request)

        # Verify session belongs to this workflow BEFORE loading the run.
        # See get_agent_run for the cross-component bypass this blocks.
        if hasattr(workflow, "aget_session"):
            session = await workflow.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                # The acceptance is the committed ticket; the run row (and on
                # a fresh session, the session row) lands a beat later. A 404
                # inside that beat reports an accepted run as nonexistent -
                # answer from the ticket instead, tenant-checked, fail-closed.
                ticket_view = await aticket_poll_fallback(
                    getattr(request.app.state, "queue_worker", None),
                    run_id,
                    session_id,
                    "workflow",
                    workflow_id,
                    user_id,
                    user_scoped=user_id is not None,
                )
                if ticket_view is not None:
                    return ticket_view
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "workflows", workflow_id, not_found_detail="Run not found")

        run_output = await workflow.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
        if run_output is None:
            ticket_view = await aticket_poll_fallback(
                getattr(request.app.state, "queue_worker", None),
                run_id,
                session_id,
                "workflow",
                workflow_id,
                user_id,
                user_scoped=user_id is not None,
            )
            if ticket_view is not None:
                return ticket_view
            raise HTTPException(status_code=404, detail="Run not found")

        # Per-resource RBAC: the run must explicitly belong to the path workflow.
        # Fail closed when workflow_id is missing.
        if not run_matches_component(run_output, "workflows", workflow_id):
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.get(
        "/workflows/{workflow_id}/runs",
        tags=["Workflows"],
        operation_id="list_workflow_runs",
        summary="List Workflow Runs",
        description=(
            "List runs for a workflow within a session, optionally filtered by status.\n\n"
            "Useful for monitoring background runs and viewing run history."
        ),
        responses={
            200: {"description": "List of runs retrieved successfully"},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def list_workflow_runs(
        workflow_id: str,
        request: Request,
        session_id: str = Query(..., description="Session ID to list runs for"),
        status: Optional[str] = Query(
            None, description="Filter by run status (PENDING, RUNNING, COMPLETED, ERROR, PAUSED)"
        ),
        factory_input: Optional[str] = Query(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        from agno.os.schema import WorkflowRunSchema

        # Non-admin callers must only see runs from sessions they own. Admins
        # (scoped_user_id is None) bypass and can list runs for any session.
        scoped_user_id = get_scoped_user_id(request)
        user_id = scoped_user_id if scoped_user_id is not None else getattr(request.state, "user_id", None)
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and query params, using request state")
            session_id = request.state.session_id

        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
            strict=False,
            published_only=False,
        )
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Run listing is not supported for remote workflows")

        # Read-only session lookup (no create) so we don't manufacture a session
        # for a user who shouldn't see it. For non-admins, scope by user_id so
        # mismatched ownership returns 404, not a leak.
        lookup_user_id = scoped_user_id if scoped_user_id is not None else None
        session = await workflow.aget_session(session_id=session_id, user_id=lookup_user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Per-resource RBAC: the session must explicitly belong to this workflow.
        # Fail closed when workflow_id is missing — an agent/team session
        # must not be reachable through a workflow route.
        assert_session_matches_component(session, "workflows", workflow_id)

        runs = session.runs or []

        # Filter to runs that belong to this workflow. Workflow sessions can
        # carry nested member runs whose workflow_id is unset; fail closed
        # rather than leaking those.
        result = []
        for run in runs:
            if not run_matches_component(run, "workflows", workflow_id):
                continue
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(WorkflowRunSchema.from_dict(run_dict))

        return result

    return router
