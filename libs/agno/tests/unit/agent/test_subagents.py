import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent, SubagentsManager
from agno.agent._subagents import DEFAULT_INSTRUCTIONS
from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, RunStatus
from agno.run.base import RunContext
from agno.run.cancel import cleanup_member_runs, get_member_run_ids
from agno.session.agent import AgentSession
from agno.tools.calculator import CalculatorTools
from agno.tools.function import Function


def make_parent(**kwargs) -> Agent:
    defaults = {"name": "Parent", "model": MagicMock(spec=Model)}
    defaults.update(kwargs)
    return Agent(**defaults)


def make_run_context(user_id=None, session_state=None) -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id=user_id, session_state=session_state)


def make_run_output(content: str = "subagent result", **kwargs) -> RunOutput:
    defaults = {"run_id": "child-run", "status": RunStatus.completed}
    defaults.update(kwargs)
    return RunOutput(content=content, **defaults)


def build_spawn_function(manager: SubagentsManager, parent: Agent, run_context=None, async_mode=False) -> Function:
    return manager.get_spawn_function(
        agent=parent,
        run_context=run_context or make_run_context(),
        async_mode=async_mode,
    )


def make_fake_child(events) -> MagicMock:
    child = MagicMock()
    child.id = "parent-subagent-fast"

    def fake_run(task, **kwargs):
        fake_run.calls.append({"task": task, **kwargs})

        def stream():
            yield from events

        return stream()

    fake_run.calls = []
    child.run = fake_run

    def fake_arun(task, **kwargs):
        fake_arun.calls.append({"task": task, **kwargs})

        async def stream():
            for event in events:
                yield event

        return stream()

    fake_arun.calls = []
    child.arun = fake_arun
    return child


async def acollect(agen) -> list:
    return [item async for item in agen]


# === Manager configuration ===


def test_manager_rejects_empty_models():
    with pytest.raises(ValueError):
        SubagentsManager(models={})


def test_single_model_becomes_default_option():
    model = MagicMock(spec=Model)
    manager = SubagentsManager(model=model)

    assert manager._models == {"default": model}
    assert manager.model is model


def test_model_and_models_are_mutually_exclusive():
    with pytest.raises(ValueError):
        SubagentsManager(model=MagicMock(spec=Model), models={"fast": MagicMock(spec=Model)})


def test_model_option_tuples_split_into_model_and_description():
    fast = MagicMock(spec=Model)
    deep = MagicMock(spec=Model)
    manager = SubagentsManager(models={"fast": fast, "deep": (deep, "complex analysis")})

    assert manager._models == {"fast": fast, "deep": deep}
    assert manager._model_descriptions == {"deep": "complex analysis"}
    # The public field keeps what the user passed
    assert manager.models == {"fast": fast, "deep": (deep, "complex analysis")}


def test_model_option_descriptions_appear_in_tool_description():
    fast = MagicMock(spec=Model)
    fast.id = "gpt-5.6-luna"
    deep = MagicMock(spec=Model)
    deep.id = "gpt-5.6-terra"
    manager = SubagentsManager(
        models={
            "fast": (fast, "quick lookups"),
            "deep": (deep, "complex analysis"),
        }
    )
    parent = make_parent()

    function = build_spawn_function(manager, parent)

    assert "fast: gpt-5.6-luna (default) - quick lookups" in function.description
    assert "deep: gpt-5.6-terra - complex analysis" in function.description


def test_models_default_to_parent_model():
    manager = SubagentsManager()
    parent = make_parent()

    models = manager._resolve_models(parent)

    assert models == {"default": parent.model}


def test_first_model_option_is_default():
    fast = MagicMock(spec=Model)
    deep = MagicMock(spec=Model)
    manager = SubagentsManager(models={"fast": fast, "deep": deep})

    selection = manager._validate_selection(model=None, tools=None, models=manager._models, allowed_tools={})

    assert selection == ("fast", [])


