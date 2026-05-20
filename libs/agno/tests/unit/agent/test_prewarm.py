"""Unit tests for Agent.prewarm() / aprewarm()."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.metrics import MessageMetrics


def _agent(**kwargs) -> Agent:
    return Agent(
        model=Claude(id="claude-sonnet-4-5"),
        system_message="You are a test assistant.",
        **kwargs,
    )


def test_agent_prewarm_skips_when_model_lacks_prewarm(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "model", SimpleNamespace(id="x"))
    assert agent.prewarm() is None


def test_agent_prewarm_delegates_system_message_to_model(monkeypatch):
    agent = _agent()
    prewarm_mock = Mock(return_value=MessageMetrics())
    monkeypatch.setattr(agent.model, "prewarm", prewarm_mock)
    agent.prewarm()
    prewarm_mock.assert_called_once()
    messages = prewarm_mock.call_args.kwargs["messages"]
    assert any(m.role == "system" and "test assistant" in str(m.content) for m in messages)


def test_agent_prewarm_returns_model_metrics(monkeypatch):
    agent = _agent()
    metrics = MessageMetrics()
    metrics.cache_write_tokens = 4096
    monkeypatch.setattr(agent.model, "prewarm", Mock(return_value=metrics))
    assert agent.prewarm() is metrics


def test_agent_prewarm_warns_on_dynamic_prompt(monkeypatch):
    agent = _agent(add_datetime_to_context=True)
    monkeypatch.setattr(agent.model, "prewarm", Mock(return_value=MessageMetrics()))
    warn_mock = Mock()
    monkeypatch.setattr("agno.agent.agent.log_warning", warn_mock)
    agent.prewarm()
    assert any("dynamic" in str(call).lower() for call in warn_mock.call_args_list)


@pytest.mark.asyncio
async def test_agent_aprewarm_skips_when_model_lacks_aprewarm(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "model", SimpleNamespace(id="x"))
    assert await agent.aprewarm() is None


@pytest.mark.asyncio
async def test_agent_aprewarm_delegates_to_model(monkeypatch):
    agent = _agent()
    aprewarm_mock = AsyncMock(return_value=MessageMetrics())
    monkeypatch.setattr(agent.model, "aprewarm", aprewarm_mock)
    result = await agent.aprewarm()
    aprewarm_mock.assert_awaited_once()
    assert isinstance(result, MessageMetrics)
