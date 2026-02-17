"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

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
        AgentSkill,
        SendMessageSuccessResponse,
        Task,
        TaskState,
        TaskStatus,
    )
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e

import warnings

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    stream_a2a_response_with_error_handling,
)
from agno.os.utils import get_agent_by_id, get_request_kwargs, get_team_by_id, get_workflow_by_id
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
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
        skill = AgentSkill(
            id=agent.id or "",
            name=agent.name or "",
            description=agent.description or "",
            tags=["agno"],
            examples=["search", "ok"],
            output_modes=["application/json"],
        )

        return AgentCard(
            name=agent.name or "",
            version="1.0.0",
            description=agent.description or "",
            url=f"{base_url}/a2a/agents/{agent.id}/v1/message:stream",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=True, push_notifications=False, state_transition_history=False),
            skills=[skill],
            supports_authenticated_extended_card=False,
        )

    @router.post(
        "/agents/{id}/v1/message:send",
        operation_id="run_message_agent",
        name="run_message_agent",
        description="Send a message to an Agno Agent (non-streaming). The Agent is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Message sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "task": {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": "completed",
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from agent"}],
                                        }
                                    ],
                                }
                            },
                        }
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Agent not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_run_agent(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_agent)

        # 1. Get the Agent to run
        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Check if non-blocking execution is requested
        blocking = request_body.get("params", {}).get("configuration", {}).get("blocking", True)

        # 4. Run the Agent
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

            # 5. Send the response
            a2a_task = map_run_output_to_a2a_task(response)
            status_code = 202 if not blocking else 200
            result = SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=a2a_task,
            )
            return JSONResponse(
                content=result.model_dump(exclude_none=True),
                status_code=status_code,
            )

        # Handle any critical error
        except Exception as e:
            from a2a.types import Message as A2AMessage
            from a2a.types import Part, Role, TextPart

            error_message = A2AMessage(
                message_id=str(uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=f"Error: {str(e)}"))],
                context_id=context_id or str(uuid4()),
            )
            failed_task = Task(
                id=str(uuid4()),
                context_id=context_id or str(uuid4()),
                status=TaskStatus(state=TaskState.failed),
                history=[error_message],
            )

            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=failed_task,
            )

    @router.post(
        "/agents/{id}/v1/tasks:get",
        operation_id="get_agent_task",
        name="get_agent_task",
        description="Get the status and result of an agent task by ID.",
        response_model_exclude_none=True,
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

        run_output = await agent.aget_run_output(run_id=task_id, session_id=context_id)
        if not run_output:
            raise HTTPException(status_code=404, detail="Task not found")

        a2a_task = map_run_output_to_a2a_task(run_output)
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=a2a_task,
        )

    @router.post(
        "/agents/{id}/v1/tasks:cancel",
        operation_id="cancel_agent_task",
        name="cancel_agent_task",
        description="Cancel a running agent task.",
        response_model_exclude_none=True,
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

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await agent.acancel_run(run_id=task_id)

        context_id = params.get("contextId", str(uuid4()))
        canceled_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.canceled),
        )
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=canceled_task,
        )

    @router.post(
        "/agents/{id}/v1/message:stream",
        operation_id="stream_message_agent",
        name="stream_message_agent",
        description="Stream a message to an Agno Agent (streaming). The Agent is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as newline-delimited JSON (NDJSON).",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Streaming response with task updates",
                "content": {
                    "text/event-stream": {
                        "example": 'event: TaskStatusUpdateEvent\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"taskId":"task-456","status":"working"}}\n\n'
                        'event: Message\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"messageId":"msg-1","role":"agent","parts":[{"kind":"text","text":"Response"}]}}\n\n'
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Agent not found"},
        },
    )
    async def a2a_stream_agent(request: Request, id: str):
        if not agents:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_agent)

        # 1. Get the Agent to run
        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Agent and stream the response
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

            # 4. Stream the response
            return StreamingResponse(
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    # ============= TEAMS =============
    @router.get("/teams/{id}/.well-known/agent-card.json")
    async def get_team_card(request: Request, id: str):
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        base_url = str(request.base_url).rstrip("/")
        skill = AgentSkill(
            id=team.id or "",
            name=team.name or "",
            description=team.description or "",
            tags=["agno"],
            examples=["search", "ok"],
            output_modes=["application/json"],
        )
        return AgentCard(
            name=team.name or "",
            version="1.0.0",
            description=team.description or "",
            url=f"{base_url}/a2a/teams/{team.id}/v1/message:stream",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=True, push_notifications=False, state_transition_history=False),
            skills=[skill],
            supports_authenticated_extended_card=False,
        )

    @router.post(
        "/teams/{id}/v1/message:send",
        operation_id="run_message_team",
        name="run_message_team",
        description="Send a message to an Agno Team (non-streaming). The Team is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Message sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "task": {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": "completed",
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from agent"}],
                                        }
                                    ],
                                }
                            },
                        }
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Team not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_run_team(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_team)

        # 1. Get the Team to run
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Check if non-blocking execution is requested
        blocking = request_body.get("params", {}).get("configuration", {}).get("blocking", True)

        # 4. Run the Team
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

            # 5. Send the response
            a2a_task = map_run_output_to_a2a_task(response)
            status_code = 202 if not blocking else 200
            result = SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=a2a_task,
            )
            return JSONResponse(
                content=result.model_dump(exclude_none=True),
                status_code=status_code,
            )

        # Handle all critical errors
        except Exception as e:
            from a2a.types import Message as A2AMessage
            from a2a.types import Part, Role, TextPart

            error_message = A2AMessage(
                message_id=str(uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=f"Error: {str(e)}"))],
                context_id=context_id or str(uuid4()),
            )
            failed_task = Task(
                id=str(uuid4()),
                context_id=context_id or str(uuid4()),
                status=TaskStatus(state=TaskState.failed),
                history=[error_message],
            )

            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=failed_task,
            )

    @router.post(
        "/teams/{id}/v1/tasks:get",
        operation_id="get_team_task",
        name="get_team_task",
        description="Get the status and result of a team task by ID.",
        response_model_exclude_none=True,
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
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=a2a_task,
        )

    @router.post(
        "/teams/{id}/v1/tasks:cancel",
        operation_id="cancel_team_task",
        name="cancel_team_task",
        description="Cancel a running team task.",
        response_model_exclude_none=True,
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

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await team.acancel_run(run_id=task_id)

        context_id = params.get("contextId", str(uuid4()))
        canceled_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.canceled),
        )
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=canceled_task,
        )

    @router.post(
        "/teams/{id}/v1/message:stream",
        operation_id="stream_message_team",
        name="stream_message_team",
        description="Stream a message to an Agno Team (streaming). The Team is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as newline-delimited JSON (NDJSON).",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Streaming response with task updates",
                "content": {
                    "text/event-stream": {
                        "example": 'event: TaskStatusUpdateEvent\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"taskId":"task-456","status":"working"}}\n\n'
                        'event: Message\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"messageId":"msg-1","role":"agent","parts":[{"kind":"text","text":"Response"}]}}\n\n'
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Team not found"},
        },
    )
    async def a2a_stream_team(request: Request, id: str):
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_team)

        # 1. Get the Team to run
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Team and stream the response
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

            # 4. Stream the response
            return StreamingResponse(
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    # ============= WORKFLOWS =============
    @router.get("/workflows/{id}/.well-known/agent-card.json")
    async def get_workflow_card(request: Request, id: str):
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        base_url = str(request.base_url).rstrip("/")
        skill = AgentSkill(
            id=workflow.id or "",
            name=workflow.name or "",
            description=workflow.description or "",
            tags=["agno"],
            examples=["search", "ok"],
            output_modes=["application/json"],
        )
        return AgentCard(
            name=workflow.name or "",
            version="1.0.0",
            description=workflow.description or "",
            url=f"{base_url}/a2a/workflows/{workflow.id}/v1/message:stream",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=False, push_notifications=False, state_transition_history=False),
            skills=[skill],
            supports_authenticated_extended_card=False,
        )

    @router.post(
        "/workflows/{id}/v1/message:send",
        operation_id="run_message_workflow",
        name="run_message_workflow",
        description="Send a message to an Agno Workflow (non-streaming). The Workflow is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Message sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "task": {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": "completed",
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from agent"}],
                                        }
                                    ],
                                }
                            },
                        }
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Workflow not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_run_workflow(request: Request, id: str):
        if not workflows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_run_workflow)

        # 1. Get the Workflow to run
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Workflow
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

            # 4. Send the response
            a2a_task = map_run_output_to_a2a_task(response)
            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=a2a_task,
            )

        # Handle all critical errors
        except Exception as e:
            from a2a.types import Message as A2AMessage
            from a2a.types import Part, Role, TextPart

            error_message = A2AMessage(
                message_id=str(uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=f"Error: {str(e)}"))],
                context_id=context_id or str(uuid4()),
            )
            failed_task = Task(
                id=str(uuid4()),
                context_id=context_id or str(uuid4()),
                status=TaskStatus(state=TaskState.failed),
                history=[error_message],
            )

            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=failed_task,
            )

    @router.post(
        "/workflows/{id}/v1/message:stream",
        operation_id="stream_message_workflow",
        name="stream_message_workflow",
        description="Stream a message to an Agno Workflow (streaming). The Workflow is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as newline-delimited JSON (NDJSON).",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Streaming response with task updates",
                "content": {
                    "text/event-stream": {
                        "example": 'event: TaskStatusUpdateEvent\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"taskId":"task-456","status":"working"}}\n\n'
                        'event: Message\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"messageId":"msg-1","role":"agent","parts":[{"kind":"text","text":"Response"}]}}\n\n'
                    }
                },
            },
            400: {"description": "Invalid request"},
            404: {"description": "Workflow not found"},
        },
    )
    async def a2a_stream_workflow(request: Request, id: str):
        if not workflows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_workflow)

        # 1. Get the Workflow to run
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Workflow and stream the response
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

            # 4. Stream the response
            return StreamingResponse(
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    # ============= DEPRECATED ENDPOINTS =============

    @router.post(
        "/message/send",
        operation_id="send_message",
        name="send_message",
        description="[DEPRECATED] Send a message to an Agno Agent, Team, or Workflow. "
        "The Agent, Team or Workflow is identified via the 'agentId' field in params.message or X-Agent-ID header. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Message sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "task": {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": "completed",
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from agent"}],
                                        }
                                    ],
                                }
                            },
                        }
                    }
                },
            },
            400: {"description": "Invalid request or unsupported method"},
            404: {"description": "Agent, Team, or Workflow not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_send_message(request: Request):
        warnings.warn(
            "This endpoint will be deprecated soon. Use /agents/{agents_id}/v1/message:send, /teams/{teams_id}/v1/message:send, or /workflows/{workflows_id}/v1/message:send instead.",
            DeprecationWarning,
        )

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_send_message)

        # 1. Get the Agent, Team, or Workflow to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId") or request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide it via 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow]] = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the agent, team, or workflow
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

            # 4. Send the response
            a2a_task = map_run_output_to_a2a_task(response)
            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=a2a_task,
            )

        # Handle all critical errors
        except Exception as e:
            from a2a.types import Message as A2AMessage
            from a2a.types import Part, Role, TextPart

            error_message = A2AMessage(
                message_id=str(uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=f"Error: {str(e)}"))],
                context_id=context_id or str(uuid4()),
            )
            failed_task = Task(
                id=str(uuid4()),
                context_id=context_id or str(uuid4()),
                status=TaskStatus(state=TaskState.failed),
                history=[error_message],
            )

            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=failed_task,
            )

    @router.post(
        "/message/stream",
        operation_id="stream_message",
        name="stream_message",
        description="[DEPRECATED] Stream a message to an Agno Agent, Team, or Workflow. "
        "The Agent, Team or Workflow is identified via the 'agentId' field in params.message or X-Agent-ID header. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as newline-delimited JSON (NDJSON).",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Streaming response with task updates",
                "content": {
                    "text/event-stream": {
                        "example": 'event: TaskStatusUpdateEvent\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"taskId":"task-456","status":"working"}}\n\n'
                        'event: Message\ndata: {"jsonrpc":"2.0","id":"request-123","result":{"messageId":"msg-1","role":"agent","parts":[{"kind":"text","text":"Response"}]}}\n\n'
                    }
                },
            },
            400: {"description": "Invalid request or unsupported method"},
            404: {"description": "Agent, Team, or Workflow not found"},
        },
    )
    async def a2a_stream_message(request: Request):
        warnings.warn(
            "This endpoint will be deprecated soon. Use /agents/{agents_id}/v1/message:stream, /teams/{teams_id}/v1/message:stream, or /workflows/{workflows_id}/v1/message:stream instead.",
            DeprecationWarning,
        )

        # Load the request body. Unknown args are passed down as kwargs.
        request_body = await request.json()
        kwargs = await get_request_kwargs(request, a2a_stream_message)

        # 1. Get the Agent, Team, or Workflow to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId")
        if not agent_id:
            agent_id = request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow]] = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if not entity and workflows:
            entity = get_workflow_by_id(agent_id, workflows)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent, Team, or Workflow with ID '{agent_id}' not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Agent, Team, or Workflow and stream the response
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

            # 4. Stream the response
            return StreamingResponse(
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="text/event-stream",
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    return router
