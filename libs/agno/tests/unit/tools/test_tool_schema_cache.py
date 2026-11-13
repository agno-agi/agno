"""Per-run tool parsing derives each tool's schema once and hands every run an
isolated Function copy.

These tests pin the two properties the derivation cache could break: nothing
one run writes into its Function copies (run context, media, user input) can
reach another run's copies, and edits to the agent's tools or to the source
Functions between runs still change what the model sees.
"""

import asyncio
from functools import partial, wraps

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


def test_per_run_closures_are_not_pinned_by_the_caches():
    """A tool built from a closure (per-run factory products close over the
    run's output, session and agent) must not be retained by the caches: a
    bounded cache of dead closures would still pin hundreds of run graphs."""
    import gc
    import weakref

    def make():
        state = {"who": "run-scoped"}

        def dynamic_tool(a: int) -> int:
            """Add.

            Args:
                a: A number.
            """
            return a + len(state)

        return dynamic_tool

    dynamic = make()
    parsed = Function.from_callable(dynamic)
    parsed.process_entrypoint()
    assert "a" in parsed.parameters["properties"]
    assert parsed.entrypoint is not None and parsed.entrypoint(a=1) == 2

    finalizer = weakref.ref(dynamic)
    del dynamic, parsed
    gc.collect()
    assert finalizer() is None


def test_transient_introspection_failure_heals_on_the_next_run():
    """A derivation that fails is replayed, never frozen: a forward reference
    defined after the tool (notebook cell order, late class registration) must
    yield the real schema on the next parse, as it did before the caches."""

    def eventually(agent, a: "DefinedLater") -> int:  # type: ignore[name-defined] # noqa: F821
        """Count.

        Args:
            a: A number.
        """
        return 1

    first = Function.from_callable(eventually)
    assert first.parameters["properties"] == {}

    globals()["DefinedLater"] = int
    try:
        second = Function.from_callable(eventually)
        assert "a" in second.parameters["properties"]

        # The process_entrypoint path heals the same way.
        manual = Function(name="eventually", entrypoint=eventually)
        manual.process_entrypoint()
        assert "a" in manual.parameters["properties"]
        assert "a" not in (manual._framework_params or set())
    finally:
        del globals()["DefinedLater"]


def test_closure_tools_still_parse_and_run_with_lifetime_cache():
    def make(suffix: str):
        def lookup(query: str) -> str:
            """Look something up.

            Args:
                query: What to look for.
            """
            return query + suffix

        return lookup

    model = MockModel()
    agent = Agent(model=model, tools=[make("-one")], telemetry=False)
    response, context, session = _run_args("r1", "s1", "u1")
    functions = determine_tools_for_model(agent, model, agent.tools, response, context, session)
    assert functions[0].name == "lookup"
    assert functions[0].entrypoint(query="q") == "q-one"
    assert functions[0]._run_context is context


def test_wrapper_closing_over_state_is_not_cached_through_its_wrapped_base():
    """A @wraps wrapper that captures per-run state must not be judged stable
    through the closure-free function it forwards to.

    functools.wraps sets __wrapped__, so a walk that only tests the object it
    ends on reads such a wrapper as a plain module function and caches it,
    pinning whatever the wrapper captured until eviction. The capture is on the
    wrapper itself, which the walk passes through, so every link is tested."""
    import gc
    import weakref

    from agno.tools.function import _cache_stable

    def base(query: str) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "base"

    class RunState:
        pass

    def make(state):
        @wraps(base)
        def per_run(*args, **kwargs):
            return f"ran-{type(state).__name__}"

        return per_run

    state = RunState()
    per_run = make(state)

    # The base it forwards to is stable; the wrapper carrying state is not.
    assert _cache_stable(base) is True
    assert _cache_stable(per_run) is False

    parsed = Function.from_callable(per_run, name="per_run")
    assert "query" in parsed.parameters["properties"]
    assert parsed.entrypoint is not None and parsed.entrypoint(query="q") == "ran-RunState"

    finalizer = weakref.ref(state)
    del state, per_run, parsed
    gc.collect()
    assert finalizer() is None


