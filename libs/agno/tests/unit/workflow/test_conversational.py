"""Unit tests for conversational sticky steps and goto helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agno.run.base import RunStatus
from agno.workflow.conversational import (
    ConversationalControl,
    ConversationalSignal,
    apply_signal_to_step_output,
    build_conversational_tools,
    clear_session_state_keys,
    collect_completed_goto_targets,
    extract_signal_from_run_output,
    find_step_index_by_name,
    is_conversational_pause_kind,
    prune_step_results,
    validate_no_conversational_in_parallel,
)
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import PauseKind, StepOutput
from agno.workflow.utils.hitl import apply_conversational_pause
from agno.workflow.workflow import Workflow


def _agent_step(name: str, conversational: bool = False) -> Step:
    agent = MagicMock()
    agent.name = name
    agent.id = f"id-{name}"
    agent.description = f"desc-{name}"
    agent.tools = []
    step = Step(name=name, agent=agent, conversational=conversational, description=f"desc-{name}")
    return step


class TestConversationalTools:
    def test_complete_step_sets_signal(self):
        control = ConversationalControl()
        complete_step, _goto = build_conversational_tools(control)
        result = complete_step(destination="Shanghai")
        assert "complete" in result.lower() or "marked" in result.lower()
        assert control.signal is not None
        assert control.signal.kind == "complete"
        assert control.signal.data == {"destination": "Shanghai"}

    def test_complete_step_without_args(self):
        control = ConversationalControl()
        complete_step, _goto = build_conversational_tools(control)
        complete_step()
        assert control.signal is not None
        assert control.signal.kind == "complete"
        assert control.signal.data is None

    def test_goto_validates_targets(self):
        control = ConversationalControl(available_goto_steps=[("destination", "collect destination")])
        _complete, goto = build_conversational_tools(control)
        bad = goto("booking")
        assert "Invalid" in bad
        assert control.signal is None

        ok = goto("destination", clear_keys=["departure_time"])
        assert "destination" in ok
        assert control.signal is not None
        assert control.signal.kind == "goto"
        assert control.signal.goto_step == "destination"
        assert control.signal.clear_keys == ["departure_time"]


class TestSignalExtraction:
    def test_extract_goto_wins_over_complete(self):
        run_output = SimpleNamespace(
            tools=[
                SimpleNamespace(tool_name="complete_step", tool_args={"city": "A"}),
                SimpleNamespace(tool_name="goto", tool_args={"step_name": "destination", "clear_keys": ["t"]}),
            ]
        )
        signal = extract_signal_from_run_output(run_output)
        assert signal is not None
        assert signal.kind == "goto"
        assert signal.goto_step == "destination"

    def test_apply_incomplete_without_signal(self):
        out = StepOutput(content="Where to?")
        result = apply_signal_to_step_output(out, None, conversational=True)
        assert result.conversational_incomplete is True

    def test_apply_complete_with_data(self):
        out = StepOutput(content="Got it")
        signal = ConversationalSignal(kind="complete", data={"destination": "Hangzhou"})
        result = apply_signal_to_step_output(out, signal, conversational=True)
        assert result.conversational_incomplete is False
        assert result.content == {"destination": "Hangzhou"}

    def test_apply_complete_without_data_keeps_nl(self):
        out = StepOutput(content="Done, destination set.")
        signal = ConversationalSignal(kind="complete", data=None)
        result = apply_signal_to_step_output(out, signal, conversational=True)
        assert result.content == "Done, destination set."


class TestGotoTargetsAndPrune:
    def test_collect_completed_goto_targets_only_earlier(self):
        steps = [_agent_step("destination"), _agent_step("departure"), _agent_step("booking")]
        results = [
            StepOutput(step_name="destination", content={"destination": "Shanghai"}),
        ]
        targets = collect_completed_goto_targets(steps, results, current_step_name="departure")
        assert targets == [("destination", "desc-destination")]

    def test_prune_removes_target_and_after(self):
        steps = [_agent_step("destination"), _agent_step("departure"), _agent_step("booking")]
        results = [
            StepOutput(step_name="destination", content="d"),
            StepOutput(step_name="departure", content="t"),
        ]
        previous = {"destination": results[0], "departure": results[1]}
        pruned, rebuilt = prune_step_results(results, previous, "destination", steps)
        assert [r.step_name for r in pruned] == []
        assert rebuilt == {}

    def test_find_step_index(self):
        steps = [_agent_step("a"), _agent_step("b")]
        assert find_step_index_by_name(steps, "b") == 1
        assert find_step_index_by_name(steps, "missing") is None

    def test_clear_session_state_keys(self):
        state = {"departure_time": "3pm", "keep": 1}
        clear_session_state_keys(state, ["departure_time", "missing"])
        assert state == {"keep": 1}


class TestParallelValidation:
    def test_rejects_conversational_inside_parallel(self):
        steps = [
            Parallel(
                _agent_step("a", conversational=True),
                _agent_step("b"),
                name="p",
            )
        ]
        with pytest.raises(ValueError, match="conversational=True is not supported inside Parallel"):
            validate_no_conversational_in_parallel(steps)

    def test_allows_conversational_outside_parallel(self):
        steps = [_agent_step("destination", conversational=True), Parallel(_agent_step("x"), _agent_step("y"))]
        validate_no_conversational_in_parallel(steps)  # should not raise


class TestPauseKindAndApply:
    def test_pause_kind_conversational(self):
        assert is_conversational_pause_kind(PauseKind.CONVERSATIONAL)
        assert is_conversational_pause_kind("conversational")
        assert not is_conversational_pause_kind(PauseKind.STEP)

    def test_apply_conversational_pause(self):
        from agno.run.workflow import WorkflowRunOutput

        run = WorkflowRunOutput(run_id="r1", session_id="s1")
        step = _agent_step("destination", conversational=True)
        out = StepOutput(content="Where would you like to go?")
        apply_conversational_pause(run, step, 0, "destination", out, [])
        assert run.status == RunStatus.paused
        assert run.pause_kind == PauseKind.CONVERSATIONAL
        assert run.content == "Where would you like to go?"
        assert run.step_requirements
        assert run.step_requirements[-1].requires_conversational_input is True


class TestStepConversationalFlag:
    def test_requires_agent_or_team(self):
        with pytest.raises(ValueError, match="conversational=True requires an agent or team"):

            def fn(step_input):  # type: ignore
                return StepOutput(content="x")

            Step(name="bad", executor=fn, conversational=True)

    def test_workflow_prepare_rejects_parallel_conversational(self):
        wf = Workflow(
            name="bad",
            steps=[
                Parallel(
                    _agent_step("a", conversational=True),
                    _agent_step("b"),
                )
            ],
        )
        with pytest.raises(ValueError, match="Parallel"):
            wf._prepare_steps()


class TestConversationalWorkflowMock:
    """End-to-end sticky pause/resume with mocked agent.run."""

    def test_sticky_pause_and_resume_then_complete(self):
        from agno.models.response import ToolExecution
        from agno.run.agent import RunOutput
        from agno.run.base import RunStatus

        agent = MagicMock()
        agent.name = "Destination"
        agent.id = "dest"
        agent.description = "collect destination"
        agent.tools = []
        agent.store_media = True
        agent.store_tool_messages = True
        agent.store_history_messages = True

        # Turn 1: no complete_step → sticky pause
        turn1 = RunOutput(content="Where would you like to go?", status=RunStatus.completed, tools=[])
        # Turn 2: complete_step → advance (and end workflow if single step)
        turn2 = RunOutput(
            content="Got it, Shanghai.",
            status=RunStatus.completed,
            tools=[ToolExecution(tool_name="complete_step", tool_args={"destination": "Shanghai"})],
        )
        agent.run.side_effect = [turn1, turn2]

        step = Step(name="destination", agent=agent, conversational=True)
        wf = Workflow(name="booking", steps=[step])

        r1 = wf.run("I want a ticket", session_id="s1")
        assert r1.status == RunStatus.paused
        assert r1.pause_kind == PauseKind.CONVERSATIONAL
        assert r1.paused_step_name == "destination"
        assert "Where would you like" in str(r1.content)

        r2 = wf.run("Shanghai", session_id="s1")
        assert r2.status == RunStatus.completed
        assert r2.step_results
        assert r2.step_results[0].content == {"destination": "Shanghai"}
        assert agent.run.call_count == 2
        # Second call should use conversational user message
        second_input = agent.run.call_args_list[1].kwargs.get("input") or agent.run.call_args_list[1][1].get("input")
        # input may be positional
        if second_input is None:
            second_input = agent.run.call_args_list[1].args[0] if agent.run.call_args_list[1].args else None
        assert second_input == "Shanghai"
