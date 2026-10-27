import asyncio
import threading

import pytest

from agno.agent import Agent
from agno.agent._tools import determine_tools_for_model
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tools.function import Function, FunctionCall
from agno.tools.toolkit import Toolkit


def prepare_tools(agent, processed_tools, session_id, async_mode=True):
    return determine_tools_for_model(
        agent=agent,
        model=agent.model,
        processed_tools=processed_tools,
        run_response=RunOutput(run_id=session_id, session_id=session_id),
        run_context=RunContext(run_id=session_id, session_id=session_id),
        session=AgentSession(session_id=session_id),
        async_mode=async_mode,
    )


def prepare(agent, loader, session_id):
    return prepare_tools(agent, [loader], session_id)


def names(tools):
    return [tool.name for tool in tools if isinstance(tool, Function)]


def named_tool(name, value):
    def tool():
        return value

    tool.__name__ = name
    return tool


def tool_source(style, name, value):
    entrypoint = named_tool(name, value)
    if style == "callable":
        return entrypoint
    if style == "function":
        return Function(name=name, entrypoint=entrypoint)
    if style == "toolkit":
        return Toolkit(name=f"{name}_toolkit", tools=[entrypoint])
    raise AssertionError(f"unknown tool source style: {style}")


def configured_entrypoints(agent, name):
    entrypoints = []
    for tool in agent.tools:
        if isinstance(tool, Function) and tool.name == name:
            entrypoints.append(tool.entrypoint)
        elif isinstance(tool, Toolkit):
            for functions in (tool.functions, tool.async_functions):
                if name in functions:
                    entrypoints.append(functions[name].entrypoint)
        elif callable(tool) and getattr(tool, "__name__", None) == name:
            entrypoints.append(tool)
    return entrypoints


def assert_same_tools(actual, expected):
    assert len(actual) == len(expected)
    assert all(current is original for current, original in zip(actual, expected))


@pytest.mark.parametrize("registered_style", ["callable", "function", "toolkit"])
@pytest.mark.parametrize("attempted_style", ["callable", "function", "toolkit"])
def test_cross_run_dynamic_tool_name_collision_fails_before_registry_or_config_mutation(
    registered_style, attempted_style
):
    registered_tool = tool_source(registered_style, "late", "from-a")
    attempted_tool = tool_source(attempted_style, "late", "from-b")

    def load_a(run_context: RunContext):
        agent.add_tool(registered_tool)
        return f"loaded:{run_context.session_id}"

    def load_b(run_context: RunContext):
        agent.add_tool(attempted_tool)
        return f"loaded:{run_context.session_id}"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_a, load_b], telemetry=False)
    registry_a = prepare(agent, load_a, "run-a")
    registry_b = prepare(agent, load_b, "run-b")
    registry_b_before = names(registry_b)

    loaded_a = FunctionCall(function=registry_a[0], arguments={}).execute()
    assert loaded_a.status == "success"
    assert names(registry_a).count("late") == 1
    assert "late" not in names(registry_b)
    assert [entrypoint() for entrypoint in configured_entrypoints(agent, "late")] == ["from-a"]
    configuration_after_a = list(agent.tools)

    loaded_b = FunctionCall(function=registry_b[0], arguments={}).execute()

    assert loaded_b.status == "failure"
    assert names(registry_b) == registry_b_before
    assert_same_tools(agent.tools, configuration_after_a)
    assert [entrypoint() for entrypoint in configured_entrypoints(agent, "late")] == ["from-a"]

    rebuilt_b = prepare_tools(agent, list(agent.tools), "run-b-rebuilt")
    rebuilt_late = [tool for tool in rebuilt_b if isinstance(tool, Function) and tool.name == "late"]
    assert len(rebuilt_late) == 1
    assert rebuilt_late[0].entrypoint() == "from-a"