def test_wrapper_with_a_stateful_callable_cell_is_not_cached():
    """A callable closure cell can hide another closure's run state even when
    the outer wrapper does not publish a __wrapped__ link."""
    import gc
    import weakref

    from agno.tools.function import _cache_stable

    class RunState:
        pass

    def make(state):
        def inner(query: str) -> str:
            return f"{query}-{type(state).__name__}"

        def outer(query: str) -> str:
            return inner(query)

        return outer

    state = RunState()
    dynamic = make(state)
    assert _cache_stable(dynamic) is False

    parsed = Function.from_callable(dynamic)
    assert parsed.entrypoint is not None and parsed.entrypoint(query="q") == "q-RunState"

    finalizer = weakref.ref(state)
    del state, dynamic, parsed
    gc.collect()
    assert finalizer() is None


def test_toolkit_bound_methods_reuse_lifetime_scoped_introspection(monkeypatch):
    """Toolkit methods are the common tool shape and must keep the cache win.

    Their cache belongs to the toolkit rather than the module: repeated runs
    reuse schema derivation and the validation wrapper, while dropping the
    toolkit can still drop the whole cache.
    """
    import copy

    import agno.tools.function as function_module
    from agno.tools.calculator import CalculatorTools

    derivations = 0
    derive_entrypoint_schema = function_module._derive_entrypoint_schema

    def counted_derivation(*args, **kwargs):
        nonlocal derivations
        derivations += 1
        return derive_entrypoint_schema(*args, **kwargs)

    monkeypatch.setattr(function_module, "_derive_entrypoint_schema", counted_derivation)

    kit = CalculatorTools()
    agent = Agent(model=MockModel(), tools=[kit], telemetry=False)
    first = parse_tools(agent, agent.tools, agent.model)
    second = parse_tools(agent, agent.tools, agent.model)

    assert derivations == len(kit.functions)
    assert all(left.entrypoint is right.entrypoint for left, right in zip(first, second))

    # Copying a toolkit must not copy a validation wrapper still bound to the
    # original owner. The copied toolkit builds and then reuses its own cache.
    copied_kit = copy.deepcopy(kit)
    copied_agent = Agent(model=MockModel(), tools=[copied_kit], telemetry=False)
    copied_first = parse_tools(copied_agent, copied_agent.tools, copied_agent.model)
    copied_second = parse_tools(copied_agent, copied_agent.tools, copied_agent.model)
    assert derivations == len(kit.functions) + len(copied_kit.functions)
    assert all(left.entrypoint is right.entrypoint for left, right in zip(copied_first, copied_second))
    assert all(left.entrypoint is not right.entrypoint for left, right in zip(first, copied_first))


def test_per_run_bound_methods_are_not_pinned_when_callable_caching_is_disabled():
    """A callable-tools factory may return a fresh stateful handler method on
    every run. The introspection caches must respect cache_callables=False and
    not become a second, implicit owner of those handlers."""
    import gc
    import weakref

    from agno.tools.function import _cache_stable, _clear_tool_introspection_caches
    from agno.utils.callables import resolve_callable_tools

    class Handler:
        def lookup(self, query: str) -> str:
            return query

    handlers = []

    def tools_factory():
        handler = Handler()
        handlers.append(weakref.ref(handler))
        return [handler.lookup]

    _clear_tool_introspection_caches()
    agent = Agent(model=MockModel(), tools=tools_factory, cache_callables=False, telemetry=False)
    try:
        for index in range(3):
            context = RunContext(run_id=f"r{index}", session_id=f"s{index}")
            resolve_callable_tools(agent, context)
            assert context.tools is not None
            assert _cache_stable(context.tools[0]) is False
            parsed = parse_tools(agent, context.tools, agent.model, context)
            assert parsed[0].entrypoint is not None
            assert parsed[0].entrypoint(query="q") == "q"

        del context, parsed
        gc.collect()
        assert all(reference() is None for reference in handlers)
    finally:
        _clear_tool_introspection_caches()