def test_allowed_tools_inherit_parent_tools():
    calculator = CalculatorTools()
    manager = SubagentsManager()
    parent = make_parent(tools=[calculator])

    allowed = manager._resolve_allowed_tools(parent)

    assert allowed == {"calculator": calculator}


def test_manager_tools_override_parent_tools():
    calculator = CalculatorTools()
    manager = SubagentsManager(tools=[calculator])
    parent = make_parent(tools=[])

    allowed = manager._resolve_allowed_tools(parent)

    assert allowed == {"calculator": calculator}


# === Agent(subagents=...) union field ===


def test_subagents_true_creates_default_manager():
    parent = make_parent(subagents=True)

    assert isinstance(parent.subagents_manager, SubagentsManager)
    assert parent.subagents_manager.models is None
    assert parent.subagents_manager.tools is None


def test_subagents_disabled_by_default():
    parent = make_parent()

    assert parent.subagents is None
    assert parent.subagents_manager is None


def test_subagents_false_resolves_to_none():
    parent = make_parent(subagents=False)

    assert parent.subagents_manager is None


def test_subagents_manager_instance_passes_through():
    manager = SubagentsManager()
    parent = make_parent(subagents=manager)

    assert parent.subagents_manager is manager


# === Child agent construction: fresh per spawn, no cache ===


def test_child_agent_has_distinct_id_and_no_db():
    fast = MagicMock(spec=Model)
    manager = SubagentsManager(models={"fast": fast})
    parent = make_parent()

    child = manager._build_child(parent, model_key="fast", tool_names=[], models={"fast": fast}, allowed_tools={})

    assert child.id == f"{parent.id}-subagent-fast"
    assert child.db is None
    assert child.model is fast
    assert child.subagents_manager is None


def test_children_are_built_fresh_per_spawn():
    fast = MagicMock(spec=Model)
    models = {"fast": fast}
    calculator = CalculatorTools()
    allowed = {"calculator": calculator}
    manager = SubagentsManager(models=models)
    parent = make_parent()

    first = manager._build_child(parent, "fast", ["calculator"], models, allowed)
    second = manager._build_child(parent, "fast", ["calculator"], models, allowed)

    # No caching: same selection still yields a new, independent Agent instance
    assert first is not second
    assert first.id == second.id


def test_shared_manager_builds_children_for_the_right_parent():
    fast = MagicMock(spec=Model)
    models = {"fast": fast}
    manager = SubagentsManager(models=models)
    parent_a = make_parent(name="Parent A", id="agent-a")
    parent_b = make_parent(name="Parent B", id="agent-b")

    child_a = manager._build_child(parent_a, "fast", [], models, {})
    child_b = manager._build_child(parent_b, "fast", [], models, {})

    # One manager shared by two agents never leaks children across parents
    assert child_a.id == "agent-a-subagent-fast"
    assert child_b.id == "agent-b-subagent-fast"
    assert "Parent A" in child_a.name
    assert "Parent B" in child_b.name


# === Spawn function factory ===


def test_spawn_function_description_lists_options():
    fast = MagicMock(spec=Model)
    fast.id = "gpt-5.6-luna"
    deep = MagicMock(spec=Model)
    deep.id = "gpt-5.6-terra"
    manager = SubagentsManager(models={"fast": fast, "deep": deep})
    parent = make_parent(tools=[CalculatorTools()])

    function = build_spawn_function(manager, parent)

    assert function.name == "spawn_agent"
    assert "fast: gpt-5.6-luna (default)" in function.description
    assert "deep: gpt-5.6-terra" in function.description
    assert "calculator" in function.description


def test_spawn_function_description_mentions_spawn_limit():
    manager = SubagentsManager(max_total_per_run=7)
    parent = make_parent()

    function = build_spawn_function(manager, parent)

    assert "at most 7 subagents" in function.description