@pytest.mark.parametrize("collision_source", ["configured", "run_local"], ids=["agent-config", "run-local-native"])
def test_mixed_toolkit_name_collision_does_not_partially_register(collision_source):
    registered_tool = named_tool("late", "from-a")
    native_tool = named_tool("late", "native")
    fresh_tool = named_tool("fresh", "from-b")
    collision_tool = named_tool("late", "from-b")
    mixed_toolkit = Toolkit(name="mixed_dynamic_tools", tools=[fresh_tool, collision_tool])

    def load_a(run_context: RunContext):
        agent.add_tool(registered_tool)
        return f"loaded:{run_context.session_id}"

    def load_b(run_context: RunContext):
        agent.add_tool(mixed_toolkit)
        return f"loaded:{run_context.session_id}"

    if collision_source == "configured":
        agent = Agent(model=OpenAIResponses(id="test"), tools=[load_a, load_b], telemetry=False)
        registry_a = prepare(agent, load_a, "run-a")
        registry_b = prepare(agent, load_b, "run-b")
        assert FunctionCall(function=registry_a[0], arguments={}).execute().status == "success"
        rebuild_tools = list(agent.tools)
        expected_late = "from-a"
    else:
        agent = Agent(model=OpenAIResponses(id="test"), tools=[load_b], telemetry=False)
        registry_b = prepare_tools(agent, [load_b, native_tool], "run-b")
        rebuild_tools = [*agent.tools, native_tool]
        expected_late = "native"
    registry_b_before = names(registry_b)

    configuration_after_a = list(agent.tools)
    loaded_b = FunctionCall(function=registry_b[0], arguments={}).execute()

    assert loaded_b.status == "failure"
    assert names(registry_b) == registry_b_before
    if collision_source == "configured":
        assert "late" not in names(registry_b)
        expected_configured = ["from-a"]
    else:
        assert names(registry_b).count("late") == 1
        native_binding = next(tool for tool in registry_b if isinstance(tool, Function) and tool.name == "late")
        assert native_binding.entrypoint() == expected_late
        expected_configured = []
    assert "fresh" not in names(registry_b)
    assert_same_tools(agent.tools, configuration_after_a)
    assert [entrypoint() for entrypoint in configured_entrypoints(agent, "late")] == expected_configured
    assert configured_entrypoints(agent, "fresh") == []

    rebuilt_b = prepare_tools(agent, rebuild_tools, "run-b-rebuilt")
    rebuilt_names = names(rebuilt_b)
    assert rebuilt_names.count("late") == 1
    rebuilt_late = next(tool for tool in rebuilt_b if isinstance(tool, Function) and tool.name == "late")
    assert rebuilt_late.entrypoint() == expected_late
    assert "fresh" not in rebuilt_names


def test_run_local_native_tool_duplicate_is_noop_and_not_persisted_on_rebuild():
    native_tool = named_tool("late", "native")
    dynamic_shadow = named_tool("late", "dynamic")

    def load_shadow(run_context: RunContext):
        agent.add_tool(dynamic_shadow)
        return f"loaded:{run_context.session_id}"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_shadow], telemetry=False)
    registry = prepare_tools(agent, [load_shadow, native_tool], "run-native")
    initial_configuration = list(agent.tools)

    loaded = FunctionCall(function=registry[0], arguments={}).execute()

    assert loaded.status == "success"
    assert names(registry).count("late") == 1
    native_binding = next(tool for tool in registry if isinstance(tool, Function) and tool.name == "late")
    assert native_binding.entrypoint() == "native"
    assert_same_tools(agent.tools, initial_configuration)
    assert configured_entrypoints(agent, "late") == []

    continued_registry = prepare_tools(agent, [*agent.tools, native_tool], "run-native-continued")
    continued_binding = next(tool for tool in continued_registry if isinstance(tool, Function) and tool.name == "late")
    assert continued_binding.entrypoint() == "native"


def test_addition_targets_originating_execution_registry():
    def late_tool():
        return "late"

    def activate(agent: Agent):
        agent.add_tool(late_tool)
        return "activated"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    first = prepare(agent, activate, "first")
    second = prepare(agent, activate, "second")

    result = FunctionCall(function=first[0], arguments={}).execute()

    assert result.status == "success"
    assert names(first) == ["activate", "late_tool"]
    assert names(second) == ["activate"]
    # add_tool still changes persistent Agent configuration for later runs.
    assert late_tool in agent.tools


def test_configuration_update_outside_tool_does_not_mutate_an_old_registry():
    def activate():
        return "activated"

    def later_configuration():
        return "later"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    old_registry = prepare(agent, activate, "first")

    agent.add_tool(later_configuration)

    assert names(old_registry) == ["activate"]
    assert later_configuration in agent.tools