def test_long_lived_owner_evicts_dynamic_bound_method_caches():
    """A persistent owner may bind a fresh closure on every run. Its method
    cache must stay bounded and release state from evicted functions."""
    import gc
    import types
    import weakref

    from agno.tools.function import _LIFETIME_CACHE_ATTRIBUTE, _LIFETIME_OWNER_CACHE_SIZE

    class Owner:
        pass

    class RunState:
        def __init__(self, index: int):
            self.index = index

    def bind(owner, state):
        def lookup(self, query: str) -> str:
            return f"{query}-{state.index}"

        return types.MethodType(lookup, owner)

    owner = Owner()
    references = []
    overflow = 3
    for index in range(_LIFETIME_OWNER_CACHE_SIZE + overflow):
        state = RunState(index)
        bound = bind(owner, state)
        references.append(weakref.ref(state))
        parsed = Function.from_callable(bound)
        assert parsed.entrypoint is not None and parsed.entrypoint(query="q") == f"q-{index}"

    del state, bound, parsed
    gc.collect()

    store = getattr(owner, _LIFETIME_CACHE_ATTRIBUTE)
    assert len(store.entries) == _LIFETIME_OWNER_CACHE_SIZE
    assert all(reference() is None for reference in references[:overflow])
    assert all(reference() is not None for reference in references[overflow:])

    del owner, store
    gc.collect()
    assert all(reference() is None for reference in references)


def test_wrappers_over_one_base_keep_their_own_identities():
    """Two per-run wrappers sharing a __wrapped__ base must each dispatch to
    themselves; a cache keyed past the wrapper would serve one for the other."""

    def base(query: str) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "base"

    def make(tag: str):
        @wraps(base)
        def per_run(*args, **kwargs):
            return f"ran-{tag}"

        return per_run

    first = Function.from_callable(make("one"), name="per_run")
    second = Function.from_callable(make("two"), name="per_run")

    assert first.entrypoint is not None and first.entrypoint(query="q") == "ran-one"
    assert second.entrypoint is not None and second.entrypoint(query="q") == "ran-two"


def test_partial_binding_run_state_is_not_cached():
    """A partial is the other way a factory pins a run's objects. Bound
    arguments are captured state even when the underlying function is a
    closure-free module function."""
    import gc
    import weakref

    from agno.tools.function import _cache_stable

    class RunState:
        pass

    def lookup(query: str, state: object = None) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "ok"

    state = RunState()
    bound = partial(lookup, state=state)

    assert _cache_stable(partial(lookup)) is True
    assert _cache_stable(bound) is False

    finalizer = weakref.ref(state)
    del state, bound
    gc.collect()
    assert finalizer() is None


def test_decorator_wrappers_over_long_lived_functions_still_cache():
    """The gate must not reject ordinary decorators. @tool wraps the decorated
    function in a wrapper that closes over it, and pydantic's validate_call
    adds further callable-holding cells; those captures live as long as the
    tool, so rejecting them would drop the framework's most common tool shape
    out of the caches and undo the derivation saving for it."""
    from agno.tools.function import _cache_stable

    def plain(query: str) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "ok"

    @tool
    def decorated(query: str) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "ok"

    assert _cache_stable(plain) is True
    assert decorated.entrypoint is not None
    assert _cache_stable(decorated.entrypoint) is True

    class Kit(Toolkit):
        def lookup(self, query: str) -> str:
            """Look something up.

            Args:
                query: What to look for.
            """
            return "ok"

    # An instance-bound method can also come from a per-run callable factory;
    # without provenance proving otherwise, it must not enter the global
    # cache. It still gets the owner-lifetime cache exercised above.
    assert _cache_stable(Kit(name="kit").lookup) is False


def test_cache_walk_depth_is_bounded_and_fails_closed():
    """A wrapper chain longer than the walk cap is unresolved, so it must be
    treated as unsafe rather than assumed closure-free past the cap."""
    from agno.tools.function import _WRAPPED_WALK_CAP, _cache_stable

    def base(query: str) -> str:
        """Look something up.

        Args:
            query: What to look for.
        """
        return "ok"

    def add_layer(inner):
        # A cell holding a callable, so the layer itself stays "stable"; only
        # the chain's depth decides the outcome here. (Nesting partials would
        # not work: CPython flattens partial(partial(f)) into one object.)
        @wraps(inner)
        def layer(*args, **kwargs):
            return inner(*args, **kwargs)

        return layer

    shallow = base
    for _ in range(_WRAPPED_WALK_CAP - 2):
        shallow = add_layer(shallow)
    assert _cache_stable(shallow) is True

    deep = base
    for _ in range(_WRAPPED_WALK_CAP + 2):
        deep = add_layer(deep)
    assert _cache_stable(deep) is False
