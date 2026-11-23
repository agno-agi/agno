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


def test_two_toolkits_are_not_collapsed_by_the_grouping_key():
    """Grouping is by emitted guidance, so toolkits that differ in any part of
    that must stay separate. Without this, one key for everything still passes
    the single-toolkit tests."""

    def a_tool() -> str:
        return "a"

    def b_tool() -> str:
        return "b"

    # Different names, different guidance: two blocks.
    first = Toolkit(name="first", tools=[a_tool], instructions="first-rule", add_instructions=True)
    second = Toolkit(name="second", tools=[b_tool], instructions="second-rule", add_instructions=True)
    agent = Agent(tools=[first, second])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    assert agent._tool_instructions == ["first-rule", "second-rule"]

    # Same name, different guidance: still two blocks.
    same_name_a = Toolkit(name="shared", tools=[a_tool], instructions="rule-a", add_instructions=True)
    same_name_b = Toolkit(name="shared", tools=[b_tool], instructions="rule-b", add_instructions=True)
    agent = Agent(tools=[same_name_a, same_name_b])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    assert agent._tool_instructions == ["rule-a", "rule-b"]

    # Same guidance, one opted out: only the opted-in toolkit emits.
    opted_in = Toolkit(name="shared", tools=[a_tool], instructions="rule", add_instructions=True)
    opted_out = Toolkit(name="shared", tools=[b_tool], instructions="rule", add_instructions=False)
    agent = Agent(tools=[opted_out, opted_in])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    assert agent._tool_instructions == ["rule"]


def test_toolkits_sharing_guidance_text_are_still_grouped_apart():
    """Two toolkits can carry the same guidance and still be different
    toolkits. Pooling their members would let one toolkit's functions satisfy
    the other's coverage check, so a fully-loaded toolkit loses its guidance to
    a partially-loaded neighbour."""

    def a_one() -> str:
        return "a1"

    def a_two() -> str:
        return "a2"

    def b_one() -> str:
        return "b1"

    alpha = Toolkit(name="alpha", tools=[a_one, a_two], instructions="shared-rule", add_instructions=True)
    beta = Toolkit(name="beta", tools=[b_one], instructions="shared-rule", add_instructions=True)
    registry = Registry(tools=[alpha, beta])

    # beta is complete, alpha is a subset, and alpha's member comes last.
    tools = _rehydrate(registry, beta) + _rehydrate(registry, alpha, only={"a_one"})
    agent = Agent(tools=tools)
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    # beta earns its guidance; alpha does not, and cannot borrow beta's members.
    assert agent._tool_instructions == ["shared-rule"]


def test_same_named_toolkits_do_not_pool_their_members():
    """Same name, same guidance, different functions: still two toolkits. Pooling
    them judges one toolkit's coverage against the other's function set, so a
    fully-loaded toolkit is silenced by a partially-loaded namesake."""

    def a_one() -> str:
        return "a1"

    def a_two() -> str:
        return "a2"

    def b_one() -> str:
        return "b1"

    def b_two() -> str:
        return "b2"

    first = Toolkit(name="shared", tools=[a_one, a_two], instructions="shared-rule", add_instructions=True)
    second = Toolkit(name="shared", tools=[b_one, b_two], instructions="shared-rule", add_instructions=True)
    registry = Registry(tools=[first, second])

    tools = _rehydrate(registry, first) + _rehydrate(registry, second, only={"b_one"})
    agent = Agent(tools=tools)
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    # `first` is complete and keeps its guidance; the partial `second` adds none.
    assert agent._tool_instructions == ["shared-rule"]


