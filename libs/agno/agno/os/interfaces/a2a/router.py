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
    from google.protobuf import json_format
except ImportError as e:
    raise ImportError("`a2a-sdk>=1.0` is required. Install with `pip install -U 'a2a-sdk>=1.0'`.") from e

from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    stream_a2a_response_with_error_handling,
)
from agno.os.utils import get_agent_by_id, get_request_kwargs, get_team_by_id, get_workflow_by_id
from agno.team import RemoteTeam, Team
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


def _build_failed_task(exc: Exception, context_id: Optional[str]) -> Task:
    """Build a Task in failed state with an error message in history."""
    ctx = context_id or str(uuid4())
    error_message = Message(
        message_id=str(uuid4()),
        role=Role.ROLE_AGENT,
        context_id=ctx,
        parts=[Part(text=f"Error: {str(exc)}", media_type="text/plain")],
    )
    return Task(
        id=str(uuid4()),
        context_id=ctx,
        status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
        history=[error_message],
    )


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
        examples=["search", "ok"],
        output_modes=["application/json"],
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
        default_input_modes=["text"],
        default_output_modes=["text"],
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

    # ============= AGENTS =============
    @router.get("/agents/{id}/.well-known/agent-card.json")
    async def get_agent_card(request: Request, id: str):
        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=agent.name or "",
                    description=getattr(agent, "description", None) or "",
                    base_url=base_url,
                    interface_path=f"/a2a/agents/{agent.id}/v1",
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

        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not isinstance(agent, (Agent, RemoteAgent)):
            raise HTTPException(status_code=501, detail="A2A protocol is not supported for this agent type")

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
            status_code = 202 if not blocking else 200
            return JSONResponse(
                content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task),
                status_code=status_code,
            )

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

        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Task polling is not supported for remote agents")
        if not isinstance(agent, Agent):
            raise HTTPException(status_code=501, detail="Task polling is not supported for this agent type")

        run_output = await agent.aget_run_output(run_id=task_id, session_id=context_id)
        if not run_output:
            raise HTTPException(status_code=404, detail="Task not found")

        a2a_task = map_run_output_to_a2a_task(run_output)
        return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

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

        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Task cancellation is not supported for remote agents")
        if not isinstance(agent, Agent):
            raise HTTPException(status_code=501, detail="Task cancellation is not supported for this agent type")

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await agent.acancel_run(run_id=task_id)

        context_id = params.get("contextId", str(uuid4()))
        canceled_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
        )
        return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), canceled_task))

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

        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
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
        body = await request.json()
        method = body.get("method") or ""
        if method == "SendMessage":
            return await a2a_run_agent(request, id)
        if method == "SendStreamingMessage":
            return await a2a_stream_agent(request, id)
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32601, "message": f"Method not found or not supported: {method!r}"},
            },
        )

    # ============= TEAMS =============
    @router.get("/teams/{id}/.well-known/agent-card.json")
    async def get_team_card(request: Request, id: str):
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=team.name or "",
                    description=team.description or "",
                    base_url=base_url,
                    interface_path=f"/a2a/teams/{team.id}/v1",
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

        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
            status_code = 202 if not blocking else 200
            return JSONResponse(
                content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task),
                status_code=status_code,
            )

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

        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Task polling is not supported for remote teams")

        run_output = await team.aget_run_output(run_id=task_id, session_id=context_id)
        if not run_output:
            raise HTTPException(status_code=404, detail="Task not found")

        a2a_task = map_run_output_to_a2a_task(run_output)  # type: ignore[arg-type]
        return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), a2a_task))

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

        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Task cancellation is not supported for remote teams")

        await team.acancel_run(run_id=task_id)

        context_id = params.get("contextId", str(uuid4()))
        canceled_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
        )
        return JSONResponse(content=_send_message_envelope(request_body.get("id", "unknown"), canceled_task))

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

        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
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
        body = await request.json()
        method = body.get("method") or ""
        if method == "SendMessage":
            return await a2a_run_team(request, id)
        if method == "SendStreamingMessage":
            return await a2a_stream_team(request, id)
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32601, "message": f"Method not found or not supported: {method!r}"},
            },
        )

    # ============= WORKFLOWS =============
    @router.get("/workflows/{id}/.well-known/agent-card.json")
    async def get_workflow_card(request: Request, id: str):
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=_proto_to_jsonable(
                _build_agent_card(
                    name=workflow.name or "",
                    description=workflow.description or "",
                    base_url=base_url,
                    interface_path=f"/a2a/workflows/{workflow.id}/v1",
                    skill_id=workflow.id or "",
                    streaming=False,
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

        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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

        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
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
        body = await request.json()
        method = body.get("method") or ""
        if method == "SendMessage":
            return await a2a_run_workflow(request, id)
        if method == "SendStreamingMessage":
            return await a2a_stream_workflow(request, id)
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32601, "message": f"Method not found or not supported: {method!r}"},
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
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        try:
            if isinstance(entity, Workflow):
                response = entity.arun(
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
                response = entity.arun(
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
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

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
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    return router
