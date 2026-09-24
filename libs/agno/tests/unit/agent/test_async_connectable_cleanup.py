import inspect

import pytest

from agno.agent import _init, _run
from agno.agent.agent import Agent
from agno.tools import Toolkit


class AsyncCloseProbe(Toolkit):
    def __init__(self) -> None:
        self.aclose_calls = 0
        self.close_calls = 0
        super().__init__(name="async_close_probe", tools=[])

    async def aclose(self) -> None:
        self.aclose_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class SyncCloseProbe(Toolkit):
    def __init__(self) -> None:
        self.close_calls = 0
        super().__init__(name="sync_close_probe", tools=[])

    def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_adisconnect_connectable_tools_prefers_async_close() -> None:
    agent = Agent(name="async-cleanup-test")
    probe = AsyncCloseProbe()
    agent._connectable_tools_initialized_on_run = [probe]

    await _init.adisconnect_connectable_tools(agent)

    assert probe.aclose_calls == 1
    assert probe.close_calls == 0
    assert agent._connectable_tools_initialized_on_run == []


@pytest.mark.asyncio
async def test_adisconnect_connectable_tools_falls_back_to_sync_close() -> None:
    agent = Agent(name="sync-cleanup-fallback-test")
    probe = SyncCloseProbe()
    agent._connectable_tools_initialized_on_run = [probe]

    await _init.adisconnect_connectable_tools(agent)

    assert probe.close_calls == 1
    assert agent._connectable_tools_initialized_on_run == []


def test_all_async_agent_run_paths_await_connectable_cleanup() -> None:
    for run_path in (
        _run._arun,
        _run._arun_stream,
        _run._acontinue_run,
        _run._acontinue_run_stream,
    ):
        source = inspect.getsource(run_path)
        assert "await adisconnect_connectable_tools(agent)" in source
