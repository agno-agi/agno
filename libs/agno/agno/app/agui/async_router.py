"""Async router handling exposing an Agno Agent or Team in an AG-UI compatible format."""

import logging
import uuid
from typing import AsyncIterator, List, Optional

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from ag_ui.core.types import Message as AGUIMessage
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent
from agno.models.message import Message as AgnoMessage
from agno.run.response import RunEvent, RunResponse
from agno.run.team import TeamRunResponse
from agno.team.team import Team

logger = logging.getLogger(__name__)


async def run_agent(agent: Agent, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    """Run the contextual Agent, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format."""
    run_id = run_input.run_id or str(uuid.uuid4())

    try:
        # Preparing the input for the Agent and emitting the run started event
        agno_messages = _convert_agui_messages_to_agno_messages(run_input.messages)
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        # Request streaming response from agent
        response_stream = await agent.arun(
            session_id=run_input.thread_id, messages=agno_messages, stream=True, stream_intermediate_steps=True
        )

        # Stream the response content
        async for event in _stream_response_content(
            response_stream=response_stream, thread_id=run_input.thread_id, run_id=run_id
        ):
            yield event

    # Emit a RunErrorEvent if any error occurs
    except Exception as e:
        logger.error(f"Error running agent: {e}", exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


async def run_team(team: Team, input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    run_id = input.run_id or str(uuid.uuid4())
    try:
        # Extract the last user message for team execution
        user_message = _get_last_user_message(input.messages) if input.messages else ""
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input.thread_id, run_id=run_id)

        # Request streaming response from team
        response_stream = await team.arun(
            message=user_message, session_id=input.thread_id, stream=True, stream_intermediate_steps=True
        )

        # Stream the response content
        async for event in _stream_team_response_content(
            response_stream=response_stream, thread_id=input.thread_id, run_id=run_id
        ):
            yield event

    except Exception as e:
        logger.error("Error in run_team: %s", e, exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


async def _stream_response_content(
    response_stream: AsyncIterator[RunResponse], thread_id: str, run_id: str
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    message_id = str(uuid.uuid4())
    message_started = False

    async for chunk in response_stream:
        content = _extract_response_chunk_content(chunk)

        # Handle text responses
        if chunk.event == RunEvent.run_response:
            # Emit an event fTeamRunResponse the message
            if not message_started:
                message_started = True
                yield TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=message_id,
                    role="assistant",
                )
            # Emit an event for each streamed delta of the message
            if content is not None and content != "":
                yield TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=content,
                )

        # Handle tool calls
        if chunk.event == RunEvent.tool_call_started:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                yield ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call.tool_call_id or "",
                    tool_call_name=tool_call.tool_name or "",
                )
        if chunk.event == RunEvent.tool_call_completed:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                yield ToolCallEndEvent(
                    type=EventType.TOOL_CALL_END,
                    tool_call_id=tool_call.tool_call_id or "",
                )

        # Handle the lifecycle end events
        if chunk.event == RunEvent.run_completed:
            yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)
            yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)


async def _stream_team_response_content(
    response_stream: AsyncIterator[TeamRunResponse], thread_id: str, run_id: str
) -> AsyncIterator[BaseEvent]:
    """Map the Agno Team response stream to AG-UI format."""
    message_id = str(uuid.uuid4())
    message_started = False

    async for chunk in response_stream:
        content = _extract_team_response_chunk_content(chunk)

        # Handle text responses
        if chunk.event == RunEvent.run_response:
            # Emit an event fTeamRunResponse the message
            if not message_started:
                message_started = True
                yield TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=message_id,
                    role="assistant",
                )
            # Emit an event for each streamed delta of the message
            if content is not None and content != "":
                yield TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=content,
                )

        # Handle tool calls
        if chunk.event == RunEvent.tool_call_started:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                yield ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call.tool_call_id or "",
                    tool_call_name=tool_call.tool_name or "",
                )
        if chunk.event == RunEvent.tool_call_completed:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                yield ToolCallEndEvent(
                    type=EventType.TOOL_CALL_END,
                    tool_call_id=tool_call.tool_call_id or "",
                )

        # Handle the lifecycle end events
        if chunk.event == RunEvent.run_completed:
            yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)
            yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)


def _get_last_user_message(messages: Optional[List[AGUIMessage]]) -> str:
    if not messages:
        return ""

    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


def _extract_response_chunk_content(response: RunResponse) -> str:
    """Given a response stream chunk, find and extract the content."""
    # Handle response with message list (for Agent)
    if hasattr(response, "messages") and response.messages:
        for msg in reversed(response.messages):
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return str(msg.content)

    return str(response.content) if response.content else ""


def _extract_team_response_chunk_content(response: TeamRunResponse) -> str:
    """Given a response stream chunk, find and extract the content."""

    # Handle Team members' responses
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:
        for member_resp in response.member_responses:
            if isinstance(member_resp, RunResponse):
                member_content = _extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunResponse):
                member_content = _extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""

    return str(response.content) + members_response


def _convert_agui_messages_to_agno_messages(messages: List[AGUIMessage]) -> List[AgnoMessage]:
    """Map AG-UI messages to Agno format."""
    converted = []
    for msg in messages:
        # No need to convert the system message
        if msg.role == "system":
            continue

        agno_msg = AgnoMessage(
            role=msg.role,
            content=msg.content,
            name=getattr(msg, "name", None),
        )

        # Handle messages containing tool calls
        if msg.role == "tool":
            agno_msg.tool_call_id = getattr(msg, "tool_call_id", None)
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


def get_async_agui_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    """Return an AG-UI compatible FastAPI router."""
    if (agent is None and team is None) or (agent is not None and team is not None):
        raise ValueError("One of 'agent' or 'team' must be provided.")

    router = APIRouter()
    encoder = EventEncoder()

    async def _run(run_input: RunAgentInput):
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
    async def run_agent_agui_awp(run_input: RunAgentInput):
        return await _run(run_input)

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
