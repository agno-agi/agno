"""History filtering must reach member inputs through the real mode-selected tools."""

from unittest.mock import MagicMock, Mock

import pytest

from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._tools import _filter_team_history
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools.function import Function


def test_filter_errors_do_not_fall_back_to_sensitive_history():
    callback = Mock(side_effect=ValueError("filter failed"))
    team = Team(members=[], team_history_filter=callback)
    assert _filter_team_history(team, None) is None
    callback.assert_not_called()
    with pytest.raises(ValueError, match="filter failed"):
        _filter_team_history(team, "secret")


@pytest.mark.parametrize("mode", list(TeamMode))
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("behavior", ["redact", "remove", "empty", "default", "disabled", "no-history"])
@pytest.mark.asyncio
async def test_filter_reaches_delegated_member_input(monkeypatch, mode, stream, async_mode, behavior):
    member = Agent(id="specialist", name="Specialist", telemetry=False)
    callback = Mock(side_effect=lambda history: history.replace("secret", "[redacted]"))
    if behavior == "remove":
        callback = Mock(return_value=None)
    elif behavior == "empty":
        callback = Mock(return_value="")
    team = Team(
        id="parent",
        members=[member],
        mode=mode,
        add_team_history_to_members=behavior != "disabled",
        num_team_history_runs=1,
        team_history_filter=None if behavior == "default" else callback,
        telemetry=False,
    )
    session = TeamSession(session_id="session", team_id=team.id)
    session.runs = (
        []
        if behavior == "no-history"
        else [
            TeamRunOutput(
                run_id="prior",
                team_id=team.id,
                status=RunStatus.completed,
                input=RunInput(input_content="public secret"),
                content="previous answer",
            )
        ]
    )
    original_history = session.get_team_history_context(num_runs=1)
    received = []

    def run_member(**kwargs):
        received.append(kwargs["input"])
        output = RunOutput(run_id=kwargs["run_id"], agent_id=member.id, content="member answer")
        return iter([output]) if stream else output

    async def arun_member(**kwargs):
        return run_member(**kwargs)

    async def stream_member(**kwargs):
        for output in run_member(**kwargs):
            yield output

    monkeypatch.setattr(member, "run", run_member)
    monkeypatch.setattr(member, "arun", stream_member if stream else arun_member)
    context = RunContext(run_id="current", session_id=session.session_id, session_state={})
    model = MagicMock()
    model.supports_native_structured_outputs = False
    tools = {
        tool.name: tool
        for tool in team._determine_tools_for_model(
            model=model,
            run_response=TeamRunOutput(run_id="current", team_id=team.id),
            run_context=context,
            team_run_context={},
            session=session,
            input_message="current request",
            stream=stream,
            async_mode=async_mode,
            check_mcp_tools=False,
        )
        if isinstance(tool, Function)
    }
    if mode == TeamMode.tasks:
        list(tools["create_task"].entrypoint(title="Current task", description="current request"))
        from agno.team.task import load_task_list

        task_id = load_task_list(context.session_state).tasks[0].id
        result = tools["execute_task"].entrypoint(task_id=task_id, member_id=member.id)
    elif mode == TeamMode.broadcast:
        result = tools["delegate_task_to_members"].entrypoint(task="current request")
    else:
        tool = tools["delegate_task_to_member"]
        if mode == TeamMode.route:
            assert tool.stop_after_tool_call is True
        result = tool.entrypoint(member_id=member.id, task="current request")
    if async_mode:
        _ = [event async for event in result]
    else:
        list(result)
    assert len(received) == 1
    prompt = received[0]
    assert "current request" in prompt
    if behavior in ("default", "disabled", "no-history"):
        callback.assert_not_called()
    else:
        callback.assert_called_once_with(original_history)
    if behavior == "redact":
        assert "public [redacted]" in prompt
        assert "secret" not in prompt
    elif behavior == "default":
        assert original_history in prompt
    else:
        assert "team_history_context" not in prompt
        assert "secret" not in prompt
    # Filtering must not redact or delete the persisted session history.
    assert session.get_team_history_context(num_runs=1) == original_history
