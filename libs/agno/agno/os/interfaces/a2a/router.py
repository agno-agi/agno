"""Async router exposing an Agno Agent/Team/Workflow over the A2A 1.0 protocol."""

import warnings
from typing import Optional, Union
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentInterface,
        AgentSkill,
        Message,
        Part,
        Role,
        SendMessageResponse,
        Task,
        TaskState,
        TaskStatus,
    )
    from a2a.utils.errors import (
        JSON_RPC_ERROR_CODE_MAP,
        A2AError,
        InvalidParamsError,
        MethodNotFoundError,
        PushNotificationNotSupportedError,
        TaskNotCancelableError,
        TaskNotFoundError,
        UnsupportedOperationError,
        VersionNotSupportedError,
    )
    from google.protobuf import json_format
except ImportError as e:
    raise ImportError("`a2a-sdk>=1.0` is required. Install with `pip install -U 'a2a-sdk>=1.0'`.") from e

from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.os.auth import check_resource_access
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    session_id_or_new,
    stream_a2a_response_with_error_handling,
)
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id, verify_run_in_session
from agno.os.utils import (
    get_agent_by_id,
    get_request_kwargs,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.run.base import RunStatus
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow


# --- shared helpers ------------------------------------------------------------


def _proto_to_jsonable(msg) -> dict:
    return json_format.MessageToDict(
        msg,
        preserving_proto_field_name=False,
        always_print_fields_with_no_presence=False,
    )


def _send_message_envelope(request_id, task: Task) -> dict:
    """JSON-RPC 2.0 envelope around a SendMessageResponse holding a Task."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": _proto_to_jsonable(SendMessageResponse(task=task)),
    }


def _task_envelope(request_id, task: Task) -> dict:
    """JSON-RPC 2.0 envelope around a bare Task.

    GetTask/CancelTask responses carry the Task directly (the a2a-sdk client
    parses `result` as a Task) — only Send* wraps it in SendMessageResponse.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": _proto_to_jsonable(task),
    }


def _build_failed_task(exc: Exception, context_id: Optional[str]) -> Task:
    """Build a Task in failed state with a generic error message in history.

    The real exception goes to the server log only — wire responses must not
    leak internal details (paths, connection strings, stack context).
    """
    log_error(f"A2A run failed: {type(exc).__name__}: {exc}")
    ctx = context_id or str(uuid4())
    error_message = Message(
        message_id=str(uuid4()),
        role=Role.ROLE_AGENT,
        context_id=ctx,
        parts=[Part(text="Error: the run failed due to an internal server error.", media_type="text/plain")],
    )
    return Task(
        id=str(uuid4()),
        context_id=ctx,
        status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
        history=[error_message],
    )


# Run states in which a task can no longer be cancelled.
_TERMINAL_RUN_STATUSES = {RunStatus.completed, RunStatus.error, RunStatus.cancelled}


def _jsonrpc_error_response(request_id, error: A2AError) -> JSONResponse:
    """JSON-RPC 2.0 error envelope with the A2A spec error code for `error`.

    Per the JSON-RPC binding, protocol-level errors ride an HTTP 200 response;
    only transport concerns (auth, malformed HTTP) use HTTP status codes.
    """
    code = JSON_RPC_ERROR_CODE_MAP.get(type(error), -32603)
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": error.message},
        }
    )


def _resolve_a2a_user_id(request: Request, request_body: dict) -> Optional[str]:
    """Resolve the run's ``user_id``, mirroring the REST run route's identity pinning.

    A2A must not take run identity from the client: the client-supplied ``X-User-ID``
    header / ``metadata.userId`` is honoured for attribution only when the caller is
    anonymous (see ``resolve_run_user_id`` for the full precedence).
    """
    client_uid = request.headers.get("X-User-ID")
    if not client_uid:
        client_uid = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")
    return resolve_run_user_id(request, client_uid)


def _entity_family(entity) -> str:
    if isinstance(entity, (Team, RemoteTeam)):
        return "teams"
    if isinstance(entity, (Workflow, RemoteWorkflow)):
        return "workflows"
    return "agents"


