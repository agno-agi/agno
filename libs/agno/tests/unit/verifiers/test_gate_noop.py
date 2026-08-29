"""stop_on_noop through the real Agent run functions, on a scripted offline model.

A controllable CallableFingerprint reads a mutable state dict; the scripted model mutates
that state (or deliberately does not) per call, so each test drives the exact fingerprint
transition it pins: a failed no-op attempt ends the run without burning the remaining
budget, a changed attempt re-enters, a passing no-op still verifies, and state changed by
the checks themselves never reads as model progress.
"""

import asyncio
from typing import Any, AsyncIterator, Callable, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.verifiers import VerificationConfig
from agno.verifiers.fingerprints import CallableFingerprint


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order, running the matching
    mutation (when given) first — the model's "work" on the world the fingerprint watches."""

    def __init__(self, script: List[ModelResponse], mutations: Optional[List[Optional[Callable[[], None]]]] = None):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.mutations = list(mutations or [])
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

    def _next(self) -> ModelResponse:
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        if index < len(self.mutations) and self.mutations[index] is not None:
            self.mutations[index]()
        return self.script[index]

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def _run_variant(agent: Agent, mode: str, prompt: str = "go") -> RunOutput:
    """Drive one of the four run variants to its final RunOutput."""
    if mode == "run":
        return agent.run(prompt)
    if mode == "arun":
        return asyncio.run(agent.arun(prompt))
    if mode == "run_stream":
        events = list(agent.run(prompt, stream=True, stream_events=True, yield_run_output=True))
        return [e for e in events if isinstance(e, RunOutput)][-1]
    if mode == "arun_stream":

        async def collect():
            out = []
            async for e in agent.arun(prompt, stream=True, stream_events=True, yield_run_output=True):
                out.append(e)
            return out

        events = asyncio.run(collect())
        return [e for e in events if isinstance(e, RunOutput)][-1]
    raise AssertionError(mode)


MODES = ["run", "arun", "run_stream", "arun_stream"]


@pytest.mark.parametrize("mode", MODES)
def test_failed_noop_attempt_stops_without_burning_budget(mode):
    """A failed attempt with an unchanged fingerprint ends the run unverified with
    stop_reason "noop" after ONE model call — the remaining budget is not spent."""
    state = {"v": "start"}
    model = ScriptedModel([_text("claimed done")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: "still failing"],
        verification=VerificationConfig(
            max_attempts=3,
            stop_on_noop=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = _run_variant(agent, mode)
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "noop"
    assert model.calls == 1
    assert len(out.verification.attempts) == 1
    assert out.verification.attempts[0].noop is True


@pytest.mark.parametrize("mode", MODES)
def test_failed_changed_attempt_reenters_the_model(mode):
    """A failed attempt whose fingerprint CHANGED is not a no-op: the model is called
    again, and the run ends on budget exhaustion, not on the noop stop."""
    state = {"v": "start"}
    model = ScriptedModel(
        [_text("try 1"), _text("try 2")],
        mutations=[lambda: state.update(v="after-1"), lambda: state.update(v="after-2")],
    )
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: "still failing"],
        verification=VerificationConfig(
            max_attempts=2,
            stop_on_noop=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = _run_variant(agent, mode)
    assert model.calls == 2
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "exhausted"
    assert [a.noop for a in out.verification.attempts] == [False, False]


@pytest.mark.parametrize("mode", MODES)
def test_passing_noop_attempt_still_verifies(mode):
    """A PASSING attempt with an unchanged fingerprint verifies: passed beats noop."""
    state = {"v": "start"}
    model = ScriptedModel([_text("done")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: True],
        verification=VerificationConfig(
            max_attempts=3,
            stop_on_noop=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = _run_variant(agent, mode)
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert out.verification.stop_reason == "passed"
    assert out.verification.attempts[0].noop is True


@pytest.mark.parametrize("mode", MODES)
def test_check_artefacts_do_not_read_as_model_progress(mode):
    """The comparison baseline settles AFTER the checks run: state the checks themselves
    mutate is folded into the baseline, so a model attempt that changes nothing on top of
    it is still a no-op. Were the baseline captured before the checks, attempt 2 would read
    the check's own mutation as progress, re-enter, and burn the rest of the budget."""
    state = {"v": "start"}

    def failing_check_that_mutates(run_output):
        state["v"] = state["v"] + "+check"
        return "still failing"

    model = ScriptedModel(
        [_text("try 1"), _text("try 2")],
        mutations=[lambda: state.update(v="model-1"), None],
    )
    agent = Agent(
        model=model,
        verifiers=[failing_check_that_mutates],
        verification=VerificationConfig(
            max_attempts=4,
            stop_on_noop=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = _run_variant(agent, mode)
    assert model.calls == 2
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "noop"
    attempts = out.verification.attempts
    assert len(attempts) == 2
    # Attempt 1: the model's own mutation reads as progress.
    assert attempts[0].noop is False
    assert attempts[0].fingerprint == "model-1"
    # Attempt 2: compared against the post-check state, not the model's last capture.
    assert attempts[1].compared_against == "model-1+check"
    assert attempts[1].noop is True
