"""Async router handling exposing an Agno Agent or Team in an AG-UI compatible format."""

import logging
import uuid
from typing import AsyncIterator, Optional

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunStartedEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent
from agno.app.agui.utils import async_stream_agno_response_as_agui_events, get_last_user_message
from agno.team.team import Team

logger = logging.getLogger(__name__)


async def run_agent(agent: Agent, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    """Run the contextual Agent, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format."""
    run_id = run_input.run_id or str(uuid.uuid4())

    try:
        # Preparing the input for the Agent and emitting the run started event
        message = get_last_user_message(run_input.messages)
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        # Request streaming response from agent
        response_stream = await agent.arun(
            message=message,
            session_id=run_input.thread_id,
            stream=True,
            stream_intermediate_steps=True,
        )

        # Stream the response content in AG-UI format
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream, thread_id=run_input.thread_id, run_id=run_id
        ):
            yield event

    # Emit a RunErrorEvent if any error occurs
    except Exception as e:
        logger.error(f"Error running agent: {e}", exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


async def run_team(team: Team, input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    """Run the contextual Team, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format."""
    run_id = input.run_id or str(uuid.uuid4())
    try:
        # Extract the last user message for team execution
        user_message = get_last_user_message(input.messages) if input.messages else ""
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input.thread_id, run_id=run_id)

        # Request streaming response from team
        response_stream = await team.arun(
            message=user_message,
            session_id=input.thread_id,
            stream=True,
            stream_intermediate_steps=True,
        )

        # Stream the response content in AG-UI format
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream, thread_id=input.thread_id, run_id=run_id
        ):
            yield event

    except Exception as e:
        logger.error(f"Error running team: {e}", exc_info=True)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


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

    @router.post("/agui")
    async def run_agent_agui(run_input: RunAgentInput):
        return await _run(run_input)

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