def _check_a2a_scope(request: Request, family: str, entity_id: str, action: str = "run") -> None:
    """In-handler RBAC check for routes whose URL alone cannot authorize the
    operation (the JSON-RPC dispatchers multiplex read and run methods on one URL).
    """
    if not getattr(request.state, "authorization_enabled", False):
        return
    if not check_resource_access(request, entity_id, family, action):
        raise HTTPException(status_code=403, detail=f"Insufficient permissions to {action} this {family[:-1]}")


def _enforce_dynamic_dispatch_scope(request: Request, entity: object, entity_id: str) -> None:
    """Re-check the run scope for the resolved family on the deprecated dispatch routes.

    ``POST /message:send`` / ``:stream`` resolve the target as an agent, team, OR workflow
    at runtime, so the route-level gate can only require a single coarse scope (``agents:run``).
    That would let an ``agents:run``-only token execute teams/workflows. Once the entity is
    resolved we know its family, so enforce ``<family>:run`` via the canonical RBAC decision.
    No-op when RBAC is not active.
    """
    _check_a2a_scope(request, _entity_family(entity), entity_id, "run")


_SUPPORTED_A2A_MAJOR = "1"


def _check_a2a_version(request: Request, request_id) -> Optional[JSONResponse]:
    """Reject explicitly-unsupported A2A-Version values.

    A missing header is served as the current version: this server does not
    implement 0.3 (the spec default for absent headers), and rejecting every
    header-less client would break otherwise-compatible 1.0 callers.
    """
    version = request.headers.get("A2A-Version")
    if not version:
        return None
    if version.split(".")[0] != _SUPPORTED_A2A_MAJOR:
        return _jsonrpc_error_response(
            request_id,
            VersionNotSupportedError(f"Unsupported A2A version {version!r}; this server supports 1.x"),
        )
    return None


