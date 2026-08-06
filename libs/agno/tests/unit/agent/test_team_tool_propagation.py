from typing import Any
from unittest.mock import MagicMock

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.registry import Registry
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


# -- Rehydrated toolkit members ----------------------------------------------


def _guided_toolkit() -> Toolkit:
    def first_tool() -> str:
        return "first"

    def second_tool() -> str:
        return "second"

    toolkit = Toolkit(
        name="my_toolkit",
        tools=[first_tool, second_tool],
        instructions="toolkit-level-rule",
        add_instructions=True,
    )
    toolkit.functions["first_tool"].instructions = "first-rule"
    toolkit.functions["second_tool"].instructions = "second-rule"
    return toolkit


def _rehydrate(registry: Registry, toolkit: Toolkit, only: Any = None) -> Any:
    stored = []
    for name, function in toolkit.get_functions().items():
        if only is not None and name not in only:
            continue
        function_dict = function.to_dict()
        function_dict["toolkit"] = toolkit.name
        stored.append(function_dict)
    return registry.rehydrate_functions(stored)


def test_rehydrated_toolkit_instructions_reach_agent_once():
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])

    agent = Agent(tools=_rehydrate(registry, toolkit))
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]


def test_rehydrated_subset_does_not_get_the_whole_toolkits_guidance():
    """A component that persisted one member of a toolkit must not be handed
    guidance naming the members it was not given."""
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])

    agent = Agent(tools=_rehydrate(registry, toolkit, only={"first_tool"}))
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["first-rule"]


def test_live_toolkit_beside_rehydrated_members_emits_guidance_once_and_last():
    """A tools list holding both representations of one toolkit must read the
    same as the live Toolkit alone -- before and after deep_copy, which clones
    the Toolkit entry while the Functions keep the live one."""
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])
    mixed = _rehydrate(registry, toolkit, only={"first_tool"}) + [toolkit]

    agent = Agent(tools=mixed)
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    assert agent._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]

    copied = Agent(tools=mixed).deep_copy()
    parse_tools(agent=copied, tools=copied.tools, model=_mock_model())
    assert copied._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]


def test_rehydrated_toolkit_guidance_survives_deep_copy():
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])

    copied = Agent(tools=_rehydrate(registry, toolkit)).deep_copy()
    assert all(tool.source_toolkit is toolkit for tool in copied.tools)
    parse_tools(agent=copied, tools=copied.tools, model=_mock_model())

    assert copied._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]


def test_non_string_toolkit_instructions_do_not_break_the_run():
    """`instructions` is declared Optional[str] but nothing enforces it. Grouping
    toolkits by their guidance must not turn a list into a hard failure."""
    toolkit = Toolkit(
        name="my_toolkit",
        tools=[lambda: "x"],
        instructions=["rule one", "rule two"],
        add_instructions=True,
    )

    agent = Agent(tools=[toolkit])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == [["rule one", "rule two"]]


def test_cloned_toolkit_and_its_rehydrated_members_are_one_toolkit():
    """deep_copy clones the Toolkit list entry while the rehydrated members keep
    the live one. Grouping by object identity would see two toolkits here and
    emit the guidance twice."""
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])
    mixed = [toolkit] + _rehydrate(registry, toolkit)

    copied = Agent(tools=mixed).deep_copy()
    # The premise: the copy really did split the object.
    assert copied.tools[0] is not toolkit
    assert copied.tools[1].source_toolkit is toolkit

    parse_tools(agent=copied, tools=copied.tools, model=_mock_model())
    assert copied._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]
