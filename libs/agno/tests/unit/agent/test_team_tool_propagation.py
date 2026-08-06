from typing import Any
from unittest.mock import MagicMock

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.tools import tool
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


def _mock_model():
    model = MagicMock()
    model.supports_native_structured_outputs = False
    return model


def _mock_team():
    team = MagicMock()
    team.__class__.__name__ = "Team"
    return team


# -- Callable tools ----------------------------------------------------------


def test_callable_tool_receives_team_from_member_agent():
    def my_tool(query: str, team: Any) -> str:
        return "ok"

    agent = Agent(tools=[my_tool])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert len(functions) == 1
    assert functions[0]._team is agent._team


def test_callable_tool_team_is_none_when_agent_has_no_team():
    def my_tool(query: str) -> str:
        return "ok"

    agent = Agent(tools=[my_tool])

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert len(functions) == 1
    assert functions[0]._team is None


# -- Function objects ---------------------------------------------------------


def test_function_tool_receives_team_from_member_agent():
    def my_tool(query: str, team: Any) -> str:
        return "ok"

    func = Function.from_callable(my_tool)
    agent = Agent(tools=[func])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert len(functions) == 1
    assert functions[0]._team is agent._team


# -- Toolkit functions --------------------------------------------------------


def test_toolkit_tool_receives_team_from_member_agent():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit")
            self.register(self.my_tool)

        def my_tool(self, query: str) -> str:
            return "ok"

    agent = Agent(tools=[MyToolkit()])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    toolkit_funcs = [f for f in functions if isinstance(f, Function)]
    assert len(toolkit_funcs) == 1
    assert toolkit_funcs[0]._team is agent._team


# -- Per-function instructions propagation -----------------------------------
# Verifies that @tool(instructions=...) reaches agent._tool_instructions
# regardless of whether the tool is registered directly or via a Toolkit.


def test_bare_function_instructions_reach_agent():
    @tool(instructions="bare-rule")
    def my_tool(x: str) -> str:
        return x

    agent = Agent(tools=[my_tool])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["bare-rule"]


def test_toolkit_per_function_instructions_reach_agent():
    """The original bug: @tool(instructions=...) inside a Toolkit was dropped."""

    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.my_tool])

        @tool(instructions="toolkit-func-rule")
        def my_tool(self, x: str) -> str:
            return x

    agent = Agent(tools=[MyToolkit()])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["toolkit-func-rule"]


def test_toolkit_level_and_per_function_instructions_both_reach_agent():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(
                name="my_toolkit",
                tools=[self.my_tool],
                instructions="toolkit-level-rule",
                add_instructions=True,
            )

        @tool(instructions="toolkit-func-rule")
        def my_tool(self, x: str) -> str:
            return x

    agent = Agent(tools=[MyToolkit()])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["toolkit-func-rule", "toolkit-level-rule"]


def test_toolkit_per_function_add_instructions_false_is_respected():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.kept, self.dropped])

        @tool(instructions="kept-rule")
        def kept(self, x: str) -> str:
            return x

        @tool(instructions="dropped-rule", add_instructions=False)
        def dropped(self, x: str) -> str:
            return x

    agent = Agent(tools=[MyToolkit()])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["kept-rule"]


def test_toolkit_multiple_per_function_instructions_all_reach_agent():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.a, self.b])

        @tool(instructions="rule-a")
        def a(self, x: str) -> str:
            return x

        @tool(instructions="rule-b")
        def b(self, x: str) -> str:
            return x

    agent = Agent(tools=[MyToolkit()])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["rule-a", "rule-b"]


def test_toolkit_function_without_instructions_does_not_append_none():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.my_tool])

        def my_tool(self, x: str) -> str:
            return x

    agent = Agent(tools=[MyToolkit()])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == []


# -- Team-only tool filtering (issue #7965) -----------------------------------
# Member agents must never see delegate_task_to_member or delegate_task_to_members
# in their tool schema even if those names somehow appear in their tools list.


def _make_delegate_function(name: str) -> Function:
    """Return a bare Function with the given name (no entrypoint needed for schema tests)."""
    func = Function(name=name)
    return func


def test_delegate_task_to_member_filtered_for_member_agent():
    """delegate_task_to_member is stripped when the agent has a parent team."""
    delegate_func = _make_delegate_function("delegate_task_to_member")
    agent = Agent(tools=[delegate_func])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    names = [f.name for f in functions if isinstance(f, Function)]
    assert "delegate_task_to_member" not in names


def test_delegate_task_to_members_filtered_for_member_agent():
    """delegate_task_to_members is stripped when the agent has a parent team."""
    delegate_func = _make_delegate_function("delegate_task_to_members")
    agent = Agent(tools=[delegate_func])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    names = [f.name for f in functions if isinstance(f, Function)]
    assert "delegate_task_to_members" not in names


def test_delegate_task_to_member_not_filtered_for_standalone_agent():
    """delegate_task_to_member is kept when the agent has no parent team."""
    delegate_func = _make_delegate_function("delegate_task_to_member")
    agent = Agent(tools=[delegate_func])
    # agent._team is None (default)

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    names = [f.name for f in functions if isinstance(f, Function)]
    assert "delegate_task_to_member" in names


def test_legitimate_tools_kept_alongside_filtered_delegate_tool():
    """Filtering delegate tools does not remove the agent's own legitimate tools."""

    def send_message(text: str) -> str:
        return text

    delegate_func = _make_delegate_function("delegate_task_to_member")
    agent = Agent(tools=[send_message, delegate_func])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    names = [f.name for f in functions if isinstance(f, Function)]
    assert "send_message" in names
    assert "delegate_task_to_member" not in names


def test_delegate_callable_filtered_for_member_agent():
    """A raw callable named delegate_task_to_member is also filtered."""

    def delegate_task_to_member(member_id: str, task: str) -> str:
        return "delegated"

    agent = Agent(tools=[delegate_task_to_member])
    agent._team = _mock_team()

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    names = [f.name for f in functions if isinstance(f, Function)]
    assert "delegate_task_to_member" not in names
