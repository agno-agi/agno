from typing import Any
from unittest.mock import MagicMock

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
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