@pytest.mark.parametrize("async_generator", [False, True])
async def test_lazy_tool_result_renews_context_without_leaking_to_consumer(async_generator):
    def late_tool():
        return "late"

    def consumer_tool():
        return "consumer"

    def activate(run_context: RunContext):
        yield "first"
        agent.add_tool(late_tool)
        yield "second"

    async def async_activate(run_context: RunContext):
        yield "first"
        agent.add_tool(late_tool)
        yield "second"

    loader = async_activate if async_generator else activate
    agent = Agent(model=OpenAIResponses(id="test"), tools=[loader], telemetry=False)
    originating = prepare(agent, loader, "first")
    competing = prepare(agent, loader, "second")
    call = FunctionCall(function=originating[0], arguments={})
    result = await call.aexecute()
    iterator = result.result

    if async_generator:
        assert await iterator.__anext__() == "first"
    else:
        assert next(iterator) == "first"

    agent.add_tool(consumer_tool)
    assert "consumer_tool" not in names(originating)
    assert "consumer_tool" not in names(competing)

    if async_generator:
        assert await iterator.__anext__() == "second"
        await iterator.aclose()
    else:
        assert next(iterator) == "second"
        iterator.close()

    assert "late_tool" in names(originating)
    assert "late_tool" not in names(competing)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_iterator", [False, True], ids=["iterator", "async-iterator"])
@pytest.mark.parametrize("allowed", [False, True], ids=["denied", "allowed"])
async def test_dynamic_wrapper_preserves_authorization_for_lazy_advance_and_close(async_iterator, allowed):
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider
    from agno.run.authorization import RunAuthorization, authorization_scope, current_authorization, require_permission

    observed = []

    def late_tool():
        return "late"

    class ResultIterator:
        def __init__(self):
            self.returned = False

        def __iter__(self):
            return self

        def __next__(self):
            observed.append(("advance", current_authorization()))
            require_permission("registry", "read")
            if self.returned:
                raise StopIteration
            self.returned = True
            agent.add_tool(late_tool)
            return "first"

        def close(self):
            observed.append(("close", current_authorization()))
            require_permission("registry", "read")

    class AsyncResultIterator:
        def __init__(self):
            self.returned = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            observed.append(("advance", current_authorization()))
            require_permission("registry", "read")
            if self.returned:
                raise StopAsyncIteration
            self.returned = True
            agent.add_tool(late_tool)
            return "first"

        async def aclose(self):
            observed.append(("close", current_authorization()))
            require_permission("registry", "read")

    def load_lazy_result(run_context: RunContext):
        return AsyncResultIterator() if async_iterator else ResultIterator()

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_lazy_result], telemetry=False)
    registry = prepare(agent, load_lazy_result, "authorized-lazy-result")
    caller = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(
            principal_id="alice",
            scopes=["registry:read"] if allowed else [],
            claims={"sub": "alice"},
        ),
    )
    with authorization_scope(lambda: caller):
        outcome = await FunctionCall(function=registry[0], arguments={}).aexecute()

    if allowed:
        if async_iterator:
            assert await outcome.result.__anext__() == "first"
            await outcome.result.aclose()
        else:
            assert next(outcome.result) == "first"
            outcome.result.close()
        assert "late_tool" in names(registry)
    else:
        with pytest.raises(PermissionError, match="registry:read"):
            if async_iterator:
                await outcome.result.__anext__()
            else:
                next(outcome.result)
        assert "late_tool" not in names(registry)

    assert {operation for operation, _ in observed} == {"advance", "close"}
    assert all(authority is caller for _, authority in observed)
    assert current_authorization() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_iterator", [False, True], ids=["iterator", "async-iterator"])
