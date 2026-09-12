"""Integration tests for external_execution + add_history_to_context under every
combination of stream/background, and via both the sync (run/continue_run) and
async (arun/acontinue_run) APIs.

Regression coverage for: a run continuing in the background is persisted as
RUNNING (for visibility) before its own messages are rebuilt for the model
call. `session.get_messages()` only excludes PAUSED/CANCELLED/ERROR/REGENERATED
runs from history, so by the time history is rebuilt the run being continued
no longer matches that exclusion and re-enters its own history as a phantom
duplicate of the turn already supplied via the caller's own input. The model
then sees its own tool_calls twice -- once unpaired -- and Chat Completions
rejects the request outright. Only reproducible with stream=True AND
background=True together; any other combination (including the doc's own
sync, non-streaming example) already worked before this fix.

Every combination is driven the same way regardless of stream/background: drain
whatever is returned (a value, a sync iterator, or an async iterator), then read
back the definitive final state via `agent.get_last_run_output()` -- a
background run's immediate return value can still be PENDING/RUNNING, so it is
never itself the terminal state to assert against.
"""

import asyncio
import time

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def _make_agent(db):
    @tool()
    def get_weather() -> str:
        """Return the current weather. Runs immediately, no pause."""
        return "sunny, 25C"

    @tool(external_execution=True)
    def get_location() -> str:
        """Return the user's current location. Executed externally."""
        return ""

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "Always call get_weather first, then call get_location. Call both tools before answering.",
        ],
        tools=[get_weather, get_location],
        db=db,
        add_history_to_context=True,
        telemetry=False,
    )
    return agent


def _resolve(requirements):
    for req in requirements:
        if req.needs_external_execution:
            req.set_external_execution_result('{"lat": 1.0, "lng": 2.0}')


def _wait_for_terminal(agent, session_id, timeout=20.0):
    """Poll get_last_run_output until it settles (paused/completed/error) --
    the return value of a background call can still be PENDING/RUNNING."""
    deadline = time.monotonic() + timeout
    run = agent.get_last_run_output(session_id=session_id)
    while run is not None and str(run.status).upper() in ("PENDING", "RUNNING") and time.monotonic() < deadline:
        time.sleep(0.25)
        run = agent.get_last_run_output(session_id=session_id)
    assert run is not None, "no run found for session"
    return run


async def _await_wait_for_terminal(agent, session_id, timeout=20.0):
    deadline = time.monotonic() + timeout
    run = agent.get_last_run_output(session_id=session_id)
    while run is not None and str(run.status).upper() in ("PENDING", "RUNNING") and time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        run = agent.get_last_run_output(session_id=session_id)
    assert run is not None, "no run found for session"
    return run


def _assert_both_results_present(run):
    assert not run.is_paused
    assert str(run.status).upper() != "ERROR", f"run errored: {run.content}"
    content_lower = (run.content or "").lower()
    assert "25" in content_lower or "sunny" in content_lower, f"weather result missing: {run.content}"
    assert "1.0" in content_lower or "1" in content_lower, f"location result missing: {run.content}"


@pytest.mark.parametrize(
    "stream,background",
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
    ids=["sync-plain", "sync-stream", "sync-background", "sync-stream-background"],
)
def test_sync_run_and_continue_run_all_flag_combinations(shared_db, stream, background):
    """agent.run + agent.continue_run must complete for every stream/background
    combination. Included for completeness alongside the async matrix below --
    the sync facade's own background handling does not go through the exact
    status-persist-then-rebuild-history ordering that caused the bug, so this
    class doesn't reproduce it, but should keep passing regardless."""
    session_id = f"test_sync_{stream}_{background}"
    agent = _make_agent(shared_db)

    result = agent.run(
        "What's the weather and my location?", session_id=session_id, stream=stream, background=background
    )
    if stream:
        for _ in result:
            pass
    run = _wait_for_terminal(agent, session_id)
    assert run.is_paused, f"expected the run to pause on get_location, got status={run.status}"

    _resolve(run.active_requirements)
    result = agent.continue_run(
        run_id=run.run_id,
        session_id=session_id,
        requirements=run.requirements,
        stream=stream,
        background=background,
    )
    if stream:
        for _ in result:
            pass
    run = _wait_for_terminal(agent, session_id)
    _assert_both_results_present(run)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stream,background",
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
    ids=["async-plain", "async-stream", "async-background", "async-stream-background"],
)
async def test_async_arun_and_acontinue_run_all_flag_combinations(shared_db, stream, background):
    """Async counterpart -- agent.arun + agent.acontinue_run, same matrix. The
    (stream=True, background=True) case is the one that actually reproduces the
    history-duplication bug (confirmed by reverting the fix and rerunning:
    only this id fails); AgentOS's own HTTP continue path is async underneath,
    so this is the class that matters for a real client."""
    session_id = f"test_async_{stream}_{background}"
    agent = _make_agent(shared_db)

    result = agent.arun(
        "What's the weather and my location?", session_id=session_id, stream=stream, background=background
    )
    if stream:
        async for _ in result:
            pass
    else:
        await result
    run = await _await_wait_for_terminal(agent, session_id)
    assert run.is_paused, f"expected the run to pause on get_location, got status={run.status}"

    _resolve(run.active_requirements)
    cont = agent.acontinue_run(
        run_id=run.run_id,
        session_id=session_id,
        requirements=run.requirements,
        stream=stream,
        background=background,
    )
    if stream:
        async for _ in cont:
            pass
    else:
        await cont
    run = await _await_wait_for_terminal(agent, session_id)
    _assert_both_results_present(run)


@pytest.mark.asyncio
async def test_background_stream_continue_does_not_drop_prior_session_history(shared_db):
    """The fix excludes the run being continued from its own history lookup --
    it must NOT exclude a genuinely separate, earlier run in the same session.
    Establishes a fact in run 1, then makes sure a background+stream continue
    of run 2's external_execution pause still has it available. Uses the async
    API deliberately: this is where the bug actually reproduces (see the
    sync-vs-async split in test_async_arun_and_acontinue_run_all_flag_combinations
    -- AgentOS's own HTTP continue path is async underneath, same as here)."""
    session_id = "test_bg_stream_keeps_other_runs_history"
    agent = _make_agent(shared_db)

    run1 = await agent.arun("My name is Priya, remember that.", session_id=session_id)
    assert not run1.is_paused

    async for _ in agent.arun(
        "What's the weather and my location?",
        session_id=session_id,
        stream=True,
        background=True,
    ):
        pass
    run2 = await _await_wait_for_terminal(agent, session_id)
    assert run2.is_paused

    _resolve(run2.active_requirements)
    async for _ in agent.acontinue_run(
        run_id=run2.run_id,
        session_id=session_id,
        requirements=run2.requirements,
        stream=True,
        background=True,
    ):
        pass
    run2 = await _await_wait_for_terminal(agent, session_id)
    _assert_both_results_present(run2)

    follow_up = await agent.arun("What's my name?", session_id=session_id)
    assert "priya" in (follow_up.content or "").lower(), (
        f"history from run 1 must survive a background+stream continue of run 2. Got: {follow_up.content}"
    )
