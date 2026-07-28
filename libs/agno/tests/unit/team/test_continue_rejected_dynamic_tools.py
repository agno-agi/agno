from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse, ToolExecution
from agno.run.messages import RunMessages
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.team._run import (
    _ahandle_team_tool_call_updates,
    _ahandle_team_tool_call_updates_stream,
    _handle_team_tool_call_updates,
    _handle_team_tool_call_updates_stream,
)


class _TeamModel(Model):
    def __init__(self) -> None:
        super().__init__(id="team-hitl", name="team-hitl", provider="test")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("provider should not be called by the update handler")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("provider should not be called by the update handler")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("provider should not be called by the update handler")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("provider should not be called by the update handler")
        yield

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _rejected_update() -> tuple[Team, TeamRunOutput, RunMessages, ToolExecution]:
    tool = ToolExecution(
        tool_call_id="proposal-1",
        tool_name="present_for_review",
        tool_args={"artifact": "draft-v1"},
        requires_confirmation=True,
        confirmed=False,
        confirmation_note="Revise the comparative.",
    )
    return (
        Team(model=_TeamModel(), members=[]),
        TeamRunOutput(run_id="team-run", tools=[tool]),
        RunMessages(),
        tool,
    )


def _assert_rejected(run_messages: RunMessages, tool: ToolExecution) -> None:
    assert tool.requires_confirmation is False
    assert tool.confirmed is False
    assert tool.tool_call_error is True
    assert len(run_messages.messages) == 1
    result = run_messages.messages[0]
    assert result.tool_call_id == "proposal-1"
    assert result.tool_name == "present_for_review"
    assert result.tool_args == {"artifact": "draft-v1"}
    assert result.content == "Revise the comparative."
    assert result.tool_call_error is True


@pytest.mark.parametrize("stream", [False, True])
def test_sync_team_rejection_survives_empty_tool_surface(stream: bool) -> None:
    team, run_response, run_messages, tool = _rejected_update()

    if stream:
        list(_handle_team_tool_call_updates_stream(team, run_response, run_messages, tools=[]))
    else:
        _handle_team_tool_call_updates(team, run_response, run_messages, tools=[])

    _assert_rejected(run_messages, tool)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_team_rejection_survives_empty_tool_surface(stream: bool) -> None:
    team, run_response, run_messages, tool = _rejected_update()

    if stream:
        async for _ in _ahandle_team_tool_call_updates_stream(team, run_response, run_messages, tools=[]):
            pass
    else:
        await _ahandle_team_tool_call_updates(team, run_response, run_messages, tools=[])

    _assert_rejected(run_messages, tool)
