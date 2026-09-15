import pytest

from agno.agent._tools import aget_tools, get_tools
from agno.agent.agent import Agent
from agno.models.base import Function
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession


def _make_run_context(client_tools=None):
    return RunContext(run_id="test-run", session_id="test-session", client_tools=client_tools)


def _make_session():
    return AgentSession(session_id="test-session")


def _make_run_response():
    return RunOutput(run_id="test-run", session_id="test-session", agent_id="test-agent")


def _make_client_tool(name: str, external_execution: bool = True) -> Function:
    return Function(
        name=name,
        description=f"A client-provided {name} tool",
        parameters={},
        external_execution=external_execution,
        external_execution_silent=True,
    )


class TestAgentClientToolsSync:
    def test_client_tools_appended_to_resolved_tools(self):
        agent = Agent(name="test-agent")
        client_tool = _make_client_tool("render_chart")

        tools = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            session=_make_session(),
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" in tool_names

    def test_no_client_tools_when_none(self):
        agent = Agent(name="test-agent")

        tools = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=None),
            session=_make_session(),
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" not in tool_names

    def test_multiple_client_tools_appended(self):
        agent = Agent(name="test-agent")
        client_tools = [
            _make_client_tool("render_chart"),
            _make_client_tool("show_modal"),
            _make_client_tool("update_sidebar"),
        ]

        tools = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=client_tools),
            session=_make_session(),
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" in tool_names
        assert "show_modal" in tool_names
        assert "update_sidebar" in tool_names

    def test_client_tools_preserve_external_execution_flag(self):
        agent = Agent(name="test-agent")
        client_tool = _make_client_tool("render_chart", external_execution=True)

        tools = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            session=_make_session(),
        )

        render_tool = next((t for t in tools if isinstance(t, Function) and t.name == "render_chart"), None)
        assert render_tool is not None
        assert render_tool.external_execution is True
        assert render_tool.external_execution_silent is True


class TestAgentClientToolsAsync:
    @pytest.mark.asyncio
    async def test_client_tools_appended_async(self):
        agent = Agent(name="test-agent")
        client_tool = _make_client_tool("render_chart")

        tools = await aget_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            session=_make_session(),
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" in tool_names

    @pytest.mark.asyncio
    async def test_no_client_tools_when_none_async(self):
        agent = Agent(name="test-agent")

        tools = await aget_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=None),
            session=_make_session(),
        )

        tool_names = {t.name for t in tools if isinstance(t, Function)}
        assert "render_chart" not in tool_names


class TestClientToolsIsolation:
    def test_client_tools_do_not_mutate_agent_tools(self):
        agent = Agent(name="test-agent")
        original_tools_count = len(agent.tools or [])

        client_tool = _make_client_tool("render_chart")
        get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            session=_make_session(),
        )

        assert len(agent.tools or []) == original_tools_count

    def test_second_run_without_client_tools_excludes_previous(self):
        agent = Agent(name="test-agent")

        client_tool = _make_client_tool("render_chart")
        tools_with_client = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=[client_tool]),
            session=_make_session(),
        )

        tools_without_client = get_tools(
            agent=agent,
            run_response=_make_run_response(),
            run_context=_make_run_context(client_tools=None),
            session=_make_session(),
        )

        with_names = {t.name for t in tools_with_client if isinstance(t, Function)}
        without_names = {t.name for t in tools_without_client if isinstance(t, Function)}

        assert "render_chart" in with_names
        assert "render_chart" not in without_names
