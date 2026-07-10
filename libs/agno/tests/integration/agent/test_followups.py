"""Tests for followup suggestions feature.

Validates that:
- followups are returned as a flat List[str] (not nested {"suggestions": [...]})
- followups work in sync, async, streaming, and async streaming modes
- followups events carry the correct type
- serialization roundtrip preserves the flat list format
"""

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.agent import RunEvent, RunOutput

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**kwargs) -> Agent:
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        followups=True,
        num_followups=3,
        telemetry=False,
        **kwargs,
    )


PROMPT = "What is the capital of France?"


# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------


def test_followups_sync():
    """Sync non-streaming: followups should be a flat list of strings."""
    agent = _make_agent()
    response: RunOutput = agent.run(PROMPT)

    assert response.content is not None
    assert response.followups is not None
    assert isinstance(response.followups, list)
    assert len(response.followups) > 0
    for item in response.followups:
        assert isinstance(item, str)


def test_followups_sync_stream():
    """Sync streaming: followups_completed event should carry a flat list."""
    agent = _make_agent()
    followups_from_event = None

    for event in agent.run(PROMPT, stream=True, stream_events=True):
        if event.event == RunEvent.followups_completed:
            followups_from_event = event.followups  # type: ignore

    assert followups_from_event is not None
    assert isinstance(followups_from_event, list)
    assert len(followups_from_event) > 0
    for item in followups_from_event:
        assert isinstance(item, str)


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followups_async():
    """Async non-streaming: followups should be a flat list of strings."""
    agent = _make_agent()
    response: RunOutput = await agent.arun(PROMPT)

    assert response.content is not None
    assert response.followups is not None
    assert isinstance(response.followups, list)
    assert len(response.followups) > 0
    for item in response.followups:
        assert isinstance(item, str)


@pytest.mark.asyncio
async def test_followups_async_stream():
    """Async streaming: followups_completed event should carry a flat list."""
    agent = _make_agent()
    followups_from_event = None

    async for event in agent.arun(PROMPT, stream=True, stream_events=True):
        if event.event == RunEvent.followups_completed:
            followups_from_event = event.followups  # type: ignore

    assert followups_from_event is not None
    assert isinstance(followups_from_event, list)
    assert len(followups_from_event) > 0
    for item in followups_from_event:
        assert isinstance(item, str)


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


def test_followups_to_dict_flat():
    """RunOutput.to_dict() should serialize followups as a flat list."""
    agent = _make_agent()
    response: RunOutput = agent.run(PROMPT)

    assert response.followups is not None

    d = response.to_dict()
    assert "followups" in d
    assert isinstance(d["followups"], list)
    for item in d["followups"]:
        assert isinstance(item, str)


def test_followups_from_dict_flat_list():
    """RunOutput.from_dict() should accept a flat list."""
    data = {
        "run_id": "test-run",
        "agent_id": "test-agent",
        "content": "Paris is the capital.",
        "followups": ["Learn about Paris", "Explore French culture", "Visit the Eiffel Tower"],
    }
    output = RunOutput.from_dict(data)
    assert output.followups == ["Learn about Paris", "Explore French culture", "Visit the Eiffel Tower"]


def test_followups_from_dict_none():
    """RunOutput.from_dict() should handle missing followups gracefully."""
    data = {
        "run_id": "test-run",
        "agent_id": "test-agent",
        "content": "Paris is the capital.",
    }
    output = RunOutput.from_dict(data)
    assert output.followups is None