def test_spawn_function_carries_parent_instructions():
    manager = SubagentsManager()
    parent = make_parent()

    function = build_spawn_function(manager, parent)

    assert function.instructions == DEFAULT_INSTRUCTIONS
    assert function.add_instructions is True


def test_spawn_function_async_mode_picks_async_entrypoint():
    manager = SubagentsManager()
    parent = make_parent()

    sync_function = build_spawn_function(manager, parent, async_mode=False)
    async_function = build_spawn_function(manager, parent, async_mode=True)

    assert sync_function.entrypoint.__name__ == "spawn_agent"
    assert async_function.entrypoint.__name__ == "aspawn_agent"


def test_spawn_function_schema_has_only_model_facing_params():
    manager = SubagentsManager()
    parent = make_parent()

    function = build_spawn_function(manager, parent)
    function.process_entrypoint()

    assert set(function.parameters["properties"].keys()) == {"task", "model", "tools"}


# === Selection errors ===


def test_unknown_model_yields_error_string():
    manager = SubagentsManager(models={"fast": MagicMock(spec=Model)})
    parent = make_parent()
    function = build_spawn_function(manager, parent)

    items = list(function.entrypoint(task="do something", model="huge"))

    assert len(items) == 1
    assert "Unknown model option 'huge'" in items[0]
    assert "fast" in items[0]


def test_unknown_tool_yields_error_string():
    manager = SubagentsManager()
    parent = make_parent(tools=[CalculatorTools()])
    function = build_spawn_function(manager, parent)

    items = list(function.entrypoint(task="do something", tools=["websearch"]))

    assert len(items) == 1
    assert "Unknown tool name(s) websearch" in items[0]
    assert "calculator" in items[0]


# === Sync spawn behavior ===


def test_sync_spawn_yields_events_tagged_for_parent():
    manager = SubagentsManager()
    parent = make_parent()
    run_context = make_run_context(user_id="ray")
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunCompletedEvent(run_id="child-run"),
        make_run_output("final answer"),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(manager, parent, run_context=run_context)
    with patch.object(manager, "_build_child", return_value=child):
        items = list(function.entrypoint(task="research topic A"))

    # Both events re-emitted with parent_run_id; RunOutput captured, not yielded;
    # content streamed so no trailing string
    assert len(items) == 2
    assert all(item.parent_run_id == "run-1" for item in items)
    assert isinstance(items[0], RunContentEvent)
    assert isinstance(items[1], RunCompletedEvent)


def test_sync_spawn_runs_child_in_parent_session():
    manager = SubagentsManager()
    parent = make_parent()
    run_context = make_run_context(user_id="ray")
    child = make_fake_child([make_run_output()])

    function = build_spawn_function(manager, parent, run_context=run_context)
    with (
        patch.object(manager, "_build_child", return_value=child),
        patch("agno.agent._subagents.register_member_run") as mock_register,
    ):
        list(function.entrypoint(task="research topic A"))

    call = child.run.calls[0]
    assert call["task"] == "research topic A"
    assert call["user_id"] == "ray"
    assert call["session_id"] == "session-1"
    assert call["stream"] is True
    assert call["stream_events"] is True
    assert call["yield_run_output"] is True
    mock_register.assert_called_once_with("run-1", call["run_id"])


def test_sync_spawn_yields_final_content_when_nothing_streamed():
    manager = SubagentsManager()
    parent = make_parent()
    child = make_fake_child([make_run_output("stored answer")])

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        items = list(function.entrypoint(task="task"))

    assert items == ["stored answer"]


def test_sync_spawn_merges_session_state_copy():
    manager = SubagentsManager()
    parent = make_parent()
    run_context = make_run_context(session_state={"count": 1})

    child = MagicMock()
    child.id = "child"

    def fake_run(task, **kwargs):
        def stream():
            kwargs["session_state"]["count"] = 2
            kwargs["session_state"]["child_key"] = "set"
            yield make_run_output()

        return stream()

    child.run = fake_run

    function = build_spawn_function(manager, parent, run_context=run_context)
    with patch.object(manager, "_build_child", return_value=child):
        list(function.entrypoint(task="task"))

    assert run_context.session_state == {"count": 2, "child_key": "set"}


