"""The verification gate through the four agent CONTINUE functions, on a scripted offline model.

Covers the continuation semantics of the gate:
- continuing an UNVERIFIED run resumes in place (no fork) and restarts the budget window
  while keeping the attempt history;
- continuing a COMPLETED run auto-forks, and the fork's verification record starts fresh;
- a streamed continuation emits the verification events and the final RunOutput carries
  the updated record;
- a HITL pause leaves a pending record with no attempts, and the confirmed resume runs
  the gate to a verdict.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.tools import tool
from agno.verifiers import VerificationConfig


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order."""

    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self  # one shared call counter, whatever the agent copies

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

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


def _tool_call(name: str, call_id: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({})},
            }
        ],
    )


def releasable_verifier():
    """A verifier that fails until the test flips the switch — the first run exhausts its
    budget, the continuation passes."""
    state = {"pass": False}

    def check(run_output):
        return True if state["pass"] else "not good enough"

    return state, check


def _unverified_first_run(max_attempts: int = 2):
    """An agent whose first run ends unverified after ``max_attempts`` failed attempts."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state, check = releasable_verifier()
    agent = Agent(model=model, verifiers=[check], verification=VerificationConfig(max_attempts=max_attempts))
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "exhausted"
    assert len(out.verification.attempts) == max_attempts
    assert model.calls == max_attempts
    return agent, model, state, out


def test_continue_of_unverified_run_restarts_the_budget():
    """Continuing an unverified run keeps the attempt history but restarts the budget
    window, and resumes IN PLACE: only a COMPLETED source auto-forks, so the unverified
    continuation keeps the run_id (like an error resume)."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)

    state["pass"] = True
    continued = agent.continue_run(run_response=out, input="try harder")

    assert continued.run_id == out.run_id
    assert continued.forked_from_run_id is None
    assert continued.status == RunStatus.completed
    assert model.calls == 3
    record = continued.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    # History kept, budget restarted at the continuation boundary.
    assert record.budget_baseline == 2
    assert len(record.attempts) == 3
    assert record.attempts[0].verdicts[0].passed is False
    assert record.attempts[1].verdicts[0].passed is False
    assert record.attempts[2].verdicts[0].passed is True


def test_acontinue_of_unverified_run_restarts_the_budget():
    """Async twin: acontinue_run resumes the unverified run in place with a fresh budget."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)

    state["pass"] = True
    continued = asyncio.run(agent.acontinue_run(run_response=out, input="try harder"))

    assert continued.run_id == out.run_id
    assert continued.forked_from_run_id is None
    assert continued.status == RunStatus.completed
    assert model.calls == 3
    record = continued.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert record.budget_baseline == 2
    assert len(record.attempts) == 3
    assert record.attempts[2].verdicts[0].passed is True


def test_continue_of_completed_run_forks_with_a_fresh_record():
    """Continuing a COMPLETED (verified) run auto-forks a sibling. The fork's verification
    record starts fresh (the fork reset clears the parent's record) and re-verifies within
    its own budget; the parent's record is untouched."""
    model = ScriptedModel([_text("first"), _text("second")])
    agent = Agent(model=model, verifiers=[lambda run_output: True])
    out = agent.run("go")
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1
    parent_record = out.verification

    continued = agent.continue_run(run_response=out, input="one more thing")

    assert continued.run_id != out.run_id
    assert continued.forked_from_run_id == out.run_id
    assert continued.status == RunStatus.completed
    record = continued.verification
    assert record is not parent_record
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert record.budget_baseline == 0
    assert len(record.attempts) == 1
    # The parent's record did not ride along and did not grow.
    assert out.verification is parent_record
    assert out.status == RunStatus.completed
    assert len(parent_record.attempts) == 1


def test_streamed_continuation_emits_verification_events():
    """A streamed continuation of an unverified run runs the gate: the started/completed
    events are emitted, the completed event's attempt number counts within the RESTARTED
    budget, and the final RunOutput carries the updated record."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)

    state["pass"] = True
    events = list(
        agent.continue_run(
            run_response=out,
            input="try harder",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )
    names = [getattr(e, "event", "") for e in events]
    assert names.count("VerificationStarted") == 1
    assert names.count("VerificationCompleted") == 1
    completed = [e for e in events if getattr(e, "event", "") == "VerificationCompleted"][0]
    assert completed.passed is True
    assert completed.stop_reason == "passed"
    # Third attempt overall, but first of the restarted window.
    assert completed.attempt == 1

    final = [e for e in events if isinstance(e, RunOutput)][-1]
    assert final.run_id == out.run_id
    assert final.status == RunStatus.completed
    assert final.verification.status == "verified"
    assert final.verification.budget_baseline == 2
    assert len(final.verification.attempts) == 3


def test_astreamed_continuation_emits_verification_events():
    """Async twin of the streamed continuation."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)

    state["pass"] = True

    async def collect():
        collected = []
        async for e in agent.acontinue_run(
            run_response=out,
            input="try harder",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        ):
            collected.append(e)
        return collected

    events = asyncio.run(collect())
    names = [getattr(e, "event", "") for e in events]
    assert names.count("VerificationStarted") == 1
    assert names.count("VerificationCompleted") == 1

    final = [e for e in events if isinstance(e, RunOutput)][-1]
    assert final.run_id == out.run_id
    assert final.status == RunStatus.completed
    assert final.verification.status == "verified"
    assert final.verification.budget_baseline == 2
    assert len(final.verification.attempts) == 3


@tool(requires_confirmation=True)
def gated_probe() -> str:
    """A confirmation-gated tool: the first run pauses on it."""
    return "probed"


def _confirmed(requirements) -> List[RunRequirement]:
    """Round-trip requirements through their wire format and confirm them, the way a
    frontend or a fresh process would send them back."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed


def test_hitl_pause_resumes_into_the_gate(tmp_path):
    """A HITL pause happens BEFORE any verification concluded: gate.begin() has already
    bound the record, so the paused run carries a pending record with no attempts. The
    confirmed resume finishes the model turn and the gate settles to verified."""
    db = SqliteDb(db_file=str(tmp_path / "hitl.db"))
    model = ScriptedModel([_tool_call("gated_probe", "tc-1"), _text("finished the job")])
    agent = Agent(
        model=model,
        tools=[gated_probe],
        verifiers=[lambda run_output: True],
        db=db,
        telemetry=False,
    )

    run1 = agent.run("go", session_id="s-hitl")
    assert run1.is_paused
    # The record was created at begin(), before the model call; the paused leg never
    # opened an attempt, so it is pending with an empty history.
    assert run1.verification is not None
    assert run1.verification.status == "pending"
    assert run1.verification.attempts == []

    continued = agent.continue_run(
        run_id=run1.run_id,
        session_id="s-hitl",
        requirements=_confirmed(run1.requirements),
    )

    assert continued.run_id == run1.run_id
    assert continued.status == RunStatus.completed
    assert continued.content == "finished the job"
    record = continued.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    # The pause held the budget window open: the resume's attempt is the first.
    assert record.budget_baseline == 0
    assert len(record.attempts) == 1
    assert record.attempts[0].verdicts[0].passed is True
