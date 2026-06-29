import asyncio
from types import ModuleType
import time
from threading import Event
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import _telemetry
from agno.agent.agent import Agent


class FakeAgentRunCreate:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_agent_telemetry():
    """Test that telemetry logging is called during sync agent run."""
    agent = Agent()

    # Assert telemetry is active by default
    assert agent.telemetry

    # Mock the telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.agent._telemetry.log_agent_telemetry") as mock_log:
        agent.model = MagicMock()
        agent.run("This is a test run")

        # Assert the telemetry logging func was called
        mock_log.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_log.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


@pytest.mark.asyncio
async def test_agent_telemetry_async():
    """Test that telemetry logging is called during async agent run."""
    agent = Agent()

    # Assert telemetry is active by default
    assert agent.telemetry

    # Mock the async telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.agent._telemetry.alog_agent_telemetry") as mock_alog:
        mock_model = AsyncMock()
        mock_model.get_instructions_for_model = MagicMock(return_value=None)
        mock_model.get_system_message_for_model = MagicMock(return_value=None)
        agent.model = mock_model

        await agent.arun("This is a test run")

        # Assert the telemetry logging func was called
        mock_alog.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_alog.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


def test_log_agent_telemetry_does_not_block_on_api_call():
    agent = Agent()
    started = Event()
    release = Event()

    def slow_create_agent_run(run):
        started.set()
        release.wait(timeout=1)

    fake_agent_api = ModuleType("agno.api.agent")
    fake_agent_api.AgentRunCreate = FakeAgentRunCreate
    fake_agent_api.create_agent_run = MagicMock(side_effect=slow_create_agent_run)

    with patch.dict("sys.modules", {"agno.api.agent": fake_agent_api}):
        start = time.perf_counter()
        _telemetry.log_agent_telemetry(agent, session_id="session-id", run_id="run-id")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5
        assert started.wait(timeout=1)
        release.set()
        assert fake_agent_api.create_agent_run.call_count == 1


def test_alog_agent_telemetry_does_not_block_on_api_call():
    async def run_test():
        agent = Agent()
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_acreate_agent_run(run):
            started.set()
            await release.wait()

        fake_agent_api = ModuleType("agno.api.agent")
        fake_agent_api.AgentRunCreate = FakeAgentRunCreate
        fake_agent_api.acreate_agent_run = AsyncMock(side_effect=slow_acreate_agent_run)

        with patch.dict("sys.modules", {"agno.api.agent": fake_agent_api}):
            start = time.perf_counter()
            await _telemetry.alog_agent_telemetry(agent, session_id="session-id", run_id="run-id")
            elapsed = time.perf_counter() - start

            assert elapsed < 0.5
            await asyncio.wait_for(started.wait(), timeout=1)
            assert len(_telemetry._BACKGROUND_AGENT_TELEMETRY_TASKS) == 1

            task = next(iter(_telemetry._BACKGROUND_AGENT_TELEMETRY_TASKS))
            release.set()
            await asyncio.wait_for(task, timeout=1)

            assert _telemetry._BACKGROUND_AGENT_TELEMETRY_TASKS == set()
            assert fake_agent_api.acreate_agent_run.call_count == 1

    asyncio.run(run_test())