def test_sync_spawn_error_status_yields_failure_string():
    manager = SubagentsManager()
    parent = make_parent()
    child = make_fake_child([make_run_output("model exploded", status=RunStatus.error)])

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        items = list(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "Subagent task failed" in items[0]
    assert "model exploded" in items[0]


def test_sync_spawn_exception_yields_failure_string():
    manager = SubagentsManager()
    parent = make_parent()

    child = MagicMock()
    child.id = "child"
    child.run = MagicMock(side_effect=RuntimeError("model exploded"))

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        items = list(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "model exploded" in items[0]


def test_sync_spawn_parent_cancel_cancels_child():
    manager = SubagentsManager()
    parent = make_parent()
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunContentEvent(content="world", run_id="child-run"),
        make_run_output(),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(manager, parent)
    with (
        patch.object(manager, "_build_child", return_value=child),
        patch("agno.agent._subagents.raise_if_cancelled", side_effect=RunCancelledException("")),
        patch("agno.agent._subagents.cancel_run") as mock_cancel,
    ):
        with pytest.raises(RunCancelledException):
            list(function.entrypoint(task="task"))

    mock_cancel.assert_called_once_with(child.run.calls[0]["run_id"])


# === Guardrails ===


def test_max_total_per_run_limits_spawns():
    manager = SubagentsManager(max_total_per_run=1)
    parent = make_parent()
    child = make_fake_child([make_run_output("first result")])

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        first = list(function.entrypoint(task="task one"))
        second = list(function.entrypoint(task="task two"))

    assert first == ["first result"]
    assert len(second) == 1
    assert "Subagent limit for this run reached (1" in second[0]
    # The second spawn never ran a child
    assert len(child.run.calls) == 1


def test_max_total_per_run_zero_disables_limit():
    manager = SubagentsManager(max_total_per_run=0)
    parent = make_parent()
    child = make_fake_child([make_run_output("result")])

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        for _ in range(3):
            list(function.entrypoint(task="task"))

    assert len(child.run.calls) == 3


def test_spawn_counter_resets_per_run():
    manager = SubagentsManager(max_total_per_run=1)
    parent = make_parent()
    child = make_fake_child([make_run_output("result")])

    with patch.object(manager, "_build_child", return_value=child):
        first_run = build_spawn_function(manager, parent)
        list(first_run.entrypoint(task="task"))
        # A new run gets a fresh spawn function and a fresh counter
        second_run = build_spawn_function(manager, parent)
        items = list(second_run.entrypoint(task="task"))

    assert items == ["result"]
    assert len(child.run.calls) == 2


def test_timeout_cancels_child_and_reports():
    manager = SubagentsManager(timeout_seconds=5)
    parent = make_parent()
    events = [
        RunContentEvent(content="partial", run_id="child-run"),
        RunContentEvent(content="never seen", run_id="child-run"),
        make_run_output(),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(manager, parent)
    with (
        patch.object(manager, "_build_child", return_value=child),
        patch("agno.agent._subagents.cancel_run") as mock_cancel,
        # First call sets the deadline (0 + 5); the check after the first event
        # sees the clock already past it
        patch("agno.agent._subagents.time.monotonic", side_effect=[0.0, 10.0, 10.0, 10.0]),
    ):
        items = list(function.entrypoint(task="slow task"))

    # First event yielded, deadline hit right after, child cancelled, rest drained
    mock_cancel.assert_called_once_with(child.run.calls[0]["run_id"])
    assert isinstance(items[0], RunContentEvent)
    assert "timed out" in items[-1]
    assert not any(isinstance(item, RunContentEvent) and item.content == "never seen" for item in items)


async def test_max_concurrent_serializes_async_spawns():
    manager = SubagentsManager(max_concurrent=1)
    parent = make_parent()
    active = {"now": 0, "peak": 0}

    child = MagicMock()
    child.id = "child"

    def fake_arun(task, **kwargs):
        async def stream():
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            await asyncio.sleep(0.005)
            yield make_run_output("done")
            active["now"] -= 1

        return stream()

    child.arun = fake_arun

    function = build_spawn_function(manager, parent, async_mode=True)
    with patch.object(manager, "_build_child", return_value=child):
        await asyncio.gather(
            acollect(function.entrypoint(task="task one")),
            acollect(function.entrypoint(task="task two")),
        )

    assert active["peak"] == 1


# === Member-run registration lifecycle ===


def test_spawn_registers_member_run_and_cleanup_empties_it():
    manager = SubagentsManager()
    parent = make_parent()
    child = make_fake_child([make_run_output()])

    function = build_spawn_function(manager, parent)
    with patch.object(manager, "_build_child", return_value=child):
        list(function.entrypoint(task="task"))

    child_run_id = child.run.calls[0]["run_id"]
    assert child_run_id in get_member_run_ids("run-1")

    # agent/_run.py calls cleanup_member_runs alongside cleanup_run at run end
    cleanup_member_runs("run-1")
    assert get_member_run_ids("run-1") == set()


# === Async spawn behavior ===


async def test_async_spawn_yields_events_tagged_for_parent():
    manager = SubagentsManager()
    parent = make_parent()
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunCompletedEvent(run_id="child-run"),
        make_run_output("final answer"),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(manager, parent, async_mode=True)
    with (
        patch.object(manager, "_build_child", return_value=child),
        patch("agno.agent._subagents.aregister_member_run") as mock_register,
    ):
        items = await acollect(function.entrypoint(task="research topic B"))

    assert len(items) == 2
    assert all(item.parent_run_id == "run-1" for item in items)
    call = child.arun.calls[0]
    assert call["session_id"] == "session-1"
    assert call["yield_run_output"] is True
    mock_register.assert_awaited_once_with("run-1", call["run_id"])


async def test_async_spawn_yields_final_content_when_nothing_streamed():
    manager = SubagentsManager()
    parent = make_parent()
    child = make_fake_child([make_run_output("stored answer")])

    function = build_spawn_function(manager, parent, async_mode=True)
    with patch.object(manager, "_build_child", return_value=child):
        items = await acollect(function.entrypoint(task="task"))

    assert items == ["stored answer"]


async def test_async_spawn_exception_yields_failure_string():
    manager = SubagentsManager()
    parent = make_parent()

    child = MagicMock()
    child.id = "child"
    child.arun = MagicMock(side_effect=RuntimeError("async exploded"))

    function = build_spawn_function(manager, parent, async_mode=True)
    with patch.object(manager, "_build_child", return_value=child):
        items = await acollect(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "async exploded" in items[0]


# === Agent integration ===


def test_agent_with_subagents_gets_spawn_agent_tool():
    from agno.agent._tools import determine_tools_for_model

    parent = make_parent(subagents=SubagentsManager())

    functions = determine_tools_for_model(
        agent=parent,
        model=parent.model,
        processed_tools=[],
        run_response=RunOutput(run_id="run-1"),
        run_context=make_run_context(),
        session=AgentSession(session_id="session-1"),
    )

    assert len(functions) == 1
    spawn_function = functions[0]
    assert spawn_function.name == "spawn_agent"
    assert set(spawn_function.parameters["properties"].keys()) == {"task", "model", "tools"}
    assert DEFAULT_INSTRUCTIONS in parent._tool_instructions


def test_agent_without_subagents_is_unchanged():
    from agno.agent._tools import determine_tools_for_model

    parent = make_parent()

    functions = determine_tools_for_model(
        agent=parent,
        model=parent.model,
        processed_tools=[],
        run_response=RunOutput(run_id="run-1"),
        run_context=make_run_context(),
        session=AgentSession(session_id="session-1"),
    )

    assert functions == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
