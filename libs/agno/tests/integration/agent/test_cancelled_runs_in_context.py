"""Integration tests for add_cancelled_runs_to_context.

These tests verify that when an agent run is cancelled mid-stream:
1. With add_cancelled_runs_to_context=True, the cancelled run's partial content
   is included in the history sent to the model on the next run
2. The follow-up run completes (the closed tool calls are accepted by the provider)
3. With the flag unset, cancelled runs stay excluded from history (default behavior)
"""

import os

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunCancelledEvent
from agno.run.base import RunStatus

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


def _cancel_run_mid_stream(agent, session_id):
    """Cancel a streaming run after a few chunks and return the persisted partial content."""
    content_chunks = []
    run_id = None
    cancelled = False

    for event in agent.run(
        input="Write a very long story about a lighthouse keeper.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id

        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)

        if len(content_chunks) >= 10 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

        if isinstance(event, RunCancelledEvent):
            break

    assert cancelled, "Run should have been cancelled"

    # Verify the cancelled run is persisted with its partial content
    session = agent.get_session(session_id=session_id)
    assert session is not None and session.runs
    cancelled_run = session.runs[-1]
    assert cancelled_run.status == RunStatus.cancelled
    assert cancelled_run.content

    return cancelled_run.content


def test_cancelled_run_included_in_context_when_enabled(shared_db):
    """A follow-up run should receive the cancelled run's partial content in history."""
    agent = Agent(
        name="Continuity Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write detailed responses.",
        db=shared_db,
        add_history_to_context=True,
        add_cancelled_runs_to_context=True,
    )

    session_id = "test_cancelled_runs_in_context_enabled"
    partial_content = _cancel_run_mid_stream(agent, session_id)

    result = agent.run(
        input="What was I asking about before?",
        session_id=session_id,
    )

    assert result.status == RunStatus.completed
    snippet = partial_content[:50]
    history_messages = [m for m in (result.messages or []) if getattr(m, "from_history", False)]
    assert any(snippet in str(m.content or "") for m in history_messages), (
        "Cancelled run's partial content should be in the history sent to the model"
    )


def test_cancelled_run_excluded_from_context_by_default(shared_db):
    """Without the flag, a cancelled run must stay out of the history sent to the model."""
    agent = Agent(
        name="Continuity Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write detailed responses.",
        db=shared_db,
        add_history_to_context=True,
    )

    session_id = "test_cancelled_runs_in_context_default"
    partial_content = _cancel_run_mid_stream(agent, session_id)

    result = agent.run(
        input="What was I asking about before?",
        session_id=session_id,
    )

    assert result.status == RunStatus.completed
    snippet = partial_content[:50]
    history_messages = [m for m in (result.messages or []) if getattr(m, "from_history", False)]
    assert all(snippet not in str(m.content or "") for m in history_messages), (
        "Cancelled run's content should be excluded from history by default"
    )


@pytest.mark.asyncio
async def test_cancelled_run_included_in_context_async(shared_db):
    """Async variant: the cancelled run's partial content reaches the follow-up run."""
    agent = Agent(
        name="Continuity Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write detailed responses.",
        db=shared_db,
        add_history_to_context=True,
        add_cancelled_runs_to_context=True,
    )

    session_id = "test_cancelled_runs_in_context_async"
    partial_content = _cancel_run_mid_stream(agent, session_id)

    result = await agent.arun(
        input="What was I asking about before?",
        session_id=session_id,
    )

    assert result.status == RunStatus.completed
    snippet = partial_content[:50]
    history_messages = [m for m in (result.messages or []) if getattr(m, "from_history", False)]
    assert any(snippet in str(m.content or "") for m in history_messages), (
        "Cancelled run's partial content should be in the history sent to the model"
    )