@pytest.mark.parametrize("enforced_caller", [False, True], ids=["no-caller", "authorized-caller"])
@pytest.mark.parametrize("initial_operation", ["close", "throw", "send"])
async def test_dynamic_wrapper_closes_unstarted_iterator_with_originating_context(
    async_iterator, enforced_caller, initial_operation
):
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider
    from agno.run.authorization import RunAuthorization, authorization_scope, current_authorization, require_permission

    late_tool = named_tool("late_tool", "late")
    caller = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="alice", scopes=["registry:read"], claims={"sub": "alice"}),
    )
    observed = []
    state = {"advances": 0, "closes": 0}

    class ResourceIterator:
        def __iter__(self):
            return self

        def __next__(self):
            state["advances"] += 1
            return "unexpected"

        def close(self):
            state["closes"] += 1
            observed.append(current_authorization())
            if enforced_caller:
                require_permission("registry", "read")
            agent.add_tool(late_tool)

    class AsyncResourceIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            state["advances"] += 1
            return "unexpected"

        async def aclose(self):
            state["closes"] += 1
            observed.append(current_authorization())
            if enforced_caller:
                require_permission("registry", "read")
            agent.add_tool(late_tool)

    def load_resource(run_context: RunContext):
        return AsyncResourceIterator() if async_iterator else ResourceIterator()

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_resource], telemetry=False)
    originating = prepare(agent, load_resource, "originating-run")
    competing = prepare(agent, load_resource, "competing-run")
    if enforced_caller:
        with authorization_scope(lambda: caller):
            outcome = await FunctionCall(function=originating[0], arguments={}).aexecute()
    else:
        outcome = await FunctionCall(function=originating[0], arguments={}).aexecute()

    assert outcome.status == "success"
    assert state == {"advances": 0, "closes": 0}
    if initial_operation != "close":
        error_type = ValueError if initial_operation == "throw" else TypeError
        with pytest.raises(error_type):
            if async_iterator:
                if initial_operation == "throw":
                    await outcome.result.athrow(ValueError("stop before iteration"))
                else:
                    await outcome.result.asend("not started")
            elif initial_operation == "throw":
                outcome.result.throw(ValueError("stop before iteration"))
            else:
                outcome.result.send("not started")
    if async_iterator:
        await outcome.result.aclose()
        await outcome.result.aclose()
    else:
        outcome.result.close()
        outcome.result.close()

    assert state == {"advances": 0, "closes": 1}
    assert observed == ([caller] if enforced_caller else [None])
    assert "late_tool" in names(originating)
    assert "late_tool" not in names(competing)
    assert late_tool in agent.tools
    assert current_authorization() is None


async def test_expired_background_context_cannot_change_configuration():
    release = asyncio.Event()
    tasks = []

    def late_tool():
        return "late"

    async def activate(agent: Agent):
        async def add_after_return():
            await release.wait()
            agent.add_tool(late_tool)

        tasks.append(asyncio.create_task(add_after_return()))
        return "activated"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    registry = prepare(agent, activate, "first")
    result = await FunctionCall(function=registry[0], arguments={}).aexecute()
    assert result.status == "success"

    release.set()
    with pytest.raises(RuntimeError, match="finished"):
        await tasks[0]

    assert late_tool not in agent.tools
    assert names(registry) == ["activate"]


@pytest.mark.parametrize("async_iterator", [False, True])
async def test_custom_lazy_iterator_registers_in_originating_run(async_iterator):
    def late_tool():
        return "late"

    class ResultIterator:
        def __init__(self, agent):
            self.agent = agent
            self.index = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.index += 1
            if self.index == 1:
                return "first"
            if self.index == 2:
                self.agent.add_tool(late_tool)
                return "second"
            raise StopIteration

    class AsyncResultIterator:
        def __init__(self, agent):
            self.result = ResultIterator(agent)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.result)
            except StopIteration:
                raise StopAsyncIteration

    def activate(agent: Agent):
        return AsyncResultIterator(agent) if async_iterator else ResultIterator(agent)

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    originating = prepare(agent, activate, "first")
    competing = prepare(agent, activate, "second")
    result = await FunctionCall(function=originating[0], arguments={}).aexecute()
    iterator = result.result

    if async_iterator:
        assert await iterator.__anext__() == "first"
        assert await iterator.__anext__() == "second"
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()
    else:
        assert next(iterator) == "first"
        assert next(iterator) == "second"
        with pytest.raises(StopIteration):
            next(iterator)

    assert "late_tool" in names(originating)
    assert "late_tool" not in names(competing)


