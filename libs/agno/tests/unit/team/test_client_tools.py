"""Tests for client_tools integration with Team._determine_tools_for_model."""

from unittest.mock import MagicMock

from agno.models.base import Function
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team


def _make_run_context(client_tools=None):
    return RunContext(run_id="test-run", session_id="test-session", client_tools=client_tools)


def _make_session():
    return TeamSession(session_id="test-session")


def _make_run_response():
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _make_model():
    model = MagicMock()
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    return model


def _make_client_tool(name: str, external_execution: bool = True) -> Function:
    return Function(
        name=name,
        description=f"A client-provided {name} tool",
        parameters={},
        external_execution=external_execution,
        external_execution_silent=True,
    )


class TestClientToolsIntegration:
    def test_client_tools_appended_to_resolved_tools(self):
        team = Team(name="test-team", members=[])
        client_tool = _make_client_tool("render_chart")

        tools = _determine_tools_for_model(
            team=team,
            model=_make_model(),
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            team_run_context={},
            session=_make_session(),
            async_mode=False,
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" in tool_names

    def test_no_client_tools_when_none(self):
        team = Team(name="test-team", members=[])

        tools = _determine_tools_for_model(
            team=team,
            model=_make_model(),
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=None),
            team_run_context={},
            session=_make_session(),
            async_mode=False,
        )

        # Should only have delegate tool, not any client tools
        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" not in tool_names

    def test_multiple_client_tools_appended(self):
        team = Team(name="test-team", members=[])
        client_tools = [
            _make_client_tool("render_chart"),
            _make_client_tool("show_modal"),
            _make_client_tool("update_sidebar"),
        ]

        tools = _determine_tools_for_model(
            team=team,
            model=_make_model(),
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=client_tools),
            team_run_context={},
            session=_make_session(),
            async_mode=False,
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" in tool_names
        assert "show_modal" in tool_names
        assert "update_sidebar" in tool_names

    def test_client_tools_preserve_external_execution_flag(self):
        team = Team(name="test-team", members=[])
        client_tool = _make_client_tool("render_chart", external_execution=True)

        tools = _determine_tools_for_model(
            team=team,
            model=_make_model(),
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            team_run_context={},
            session=_make_session(),
            async_mode=False,
        )

        render_tool = next((t for t in tools if isinstance(t, Function) and t.name == "render_chart"), None)
        assert render_tool is not None
        assert render_tool.external_execution is True
        assert render_tool.external_execution_silent is True

    def test_client_tools_coexist_with_team_tools(self):
        # Team has a built-in tool
        def my_team_tool(x: int) -> int:
            return x * 2

        team = Team(name="test-team", members=[], tools=[my_team_tool])
        client_tool = _make_client_tool("render_chart")

        tools = _determine_tools_for_model(
            team=team,
            model=_make_model(),
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            team_run_context={},
            session=_make_session(),
            async_mode=False,
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        # Both team tool and client tool should be present
        assert "my_team_tool" in tool_names
        assert "render_chart" in tool_names
