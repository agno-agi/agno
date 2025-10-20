"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

from typing import Optional, Union
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import SendMessageSuccessResponse, Task, TaskState, TaskStatus
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e

from agno.agent import Agent
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    stream_a2a_response_with_error_handling,
)
from agno.os.router import _get_request_kwargs
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import Team
from agno.workflow import Workflow


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Agent]] = None,
    teams: Optional[List[Team]] = None,
    workflows: Optional[List[Workflow]] = None,
) -> APIRouter:
    if agents is None and teams is None and workflows is None:
        raise ValueError("Agents, Teams, or Workflows are required to setup the A2A interface.")

    @router.post(
        "/message/send",
        operation_id="send_message",
        name="send_message",
        description="Send a message to an Agno Agent, Team, or Workflow. "
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
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_send_message)

        # 1. Get the Agent, Team, or Workflow to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId") or request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide it via 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, Team, Workflow]] = None
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
                    images=run_input.images,
                    videos=run_input.videos,
                    audio=run_input.audios,
                    files=run_input.files,
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
        description="Stream a message to an Agno Agent, Team, or Workflow."
        "The Agent, Team or Workflow is identified via the 'agentId' field in params.message or X-Agent-ID header. "
        "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata. "
        "Returns real-time updates as newline-delimited JSON (NDJSON).",
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Streaming response with task updates",
                "content": {
                    "application/x-ndjson": {
                        "example": '{"jsonrpc":"2.0","id":"request-123","result":{"taskId":"task-456","status":"working"}}\n'
                        '{"jsonrpc":"2.0","id":"request-123","result":{"messageId":"msg-1","role":"agent","parts":[{"kind":"text","text":"Response"}]}}\n'
                    }
                },
            },
            400: {"description": "Invalid request or unsupported method"},
            404: {"description": "Agent, Team, or Workflow not found"},
        },
    )
    async def a2a_stream_message(request: Request):
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_stream_message)

        # 1. Get the Agent, Team, or Workflow to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId")
        if not agent_id:
            agent_id = request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Entity ID required. Provide 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity: Optional[Union[Agent, Team, Workflow]] = None
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
                    stream_intermediate_steps=True,
                    **kwargs,
                )
            else:
                event_stream = entity.arun(  # type: ignore[assignment]
                    input=run_input.input_content,
                    images=run_input.images,
                    videos=run_input.videos,
                    audio=run_input.audios,
                    files=run_input.files,
                    session_id=context_id,
                    user_id=user_id,
                    stream=True,
                    stream_intermediate_steps=True,
                    **kwargs,
                )

            # 4. Stream the response
            return StreamingResponse(
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),  # type: ignore[arg-type]
                media_type="application/x-ndjson",
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start run: {str(e)}")

    return router