def test_async_only_members_are_counted_when_checking_coverage():
    """In async mode a live Toolkit contributes its async variants too, and the
    registry cannot rehydrate those. The component is genuinely short a tool, so
    the toolkit's guidance must not describe it."""

    def sync_tool() -> str:
        return "sync"

    async def async_only_tool() -> str:
        return "async"

    toolkit = Toolkit(
        name="my_toolkit",
        tools=[sync_tool, async_only_tool],
        instructions="toolkit-level-rule",
        add_instructions=True,
    )
    registry = Registry(tools=[toolkit])
    rehydrated = _rehydrate(registry, toolkit)
    assert [tool.name for tool in rehydrated] == ["sync_tool"]

    agent = Agent(tools=list(rehydrated))
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    assert agent._tool_instructions == ["toolkit-level-rule"]

    agent = Agent(tools=list(rehydrated))
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model(), async_mode=True)
    assert agent._tool_instructions == []


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


def test_duplicate_last_member_still_emits_toolkit_guidance():
    """Guidance is emitted at the toolkit's last list position. When that
    position holds a duplicate-named member, the duplicate is skipped as a
    tool but the position still owes the toolkit its guidance."""
    toolkit = _guided_toolkit()
    registry = Registry(tools=[toolkit])
    rehydrated = _rehydrate(registry, toolkit)
    second_again = registry.rehydrate_functions([rehydrated[1].to_dict() | {"toolkit": toolkit.name}])

    agent = Agent(tools=rehydrated + second_again)
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["first-rule", "second-rule", "toolkit-level-rule"]


def test_junk_source_toolkit_is_ignored():
    """source_toolkit is typed Any and travels through copies; a value that is
    not a live Toolkit must not crash collection or fabricate guidance."""

    def lone_tool() -> str:
        return "lone"

    function = Function.from_callable(lone_tool)
    function.source_toolkit = "junk"

    agent = Agent(tools=[function])
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == []


def test_swapped_sync_async_surfaces_are_not_pooled():
    """Coverage is measured per mode, so the sync and async surfaces are
    separate parts of the grouping key. Two same-named toolkits whose surfaces
    agree only as a union would otherwise pool their members, and a complete
    toolkit's guidance would be judged against -- and silenced by -- its
    namesake's function set."""

    def make_first() -> Toolkit:
        def a() -> str:
            return "a"

        def b() -> str:
            return "b"

        async def c() -> str:
            return "c"

        async def d() -> str:
            return "d"

        return Toolkit(name="shared", tools=[a, b, c, d], instructions="rule", add_instructions=True)

    def make_second() -> Toolkit:
        def c() -> str:
            return "c"

        def d() -> str:
            return "d"

        async def a() -> str:
            return "a"

        async def b() -> str:
            return "b"

        return Toolkit(name="shared", tools=[c, d, a, b], instructions="rule", add_instructions=True)

    first, second = make_first(), make_second()
    registry = Registry(tools=[first, second])

    # All of first, plus one member of second: first earned the guidance.
    tools = _rehydrate(registry, first) + _rehydrate(registry, second, only={"c"})
    agent = Agent(tools=tools)
    parse_tools(agent=agent, tools=agent.tools, model=_mock_model())

    assert agent._tool_instructions == ["rule"]


def test_user_input_does_not_leak_between_runs_of_a_rehydrated_agent():
    """parse_tools hands the model a per-run copy of each Function, and the
    model layer writes the user's answer into that copy's user_input_schema in
    place. The copy must not alias the loaded component's schema, or one run's
    input reappears in the next run -- and nothing purges it in between."""

    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email."""
        return "sent"

    live = Function.from_callable(send_email)
    live.requires_user_input = True
    live.user_input_fields = ["body"]
    live.process_entrypoint()
    live.skip_entrypoint_processing = True

    registry = Registry(tools=[live])
    agent = Agent(tools=registry.rehydrate_functions([live.to_dict()]))

    first_run = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    first_fn = next(f for f in first_run if isinstance(f, Function))
    assert first_fn.user_input_schema
    for input_field in first_fn.user_input_schema:
        input_field.value = "secret-from-run-1"

    second_run = parse_tools(agent=agent, tools=agent.tools, model=_mock_model())
    second_fn = next(f for f in second_run if isinstance(f, Function))
    assert second_fn.user_input_schema
    assert all(input_field.value is None for input_field in second_fn.user_input_schema)
    assert all(input_field.value is None for input_field in live.user_input_schema or [])


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
