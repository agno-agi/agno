"""Unit tests for Agent.get_prewarm_payload() / aget_prewarm_payload()."""

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.message import Message


def _agent(**kwargs) -> Agent:
    return Agent(
        model=Claude(id="claude-sonnet-4-5"),
        system_message="You are a test assistant.",
        **kwargs,
    )


def test_get_prewarm_payload_returns_system_and_tools():
    payload = _agent().get_prewarm_payload()
    assert payload is not None
    system_message, tools = payload
    assert isinstance(system_message, Message)
    assert system_message.role == "system"
    assert "test assistant" in str(system_message.content)
    assert isinstance(tools, list)


def test_get_prewarm_payload_returns_none_when_no_system_message():
    agent = Agent(model=Claude(id="claude-sonnet-4-5"))
    assert agent.get_prewarm_payload() is None


def test_get_prewarm_payload_works_with_output_schema():
    """Regression: output_schema does not break payload construction (review bug #1)."""
    from pydantic import BaseModel

    class _Schema(BaseModel):
        value: str

    payload = _agent(output_schema=_Schema).get_prewarm_payload()
    assert payload is not None


def test_get_prewarm_payload_accepts_session_id_and_user_id():
    payload = _agent().get_prewarm_payload(session_id="sess123", user_id="user456")
    assert payload is not None


@pytest.mark.asyncio
async def test_aget_prewarm_payload_returns_system_and_tools():
    payload = await _agent().aget_prewarm_payload()
    assert payload is not None
    system_message, tools = payload
    assert isinstance(system_message, Message)
    assert system_message.role == "system"
    assert "test assistant" in str(system_message.content)
