"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import SendMessageSuccessResponse, Task, TaskState, TaskStatus
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a`") from e

from agno.agent import Agent
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    stream_a2a_response_with_error_handling,
)
from agno.os.router import _get_request_kwargs
from agno.os.utils import get_agent_by_id, get_team_by_id
from agno.team import Team


def attach_routes(
    router: APIRouter, agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None
) -> APIRouter:
    if agents is None and teams is None:
        raise ValueError("Agents or Teams are required to setup the A2A interface.")

    @router.post(
        "/message/send",
        tags=["A2A"],
        operation_id="send_message",
        summary="Send message to Agent or Team (A2A Protocol)",
        description="Send a message to an Agno Agent or Team. "
        "The agent or team is identified via the 'agentId' field in params.message or X-Agent-ID header. "
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
            404: {"description": "Agent or Team not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_send_message(request: Request):
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_send_message)

        # 1. Get the Agent or Team to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId") or request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Agent/Team ID required. Provide it via 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent or Team with ID '{agent_id}' not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the agent or team
        try:
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
        tags=["A2A"],
        operation_id="stream_message",
        summary="Stream message to Agent or Team (A2A Protocol)",
        description="Stream a message to an Agno Agent or Team using the A2A protocol standard endpoint. "
        "The agent or team is identified via the 'agentId' field in params.message or X-Agent-ID header. "
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
            404: {"description": "Agent or Team not found"},
        },
    )
    async def a2a_stream_message(request: Request):
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_stream_message)

        # 1. Get the Agent or Team to run
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId")
        if not agent_id:
            agent_id = request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Agent/Team ID required. Provide 'agentId' in params.message or 'X-Agent-ID' header.",
            )
        entity = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent or Team with ID '{agent_id}' not found")

        # 2. Map the request to our run_input and run variables
        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            user_id = request_body.get("params", {}).get("message", {}).get("metadata", {}).get("userId")

        # 3. Run the Agent or Team and stream the response
        try:
            event_stream = entity.arun(
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
                stream_a2a_response_with_error_handling(event_stream=event_stream, request_id=request_body["id"]),
                media_type="application/x-ndjson",
            )

        except Exception as e:
            # Handle errors prior to streaming
            raise HTTPException(status_code=500, detail=f"Failed to start agent run: {str(e)}")

    return router
