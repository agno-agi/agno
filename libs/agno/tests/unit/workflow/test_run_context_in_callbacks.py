"""Tests that Router selectors and Condition evaluators receive run_context.

Regression test for https://github.com/agno-agi/agno/issues/5827
Router selectors (and Condition evaluators) written with a `run_context` parameter,
as documented, failed with "missing 1 required positional argument: 'run_context'"
because only `session_state` and `step_choices` were injected by signature inspection.
"""

from typing import Any, Dict, List

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.base import RunContext
from agno.workflow.condition import Condition
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

SESSION_STATE = {"agent_preference": "technical", "interaction_count": 0}


def _echo_executor(step_input: StepInput) -> StepOutput:
    return StepOutput(content="step ran")


def _make_step(name: str) -> Step:
    return Step(name=name, executor=_echo_executor)


def _make_workflow(steps: List[Any]) -> Workflow:
    return Workflow(
        name="Run Context Callback Workflow",
        db=InMemoryDb(),
        steps=steps,
        session_state=dict(SESSION_STATE),
    )


class TestRouterSelectorRunContext:
    def test_sync_selector_with_run_context(self):
        seen: Dict[str, Any] = {}
        target = _make_step("target")

        def selector(step_input: StepInput, run_context: RunContext) -> Step:
            seen["session_state"] = run_context.session_state
            run_context.session_state["selector_ran"] = True
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert seen["session_state"]["agent_preference"] == "technical"
        assert workflow.get_session_state(session_id="s1")["selector_ran"] is True

    def test_sync_selector_with_run_context_streaming(self):
        target = _make_step("target")

        def selector(step_input: StepInput, run_context: RunContext) -> Step:
            run_context.session_state["selector_ran"] = True
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        events = list(workflow.run(input="hello", session_id="s1", user_id="u1", stream=True))

        assert not any("Error" in type(event).__name__ for event in events)
        assert workflow.get_session_state(session_id="s1")["selector_ran"] is True

    @pytest.mark.asyncio
    async def test_async_selector_with_run_context(self):
        target = _make_step("target")

        async def selector(step_input: StepInput, run_context: RunContext) -> Step:
            run_context.session_state["selector_ran"] = True
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        response = await workflow.arun(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert workflow.get_session_state(session_id="s1")["selector_ran"] is True

    def test_selector_with_session_state_still_works(self):
        target = _make_step("target")

        def selector(step_input: StepInput, session_state: dict) -> Step:
            session_state["selector_ran"] = True
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert workflow.get_session_state(session_id="s1")["selector_ran"] is True

    def test_selector_with_run_context_and_session_state(self):
        target = _make_step("target")

        def selector(step_input: StepInput, run_context: RunContext, session_state: dict) -> Step:
            assert run_context.session_state is session_state
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"

    def test_selector_with_run_context_and_step_choices(self):
        seen: Dict[str, Any] = {}
        target = _make_step("target")

        def selector(step_input: StepInput, run_context: RunContext, step_choices: List[Step]) -> Step:
            seen["choices"] = [step.name for step in step_choices]
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert seen["choices"] == ["target"]


class TestConditionEvaluatorRunContext:
    def test_sync_evaluator_with_run_context(self):
        def evaluator(step_input: StepInput, run_context: RunContext) -> bool:
            run_context.session_state["evaluator_ran"] = True
            return True

        workflow = _make_workflow([Condition(name="condition", evaluator=evaluator, steps=[_make_step("inner")])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert workflow.get_session_state(session_id="s1")["evaluator_ran"] is True

    @pytest.mark.asyncio
    async def test_async_evaluator_with_run_context(self):
        async def evaluator(step_input: StepInput, run_context: RunContext) -> bool:
            run_context.session_state["evaluator_ran"] = True
            return True

        workflow = _make_workflow([Condition(name="condition", evaluator=evaluator, steps=[_make_step("inner")])])
        response = await workflow.arun(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert workflow.get_session_state(session_id="s1")["evaluator_ran"] is True

    def test_evaluator_with_session_state_still_works(self):
        def evaluator(step_input: StepInput, session_state: dict) -> bool:
            session_state["evaluator_ran"] = True
            return True

        workflow = _make_workflow([Condition(name="condition", evaluator=evaluator, steps=[_make_step("inner")])])
        response = workflow.run(input="hello", session_id="s1", user_id="u1")

        assert response.status.value == "COMPLETED"
        assert workflow.get_session_state(session_id="s1")["evaluator_ran"] is True


class TestSessionStateParamDeprecation:
    def test_session_state_param_warns_once(self, caplog):
        from agno.workflow.types import _session_state_param_deprecation_warned

        _session_state_param_deprecation_warned.clear()
        target = _make_step("target")

        def deprecated_spelling_selector(step_input: StepInput, session_state: dict) -> Step:
            return target

        workflow = _make_workflow([Router(name="router", selector=deprecated_spelling_selector, choices=[target])])
        with caplog.at_level("WARNING", logger="agno"):
            workflow.run(input="hello", session_id="s1", user_id="u1")
            workflow.run(input="again", session_id="s1", user_id="u1")

        warnings = [record for record in caplog.records if "session_state" in record.message]
        assert len(warnings) == 1
        assert "deprecated" in warnings[0].message
        assert "run_context.session_state" in warnings[0].message

    def test_run_context_param_does_not_warn(self, caplog):
        target = _make_step("target")

        def selector(step_input: StepInput, run_context: RunContext) -> Step:
            return target

        workflow = _make_workflow([Router(name="router", selector=selector, choices=[target])])
        with caplog.at_level("WARNING", logger="agno"):
            workflow.run(input="hello", session_id="s1", user_id="u1")

        assert not any("deprecated" in record.message for record in caplog.records)