@pytest.mark.asyncio
async def test_concurrent_same_name_registrations_are_serialized_across_model_tool_calls():
    a_preparing = threading.Event()
    release_a = threading.Event()
    b_started = threading.Event()
    b_preparing = threading.Event()
    function_reads = {}

    class GatedToolkit(Toolkit):
        def get_async_functions(self):
            reads = function_reads.get(self.name, 0) + 1
            function_reads[self.name] = reads
            # The first read discovers the proposed names. The next read is
            # part of preparing the tools to add to the originating registry.
            if self.name == "first_late_toolkit" and reads == 2:
                a_preparing.set()
                if not release_a.wait(timeout=5):
                    raise TimeoutError("first dynamic tool preparation was not released")
            elif self.name == "second_late_toolkit" and reads == 2:
                b_preparing.set()
            return super().get_async_functions()

    first_toolkit = GatedToolkit(name="first_late_toolkit", tools=[named_tool("late", "from-a")])
    second_toolkit = GatedToolkit(name="second_late_toolkit", tools=[named_tool("late", "from-b")])
    # Toolkit construction may inspect its functions, so start the observable
    # counts immediately before either registration attempt.
    function_reads[first_toolkit.name] = 0
    function_reads[second_toolkit.name] = 0

    def load_a(run_context: RunContext):
        agent.add_tool(first_toolkit)
        return f"loaded:{run_context.session_id}"

    def load_b(run_context: RunContext):
        b_started.set()
        agent.add_tool(second_toolkit)
        return f"loaded:{run_context.session_id}"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_a, load_b], telemetry=False)
    registry_a = prepare(agent, load_a, "run-a")
    registry_b = prepare(agent, load_b, "run-b")
    registry_b_before = names(registry_b)
    configuration_before = list(agent.tools)

    call_a = asyncio.create_task(agent.model.arun_function_call(FunctionCall(function=registry_a[0], arguments={})))
    call_b = None
    b_entered_preparation_while_a_was_gated = False
    try:
        assert await asyncio.wait_for(asyncio.to_thread(a_preparing.wait, 3), timeout=4)
        call_b = asyncio.create_task(agent.model.arun_function_call(FunctionCall(function=registry_b[0], arguments={})))
        assert await asyncio.wait_for(asyncio.to_thread(b_started.wait, 3), timeout=4)
        b_entered_preparation_while_a_was_gated = await asyncio.wait_for(
            asyncio.to_thread(b_preparing.wait, 0.4), timeout=1
        )
    finally:
        release_a.set()
        calls = [call_a] if call_b is None else [call_a, call_b]
        results = await asyncio.wait_for(asyncio.gather(*calls, return_exceptions=True), timeout=8)

    assert len(results) == 2

    def result_summary(result):
        if isinstance(result, BaseException):
            return ("exception", type(result).__name__)
        success, _, _, execution = result
        return (success, execution.status)

    actual = (
        b_entered_preparation_while_a_was_gated,
        result_summary(results[0]),
        result_summary(results[1]),
        names(registry_a),
        names(registry_b),
        [entrypoint() for entrypoint in configured_entrypoints(agent, "late")],
        len(agent.tools),
    )
    expected = (
        False,
        (True, "success"),
        (False, "failure"),
        ["load_a", "late"],
        registry_b_before,
        ["from-a"],
        len(configuration_before) + 1,
    )
    assert actual == expected, f"same-name tool registration overlapped or changed the losing run: {actual!r}"


def test_same_agent_reentrant_dynamic_registration_is_rejected_and_released():
    function_reads = {"reentrant_late_toolkit": 0}
    reentered = False
    inner_tool = named_tool("inner_tool", "inner")
    outer_tool = named_tool("outer_tool", "outer")
    after_reentry_tool = named_tool("after_reentry_tool", "recovered")

    class ReentrantToolkit(Toolkit):
        def get_functions(self):
            nonlocal reentered
            function_reads[self.name] = function_reads.get(self.name, 0) + 1
            # The first read discovers names; reenter during preparation.
            if function_reads[self.name] == 2 and not reentered:
                reentered = True
                agent.add_tool(inner_tool)
            return super().get_functions()

    outer_toolkit = ReentrantToolkit(name="reentrant_late_toolkit", tools=[outer_tool])
    function_reads[outer_toolkit.name] = 0

    def load_outer(run_context: RunContext):
        agent.add_tool(outer_toolkit)
        return f"loaded:{run_context.session_id}"

    def load_after_reentry(run_context: RunContext):
        agent.add_tool(after_reentry_tool)
        return f"loaded:{run_context.session_id}"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[load_outer, load_after_reentry], telemetry=False)
    outer_registry = prepare_tools(agent, [load_outer], "run-outer", async_mode=False)
    recovery_registry = prepare_tools(agent, [load_after_reentry], "run-recovery", async_mode=False)
    configuration_before = list(agent.tools)

    rejected = FunctionCall(function=outer_registry[0], arguments={}).execute()

    assert rejected.status == "failure"
    assert names(outer_registry) == ["load_outer"]
    assert_same_tools(agent.tools, configuration_before)

    recovered = FunctionCall(function=recovery_registry[0], arguments={}).execute()

    assert recovered.status == "success"
    assert names(recovery_registry) == ["load_after_reentry", "after_reentry_tool"]
    assert "inner_tool" not in names(recovery_registry)
    assert_same_tools(agent.tools, [*configuration_before, after_reentry_tool])
