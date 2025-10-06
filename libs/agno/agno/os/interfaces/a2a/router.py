"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import SendMessageSuccessResponse
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a`") from e

from agno.agent import Agent
from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    stream_a2a_response,
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
        "The agent or team is identified via the 'agentId' field in params.message or X-Agent-ID header.",
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

        # Extract agent/team ID from params.message.agentId or header
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId") or request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Agent/Team ID required. Provide it via 'agentId' in params.message or 'X-Agent-ID' header.",
            )

        kwargs = await _get_request_kwargs(request, a2a_send_message)

        # Try to find agent first, then team
        entity = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)

        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent or Team with ID '{agent_id}' not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=False)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")

        # Run the agent or team
        response = await entity.arun(
            input=run_input.input_content,
            images=run_input.images,
            videos=run_input.videos,
            audio=run_input.audios,
            files=run_input.files,
            session_id=context_id,
            **kwargs,
        )

        a2a_task = map_run_output_to_a2a_task(response)

        # Send A2A-valid JSON-RPC response
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=a2a_task,
        )

    @router.post(
        "/message/stream",
        tags=["A2A"],
        operation_id="stream_message",
        summary="Stream message to Agent or Team (A2A Protocol)",
        description="Stream a message to an Agno Agent or Team using the A2A protocol standard endpoint. "
        "The agent or team is identified via the 'agentId' field in params.message or X-Agent-ID header. "
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

        # Extract agent/team ID from params.message.agentId or header
        agent_id = request_body.get("params", {}).get("message", {}).get("agentId")
        if not agent_id:
            agent_id = request.headers.get("X-Agent-ID")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="Agent/Team ID required. Provide 'agentId' in params.message or 'X-Agent-ID' header.",
            )

        kwargs = await _get_request_kwargs(request, a2a_stream_message)

        # Try to find agent first, then team
        entity = None
        if agents:
            entity = get_agent_by_id(agent_id, agents)
        if not entity and teams:
            entity = get_team_by_id(agent_id, teams)

        if entity is None:
            raise HTTPException(status_code=404, detail=f"Agent or Team with ID '{agent_id}' not found")

        run_input = await map_a2a_request_to_run_input(request_body, stream=True)
        context_id = request_body.get("params", {}).get("message", {}).get("contextId")

        # Stream the response
        event_stream = entity.arun(
            input=run_input.input_content,
            images=run_input.images,
            videos=run_input.videos,
            audio=run_input.audios,
            files=run_input.files,
            session_id=context_id,
            stream=True,
            stream_intermediate_steps=True,
            **kwargs,
        )

        return StreamingResponse(
            stream_a2a_response(event_stream=event_stream, request_id=request_body["id"]),
            media_type="application/x-ndjson",
        )

    return router
