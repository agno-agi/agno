"""Per-run tool parsing derives each tool's schema once and hands every run an
isolated Function copy.

These tests pin the two properties the derivation cache could break: nothing
one run writes into its Function copies (run context, media, user input) can
reach another run's copies, and edits to the agent's tools or to the source
Functions between runs still change what the model sees.
"""

import asyncio

import pytest

from agno.agent import Agent
from agno.agent._tools import determine_tools_for_model, parse_tools
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput
from agno.session.agent import AgentSession
from agno.tools.decorator import tool
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


class MockModel(Model):
    """Offline model returning a canned response; sleeps in async so two runs overlap."""

    def __init__(self):
        super().__init__(id="mock", name="mock", provider="mock")
        self._mock_response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._mock_response

    async def ainvoke(self, *args, **kwargs):
        await asyncio.sleep(0.02)
        return self._mock_response

    def invoke_stream(self, *args, **kwargs):
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._mock_response

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def looker(query: str, images=None, run_context=None) -> str:
    """Look something up.

    Args:
        query: What to look for.
    """
    return query


def adder(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return a + b


def _run_args(run_id: str, session_id: str, user_id: str, images=None):
    run_response = RunOutput(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        input=RunInput(input_content="hi", images=images),
    )
    run_context = RunContext(run_id=run_id, session_id=session_id, user_id=user_id)
    session = AgentSession(session_id=session_id, user_id=user_id)
    return run_response, run_context, session


def test_runs_do_not_share_run_context_or_media():
    """Two sequential runs on one agent: each run's Functions carry that run's
    context and media, and the first run's copies are untouched by the second."""
    model = MockModel()
    agent = Agent(model=model, tools=[looker, adder], telemetry=False)

    image_one = Image(url="http://example.com/one.png")
    image_two = Image(url="http://example.com/two.png")

    response_one, context_one, session_one = _run_args("r1", "s1", "user-one", images=[image_one])
    functions_one = determine_tools_for_model(
        agent, model, agent.tools, run_response=response_one, run_context=context_one, session=session_one
    )

    response_two, context_two, session_two = _run_args("r2", "s2", "user-two", images=[image_two])
    functions_two = determine_tools_for_model(
        agent, model, agent.tools, run_response=response_two, run_context=context_two, session=session_two
    )

    assert {f.name for f in functions_one} == {"looker", "adder"}
    assert {f.name for f in functions_two} == {"looker", "adder"}

    # Distinct Function instances per run: sharing one instance is exactly the
    # bug that would let run two's context overwrite run one's.
    shared = {id(f) for f in functions_one} & {id(f) for f in functions_two}
    assert shared == set()

    # After run two was prepared, run one's copies still hold run one's state.
    for function in functions_one:
        assert function._run_context is context_one
        assert function._images == [image_one]
    for function in functions_two:
        assert function._run_context is context_two
        assert function._images == [image_two]


def test_run_context_does_not_leak_between_users_and_sessions():
    """The run context handed to a tool identifies the caller; a stale one from
    a previous run would hand one user's identity to another."""
    model = MockModel()
    agent = Agent(model=model, tools=[adder], telemetry=False)

    for user_id, session_id in [("alice", "s-a"), ("bob", "s-b"), ("alice", "s-c")]:
        response, context, session = _run_args(f"r-{session_id}", session_id, user_id)
        functions = determine_tools_for_model(
            agent, model, agent.tools, run_response=response, run_context=context, session=session
        )
        assert functions[0]._run_context.user_id == user_id
        assert functions[0]._run_context.session_id == session_id


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_cross_contaminate(monkeypatch):
    """Two arun() calls in flight on one agent at the same time: each run's
    Functions must carry that run's own context and media."""
    from agno.agent import _tools as agent_tools_module

    captured = []
    real_determine = agent_tools_module.determine_tools_for_model

    def capturing_determine(agent, model, processed_tools, run_response, run_context, session, async_mode=False):
        functions = real_determine(
            agent, model, processed_tools, run_response, run_context, session, async_mode=async_mode
        )
        captured.append((run_context, functions))
        return functions

    monkeypatch.setattr(agent_tools_module, "determine_tools_for_model", capturing_determine)

    agent = Agent(model=MockModel(), tools=[looker, adder], telemetry=False)
    image_one = Image(url="http://example.com/one.png")
    image_two = Image(url="http://example.com/two.png")

    await asyncio.gather(
        agent.arun("hi", session_id="s1", user_id="user-one", images=[image_one]),
        agent.arun("hi", session_id="s2", user_id="user-two", images=[image_two]),
    )

    assert len(captured) == 2
    expected_images = {"user-one": [image_one], "user-two": [image_two]}
    seen_users = set()
    for run_context, functions in captured:
        seen_users.add(run_context.user_id)
        for function in functions:
            # Each copy still holds its own run's identity and media after
            # both runs finished; a shared instance would hold the loser's.
            assert function._run_context is run_context
            assert function._images == expected_images[run_context.user_id]
    assert seen_users == {"user-one", "user-two"}

    instances_one = {id(f) for f in captured[0][1]}
    instances_two = {id(f) for f in captured[1][1]}
    assert instances_one & instances_two == set()


def test_mutating_agent_tools_between_runs_changes_the_model_tools():
    model = MockModel()
    agent = Agent(model=model, tools=[adder], telemetry=False)

    response, context, session = _run_args("r1", "s1", "u1")
    names = {f.name for f in determine_tools_for_model(agent, model, agent.tools, response, context, session)}
    assert names == {"adder"}

    agent.tools.append(looker)
    response, context, session = _run_args("r2", "s1", "u1")
    names = {f.name for f in determine_tools_for_model(agent, model, agent.tools, response, context, session)}
    assert names == {"adder", "looker"}

    agent.tools = [looker]
    response, context, session = _run_args("r3", "s1", "u1")
    names = {f.name for f in determine_tools_for_model(agent, model, agent.tools, response, context, session)}
    assert names == {"looker"}


def test_from_callable_returns_isolated_copies():
    first = Function.from_callable(adder)
    second = Function.from_callable(adder)

    assert first is not second
    assert first.parameters is not second.parameters
    assert first.parameters == second.parameters

    # A caller may mutate its copy freely without poisoning later copies.
    first.parameters["properties"]["a"]["description"] = "mutated"
    first.description = "mutated"
    third = Function.from_callable(adder)
    assert third.parameters["properties"]["a"].get("description") != "mutated"
    assert third.description != "mutated"


def test_from_callable_keys_on_name_and_strict():
    plain = Function.from_callable(adder)
    renamed = Function.from_callable(adder, name="other_adder")
    strict = Function.from_callable(adder, strict=True)

    assert plain.name == "adder"
    assert renamed.name == "other_adder"
    assert strict.parameters["required"] == ["a", "b"]
    assert strict.parameters.get("additionalProperties") is False
    assert plain.parameters.get("additionalProperties") is None


def test_distinct_callables_with_the_same_name_get_distinct_schemas():
    def make(description_a: bool):
        if description_a:

            def f(x: int) -> int:
                """Version A.

                Args:
                    x: A number.
                """
                return x
        else:

            def f(x: str, y: str) -> str:
                """Version B.

                Args:
                    x: A string.
                    y: Another string.
                """
                return x

        return f

    one = Function.from_callable(make(True))
    two = Function.from_callable(make(False))
    assert set(one.parameters["properties"]) == {"x"}
    assert set(two.parameters["properties"]) == {"x", "y"}
    assert one.description == "Version A."
    assert two.description == "Version B."


def test_source_function_edits_flow_through_between_runs():
    """The derivation is cached, but the live fields of a source Function are
    read fresh on every run."""

    @tool(instructions="first instructions")
    def guided(x: int) -> int:
        """Do a thing.

        Args:
            x: A number.
        """
        return x

    model = MockModel()
    agent = Agent(model=model, tools=[guided], telemetry=False)

    context = RunContext(run_id="r1", session_id="s1")
    parse_tools(agent, tools=agent.tools, model=model, run_context=context)
    assert agent._tool_instructions == ["first instructions"]

    guided.instructions = "second instructions"
    parse_tools(agent, tools=agent.tools, model=model, run_context=context)
    assert agent._tool_instructions == ["second instructions"]


def test_toolkit_surface_changes_between_runs_are_seen():
    class Kit(Toolkit):
        def __init__(self):
            super().__init__(name="kit", tools=[adder])

    kit = Kit()
    model = MockModel()
    agent = Agent(model=model, tools=[kit], telemetry=False)

    context = RunContext(run_id="r1", session_id="s1")
    names = {f.name for f in parse_tools(agent, tools=agent.tools, model=model, run_context=context)}
    assert names == {"adder"}

    kit.register(looker)
    names = {f.name for f in parse_tools(agent, tools=agent.tools, model=model, run_context=context)}
    assert names == {"adder", "looker"}


def test_parsed_tool_parameters_are_isolated_between_runs():
    """A run (or a user hook) may write into a parsed Function's parameters;
    the next run's schema must not carry that write."""
    kit = Toolkit(name="kit", tools=[adder])
    model = MockModel()
    agent = Agent(model=model, tools=[kit], telemetry=False)
    context = RunContext(run_id="r1", session_id="s1")

    first = parse_tools(agent, tools=agent.tools, model=model, run_context=context)[0]
    first.parameters["properties"]["a"]["description"] = "poisoned"

    second = parse_tools(agent, tools=agent.tools, model=model, run_context=context)[0]
    assert second.parameters["properties"]["a"].get("description") != "poisoned"
    assert first.parameters is not second.parameters


def test_user_input_schema_is_fresh_per_run():
    """The model layer writes the user's answers into UserInputField objects in
    place, so every parse must hand out fresh ones."""

    @tool(requires_user_input=True, user_input_fields=["a"])
    def ask(a: int, b: int) -> int:
        """Add.

        Args:
            a: First.
            b: Second.
        """
        return a + b

    model = MockModel()
    agent = Agent(model=model, tools=[ask], telemetry=False)
    context = RunContext(run_id="r1", session_id="s1")

    first = parse_tools(agent, tools=agent.tools, model=model, run_context=context)[0]
    second = parse_tools(agent, tools=agent.tools, model=model, run_context=context)[0]

    assert first.user_input_schema is not None and second.user_input_schema is not None
    first_fields = {id(field) for field in first.user_input_schema}
    second_fields = {id(field) for field in second.user_input_schema}
    assert first_fields & second_fields == set()

    # An answer written into one run's schema stays in that run.
    first.user_input_schema[0].value = 42
    assert all(field.value is None for field in second.user_input_schema)


def test_stale_per_run_state_on_a_source_function_is_not_carried():
    """Per-run copies start clean even when the source object is dirty: a
    source that somehow holds one run's context must not hand it to the next."""
    source = Function.from_callable(adder)
    source._run_context = RunContext(run_id="stale", session_id="stale")
    source._images = [Image(url="http://example.com/stale.png")]

    copied = source._per_run_copy()
    assert copied._run_context is None
    assert copied._images is None
    assert copied._agent is None and copied._team is None


def test_per_run_copies_share_the_wrapped_entrypoint_but_validate_independently():
    first = Function.from_callable(adder)
    second = Function.from_callable(adder)
    # The validate_call wrapper holds no per-call state, so sharing it across
    # runs is safe and skips pydantic schema generation on every run.
    assert first.entrypoint is second.entrypoint
    assert first.entrypoint(a=1, b=2) == 3
