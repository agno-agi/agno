import logging
import uuid
from typing import Any, AsyncIterator, List, Optional, Union

from ag_ui.core import (
    BaseEvent,
    EventType,
    Message,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent
from agno.models.message import Message as AgnoMessage
from agno.team.team import Team

logger = logging.getLogger(__name__)


async def run_agent(agent: Agent, input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    run_id = input.run_id or str(uuid.uuid4())
    thread_id = input.thread_id or str(uuid.uuid4())

    # Emit run started event
    yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id)

    try:
        # Convert AG-UI messages to Agno format
        agno_messages = _convert_messages(input.messages) if input.messages else []

        # Request streaming response from agent
        response_stream = await agent.arun(
            None,
            messages=agno_messages,
            stream=True,
            session_id=thread_id,
        )

        # Stream the response content
        async for event in _stream_response_content(response_stream):
            yield event

    except Exception as e:
        logger.error("Error in run_agent: %s", e, exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))
    finally:
        # Always emit run finished event
        yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)


async def run_team(team: Team, input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    run_id = input.run_id or str(uuid.uuid4())
    thread_id = input.thread_id or str(uuid.uuid4())

    # Emit run started event
    yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id)

    try:
        # Extract the last user message for team execution
        user_message = _get_last_user_message(input.messages) if input.messages else ""

        # Request streaming response from team
        response_stream = await team.arun(
            user_message,
            session_id=thread_id,
            stream=True,
        )

        # Stream the response content
        async for event in _stream_response_content(response_stream):
            yield event

    except Exception as e:
        logger.error("Error in run_team: %s", e, exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))
    finally:
        # Always emit run finished event
        yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)


async def _stream_response_content(response_stream: AsyncIterator[Any]) -> AsyncIterator[BaseEvent]:
    message_id = str(uuid.uuid4())
    message_started = False

    async for chunk in response_stream:
        # Extract content from each chunk
        content = _extract_content(chunk)
        if content:
            # Start message if not already started
            if not message_started:
                message_started = True
                yield TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=message_id,
                    role="assistant",
                )

            # Stream content chunk
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=content,
            )

    # End message if it was started
    if message_started:
        yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)


def _get_last_user_message(messages: Optional[List[Message]]) -> str:
    if not messages:
        return ""

    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


def _extract_content(response: Union[str, object]) -> str:
    # Handle plain string responses
    if isinstance(response, str):
        return response

    # Handle objects with content attribute
    if hasattr(response, "content") and response.content:
        return str(response.content)

    # Handle TeamRunResponse with member responses
    if hasattr(response, "member_responses") and response.member_responses:
        contents = []
        for member_resp in response.member_responses:
            member_content = _extract_content(member_resp)
            if member_content:
                contents.append(member_content)
        if contents:
            return "\n\n".join(contents)

    # Handle response with message list
    if hasattr(response, "messages") and response.messages:
        for msg in reversed(response.messages):
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return msg.content

    return ""


def _convert_messages(messages: List[Message]) -> List[AgnoMessage]:
    converted = []

    for msg in messages:
        # Skip system messages - agents have their own instructions
        if msg.role == "system":
            continue

        # Create base message
        agno_msg = AgnoMessage(
            role=msg.role,
            content=msg.content,
            name=getattr(msg, "name", None),
        )

        # Handle tool response messages
        if msg.role == "tool":
            agno_msg.tool_call_id = getattr(msg, "tool_call_id", None)

        # Handle assistant messages with tool calls
        elif msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
            agno_msg.tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
                if hasattr(tc, "function")
            ]

        converted.append(agno_msg)

    return converted


# Router functionality
def get_agui_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    """Create AG-UI compatible router for FastAPI."""
    router = APIRouter()

    if not agent and not team:
        raise ValueError("Either agent or team must be provided")

    encoder = EventEncoder()

    async def _run_agent(request: Request, agent_name: Optional[str] = None):
        try:
            request_data = await request.json()
            run_input = RunAgentInput(**request_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request format: {str(e)}")

        async def event_generator():
            if agent:
                async for event in run_agent(agent, run_input):
                    encoded_event = encoder.encode(event)
                    yield encoded_event
            elif team:
                async for event in run_team(team, run_input):
                    encoded_event = encoder.encode(event)
                    yield encoded_event

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            },
        )

    @router.post("/agui/awp")
    async def run_agent_agui_awp(request: Request, agent: Optional[str] = None):
        return await _run_agent(request, agent)

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
