from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent
from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, RunStatus
from agno.run.base import RunContext
from agno.session.agent import AgentSession
from agno.subagent import SubagentsConfig
from agno.subagent.subagent import DEFAULT_INSTRUCTIONS
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


def build_spawn_function(config: SubagentsConfig, parent: Agent, run_context=None, async_mode=False) -> Function:
    return config.get_spawn_function(
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


# === Config ===


def test_config_rejects_empty_models():
    with pytest.raises(ValueError):
        SubagentsConfig(models={})


def test_single_model_becomes_default_option():
    model = MagicMock(spec=Model)
    config = SubagentsConfig(model=model)

    assert config.models == {"default": model}


def test_model_and_models_are_mutually_exclusive():
    with pytest.raises(ValueError):
        SubagentsConfig(model=MagicMock(spec=Model), models={"fast": MagicMock(spec=Model)})


def test_model_option_tuples_split_into_model_and_description():
    fast = MagicMock(spec=Model)
    deep = MagicMock(spec=Model)
    config = SubagentsConfig(models={"fast": fast, "deep": (deep, "complex analysis")})

    assert config.models == {"fast": fast, "deep": deep}
    assert config.model_descriptions == {"deep": "complex analysis"}


def test_model_option_descriptions_appear_in_tool_description():
    fast = MagicMock(spec=Model)
    fast.id = "gpt-5.6-luna"
    deep = MagicMock(spec=Model)
    deep.id = "gpt-5.6-terra"
    config = SubagentsConfig(
        models={
            "fast": (fast, "quick lookups"),
            "deep": (deep, "complex analysis"),
        }
    )
    parent = make_parent()

    function = build_spawn_function(config, parent)

    assert "fast: gpt-5.6-luna (default) - quick lookups" in function.description
    assert "deep: gpt-5.6-terra - complex analysis" in function.description


def test_enable_subagents_creates_default_config():
    parent = make_parent(enable_subagents=True)

    assert isinstance(parent.subagents_config, SubagentsConfig)
    assert parent.subagents_config.models is None
    assert parent.subagents_config.tools is None


def test_subagents_disabled_by_default():
    parent = make_parent()

    assert parent.enable_subagents is False
    assert parent.subagents_config is None


def test_explicit_config_wins_over_enable_flag():
    config = SubagentsConfig()
    parent = make_parent(subagents_config=config, enable_subagents=True)

    assert parent.subagents_config is config


def test_models_default_to_parent_model():
    config = SubagentsConfig()
    parent = make_parent()

    models = config._resolve_models(parent)

    assert models == {"default": parent.model}


def test_first_model_option_is_default():
    fast = MagicMock(spec=Model)
    deep = MagicMock(spec=Model)
    config = SubagentsConfig(models={"fast": fast, "deep": deep})

    selection = config._validate_selection(model=None, tools=None, models=config.models, allowed_tools={})

    assert selection == ("fast", [])


def test_allowed_tools_inherit_parent_tools():
    calculator = CalculatorTools()
    config = SubagentsConfig()
    parent = make_parent(tools=[calculator])

    allowed = config._resolve_allowed_tools(parent)

    assert allowed == {"calculator": calculator}


def test_config_tools_override_parent_tools():
    calculator = CalculatorTools()
    config = SubagentsConfig(tools=[calculator])
    parent = make_parent(tools=[])

    allowed = config._resolve_allowed_tools(parent)

    assert allowed == {"calculator": calculator}


# === Child agent construction and caching ===


def test_child_agent_has_distinct_id_and_no_db():
    fast = MagicMock(spec=Model)
    config = SubagentsConfig(models={"fast": fast})
    parent = make_parent()

    child = config._get_child(parent, model_key="fast", tool_names=[], models={"fast": fast}, allowed_tools={})

    assert child.id == f"{parent.id}-subagent-fast"
    assert child.db is None
    assert child.model is fast
    assert child.subagents_config is None


def test_child_agent_cached_per_model_and_toolset():
    fast = MagicMock(spec=Model)
    deep = MagicMock(spec=Model)
    models = {"fast": fast, "deep": deep}
    calculator = CalculatorTools()
    allowed = {"calculator": calculator}
    config = SubagentsConfig(models=models)
    parent = make_parent()

    first = config._get_child(parent, "fast", ["calculator"], models, allowed)
    second = config._get_child(parent, "fast", ["calculator"], models, allowed)
    different_tools = config._get_child(parent, "fast", [], models, allowed)
    different_model = config._get_child(parent, "deep", ["calculator"], models, allowed)

    assert first is second
    assert first is not different_tools
    assert first is not different_model


# === Spawn function factory ===


def test_spawn_function_description_lists_options():
    fast = MagicMock(spec=Model)
    fast.id = "gpt-5.6-luna"
    deep = MagicMock(spec=Model)
    deep.id = "gpt-5.6-terra"
    config = SubagentsConfig(models={"fast": fast, "deep": deep})
    parent = make_parent(tools=[CalculatorTools()])

    function = build_spawn_function(config, parent)

    assert function.name == "spawn_agent"
    assert "fast: gpt-5.6-luna (default)" in function.description
    assert "deep: gpt-5.6-terra" in function.description
    assert "calculator" in function.description


def test_spawn_function_carries_parent_instructions():
    config = SubagentsConfig()
    parent = make_parent()

    function = build_spawn_function(config, parent)

    assert function.instructions == DEFAULT_INSTRUCTIONS
    assert function.add_instructions is True


def test_spawn_function_async_mode_picks_async_entrypoint():
    config = SubagentsConfig()
    parent = make_parent()

    sync_function = build_spawn_function(config, parent, async_mode=False)
    async_function = build_spawn_function(config, parent, async_mode=True)

    assert sync_function.entrypoint.__name__ == "spawn_agent"
    assert async_function.entrypoint.__name__ == "aspawn_agent"


def test_spawn_function_schema_has_only_model_facing_params():
    config = SubagentsConfig()
    parent = make_parent()

    function = build_spawn_function(config, parent)
    function.process_entrypoint()

    assert set(function.parameters["properties"].keys()) == {"task", "model", "tools"}


# === Selection errors ===


def test_unknown_model_yields_error_string():
    config = SubagentsConfig(models={"fast": MagicMock(spec=Model)})
    parent = make_parent()
    function = build_spawn_function(config, parent)

    items = list(function.entrypoint(task="do something", model="huge"))

    assert len(items) == 1
    assert "Unknown model option 'huge'" in items[0]
    assert "fast" in items[0]


def test_unknown_tool_yields_error_string():
    config = SubagentsConfig()
    parent = make_parent(tools=[CalculatorTools()])
    function = build_spawn_function(config, parent)

    items = list(function.entrypoint(task="do something", tools=["websearch"]))

    assert len(items) == 1
    assert "Unknown tool name(s) websearch" in items[0]
    assert "calculator" in items[0]


# === Sync spawn behavior ===


def test_sync_spawn_yields_events_tagged_for_parent():
    config = SubagentsConfig()
    parent = make_parent()
    run_context = make_run_context(user_id="ray")
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunCompletedEvent(run_id="child-run"),
        make_run_output("final answer"),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(config, parent, run_context=run_context)
    with patch.object(config, "_get_child", return_value=child):
        items = list(function.entrypoint(task="research topic A"))

    # Both events re-emitted with parent_run_id; RunOutput captured, not yielded;
    # content streamed so no trailing string
    assert len(items) == 2
    assert all(item.parent_run_id == "run-1" for item in items)
    assert isinstance(items[0], RunContentEvent)
    assert isinstance(items[1], RunCompletedEvent)


def test_sync_spawn_runs_child_in_parent_session():
    config = SubagentsConfig()
    parent = make_parent()
    run_context = make_run_context(user_id="ray")
    child = make_fake_child([make_run_output()])

    function = build_spawn_function(config, parent, run_context=run_context)
    with (
        patch.object(config, "_get_child", return_value=child),
        patch("agno.subagent.subagent.register_member_run") as mock_register,
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
    config = SubagentsConfig()
    parent = make_parent()
    child = make_fake_child([make_run_output("stored answer")])

    function = build_spawn_function(config, parent)
    with patch.object(config, "_get_child", return_value=child):
        items = list(function.entrypoint(task="task"))

    assert items == ["stored answer"]


def test_sync_spawn_merges_session_state_copy():
    config = SubagentsConfig()
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

    function = build_spawn_function(config, parent, run_context=run_context)
    with patch.object(config, "_get_child", return_value=child):
        list(function.entrypoint(task="task"))

    assert run_context.session_state == {"count": 2, "child_key": "set"}


def test_sync_spawn_error_status_yields_failure_string():
    config = SubagentsConfig()
    parent = make_parent()
    child = make_fake_child([make_run_output("model exploded", status=RunStatus.error)])

    function = build_spawn_function(config, parent)
    with patch.object(config, "_get_child", return_value=child):
        items = list(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "Subagent task failed" in items[0]
    assert "model exploded" in items[0]


def test_sync_spawn_exception_yields_failure_string():
    config = SubagentsConfig()
    parent = make_parent()

    child = MagicMock()
    child.id = "child"
    child.run = MagicMock(side_effect=RuntimeError("model exploded"))

    function = build_spawn_function(config, parent)
    with patch.object(config, "_get_child", return_value=child):
        items = list(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "model exploded" in items[0]


def test_sync_spawn_parent_cancel_cancels_child():
    config = SubagentsConfig()
    parent = make_parent()
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunContentEvent(content="world", run_id="child-run"),
        make_run_output(),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(config, parent)
    with (
        patch.object(config, "_get_child", return_value=child),
        patch("agno.subagent.subagent.raise_if_cancelled", side_effect=RunCancelledException("")),
        patch("agno.subagent.subagent.cancel_run") as mock_cancel,
    ):
        with pytest.raises(RunCancelledException):
            list(function.entrypoint(task="task"))

    mock_cancel.assert_called_once_with(child.run.calls[0]["run_id"])


# === Async spawn behavior ===


async def test_async_spawn_yields_events_tagged_for_parent():
    config = SubagentsConfig()
    parent = make_parent()
    events = [
        RunContentEvent(content="hello", run_id="child-run"),
        RunCompletedEvent(run_id="child-run"),
        make_run_output("final answer"),
    ]
    child = make_fake_child(events)

    function = build_spawn_function(config, parent, async_mode=True)
    with (
        patch.object(config, "_get_child", return_value=child),
        patch("agno.subagent.subagent.aregister_member_run") as mock_register,
    ):
        items = await acollect(function.entrypoint(task="research topic B"))

    assert len(items) == 2
    assert all(item.parent_run_id == "run-1" for item in items)
    call = child.arun.calls[0]
    assert call["session_id"] == "session-1"
    assert call["yield_run_output"] is True
    mock_register.assert_awaited_once_with("run-1", call["run_id"])


async def test_async_spawn_yields_final_content_when_nothing_streamed():
    config = SubagentsConfig()
    parent = make_parent()
    child = make_fake_child([make_run_output("stored answer")])

    function = build_spawn_function(config, parent, async_mode=True)
    with patch.object(config, "_get_child", return_value=child):
        items = await acollect(function.entrypoint(task="task"))

    assert items == ["stored answer"]


async def test_async_spawn_exception_yields_failure_string():
    config = SubagentsConfig()
    parent = make_parent()

    child = MagicMock()
    child.id = "child"
    child.arun = MagicMock(side_effect=RuntimeError("async exploded"))

    function = build_spawn_function(config, parent, async_mode=True)
    with patch.object(config, "_get_child", return_value=child):
        items = await acollect(function.entrypoint(task="doomed task"))

    assert len(items) == 1
    assert "async exploded" in items[0]


# === Agent integration ===


def test_agent_with_subagent_gets_spawn_agent_tool():
    from agno.agent._tools import determine_tools_for_model

    config = SubagentsConfig()
    parent = make_parent(subagents_config=config)

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


def test_agent_without_subagent_is_unchanged():
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
