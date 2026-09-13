"""Tests for Team RunPausedEvent.tools_awaiting_external_execution property."""

from agno.models.response import ToolExecution
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent


def _make_tool_execution(
    tool_name: str,
    external_execution_required: bool = False,
    **overrides,
) -> ToolExecution:
    defaults = dict(
        tool_call_id=f"call_{tool_name}",
        tool_name=tool_name,
        tool_args={},
        external_execution_required=external_execution_required,
    )
    defaults.update(overrides)
    return ToolExecution(**defaults)


class TestToolsAwaitingExternalExecution:
    def test_returns_empty_when_no_tools(self):
        event = TeamRunPausedEvent(run_id="test", session_id="sess", team_id="team")
        assert event.tools_awaiting_external_execution == []

    def test_returns_empty_when_tools_is_none(self):
        event = TeamRunPausedEvent(run_id="test", session_id="sess", team_id="team", tools=None)
        assert event.tools_awaiting_external_execution == []

    def test_returns_only_external_execution_tools(self):
        external_tool = _make_tool_execution("send_email", external_execution_required=True)
        internal_tool = _make_tool_execution("get_weather", external_execution_required=False)
        event = TeamRunPausedEvent(
            run_id="test",
            session_id="sess",
            team_id="team",
            tools=[external_tool, internal_tool],
        )
        awaiting = event.tools_awaiting_external_execution
        assert len(awaiting) == 1
        assert awaiting[0].tool_name == "send_email"

    def test_returns_multiple_external_tools(self):
        tool1 = _make_tool_execution("send_email", external_execution_required=True)
        tool2 = _make_tool_execution("run_shell", external_execution_required=True)
        tool3 = _make_tool_execution("get_weather", external_execution_required=False)
        event = TeamRunPausedEvent(
            run_id="test",
            session_id="sess",
            team_id="team",
            tools=[tool1, tool2, tool3],
        )
        awaiting = event.tools_awaiting_external_execution
        assert len(awaiting) == 2
        names = {t.tool_name for t in awaiting}
        assert names == {"send_email", "run_shell"}

    def test_returns_empty_when_all_internal(self):
        tool1 = _make_tool_execution("get_weather", external_execution_required=False)
        tool2 = _make_tool_execution("search_web", external_execution_required=False)
        event = TeamRunPausedEvent(
            run_id="test",
            session_id="sess",
            team_id="team",
            tools=[tool1, tool2],
        )
        assert event.tools_awaiting_external_execution == []

    def test_parity_with_agent_behavior(self):
        external_tool = _make_tool_execution("send_email", external_execution_required=True)
        internal_tool = _make_tool_execution("get_weather", external_execution_required=False)

        # Agent side
        agent_event = AgentRunPausedEvent(
            run_id="test",
            session_id="sess",
            agent_id="agent",
            tools=[external_tool, internal_tool],
        )
        agent_awaiting = agent_event.tools_awaiting_external_execution

        # Team side
        team_event = TeamRunPausedEvent(
            run_id="test",
            session_id="sess",
            team_id="team",
            tools=[external_tool, internal_tool],
        )
        team_awaiting = team_event.tools_awaiting_external_execution

        # Same behavior
        assert len(agent_awaiting) == len(team_awaiting) == 1
        assert agent_awaiting[0].tool_name == team_awaiting[0].tool_name == "send_email"
