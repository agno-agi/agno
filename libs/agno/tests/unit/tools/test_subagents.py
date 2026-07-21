from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.run.base import RunContext
from agno.tools.calculator import CalculatorTools
from agno.tools.subagents import SubAgent


def make_parent(**kwargs) -> Agent:
    defaults = {"name": "Parent", "model": MagicMock(spec=Model), "db": MagicMock()}
    defaults.update(kwargs)
    return Agent(**defaults)


def make_run_context(user_id=None) -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id=user_id)


def make_run_output(content: str = "subagent result") -> MagicMock:
    run_output = MagicMock()
    run_output.get_content_as_string.return_value = content
    return run_output


# === Initialization ===


def test_init_registers_run_task():
    toolkit = SubAgent()
    assert list(toolkit.functions.keys()) == ["run_task"]
    assert list(toolkit.async_functions.keys()) == ["run_task"]


def test_init_adds_instructions():
    toolkit = SubAgent()
    assert toolkit.instructions is not None
    assert "run_task" in toolkit.instructions
    assert toolkit.add_instructions is True


# === Subagent construction ===


def test_subagent_inherits_parent_defaults():
    calculator = CalculatorTools()
    toolkit = SubAgent()
    parent = make_parent(tools=[calculator, toolkit])

    subagent = toolkit._get_subagent(parent)

    assert subagent.model is parent.model
    assert subagent.db is parent.db
    assert subagent.id == parent.id
    assert subagent.name == parent.name
    assert calculator in subagent.tools
    assert all(not isinstance(t, SubAgent) for t in subagent.tools)


def test_subagent_constructor_overrides_win():
    override_model = MagicMock(spec=Model)
    override_db = MagicMock()
    override_tools = [CalculatorTools()]
    toolkit = SubAgent(model=override_model, tools=override_tools, db=override_db)
    parent = make_parent(tools=[toolkit])

    subagent = toolkit._get_subagent(parent)

    assert subagent.model is override_model
    assert subagent.db is override_db
    assert subagent.tools == override_tools


def test_subagent_instance_is_reused():
    toolkit = SubAgent()
    parent = make_parent()

    assert toolkit._get_subagent(parent) is toolkit._get_subagent(parent)


# === run_task ===


def test_run_task_inherits_run_user_id():
    toolkit = SubAgent()
    parent = make_parent()

    subagent = MagicMock()
    subagent.run.return_value = make_run_output("the answer")
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        result = toolkit.run_task(agent=parent, run_context=make_run_context(user_id="ray"), task="research topic A")

    assert result == "the answer"
    _, kwargs = subagent.run.call_args
    assert kwargs["user_id"] == "ray"
    assert kwargs["session_id"].startswith(f"{parent.id}-subagent-task-")


def test_run_task_falls_back_to_parent_id_without_run_user():
    toolkit = SubAgent()
    parent = make_parent()

    subagent = MagicMock()
    subagent.run.return_value = make_run_output()
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        toolkit.run_task(agent=parent, run_context=make_run_context(), task="research topic A")

    assert subagent.run.call_args.kwargs["user_id"] == parent.id


def test_run_task_sessions_are_unique():
    toolkit = SubAgent()
    parent = make_parent()

    subagent = MagicMock()
    subagent.run.return_value = make_run_output()
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        toolkit.run_task(agent=parent, run_context=make_run_context(), task="task one")
        toolkit.run_task(agent=parent, run_context=make_run_context(), task="task two")

    first = subagent.run.call_args_list[0].kwargs["session_id"]
    second = subagent.run.call_args_list[1].kwargs["session_id"]
    assert first != second


def test_run_task_error_is_returned_as_string():
    toolkit = SubAgent()
    parent = make_parent()

    subagent = MagicMock()
    subagent.run.side_effect = RuntimeError("model exploded")
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        result = toolkit.run_task(agent=parent, run_context=make_run_context(), task="doomed task")

    assert "model exploded" in result


async def test_arun_task_inherits_run_user_id():
    toolkit = SubAgent()
    parent = make_parent()
    calls = {}

    async def fake_arun(task, **kwargs):
        calls["task"] = task
        calls.update(kwargs)
        return make_run_output("async answer")

    subagent = MagicMock()
    subagent.db = None
    subagent.arun = fake_arun
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        result = await toolkit.arun_task(
            agent=parent, run_context=make_run_context(user_id="ray"), task="research topic B"
        )

    assert result == "async answer"
    assert calls["task"] == "research topic B"
    assert calls["user_id"] == "ray"
    assert calls["session_id"].startswith(f"{parent.id}-subagent-task-")


async def test_arun_task_streams_in_background_when_db_is_set():
    toolkit = SubAgent()
    parent = make_parent()
    calls = {}

    completed = MagicMock()
    completed.get_content_as_string.return_value = "background answer"

    def fake_arun(task, **kwargs):
        calls.update(kwargs)

        async def event_stream():
            yield "event: RunStarted"
            yield "event: RunCompleted"

        return event_stream()

    async def fake_aget_run_output(run_id, session_id=None, user_id=None):
        calls["fetched_run_id"] = run_id
        return completed

    subagent = MagicMock()
    subagent.db = MagicMock()
    subagent.arun = fake_arun
    subagent.aget_run_output = fake_aget_run_output
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        result = await toolkit.arun_task(agent=parent, run_context=make_run_context(user_id="ray"), task="task")

    assert result == "background answer"
    assert calls["background"] is True
    assert calls["stream"] is True
    assert calls["stream_events"] is True
    assert calls["user_id"] == "ray"
    assert calls["fetched_run_id"] == calls["run_id"]


async def test_arun_task_error_is_returned_as_string():
    toolkit = SubAgent()
    parent = make_parent()

    async def fake_arun(task, **kwargs):
        raise RuntimeError("async exploded")

    subagent = MagicMock()
    subagent.db = None
    subagent.arun = fake_arun
    with patch.object(toolkit, "_get_subagent", return_value=subagent):
        result = await toolkit.arun_task(agent=parent, run_context=make_run_context(), task="doomed task")

    assert "async exploded" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
