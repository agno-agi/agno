"""Regression tests for default-reasoning session_state propagation.

Bug: ``ReasoningManager`` builds the default Chain-of-Thought sub-agent with
``db=None`` and only seeds ``session_state`` via the constructor. When that
sub-agent runs, ``read_or_create_session`` deepcopies ``agent.session_state``
into a fresh ``session_data`` dict and ``load_session_state`` overwrites the
run's ``session_state`` with that copy — so any tool calls fired inside the
sub-agent mutate an isolated dict and the parent run never sees the writes.

Passing ``session_state=parent_state`` on the sub-agent's ``run``/``arun`` call
preserves dict identity end-to-end (``load_session_state`` mutates in place
via ``clear``/``update``), so tool writes land on the parent's dict.
"""

from typing import Any, List, Optional

import pytest

from agno.models.message import Message
from agno.reasoning.manager import ReasoningConfig, ReasoningManager
from agno.reasoning.step import NextAction, ReasoningStep, ReasoningSteps
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.run.messages import RunMessages


class _FakeReasoningAgent:
    """Stub stand-in for the default reasoning sub-agent.

    Captures the kwargs passed to ``run``/``arun`` and returns a final-answer
    ``RunOutput`` so the manager loop terminates after one step.
    """

    def __init__(self) -> None:
        self.run_calls: List[dict] = []
        self.arun_calls: List[dict] = []
        self.output_schema = ReasoningSteps

    def _final_answer_output(self) -> RunOutput:
        steps = ReasoningSteps(
            reasoning_steps=[
                ReasoningStep(
                    title="done",
                    action="finish",
                    result="ok",
                    reasoning="done",
                    next_action=NextAction.FINAL_ANSWER,
                    confidence=1.0,
                )
            ]
        )
        return RunOutput(
            run_id="r-1",
            agent_id="a-1",
            content=steps,
            messages=[Message(role="assistant", content="done")],
        )

    def run(self, **kwargs: Any) -> RunOutput:
        self.run_calls.append(kwargs)
        return self._final_answer_output()

    async def arun(self, **kwargs: Any) -> RunOutput:
        self.arun_calls.append(kwargs)
        return self._final_answer_output()


def _build_manager(
    fake_agent: _FakeReasoningAgent,
    session_state: Optional[dict],
) -> ReasoningManager:
    run_context = RunContext(run_id="r-1", session_id="s-1", session_state=session_state)
    config = ReasoningConfig(run_context=run_context)
    manager = ReasoningManager(config)
    # Bypass the real sub-agent construction so we don't need a model.
    manager._get_default_reasoning_agent = lambda model: fake_agent  # type: ignore[assignment, method-assign]
    return manager


def _drain(it: Any) -> None:
    for _ in it:
        pass


async def _adrain(it: Any) -> None:
    async for _ in it:
        pass


def test_run_default_reasoning_passes_parent_session_state() -> None:
    """Sync: the sub-agent must receive the parent's session_state by reference."""
    parent_state: dict = {"existing_key": "existing_value"}
    fake = _FakeReasoningAgent()
    manager = _build_manager(fake, parent_state)

    _drain(manager.run_default_reasoning(model=None, run_messages=RunMessages()))  # type: ignore[arg-type]

    assert len(fake.run_calls) == 1
    kwargs = fake.run_calls[0]
    assert "session_state" in kwargs
    assert kwargs["session_state"] is parent_state


@pytest.mark.asyncio
async def test_arun_default_reasoning_passes_parent_session_state() -> None:
    """Async: the sub-agent must receive the parent's session_state by reference."""
    parent_state: dict = {"existing_key": "existing_value"}
    fake = _FakeReasoningAgent()
    manager = _build_manager(fake, parent_state)

    await _adrain(manager.arun_default_reasoning(model=None, run_messages=RunMessages()))  # type: ignore[arg-type]

    assert len(fake.arun_calls) == 1
    kwargs = fake.arun_calls[0]
    assert "session_state" in kwargs
    assert kwargs["session_state"] is parent_state


def test_run_default_reasoning_without_run_context_passes_none() -> None:
    """When no run_context is configured, session_state must be None (not crash)."""
    fake = _FakeReasoningAgent()
    config = ReasoningConfig(run_context=None)
    manager = ReasoningManager(config)
    manager._get_default_reasoning_agent = lambda model: fake  # type: ignore[assignment, method-assign]

    _drain(manager.run_default_reasoning(model=None, run_messages=RunMessages()))  # type: ignore[arg-type]

    assert len(fake.run_calls) == 1
    assert fake.run_calls[0]["session_state"] is None
