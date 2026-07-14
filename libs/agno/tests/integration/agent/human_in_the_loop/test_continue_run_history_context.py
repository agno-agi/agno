"""
Integration tests for continue_run with add_history_to_context=True (issue #6884).

When continue_run is called with run_id, messages are loaded from the DB where
history is scrubbed (store_history_messages defaults to False). Without the fix,
history from prior runs is missing in the continue_run context.

These tests verify that:
1. continue_run(run_id=...) includes history from prior runs
2. A fresh agent instance also gets history via run_id
3. Async acontinue_run(run_id=...) includes history from prior runs
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool

INSTRUCTIONS = (
    "You are a note-taking assistant. "
    "You MUST use the save_note tool whenever the user asks you to save a note. "
    "IMPORTANT: Always address the user by their name in every response."
)


@tool(requires_confirmation=True)
def save_note(title: str, content: str) -> str:
    """Save a note. Requires user confirmation.

    Args:
        title: Title of the note.
        content: Content of the note.

    Returns:
        Confirmation message.
    """
    return f"Note saved - Title: '{title}', Content: '{content}'"


def _make_agent(db, **kwargs):
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[save_note],
        instructions=INSTRUCTIONS,
        db=db,
        add_history_to_context=True,
        num_history_runs=5,
        # Strip tool calls from history to avoid OpenAI 400 errors when
        # history contains tool_call messages without matching tool responses.
        max_tool_calls_from_history=0,
        telemetry=False,
        **kwargs,
    )


def test_continue_run_via_run_id_includes_history(shared_db):
    """continue_run(run_id=...) should include history from prior runs.

    Steps:
    1. First run: user introduces themselves (establishes history)
    2. Second run: triggers a requires_confirmation tool (pauses)
    3. continue_run via run_id: after confirmation, the model's response
       should reference the user's name from the first run, proving
       history was included in the context.
    """
    session_id = "test_history_runid_1"
    agent = _make_agent(shared_db)

    # Step 1: Establish history
    run1 = agent.run("Hi, my name is Alice.", session_id=session_id)
    assert not run1.is_paused

    # Step 2: Trigger tool requiring confirmation — be very explicit
    run2 = agent.run(
        "Please use the save_note tool to save a note with title 'Reminder' and content 'Buy groceries'.",
        session_id=session_id,
    )
    assert run2.is_paused, f"Expected paused (tool should require confirmation), got status={run2.status}"
    assert run2.active_requirements

    # Confirm all requirements
    for req in run2.active_requirements:
        if req.needs_confirmation:
            req.confirm()

    # Step 3: continue_run via run_id (loads from DB, history scrubbed)
    result = agent.continue_run(
        run_id=run2.run_id,
        requirements=run2.requirements,
        session_id=session_id,
    )
    assert not result.is_paused

    # The model should mention "Alice" — it can only know this from history
    content_lower = (result.content or "").lower()
    assert "alice" in content_lower, (
        f"continue_run response should reference user's name from history. Got: {result.content}"
    )


def test_continue_run_via_run_id_new_agent_includes_history(shared_db):
    """A fresh agent instance should still get history when using run_id.

    This simulates a real-world scenario where the agent is recreated
    (e.g., in a new API request) and continues a paused run.
    """
    session_id = "test_history_newagent_1"

    # First agent instance: establish history + trigger pause
    agent1 = _make_agent(shared_db)

    run1 = agent1.run("Hi, my name is Bob.", session_id=session_id)
    assert not run1.is_paused

    run2 = agent1.run(
        "Please use the save_note tool to save a note with title 'TODO' and content 'Finish report'.",
        session_id=session_id,
    )
    assert run2.is_paused, f"Expected paused (tool should require confirmation), got status={run2.status}"

    # Confirm requirements
    for req in run2.active_requirements:
        if req.needs_confirmation:
            req.confirm()

    # Second agent instance (simulates new request/process)
    agent2 = _make_agent(shared_db)

    result = agent2.continue_run(
        run_id=run2.run_id,
        requirements=run2.requirements,
        session_id=session_id,
    )
    assert not result.is_paused

    content_lower = (result.content or "").lower()
    assert "bob" in content_lower, (
        f"New agent's continue_run should reference user's name from history. Got: {result.content}"
    )


@pytest.mark.asyncio
async def test_acontinue_run_via_run_id_includes_history(shared_db):
    """Async version: acontinue_run(run_id=...) should include history from prior runs."""
    session_id = "test_history_async_1"
    agent = _make_agent(shared_db)

    # Step 1: Establish history
    run1 = agent.run("Hi, my name is Charlie.", session_id=session_id)
    assert not run1.is_paused

    # Step 2: Trigger tool requiring confirmation
    run2 = agent.run(
        "Please use the save_note tool to save a note with title 'Shopping' and content 'Buy milk'.",
        session_id=session_id,
    )
    if not run2.is_paused:
        pytest.skip("Model did not call the tool (flaky with gpt-4o-mini)")

    for req in run2.active_requirements:
        if req.needs_confirmation:
            req.confirm()

    # Step 3: acontinue_run via run_id
    result = await agent.acontinue_run(
        run_id=run2.run_id,
        requirements=run2.requirements,
        session_id=session_id,
    )
    assert not result.is_paused

    content_lower = (result.content or "").lower()
    assert "charlie" in content_lower, (
        f"acontinue_run response should reference user's name from history. Got: {result.content}"
    )