def _build_agent_card(
    *,
    name: str,
    description: str,
    base_url: str,
    interface_path: str,
    skill_id: str,
    streaming: bool,
) -> AgentCard:
    """Construct an A2A v1 AgentCard with a single JSON-RPC interface."""
    skill = AgentSkill(
        id=skill_id,
        name=name,
        description=description,
        tags=["agno"],
        output_modes=["text/plain", "application/json"],
    )
    capabilities = AgentCapabilities(
        streaming=streaming,
        push_notifications=False,
        extended_agent_card=False,
    )
    interface = AgentInterface(
        url=f"{base_url}{interface_path}",
        protocol_binding="JSONRPC",
        protocol_version="1.0",
    )
    return AgentCard(
        name=name,
        version="1.0.0",
        description=description,
        supported_interfaces=[interface],
        # Input/output modes are media types per the spec.
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        capabilities=capabilities,
        skills=[skill],
    )


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
) -> APIRouter:
    if agents is None and teams is None and workflows is None:
        raise ValueError("Agents, Teams, or Workflows are required to setup the A2A interface.")

    # Mount prefix (e.g. "/a2a", or custom via A2A(prefix=...)) — agent-card
    # interface URLs must advertise the real mount point.
    prefix = router.prefix or ""

    # JSON-RPC methods this server declines, with their spec error. Push
    # notification configs and the remaining optional operations are declared
    # unsupported in the agent card capabilities.
    _PUSH_CONFIG_METHODS = {
        "CreateTaskPushNotificationConfig",
        "GetTaskPushNotificationConfig",
        "ListTaskPushNotificationConfigs",
        "DeleteTaskPushNotificationConfig",
    }
    _UNSUPPORTED_METHODS = {"ListTasks", "SubscribeToTask", "GetExtendedAgentCard"}
    _METHOD_ACTIONS = {"SendMessage": "run", "SendStreamingMessage": "run", "GetTask": "read", "CancelTask": "run"}

    async def _dispatch_a2a_method(request: Request, id: str, family: str, handlers: dict) -> JSONResponse:
        """Shared JSON-RPC dispatcher body for all three families.

        The scope check is per-method because one URL multiplexes read and run
        operations — route-level gating cannot distinguish them.
        """
        # Note: delegated handlers call request.json() again; Starlette caches
        # the body so this is a single read on the wire.
        body = await request.json()
        request_id = body.get("id")
        version_error = _check_a2a_version(request, request_id)
        if version_error is not None:
            return version_error

        method = body.get("method") or ""
        if method in _PUSH_CONFIG_METHODS:
            return _jsonrpc_error_response(request_id, PushNotificationNotSupportedError())
        if method in _UNSUPPORTED_METHODS:
            return _jsonrpc_error_response(request_id, UnsupportedOperationError(f"{method} is not supported"))
        handler = handlers.get(method)
        if handler is None:
            if method in _METHOD_ACTIONS:
                # Known spec method this family cannot serve (e.g. workflow tasks).
                return _jsonrpc_error_response(
                    request_id, UnsupportedOperationError(f"{method} is not supported for {family}")
                )
            return _jsonrpc_error_response(
                request_id, MethodNotFoundError(f"Method not found or not supported: {method!r}")
            )

        _check_a2a_scope(request, family, id, _METHOD_ACTIONS[method])
        try:
            return await handler(request, id)
        except HTTPException as exc:
            # Map task-level failures onto the spec's typed JSON-RPC errors;
            # auth and server errors stay transport-level HTTP.
            if exc.status_code == 404 and method in ("GetTask", "CancelTask"):
                return _jsonrpc_error_response(request_id, TaskNotFoundError(str(exc.detail)))
            if exc.status_code == 400:
                return _jsonrpc_error_response(request_id, InvalidParamsError(str(exc.detail)))
            raise

    # ============= AGENTS =============
    @router.get("/agents/{id}/.well-known/agent-card.json")
    async def get_agent_card(request: Request, id: str):
        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=agent.name or "",
                    description=getattr(agent, "description", None) or "",
                    base_url=base_url,
                    interface_path=f"{prefix}/agents/{agent.id}/v1",
                    skill_id=agent.id or "",
                    streaming=True,
                )
            )
        )

    @router.post(
        "/agents/{id}/v1/message:send",
        operation_id="run_message_agent",
        name="run_message_agent",
        description="Send a message to an Agno Agent (non-streaming). The Agent is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Agent not found"},
        },
    )
    async def a2a_run_agent(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_agent)

        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not isinstance(agent, (Agent, RemoteAgent)):
            raise HTTPException(status_code=501, detail="A2A protocol is not supported for this agent type")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        blocking = request_body.get("params", {}).get("configuration", {}).get("blocking", True)

        try:
            response = await agent.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                background=not blocking,
                **kwargs,
            )

            a2a_task = map_run_output_to_a2a_task(response)
            # The JSON-RPC binding expects 200 for every successful envelope,
            # including non-blocking sends (the SUBMITTED state carries the async
            # semantics; a 202 makes strict clients treat the call as failed).
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

        except Exception as e:
            failed_task = _build_failed_task(e, context_id)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), failed_task))

    @router.post(
        "/agents/{id}/v1/tasks:get",
        operation_id="get_agent_task",
        name="get_agent_task",
        description="Get the status and result of an agent task by ID.",
    )
    async def a2a_get_agent_task(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        request_body = await request.json()
        params = request_body.get("params", {})
        task_id = params.get("id")
        context_id = params.get("contextId")

        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID (params.id) is required")
        if not context_id:
            # The run is not locatable without its session.
            raise HTTPException(status_code=400, detail="contextId is required to poll a task")

        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Task polling is not supported for remote agents")
        if not isinstance(agent, Agent):
            raise HTTPException(status_code=501, detail="Task polling is not supported for this agent type")

        # A scoped caller may only read runs in sessions it owns, pinned to this
        # agent (mirrors feat/v2.7's tasks:get hardening).
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            await verify_run_in_session(
                agent, context_id, task_id, scoped_user_id, component_type="agents", component_id=id
            )

        run_output = await agent.aget_run_output(run_id=task_id, session_id=context_id, user_id=scoped_user_id)
        if not run_output:
            raise HTTPException(status_code=404, detail="Task not found")

        a2a_task = map_run_output_to_a2a_task(run_output)
        return JSONResponse(content=_task_envelope(request_body.get("id", "unknown"), a2a_task))

    @router.post(
        "/agents/{id}/v1/tasks:cancel",
        operation_id="cancel_agent_task",
        name="cancel_agent_task",
        description="Cancel a running agent task.",
    )
    async def a2a_cancel_agent_task(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        request_body = await request.json()
        params = request_body.get("params", {})
        task_id = params.get("id")

        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID (params.id) is required")

        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Task cancellation is not supported for remote agents")
        if not isinstance(agent, Agent):
            raise HTTPException(status_code=501, detail="Task cancellation is not supported for this agent type")

        # CancelTaskRequest has no contextId field; the official client can carry
        # it in the request's metadata Struct, so accept both locations.
        context_id = params.get("contextId") or params.get("metadata", {}).get("contextId")
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not context_id:
                raise HTTPException(status_code=400, detail="contextId is required to cancel a task")
            await verify_run_in_session(
                agent, context_id, task_id, scoped_user_id, component_type="agents", component_id=id
            )

        # When the run is locatable, be honest about the outcome: a finished run
        # is not cancelable and a nonexistent one is not found. Without a
        # contextId (unscoped callers only) keep the blind cancel-intent store —
        # it covers cancel-before-start scenarios.
        if context_id:
            run_output = await agent.aget_run_output(run_id=task_id, session_id=context_id, user_id=scoped_user_id)
            if run_output is None:
                return _jsonrpc_error_response(request_body.get("id"), TaskNotFoundError())
            if run_output.status in _TERMINAL_RUN_STATUSES:
                return _jsonrpc_error_response(request_body.get("id"), TaskNotCancelableError())

        await agent.acancel_run(run_id=task_id)

        canceled_task = Task(
            id=task_id,
            context_id=context_id or str(uuid4()),
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
        )
        return JSONResponse(content=_task_envelope(request_body.get("id", "unknown"), canceled_task))

    @router.post(
        "/agents/{id}/v1/message:stream",
        operation_id="stream_message_agent",
        name="stream_message_agent",
        description="Stream a message to an Agno Agent. The Agent is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns Server-Sent Events.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Agent not found"},
        },
    )
    async def a2a_stream_agent(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_agent)

        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            event_stream = agent.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                stream=True,
                stream_events=True,
                **kwargs,
            )
            return StreamingResponse(
                stream_a2a_response_with_error_handling(
                    event_stream=event_stream,  # type: ignore[arg-type]
                    request_id=request_body.get("id", ""),
                ),
                media_type="text/event-stream",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    @router.post(
        "/agents/{id}/v1",
        operation_id="a2a_agent_jsonrpc",
        name="a2a_agent_jsonrpc",
        description="A2A 1.0 JSON-RPC dispatcher for an Agno Agent. The official a2a-sdk client POSTs every operation here with the method in the JSON-RPC `method` field.",
    )
    async def a2a_agent_jsonrpc(request: Request, id: str):
        return await _dispatch_a2a_method(
            request,
            id,
            "agents",
            {
                "SendMessage": a2a_run_agent,
                "SendStreamingMessage": a2a_stream_agent,
                "GetTask": a2a_get_agent_task,
                "CancelTask": a2a_cancel_agent_task,
            },
        )

    # ============= TEAMS =============
    @router.get("/teams/{id}/.well-known/agent-card.json")
    async def get_team_card(request: Request, id: str):
        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=team.name or "",
                    description=team.description or "",
                    base_url=base_url,
                    interface_path=f"{prefix}/teams/{team.id}/v1",
                    skill_id=team.id or "",
                    streaming=True,
                )
            )
        )

    @router.post(
        "/teams/{id}/v1/message:send",
        operation_id="run_message_team",
        name="run_message_team",
        description="Send a message to an Agno Team (non-streaming). The Team is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Team not found"},
        },
    )
    async def a2a_run_team(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_team)

        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        blocking = request_body.get("params", {}).get("configuration", {}).get("blocking", True)

        try:
            response = await team.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                background=not blocking,
                **kwargs,
            )

            a2a_task = map_run_output_to_a2a_task(response)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

        except Exception as e:
            failed_task = _build_failed_task(e, context_id)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), failed_task))

    @router.post(
        "/teams/{id}/v1/tasks:get",
        operation_id="get_team_task",
        name="get_team_task",
        description="Get the status and result of a team task by ID.",
    )
    async def a2a_get_team_task(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        request_body = await request.json()
        params = request_body.get("params", {})
        task_id = params.get("id")
        context_id = params.get("contextId")

        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID (params.id) is required")
        if not context_id:
            raise HTTPException(status_code=400, detail="contextId is required to poll a task")

        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Task polling is not supported for remote teams")

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            await verify_run_in_session(
                team, context_id, task_id, scoped_user_id, component_type="teams", component_id=id
            )

        run_output = await team.aget_run_output(run_id=task_id, session_id=context_id, user_id=scoped_user_id)
        if not run_output:
            raise HTTPException(status_code=404, detail="Task not found")

        a2a_task = map_run_output_to_a2a_task(run_output)  # type: ignore[arg-type]
        return JSONResponse(content=_task_envelope(request_body.get("id", "unknown"), a2a_task))

    @router.post(
        "/teams/{id}/v1/tasks:cancel",
        operation_id="cancel_team_task",
        name="cancel_team_task",
        description="Cancel a running team task.",
    )
    async def a2a_cancel_team_task(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        request_body = await request.json()
        params = request_body.get("params", {})
        task_id = params.get("id")

        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID (params.id) is required")

        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Task cancellation is not supported for remote teams")

        context_id = params.get("contextId") or params.get("metadata", {}).get("contextId")
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not context_id:
                raise HTTPException(status_code=400, detail="contextId is required to cancel a task")
            await verify_run_in_session(
                team, context_id, task_id, scoped_user_id, component_type="teams", component_id=id
            )

        if context_id:
            run_output = await team.aget_run_output(run_id=task_id, session_id=context_id, user_id=scoped_user_id)
            if run_output is None:
                return _jsonrpc_error_response(request_body.get("id"), TaskNotFoundError())
            if run_output.status in _TERMINAL_RUN_STATUSES:
                return _jsonrpc_error_response(request_body.get("id"), TaskNotCancelableError())

        await team.acancel_run(run_id=task_id)

        canceled_task = Task(
            id=task_id,
            context_id=context_id or str(uuid4()),
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
        )
        return JSONResponse(content=_task_envelope(request_body.get("id", "unknown"), canceled_task))

    @router.post(
        "/teams/{id}/v1/message:stream",
        operation_id="stream_message_team",
        name="stream_message_team",
        description="Stream a message to an Agno Team. The Team is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns Server-Sent Events.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Team not found"},
        },
    )
    async def a2a_stream_team(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_team)

        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            event_stream = team.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                stream=True,
                stream_events=True,
                **kwargs,
            )
            return StreamingResponse(
                stream_a2a_response_with_error_handling(
                    event_stream=event_stream,  # type: ignore[arg-type]
                    request_id=request_body.get("id", ""),
                ),
                media_type="text/event-stream",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    @router.post(
        "/teams/{id}/v1",
        operation_id="a2a_team_jsonrpc",
        name="a2a_team_jsonrpc",
        description="A2A 1.0 JSON-RPC dispatcher for an Agno Team.",
    )
    async def a2a_team_jsonrpc(request: Request, id: str):
        return await _dispatch_a2a_method(
            request,
            id,
            "teams",
            {
                "SendMessage": a2a_run_team,
                "SendStreamingMessage": a2a_stream_team,
                "GetTask": a2a_get_team_task,
                "CancelTask": a2a_cancel_team_task,
            },
        )

    # ============= WORKFLOWS =============
    @router.get("/workflows/{id}/.well-known/agent-card.json")
    async def get_workflow_card(request: Request, id: str):
        workflow = get_workflow_by_id(id, workflows, create_fresh=True)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=workflow.name or "",
                    description=workflow.description or "",
                    base_url=base_url,
                    interface_path=f"{prefix}/workflows/{workflow.id}/v1",
                    skill_id=workflow.id or "",
                    # The workflow message:stream route exists — the card must say so,
                    # or SDK clients refuse to stream from workflows.
                    streaming=True,
                )
            )
        )

    @router.post(
        "/workflows/{id}/v1/message:send",
        operation_id="run_message_workflow",
        name="run_message_workflow",
        description="Send a message to an Agno Workflow (non-streaming). The Workflow is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Workflow not found"},
        },
    )
    async def a2a_run_workflow(request: Request, id: str):
        if not workflows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_workflow)

        workflow = get_workflow_by_id(id, workflows, create_fresh=True)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            response = await workflow.arun(
                input=run_input.input_content,
                images=list(run_input.images) if run_input.images else None,
                videos=list(run_input.videos) if run_input.videos else None,
                audio=list(run_input.audios) if run_input.audios else None,
                files=list(run_input.files) if run_input.files else None,
                session_id=context_id,
                user_id=user_id,
                **kwargs,
            )
            a2a_task = map_run_output_to_a2a_task(response)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

        except Exception as e:
            failed_task = _build_failed_task(e, context_id)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), failed_task))

    @router.post(
        "/workflows/{id}/v1/message:stream",
        operation_id="stream_message_workflow",
        name="stream_message_workflow",
        description="Stream a message to an Agno Workflow. The Workflow is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns Server-Sent Events.",
        responses={
            400: {"description": "Invalid request"},
            404: {"description": "Workflow not found"},
        },
    )
    async def a2a_stream_workflow(request: Request, id: str):
        if not workflows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_workflow)

        workflow = get_workflow_by_id(id, workflows, create_fresh=True)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        version_error = _check_a2a_version(request, request_body.get("id"))
        if version_error is not None:
            return version_error

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            event_stream = workflow.arun(
                input=run_input.input_content,
                images=list(run_input.images) if run_input.images else None,
                videos=list(run_input.videos) if run_input.videos else None,
                audio=list(run_input.audios) if run_input.audios else None,
                files=list(run_input.files) if run_input.files else None,
                session_id=context_id,
                user_id=user_id,
                stream=True,
                stream_events=True,
                **kwargs,
            )
            return StreamingResponse(
                stream_a2a_response_with_error_handling(
                    event_stream=event_stream, request_id=request_body.get("id", "")
                ),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    @router.post(
        "/workflows/{id}/v1",
        operation_id="a2a_workflow_jsonrpc",
        name="a2a_workflow_jsonrpc",
        description="A2A 1.0 JSON-RPC dispatcher for an Agno Workflow.",
    )
    async def a2a_workflow_jsonrpc(request: Request, id: str):
        # Workflows have no task get/cancel routes; the dispatcher reports those
        # spec methods as UnsupportedOperation rather than MethodNotFound.
        return await _dispatch_a2a_method(
            request,
            id,
            "workflows",
            {
                "SendMessage": a2a_run_workflow,
                "SendStreamingMessage": a2a_stream_workflow,
            },
        )

    # ============= DEPRECATED ENDPOINTS =============

    @router.post(
        "/message/send",
        operation_id="send_message",
        name="send_message",
        description="[DEPRECATED] Send a message. Use /agents|teams|workflows/{id}/v1/message:send instead. "
        "Entity is selected via 'agentId' in params.message or X-Agent-ID header.",
    )
    async def a2a_send_message(request: Request):
        warnings.warn(
            "This endpoint will be deprecated soon. Use /agents/{agents_id}/v1/message:send, "
            "/teams/{teams_id}/v1/message:send, or /workflows/{workflows_id}/v1/message:send instead.",
            DeprecationWarning,
        )

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_send_message)

        agent_id = request_body.get("params", {}).get("message", {}).get("agentId") or request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide it via 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, RemoteAgent, AgentProtocol, Team, RemoteTeam, Workflow, RemoteWorkflow]] = None
        if agents:
            entity = get_agent_by_id(agent_id, agents, create_fresh=True)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams, create_fresh=True)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows, create_fresh=True)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        # The route-level gate for this dynamic-dispatch endpoint can only be
        # coarse; re-check the resolved entity's family here (mirrors feat/v2.7's
        # _enforce_dynamic_dispatch_scope).
        _enforce_dynamic_dispatch_scope(request, entity, agent_id)

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            if isinstance(entity, Workflow):
                response = await entity.arun(
                    input=run_input.input_content,
                    images=list(run_input.images) if run_input.images else None,
                    videos=list(run_input.videos) if run_input.videos else None,
                    audio=list(run_input.audios) if run_input.audios else None,
                    files=list(run_input.files) if run_input.files else None,
                    session_id=context_id,
                    user_id=user_id,
                    **kwargs,
                )
            else:
                response = await entity.arun(
                    input=run_input.input_content,
                    images=run_input.images,  # type: ignore
                    videos=run_input.videos,  # type: ignore
                    audio=run_input.audios,  # type: ignore
                    files=run_input.files,  # type: ignore
                    session_id=context_id,
                    user_id=user_id,
                    **kwargs,
                )

            a2a_task = map_run_output_to_a2a_task(response)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

        except Exception as e:
            failed_task = _build_failed_task(e, context_id)
            return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), failed_task))

    @router.post(
        "/message/stream",
        operation_id="stream_message",
        name="stream_message",
        description="[DEPRECATED] Stream a message. Use /agents|teams|workflows/{id}/v1/message:stream instead.",
    )
    async def a2a_stream_message(request: Request):
        warnings.warn(
            "This endpoint will be deprecated soon. Use /agents/{agents_id}/v1/message:stream, "
            "/teams/{teams_id}/v1/message:stream, or /workflows/{workflows_id}/v1/message:stream instead.",
            DeprecationWarning,
        )

        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_message)

        agent_id = request_body.get("params", {}).get("message", {}).get("agentId")
        if not agent_id:
            agent_id = request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, RemoteAgent, AgentProtocol, Team, RemoteTeam, Workflow, RemoteWorkflow]] = None
        if agents:
            entity = get_agent_by_id(agent_id, agents, create_fresh=True)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams, create_fresh=True)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows, create_fresh=True)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        _enforce_dynamic_dispatch_scope(request, entity, agent_id)

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        # contextId is optional on first contact: mint the session here (never forward
        # None to arun -- see session_id_or_new) and return it to the client via the
        # Task / stream events so the conversation can be continued.
        context_id = session_id_or_new(request_body.get("params", {}).get("message", {}).get("contextId"))
        user_id = _resolve_a2a_user_id(request, request_body)

        try:
            if isinstance(entity, Workflow):
                event_stream = entity.arun(
                    input=run_input.input_content,
                    images=list(run_input.images) if run_input.images else None,
                    videos=list(run_input.videos) if run_input.videos else None,
                    audio=list(run_input.audios) if run_input.audios else None,
                    files=list(run_input.files) if run_input.files else None,
                    session_id=context_id,
                    user_id=user_id,
                    stream=True,
                    stream_events=True,
                    **kwargs,
                )
            else:
                event_stream = entity.arun(  # type: ignore
                    input=run_input.input_content,
                    images=run_input.images,
                    videos=run_input.videos,
                    audio=run_input.audios,
                    files=run_input.files,
                    session_id=context_id,
                    user_id=user_id,
                    stream=True,
                    stream_events=True,
                    **kwargs,
                )
            return StreamingResponse(
                stream_a2a_response_with_error_handling(
                    event_stream=event_stream, request_id=request_body.get("id", "")
                ),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    return router
