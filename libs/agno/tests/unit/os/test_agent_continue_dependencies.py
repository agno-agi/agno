from typing import Any, Dict, cast

import pytest

from agno.os.routers.agents.router import agent_continue_response_streamer


class _DummyAgent:
    def __init__(self) -> None:
        self.kwargs: Dict[str, Any] = {}

    def acontinue_run(self, **kwargs: Any):
        self.kwargs = kwargs

        async def _empty_stream():
            if False:
                yield None

        return _empty_stream()


@pytest.mark.asyncio
async def test_continue_streamer_forwards_dependencies():
    agent = _DummyAgent()
    _ = [
        event
        async for event in agent_continue_response_streamer(
            agent=cast(Any, agent),
            run_id="run-1",
            dependencies={"user_token": "token-123"},
        )
    ]

    assert "dependencies" in agent.kwargs
    assert agent.kwargs["dependencies"] == {"user_token": "token-123"}
