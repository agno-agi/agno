"""The verification gate through the real Team run functions, on scripted offline models.

Covers the four leader run variants (run, run(stream=True), arun, arun(stream=True)):
re-entry mechanics, statuses, the report message, team events, the system-message notice,
construction errors, persistence round-trips, a member with its own verifiers running
inside team delegation, and a tasks-mode exhaustion case.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.verifiers import VerificationConfig


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order."""

    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

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
    response = ModelResponse(role="assistant", content=content)
    response.event = ModelResponseEvent.assistant_response.value
    response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
    return response


def _tool(name: str, args: dict, tool_call_id: str) -> ModelResponse:
    response = ModelResponse(role="assistant")
    response.tool_calls = [
        {"id": tool_call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    ]
    response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
    return response


def fail_once():
    calls = {"n": 0}

    def report_exists(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "report.md is missing"

    return report_exists


def _member() -> Agent:
    return Agent(name="member", id="member", model=ScriptedModel([_text("member ok")]), telemetry=False)


def _team(leader_model: Model, **kwargs: Any) -> Team:
    kwargs.setdefault("members", [_member()])
    kwargs.setdefault("telemetry", False)
    return Team(model=leader_model, **kwargs)


def _run_variant(team: Team, mode: str, prompt: str = "go") -> TeamRunOutput:
    """Drive one of the four leader run variants to its final TeamRunOutput."""
    if mode == "run":
        return team.run(prompt)
    if mode == "arun":
        return asyncio.run(team.arun(prompt))
    if mode == "run_stream":
        events = list(team.run(prompt, stream=True, stream_events=True, yield_run_output=True))
        return [e for e in events if isinstance(e, TeamRunOutput)][-1]
    if mode == "arun_stream":

        async def collect():
            out = []
            async for e in team.arun(prompt, stream=True, stream_events=True, yield_run_output=True):
                out.append(e)
            return out

        events = asyncio.run(collect())
        return [e for e in events if isinstance(e, TeamRunOutput)][-1]
    raise AssertionError(mode)


MODES = ["run", "arun", "run_stream", "arun_stream"]


@pytest.mark.parametrize("mode", MODES)
def test_team_fail_then_pass_is_one_run(mode):
    model = ScriptedModel([_text("claimed done"), _text("actually done")])
    team = _team(model, verifiers=[fail_once()])
    out = _run_variant(team, mode)
    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert out.verification.stop_reason == "passed"
    assert len(out.verification.attempts) == 2
    assert out.verification.attempts[0].verdicts[0].passed is False
    assert out.verification.attempts[1].verdicts[0].passed is True
    reports = [m for m in (out.messages or []) if m.role == "user" and "<verification" in str(m.content)]
    assert len(reports) == 1
    assert "[FAIL] report_exists: report.md is missing" in reports[0].content
    assert 'attempt="1/3"' in reports[0].content
    assert out.content == "actually done"
    # The report is real transcript: persisted and replayed, not temporary.
    assert reports[0].add_to_agent_memory is True
    assert reports[0].temporary is False


@pytest.mark.parametrize("mode", MODES)
def test_team_exhausted_ends_unverified(mode):
    model = ScriptedModel([_text("nope")])
    team = _team(model, verifiers=[lambda run_output: "never good"])
    out = _run_variant(team, mode)
    assert model.calls == 3
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "exhausted"
    assert len(out.verification.attempts) == 3


@pytest.mark.parametrize("mode", MODES)
def test_team_pass_first_attempt(mode):
    model = ScriptedModel([_text("done")])
    team = _team(model, verifiers=[lambda run_output: True])
    out = _run_variant(team, mode)
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1


def test_team_construction_errors():
    with pytest.raises(ValueError):
        _team(ScriptedModel([_text("x")]), verifiers=[object()])
    with pytest.raises(TypeError):
        _team(ScriptedModel([_text("x")]), verifiers=[lambda unknown_name: True])


def test_team_notice_in_system_message():
    model = ScriptedModel([_text("done")])

    def report_exists(run_output):
        return True

    team = _team(model, verifiers=[report_exists], instructions="Do the thing.")
    out = team.run("go")
    system = out.messages[0]
    assert system.role == "system"
    assert "Completion is checked by the host" in str(system.content)
    assert "report_exists" in str(system.content)


def test_team_add_notice_false_suppresses_the_notice():
    model = ScriptedModel([_text("done")])
    team = _team(
        model,
        verifiers=[lambda run_output: True],
        verification=VerificationConfig(add_notice=False),
        instructions="Do the thing.",
    )
    out = team.run("go")
    assert "Completion is checked by the host" not in str(out.messages[0].content)


def test_team_no_verifiers_no_notice_no_record():
    model = ScriptedModel([_text("plain")])
    team = _team(model, instructions="x")
    out = team.run("hi")
    assert out.verification is None
    assert out.status == RunStatus.completed
    assert "Completion is checked" not in str(out.messages[0].content)


def test_team_stream_event_sequence():
    model = ScriptedModel([_text("claimed"), _text("real")])
    team = _team(model, verifiers=[fail_once()])
    events = list(team.run("go", stream=True, stream_events=True, yield_run_output=True))
    names = [getattr(e, "event", "") for e in events]
    assert names.count("TeamVerificationStarted") == 2
    assert names.count("TeamVerificationCompleted") == 2
    assert names.count("TeamRunContentCompleted") == 1
    assert names.index("TeamVerificationStarted") < names.index("TeamVerificationCompleted")
    assert names.index("TeamRunContentCompleted") > names.index("TeamVerificationCompleted")
    completed_events = [e for e in events if getattr(e, "event", "") == "TeamVerificationCompleted"]
    assert completed_events[0].passed is False and completed_events[0].attempt == 1
    assert completed_events[1].passed is True and completed_events[1].attempt == 2
    assert completed_events[1].stop_reason == "passed"
    assert completed_events[0].verdicts[0]["name"] == "report_exists"


def test_team_persistence_round_trip():
    model = ScriptedModel([_text("nope")])
    team = _team(model, verifiers=[lambda run_output: "still wrong"])
    out = team.run("go")
    data = json.loads(json.dumps(out.to_dict(), default=str))
    back = TeamRunOutput.from_dict(data)
    assert back.verification is not None
    assert back.verification.status == "unverified"
    assert back.verification.attempts[0].verdicts[0].report == "still wrong"
    assert back.status == RunStatus.unverified


def test_member_verifiers_run_inside_delegation():
    """A member with its own verifiers ends its run unverified inside team delegation,
    and the leader's TeamRunOutput surfaces that status on the member response."""
    member = Agent(
        name="member",
        id="member",
        model=ScriptedModel([_text("member claims done")]),
        verifiers=[lambda run_output: "member evidence missing"],
        verification=VerificationConfig(max_attempts=1),
        telemetry=False,
    )
    leader = ScriptedModel(
        [
            _tool("delegate_task_to_member", {"member_id": "member", "task": "do the thing"}, "tc-deleg"),
            _text("All done."),
        ]
    )
    team = Team(members=[member], model=leader, telemetry=False)
    out = team.run("go")
    # The team itself has no verifiers: its own run completes.
    assert out.status == RunStatus.completed
    assert out.verification is None
    assert len(out.member_responses) == 1
    member_run = out.member_responses[0]
    assert member_run.status == RunStatus.unverified
    assert member_run.verification is not None
    assert member_run.verification.status == "unverified"
    assert member_run.verification.stop_reason == "exhausted"


def releasable_verifier():
    """A verifier that fails until the test flips the switch — the first run exhausts its
    budget, the continuation passes."""
    state = {"pass": False}

    def check(run_output):
        return True if state["pass"] else "not good enough"

    return state, check


def test_team_continue_of_unverified_run_restarts_the_budget():
    """Continuing an unverified team run resumes in place, keeps the attempt history,
    and restarts the budget window for the new instruction."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state, check = releasable_verifier()
    team = _team(model, verifiers=[check], verification=VerificationConfig(max_attempts=2))
    out = team.run("go")
    assert out.status == RunStatus.unverified
    assert len(out.verification.attempts) == 2
    assert model.calls == 2

    state["pass"] = True
    continued = team.continue_run(run_response=out, input="try harder")
    assert continued.run_id == out.run_id
    assert continued.status == RunStatus.completed
    assert model.calls == 3
    record = continued.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert len(record.attempts) == 3
    assert record.budget_baseline == 2


def test_team_acontinue_of_unverified_run_restarts_the_budget():
    """Async twin: the gate in _acontinue_run runs after the shared model helper."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state, check = releasable_verifier()
    team = _team(model, verifiers=[check], verification=VerificationConfig(max_attempts=2))
    out = asyncio.run(team.arun("go"))
    assert out.status == RunStatus.unverified
    assert model.calls == 2

    state["pass"] = True
    continued = asyncio.run(team.acontinue_run(run_response=out, input="try harder", session_id=out.session_id))
    assert continued.status == RunStatus.completed
    assert model.calls == 3
    assert continued.verification.status == "verified"
    assert len(continued.verification.attempts) == 3


def test_team_continue_still_failing_stays_unverified():
    """A continuation that never passes re-exhausts the restarted budget and the
    continue path's terminal completed stamp does not overwrite unverified."""
    model = ScriptedModel([_text("try 1")])
    team = _team(model, verifiers=[lambda run_output: "still bad"], verification=VerificationConfig(max_attempts=1))
    out = team.run("go")
    assert out.status == RunStatus.unverified

    continued = team.continue_run(run_response=out, input="again")
    assert continued.status == RunStatus.unverified
    assert continued.verification.status == "unverified"
    assert continued.verification.stop_reason == "exhausted"
    assert len(continued.verification.attempts) == 2
    assert continued.verification.budget_baseline == 1


def test_team_continue_stream_of_unverified_run():
    """The gate in _continue_run_stream: a streamed continuation of an unverified run
    emits the verification events and ends verified."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state, check = releasable_verifier()
    team = _team(model, verifiers=[check], verification=VerificationConfig(max_attempts=2))
    out = team.run("go")
    assert out.status == RunStatus.unverified

    state["pass"] = True
    events = list(
        team.continue_run(run_response=out, input="try harder", stream=True, stream_events=True, yield_run_output=True)
    )
    names = [getattr(e, "event", "") for e in events]
    assert names.count("TeamVerificationStarted") == 1
    assert names.count("TeamVerificationCompleted") == 1
    continued = [e for e in events if isinstance(e, TeamRunOutput)][-1]
    assert continued.status == RunStatus.completed
    assert continued.verification.status == "verified"
    assert model.calls == 3


def test_team_acontinue_stream_of_unverified_run():
    """The gate in _acontinue_run_stream (team-level branch)."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state, check = releasable_verifier()
    team = _team(model, verifiers=[check], verification=VerificationConfig(max_attempts=2))
    out = asyncio.run(team.arun("go"))
    assert out.status == RunStatus.unverified

    state["pass"] = True

    async def collect():
        collected = []
        async for e in team.acontinue_run(
            run_response=out,
            input="try harder",
            session_id=out.session_id,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        ):
            collected.append(e)
        return collected

    events = asyncio.run(collect())
    names = [getattr(e, "event", "") for e in events]
    assert names.count("TeamVerificationStarted") == 1
    assert names.count("TeamVerificationCompleted") == 1
    continued = [e for e in events if isinstance(e, TeamRunOutput)][-1]
    assert continued.status == RunStatus.completed
    assert continued.verification.status == "verified"
    assert model.calls == 3


@pytest.mark.parametrize("mode", MODES)
def test_tasks_mode_exhausted_ends_unverified(mode):
    """Tasks mode: the gate wraps the whole task loop; a re-entry re-runs it. With no
    tasks the loop answers in two turns per window (answer + reminder), so three
    verification attempts cost six leader calls."""
    model = ScriptedModel([_text("no tasks needed, here is the answer")])
    team = _team(model, mode="tasks", verifiers=[lambda run_output: "still not verified"])
    out = _run_variant(team, mode)
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "exhausted"
    assert len(out.verification.attempts) == 3
    assert model.calls == 6
