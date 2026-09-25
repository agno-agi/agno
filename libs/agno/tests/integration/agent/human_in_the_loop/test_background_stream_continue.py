"""Integration tests for continuing a paused agent run with background=True and stream=True.

A background continue persists the run as PENDING/RUNNING before its messages are
rebuilt, so the continued run must not be read back as its own history. Chat
Completions rejects a request where an assistant tool call has no matching tool
result, so a duplicated tool call makes the continue end in ERROR instead of COMPLETED.
"""

import asyncio
import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart a service.

    Args:
        service: Name of the service to restart.
    """
    return f"Restarted {service}"


@tool(external_execution=True)
def get_location() -> str:
    """Return the user's current location. Executed by the client."""
    return ""


@tool(requires_user_input=True, user_input_fields=["city"])
def book_hotel(city: str = "") -> str:
    """Book a hotel in the city the user provides.

    Args:
        city: City to book the hotel in.
    """
    return f"Booked a hotel in {city}"


PAUSE_CASES = {
    "confirmation": (restart_service, "Restart the billing service."),
    "external_execution": (get_location, "Where am I right now? Use the get_location tool."),
    "user_input": (book_hotel, "Book me a hotel. Use the book_hotel tool."),
}


def _make_agent(db, tool_fn, **kwargs) -> Agent:
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[tool_fn],
        db=db,
        add_history_to_context=True,
        instructions=[
            "Always call the available tool when the user asks for something it can do.",
            "Never ask for confirmation or details in chat; the tool collects them.",
        ],
        telemetry=False,
        **kwargs,
    )


def _resolve(run: RunOutput) -> None:
    for requirement in run.active_requirements:
        if requirement.needs_confirmation:
            requirement.confirm()
        elif requirement.needs_external_execution:
            requirement.set_external_execution_result('{"city": "Paris"}')
        elif requirement.needs_user_input:
            requirement.provide_user_input({"city": "Paris"})


async def _wait_for_terminal_run(agent: Agent, run_id: str, session_id: str, timeout: float = 30.0) -> RunOutput:
    """Background runs finish on a detached task, so poll the database for a settled status."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        run = await agent.aget_run_output(run_id=run_id, session_id=session_id)
        if run is not None and run.status not in (RunStatus.pending, RunStatus.running):
            return run
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"Run {run_id} did not settle; last status: {run.status if run else None}")
        await asyncio.sleep(0.1)


async def _start_background_stream(agent: Agent, message: str, session_id: str) -> RunOutput:
    async for _ in agent.arun(message, session_id=session_id, stream=True, background=True):
        pass
    last = agent.get_last_run_output(session_id=session_id)
    assert last is not None and last.run_id is not None
    return await _wait_for_terminal_run(agent, last.run_id, session_id)


async def _continue_background_stream(agent: Agent, run: RunOutput) -> RunOutput:
    assert run.run_id is not None and run.session_id is not None
    async for _ in agent.acontinue_run(
        run_id=run.run_id,
        session_id=run.session_id,
        requirements=run.requirements,
        stream=True,
        background=True,
    ):
        pass
    return await _wait_for_terminal_run(agent, run.run_id, run.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_type", list(PAUSE_CASES))
async def test_background_stream_continue_completes(shared_db, pause_type):
    tool_fn, prompt = PAUSE_CASES[pause_type]
    agent = _make_agent(shared_db, tool_fn)
    session_id = f"bg-stream-{pause_type}"

    paused = await _start_background_stream(agent, prompt, session_id)
    assert paused.status == RunStatus.paused, f"expected a pause, got {paused.status}: {paused.content}"

    _resolve(paused)
    completed = await _continue_background_stream(agent, paused)

    assert completed.status == RunStatus.completed, f"continue ended {completed.status}: {completed.content}"


@pytest.mark.asyncio
async def test_background_stream_continue_keeps_prior_history(shared_db):
    """Excluding the continued run must not drop genuinely earlier turns from history."""
    agent = _make_agent(
        shared_db,
        restart_service,
        additional_context="IMPORTANT: Always address the user by their name in every response.",
    )
    session_id = "bg-stream-history"

    first = await _start_background_stream(agent, "Hi, my name is Alice.", session_id)
    assert first.status == RunStatus.completed

    paused = await _start_background_stream(agent, "Restart the billing service.", session_id)
    assert paused.status == RunStatus.paused

    _resolve(paused)
    completed = await _continue_background_stream(agent, paused)
    assert completed.status == RunStatus.completed, f"continue ended {completed.status}: {completed.content}"

    # The name only reaches the continued request through history from the first run
    assert "alice" in (completed.content or "").lower(), f"prior history missing: {completed.content}"


@pytest.mark.asyncio
async def test_background_stream_continue_across_two_pauses(shared_db):
    """A run that pauses more than once completes after each background continue."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[restart_service],
        db=shared_db,
        add_history_to_context=True,
        instructions=[
            "When asked to restart several services, call restart_service once per service, one call at a time.",
            "Never ask for confirmation in chat; the tool enforces it.",
        ],
        telemetry=False,
    )
    session_id = "bg-stream-two-pauses"

    run = await _start_background_stream(
        agent, "Restart the billing service, then restart the search service.", session_id
    )
    assert run.status == RunStatus.paused

    continues = 0
    while run.status == RunStatus.paused and continues < 4:
        _resolve(run)
        run = await _continue_background_stream(agent, run)
        continues += 1

    assert run.status == RunStatus.completed, f"run ended {run.status}: {run.content}"


@pytest.mark.asyncio
async def test_foreground_stream_continue_is_unchanged(shared_db):
    """The normal (non-background) continue path is unaffected."""
    agent = _make_agent(shared_db, restart_service)
    session_id = "fg-stream"

    async for _ in agent.arun("Restart the billing service.", session_id=session_id, stream=True):
        pass
    paused = agent.get_last_run_output(session_id=session_id)
    assert paused is not None and paused.status == RunStatus.paused

    _resolve(paused)
    async for _ in agent.acontinue_run(
        run_id=paused.run_id, session_id=session_id, requirements=paused.requirements, stream=True
    ):
        pass
    completed = agent.get_last_run_output(session_id=session_id)

    assert completed is not None and completed.status == RunStatus.completed
