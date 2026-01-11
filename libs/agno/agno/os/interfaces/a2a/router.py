"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

from typing import Optional, Union, cast
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from typing_extensions import List

from agno.os.interfaces.a2a.schema import GetTaskEndpointResponse, ListTasksEndpointResponse

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
from agno.db.base import AsyncBaseDb, SessionType
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    map_run_schema_to_a2a_task,
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
    async def get_agent_card(request: Request, id: str) -> AgentCard:
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
    async def a2a_run_agent(request: Request, id: str) -> SendMessageSuccessResponse:
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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

        # 3. Run the Agent
        try:
            response = await agent.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                run_id=task_id,
                **kwargs,
            )

            # 4. Send the response
            a2a_task = map_run_output_to_a2a_task(response)
            return SendMessageSuccessResponse(
                id=request_body.get("id", "unknown"),
                result=a2a_task,
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
        "/agents/{id}/v1/message:stream",
        operation_id="stream_message_agent",
        name="stream_message_agent",
        description="Stream a message to an Agno Agent (streaming). The Agent is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as Server-Sent Events (SSE).",
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
    async def a2a_stream_agent(request: Request, id: str) -> StreamingResponse:
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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

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
                run_id=task_id,
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

    @router.get(
        "/agents/{id}/v1/tasks",
        operation_id="list_agent_tasks",
        name="list_agent_tasks",
        description="List all A2A Tasks for an Agent. If session_id is provided, returns tasks from that session only. Otherwise, returns tasks from all sessions for this agent.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Tasks retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": [
                                {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": {"state": "completed"},
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from agent"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                },
            },
            404: {"description": "Agent not found or no tasks found"},
        },
    )
    async def list_agent_tasks(
        request: Request,
        id: str,
        session_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        pagesize: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> ListTasksEndpointResponse:
        """List all tasks for an Agent. If session_id is provided, returns tasks from that session only."""

        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        db = agent.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.AGENT

        a2a_tasks = []

        if session_id:
            # Load specific session
            if isinstance(db, AsyncBaseDb):
                session = await db.get_session(
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                session = db.get_session(  # type: ignore
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )

            if not session:
                raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

            session_dict = cast(dict, session)
            runs = session_dict.get("runs", [])
            # Apply pagesize within this session if provided
            if pagesize is not None and pagesize > 0:
                runs = runs[-pagesize:]
            a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])
        else:
            # Load all sessions for this agent
            if isinstance(db, AsyncBaseDb):
                sessions, _ = await db.get_sessions(
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                sessions, _ = db.get_sessions(  # type: ignore
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )

            sessions_list = cast(list, sessions)
            for session_dict in sessions_list:
                runs = cast(dict, session_dict).get("runs", [])
                a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])

            # Apply pagesize across all sessions if provided
            if pagesize is not None and pagesize > 0:
                a2a_tasks = a2a_tasks[-pagesize:]
        return ListTasksEndpointResponse(id=request_id or None, result=a2a_tasks)

    @router.get(
        "/agents/{id}/v1/tasks/{task_id}",
        operation_id="get_agent_task",
        name="get_agent_task",
        description="Retrieve a specific A2A Task by ID for an Agent. Requires session_id query parameter.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Task retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "id": "task-456",
                                "context_id": "context-789",
                                "status": {"state": "completed"},
                                "history": [
                                    {
                                        "message_id": "msg-1",
                                        "role": "agent",
                                        "parts": [{"kind": "text", "text": "Response from agent"}],
                                    }
                                ],
                            },
                        }
                    }
                },
            },
            404: {"description": "Task not found"},
        },
    )
    async def get_agent_task(
        request: Request,
        id: str,
        task_id: str,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> GetTaskEndpointResponse:
        """
        Retrieve an Agent Task in A2A format, based on the given filters.

        Notice an Agent Task maps to an Agno Run in this context.
        """
        # 1. Ensure agent and agent.db are present
        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        db = agent.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.AGENT

        # 2. Load the session from the database
        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        else:
            session = db.get_session(  # type: ignore
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        # 3. Load the runs from the session
        session_dict = cast(dict, session)
        runs = session_dict.get("runs", [])
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        # 4. Find the target run
        target_run = next((run for run in runs if run.get("run_id") == task_id), None)
        if not target_run:
            raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found in session {session_id}")

        # 5. Map the Agno Run into an A2A Task, and return it
        a2a_task = map_run_schema_to_a2a_task(target_run)
        return GetTaskEndpointResponse(id=request_id or None, result=a2a_task)

    @router.post(
        "/agents/{id}/v1/tasks/{task_id}:cancel",
        operation_id="cancel_agent_task",
        name="cancel_agent_task",
        description="Cancel a running task for an Agent.",
    )
    async def cancel_task_agent(request: Request, id: str, task_id: str) -> GetTaskEndpointResponse:
        request_body = await request.json()
        request_id = request_body.get("id", "unknown")

        # 1. Ensure agent is present
        agent = get_agent_by_id(id, agents)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        session_id = request_body.get("params", {}).get("session_id")

        # 2. Cancel the run
        if not agent.cancel_run(run_id=task_id): # type: ignore
            raise HTTPException(status_code=500, detail=f"Failed to cancel run with ID {task_id}")

        # 3. Build the canceled task response
        a2a_task = Task(id=task_id, context_id=session_id or str(uuid4()), status=TaskStatus(state=TaskState.canceled))
        return GetTaskEndpointResponse(id=request_id, result=a2a_task)

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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

        # 3. Run the Team
        try:
            response = await team.arun(
                input=run_input.input_content,
                images=run_input.images,
                videos=run_input.videos,
                audio=run_input.audios,
                files=run_input.files,
                session_id=context_id,
                user_id=user_id,
                run_id=task_id,
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
        "/teams/{id}/v1/message:stream",
        operation_id="stream_message_team",
        name="stream_message_team",
        description="Stream a message to an Agno Team (streaming). The Team is identified via the path parameter '{id}'. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as Server-Sent Events (SSE).",
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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

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
                run_id=task_id,
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

    @router.get(
        "/teams/{id}/v1/tasks",
        operation_id="list_team_tasks",
        name="list_team_tasks",
        description="List all A2A Tasks for a Team. If session_id is provided, returns tasks from that session only. Otherwise, returns tasks from all sessions for this team.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Tasks retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": [
                                {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": {"state": "completed"},
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from team"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                },
            },
            404: {"description": "Team not found or no tasks found"},
        },
    )
    async def list_team_tasks(
        request: Request,
        id: str,
        session_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        pagesize: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> ListTasksEndpointResponse:
        """List all tasks for a Team. If session_id is provided, returns tasks from that session only."""

        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        db = team.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.TEAM

        a2a_tasks = []

        if session_id:
            # Load specific session
            if isinstance(db, AsyncBaseDb):
                session = await db.get_session(
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                session = db.get_session(  # type: ignore
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )

            if not session:
                raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

            session_dict = cast(dict, session)
            runs = session_dict.get("runs", [])
            # Apply pagesize within this session if provided
            if pagesize is not None and pagesize > 0:
                runs = runs[-pagesize:]
            a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])
        else:
            # Load all sessions for this team
            if isinstance(db, AsyncBaseDb):
                sessions, _ = await db.get_sessions(
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                sessions, _ = db.get_sessions(  # type: ignore
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )

            sessions_list = cast(list, sessions)
            for session_dict in sessions_list:
                runs = cast(dict, session_dict).get("runs", [])
                a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])

            # Apply pagesize across all sessions if provided
            if pagesize is not None and pagesize > 0:
                a2a_tasks = a2a_tasks[-pagesize:]

        return ListTasksEndpointResponse(id=request_id or None, result=a2a_tasks)

    @router.get(
        "/teams/{id}/v1/tasks/{task_id}",
        operation_id="get_team_task",
        name="get_team_task",
        description="Retrieve a specific A2A Task by ID for a Team. Requires session_id query parameter.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Task retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "id": "task-456",
                                "context_id": "context-789",
                                "status": {"state": "completed"},
                                "history": [
                                    {
                                        "message_id": "msg-1",
                                        "role": "agent",
                                        "parts": [{"kind": "text", "text": "Response from team"}],
                                    }
                                ],
                            },
                        }
                    }
                },
            },
            404: {"description": "Task not found"},
        },
    )
    async def get_team_task(
        request: Request,
        id: str,
        task_id: str,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> GetTaskEndpointResponse:
        """
        Retrieve a Team Task in A2A format, based on the given filters.

        Notice a Team Task maps to an Agno Run in this context.
        """
        # 1. Ensure team and team.db are present
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        db = team.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.TEAM

        # 2. Load the session from the database
        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        else:
            session = db.get_session(  # type: ignore
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        # 3. Load the runs from the session
        session_dict = cast(dict, session)
        runs = session_dict.get("runs", [])
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        # 4. Find the target run
        target_run = next((run for run in runs if run.get("run_id") == task_id), None)
        if not target_run:
            raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found in session {session_id}")

        # 5. Map the Agno Run into an A2A Task, and return it
        a2a_task = map_run_schema_to_a2a_task(target_run)
        return GetTaskEndpointResponse(id=request_id or None, result=a2a_task)

    @router.post(
        "/teams/{id}/v1/tasks/{task_id}:cancel",
        operation_id="cancel_team_task",
        name="cancel_team_task",
        description="Cancel a running task for a Team.",
    )
    async def cancel_task_team(request: Request, id: str, task_id: str) -> GetTaskEndpointResponse:
        request_body = await request.json()
        request_id = request_body.get("id", "unknown")

        # 1. Ensure team is present
        team = get_team_by_id(id, teams)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        session_id = request_body.get("params", {}).get("session_id")

        # 2. Cancel the run
        if not team.cancel_run(run_id=task_id): # type: ignore
            raise HTTPException(status_code=500, detail=f"Failed to cancel run with ID {task_id}")

        # 3. Build the canceled task response
        a2a_task = Task(id=task_id, context_id=session_id or str(uuid4()), status=TaskStatus(state=TaskState.canceled))
        return GetTaskEndpointResponse(id=request_id, result=a2a_task)

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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

        # 3. Run the Workflow
        try:
            response = await workflow.arun(
                input=run_input.input_content,
                images=list(run_input.images) if run_input.images else None,
                videos=list(run_input.videos) if run_input.videos else None,
                audio=list(run_input.audios) if run_input.audios else None,
                files=list(run_input.files) if run_input.files else None,
                session_id=context_id,
                run_id=task_id,
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
        "Returns real-time updates as Server-Sent Events (SSE).",
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
        task_id = request_body.get("id")
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

        # 3. Run the Workflow and stream the response
        try:
            event_stream = workflow.arun(
                input=run_input.input_content,
                images=list(run_input.images) if run_input.images else None,
                videos=list(run_input.videos) if run_input.videos else None,
                audio=list(run_input.audios) if run_input.audios else None,
                files=list(run_input.files) if run_input.files else None,
                session_id=context_id,
                run_id=task_id,
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

    @router.get(
        "/workflows/{id}/v1/tasks",
        operation_id="list_workflow_tasks",
        name="list_workflow_tasks",
        description="List all A2A Tasks for a Workflow. If session_id is provided, returns tasks from that session only. Otherwise, returns tasks from all sessions for this workflow.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Tasks retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": [
                                {
                                    "id": "task-456",
                                    "context_id": "context-789",
                                    "status": {"state": "completed"},
                                    "history": [
                                        {
                                            "message_id": "msg-1",
                                            "role": "agent",
                                            "parts": [{"kind": "text", "text": "Response from workflow"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                },
            },
            404: {"description": "Workflow not found or no tasks found"},
        },
    )
    async def list_workflow_tasks(
        request: Request,
        id: str,
        session_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        pagesize: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> ListTasksEndpointResponse:
        """List all tasks for a Workflow. If session_id is provided, returns tasks from that session only."""

        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        db = workflow.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.WORKFLOW

        a2a_tasks = []

        if session_id:
            # Load specific session
            if isinstance(db, AsyncBaseDb):
                session = await db.get_session(
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                session = db.get_session(  # type: ignore
                    session_id=session_id,
                    session_type=session_type,
                    user_id=user_id,
                    deserialize=False,
                )

            if not session:
                raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

            session_dict = cast(dict, session)
            runs = session_dict.get("runs", [])
            # Apply pagesize within this session if provided
            if pagesize is not None and pagesize > 0:
                runs = runs[-pagesize:]
            a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])
        else:
            # Load all sessions for this workflow
            if isinstance(db, AsyncBaseDb):
                sessions, _ = await db.get_sessions(
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )
            else:
                sessions, _ = db.get_sessions(  # type: ignore
                    session_type=session_type,
                    component_id=id,
                    user_id=user_id,
                    deserialize=False,
                )

            sessions_list = cast(list, sessions)
            for session_dict in sessions_list:
                runs = cast(dict, session_dict).get("runs", [])
                a2a_tasks.extend([map_run_schema_to_a2a_task(run) for run in runs])

            # Apply pagesize across all sessions if provided
            if pagesize is not None and pagesize > 0:
                a2a_tasks = a2a_tasks[-pagesize:]

        return ListTasksEndpointResponse(id=request_id or None, result=a2a_tasks)

    @router.get(
        "/workflows/{id}/v1/tasks/{task_id}",
        operation_id="get_workflow_task",
        name="get_workflow_task",
        description="Retrieve a specific A2A Task by ID for a Workflow. Requires session_id query parameter.",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Task retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "jsonrpc": "2.0",
                            "id": "request-123",
                            "result": {
                                "id": "task-456",
                                "context_id": "context-789",
                                "status": {"state": "completed"},
                                "history": [
                                    {
                                        "message_id": "msg-1",
                                        "role": "agent",
                                        "parts": [{"kind": "text", "text": "Response from workflow"}],
                                    }
                                ],
                            },
                        }
                    }
                },
            },
            404: {"description": "Task not found"},
        },
    )
    async def get_workflow_task(
        request: Request,
        id: str,
        task_id: str,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> GetTaskEndpointResponse:
        """
        Retrieve a Workflow Task in A2A format, based on the given filters.

        Notice a Workflow Task maps to an Agno Run in this context.
        """
        # 1. Ensure workflow and workflow.db are present
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        db = workflow.db
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        if session_type is None:
            session_type = SessionType.WORKFLOW

        # 2. Load the session from the database
        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        else:
            session = db.get_session(  # type: ignore
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        # 3. Load the runs from the session
        session_dict = cast(dict, session)
        runs = session_dict.get("runs", [])
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        # 4. Find the target run
        target_run = next((run for run in runs if run.get("run_id") == task_id), None)
        if not target_run:
            raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found in session {session_id}")

        # 5. Map the Agno Run into an A2A Task, and return it
        a2a_task = map_run_schema_to_a2a_task(target_run)
        return GetTaskEndpointResponse(id=request_id or None, result=a2a_task)

    @router.post(
        "/workflows/{id}/v1/tasks/{task_id}:cancel",
        operation_id="cancel_workflow_task",
        name="cancel_workflow_task",
        description="Cancel a running task for a Workflow.",
    )
    async def cancel_task_workflow(request: Request, id: str, task_id: str) -> GetTaskEndpointResponse:
        request_body = await request.json()
        request_id = request_body.get("id", "unknown")

        # 1. Ensure workflow is present
        workflow = get_workflow_by_id(id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        session_id = request_body.get("params", {}).get("session_id")

        # 2. Cancel the run
        if not workflow.cancel_run(run_id=task_id): # type: ignore
            raise HTTPException(status_code=500, detail=f"Failed to cancel run with ID {task_id}")

        # 3. Build the canceled task response
        a2a_task = Task(id=task_id, context_id=session_id or str(uuid4()), status=TaskStatus(state=TaskState.canceled))
        return GetTaskEndpointResponse(id=request_id, result=a2a_task)

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
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

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
        "Returns real-time updates as Server-Sent Events (SSE).",
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
        user_id = request.headers.get("X-User-ID") or request_body.get("params", {}).get("message", {}).get(
            "metadata", {}
        ).get("userId")

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
