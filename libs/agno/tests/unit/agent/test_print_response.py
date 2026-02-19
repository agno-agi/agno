"""Tests for print_response and aprint_response returning RunOutput."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput


@pytest.fixture
def mock_run_output():
    """Create a mock RunOutput for testing."""
    return RunOutput(
        run_id="test-run-id",
        agent_id="test-agent-id",
        agent_name="TestAgent",
        session_id="test-session-id",
        content="Hello, this is a test response.",
    )


@pytest.fixture
def agent():
    """Create a minimal agent with a mock model."""
    mock_model = MagicMock(spec=OpenAIChat)
    return Agent(name="TestAgent", model=mock_model, markdown=False)


class TestPrintResponseReturnsRunOutput:
    def test_print_response_returns_run_output(self, agent, mock_run_output, monkeypatch):
        """Test that print_response returns RunOutput when stream=False."""
        from agno.agent import _init

        monkeypatch.setattr(_init, "has_async_db", lambda a: False)

        with patch.object(agent, "run", return_value=mock_run_output):
            result = agent.print_response("Hello", stream=False)

        assert isinstance(result, RunOutput)
        assert result.run_id == "test-run-id"
        assert result.content == "Hello, this is a test response."

    def test_print_response_returns_none_when_streaming(self, agent, monkeypatch):
        """Test that print_response returns None when stream=True."""
        from agno.agent import _init

        monkeypatch.setattr(_init, "has_async_db", lambda a: False)

        # For streaming, the function iterates over events, so we mock run to return an iterable
        with patch.object(agent, "run", return_value=iter([])):
            result = agent.print_response("Hello", stream=True)

        assert result is None


class TestAPrintResponseReturnsRunOutput:
    def test_aprint_response_returns_run_output(self, agent, mock_run_output):
        """Test that aprint_response returns RunOutput when stream=False."""

        async def _test():
            with patch.object(agent, "arun", new_callable=AsyncMock, return_value=mock_run_output):
                result = await agent.aprint_response("Hello", stream=False)
            return result

        result = asyncio.get_event_loop().run_until_complete(_test())
        assert isinstance(result, RunOutput)
        assert result.run_id == "test-run-id"
        assert result.content == "Hello, this is a test response."

    def test_aprint_response_returns_none_when_streaming(self, agent):
        """Test that aprint_response returns None when stream=True."""

        async def _empty_async_gen():
            return
            yield  # noqa: unreachable - makes this an async generator

        async def _test():
            with patch.object(agent, "arun", return_value=_empty_async_gen()):
                result = await agent.aprint_response("Hello", stream=True)
            return result

        result = asyncio.get_event_loop().run_until_complete(_test())
        assert result is None
