"""Per-check policy through the real Agent gate: required, rerun, run_when, fatal.

Policy rides the check; the shared loop budget stays on the mount. These cases pin the
boundary between the two.
"""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.verifiers import ShellVerifier, Verdict, VerificationConfig, check


class ScriptedModel(Model):
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
    return ModelResponse(role="assistant", content=content)


# ---------------------------------------------------------------------------
# required=False: advisory checks report but never gate
# ---------------------------------------------------------------------------


def test_advisory_failure_does_not_gate():
    def lint(run_output):
        return "3 style findings"

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(lint, required=False), lambda run_output: True])
    out = agent.run("go")
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    verdicts = out.verification.attempts[0].verdicts
    assert verdicts[0].passed is False and verdicts[0].required is False
    assert verdicts[1].passed is True and verdicts[1].required is True


def test_advisory_failure_shows_as_warn_when_a_required_check_fails():
    calls = {"n": 0}

    def report_missing(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "report.md is missing"

    def lint(run_output):
        return "3 style findings"

    model = ScriptedModel([_text("claimed"), _text("done")])
    agent = Agent(model=model, verifiers=[report_missing, check(lint, required=False)])
    out = agent.run("go")
    assert out.verification.status == "verified"
    reports = [m for m in (out.messages or []) if m.role == "user" and "<verification" in str(m.content)]
    assert len(reports) == 1
    body = str(reports[0].content)
    assert "[FAIL] report_missing: report.md is missing" in body
    assert "[WARN] lint: 3 style findings (advisory)" in body


def test_all_advisory_verifies_with_warnings_on_record():
    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(lambda run_output: "meh", name="style", required=False)])
    out = agent.run("go")
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert out.verification.attempts[0].verdicts[0].passed is False


# ---------------------------------------------------------------------------
# rerun: the check itself retries before a failure counts
# ---------------------------------------------------------------------------


def test_rerun_retries_a_flaky_check_within_one_attempt():
    calls = {"n": 0}

    def flaky(run_output):
        calls["n"] += 1
        return True if calls["n"] >= 3 else "transient failure"

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(flaky, rerun=2)])
    out = agent.run("go")
    assert model.calls == 1, "the model must not pay for a flaky check"
    assert calls["n"] == 3
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1


def test_rerun_exhausted_still_fails_the_attempt():
    calls = {"n": 0}

    def flaky(run_output):
        calls["n"] += 1
        return "still failing"

    model = ScriptedModel([_text("nope")])
    agent = Agent(
        model=model,
        verifiers=[check(flaky, rerun=1)],
        verification=VerificationConfig(max_attempts=1),
    )
    out = agent.run("go")
    assert calls["n"] == 2
    assert out.status == RunStatus.unverified


# ---------------------------------------------------------------------------
# run_when: gate expensive checks on earlier verdicts
# ---------------------------------------------------------------------------


def test_run_when_skips_and_records_without_gating():
    judge_calls = {"n": 0}

    def cheap(run_output):
        return "cheap check failing"

    def required_passing(verdicts):
        return all(v.passed for v in verdicts if v.required and not v.skipped)

    def judge(run_output):
        judge_calls["n"] += 1
        return True

    model = ScriptedModel([_text("nope")])
    agent = Agent(
        model=model,
        verifiers=[cheap, check(judge, run_when=required_passing)],
        verification=VerificationConfig(max_attempts=1),
    )
    out = agent.run("go")
    assert judge_calls["n"] == 0, "the judge must not run while the cheap check fails"
    assert out.status == RunStatus.unverified
    verdicts = out.verification.attempts[0].verdicts
    assert verdicts[1].skipped is True
    assert verdicts[1].name == "judge"


def test_run_when_runs_the_check_once_predicate_allows():
    judge_calls = {"n": 0}

    def required_passing(verdicts):
        return all(v.passed for v in verdicts if v.required and not v.skipped)

    def judge(run_output):
        judge_calls["n"] += 1
        return True

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[lambda run_output: True, check(judge, run_when=required_passing)])
    out = agent.run("go")
    assert judge_calls["n"] == 1
    assert out.verification.status == "verified"
    assert not out.verification.attempts[0].verdicts[1].skipped


def test_broken_run_when_runs_the_check():
    ran = {"n": 0}

    def boom(verdicts):
        raise RuntimeError("broken predicate")

    def the_check(run_output):
        ran["n"] += 1
        return True

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(the_check, run_when=boom)])
    out = agent.run("go")
    assert ran["n"] == 1, "a broken predicate must not silently skip a gate"
    assert out.verification.status == "verified"


# ---------------------------------------------------------------------------
# fatal: retrying is pointless
# ---------------------------------------------------------------------------


def test_fatal_failure_ends_the_run_immediately():
    def repo_gone(run_output):
        return "the repository no longer exists"

    model = ScriptedModel([_text("claimed")])
    agent = Agent(
        model=model,
        verifiers=[check(repo_gone, fatal=True)],
        verification=VerificationConfig(max_attempts=5),
    )
    out = agent.run("go")
    assert model.calls == 1, "no re-entry after a fatal failure"
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "fatal"
    assert len(out.verification.attempts) == 1


def test_fatal_check_that_passes_does_not_stop_anything():
    calls = {"n": 0}

    def flaky_required(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "not yet"

    model = ScriptedModel([_text("claimed"), _text("done")])
    agent = Agent(model=model, verifiers=[flaky_required, check(lambda run_output: True, name="env ok", fatal=True)])
    out = agent.run("go")
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 2


# ---------------------------------------------------------------------------
# The wrapper, shipped-verifier kwargs, and construction errors
# ---------------------------------------------------------------------------


def test_shipped_verifier_takes_policy_kwargs():
    shell = ShellVerifier("exit 1", required=False, name="advisory shell")
    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[shell])
    out = agent.run("go")
    assert out.verification.status == "verified"
    assert out.verification.attempts[0].verdicts[0].required is False


def test_protocol_object_policy_attributes_are_honoured():
    class Advisory:
        name = "advisory object"
        required = False

        def verify(self, run_output, run_context):
            return Verdict(passed=False, report="always warns")

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[Advisory()])
    out = agent.run("go")
    assert out.verification.status == "verified"
    assert out.verification.attempts[0].verdicts[0].required is False


def test_check_wrapper_construction_errors():
    with pytest.raises(ValueError):
        check(lambda run_output: True, rerun=-1)
    with pytest.raises(TypeError):
        check(lambda run_output: True, run_when="not callable")
    with pytest.raises(TypeError):
        check(lambda run_output: True, run_when=lambda unknown_name: True)


def test_check_wrapper_is_not_double_wrapped_by_the_agent():
    seen = {}

    def probe(run_output, agent, session):
        seen["agent"] = agent
        seen["session"] = session
        return True

    model = ScriptedModel([_text("done")])
    a = Agent(model=model, verifiers=[check(probe, required=True)])
    out = a.run("go")
    assert out.verification.status == "verified"
    assert seen["agent"] is a, "owner routing must survive the check() wrapper"
    assert seen["session"] is not None


def test_events_carry_required_and_skipped():
    def lint(run_output):
        return "advisory finding"

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(lint, required=False)], store_events=True)
    out = agent.run("go")
    completed = [e for e in (out.events or []) if getattr(e, "event", "") == "VerificationCompleted"]
    assert len(completed) == 1
    payload = completed[0].verdicts[0]
    assert payload["required"] is False and payload["skipped"] is False


def test_policy_round_trips_through_persistence():
    import json

    from agno.run.agent import RunOutput

    def lint(run_output):
        return "advisory finding"

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[check(lint, required=False)])
    out = agent.run("go")
    back = RunOutput.from_dict(json.loads(json.dumps(out.to_dict(), default=str)))
    verdict = back.verification.attempts[0].verdicts[0]
    assert verdict.required is False and verdict.skipped is False


# ---------------------------------------------------------------------------
# Owner-named parameters are kind-matched, never aliased
# ---------------------------------------------------------------------------


def _fake_team():
    # Owner kind is classified by class name in the MRO; a class named Team stands in
    # for the real mount without importing agno.team.
    class Team:
        pass

    return Team()


def _fake_workflow():
    class Workflow:
        pass

    return Workflow()


def test_agent_mount_fills_only_the_agent_param():
    seen = {}

    def probe(run_output, agent, team, workflow):
        seen["agent"] = agent
        seen["team"] = team
        seen["workflow"] = workflow
        return True

    model = ScriptedModel([_text("done")])
    a = Agent(model=model, verifiers=[probe])
    out = a.run("go")
    assert out.verification.status == "verified"
    assert seen["agent"] is a
    assert seen["team"] is None
    assert seen["workflow"] is None


def test_shared_runner_kind_matches_a_team_owner():
    from agno.verifiers._gate import run_checks

    seen = {}

    def wants_team(run_output, team):
        seen["team"] = team
        return True

    def wants_agent(run_output, agent):
        seen["agent"] = agent
        return True

    owner = _fake_team()
    result = run_checks([check(wants_team), check(wants_agent)], run_output=object(), owner=owner)
    assert result.passed is True
    assert seen["team"] is owner
    assert seen["agent"] is None


def test_shared_runner_kind_matches_a_workflow_owner():
    import asyncio

    from agno.verifiers._gate import arun_checks, run_checks

    seen = {}

    def wants_workflow(run_output, workflow):
        seen["workflow"] = workflow
        return True

    def wants_agent(run_output, agent):
        seen["agent"] = agent
        return True

    owner = _fake_workflow()
    result = run_checks([check(wants_workflow), check(wants_agent)], run_output=object(), owner=owner)
    assert result.passed is True
    assert seen["workflow"] is owner
    assert seen["agent"] is None

    seen.clear()
    result = asyncio.run(arun_checks([check(wants_workflow), check(wants_agent)], run_output=object(), owner=owner))
    assert result.passed is True
    assert seen["workflow"] is owner
    assert seen["agent"] is None


def test_run_when_predicate_owner_is_kind_matched():
    from agno.verifiers._gate import run_checks

    seen = {}

    def predicate(team, workflow):
        seen["team"] = team
        seen["workflow"] = workflow
        return True

    owner = _fake_team()
    result = run_checks([check(lambda run_output: True, run_when=predicate)], run_output=object(), owner=owner)
    assert result.passed is True
    assert seen["team"] is owner
    assert seen["workflow"] is None


# ---------------------------------------------------------------------------
# check() overrides only the knobs it was passed
# ---------------------------------------------------------------------------


def test_check_preserves_declared_policy_for_knobs_not_passed():
    shell = ShellVerifier("exit 1", required=False, name="advisory shell")
    wrapped = check(shell, rerun=1)
    assert wrapped.required is False, "a knob not passed to check() must keep the target's declaration"
    assert wrapped.rerun == 1
    assert wrapped.fatal is False

    def predicate(verdicts):
        return True

    def lint(run_output):
        return True

    lint.required = False
    lint.run_when = predicate
    wrapped = check(lint, rerun=2)
    assert wrapped.required is False
    assert wrapped.run_when is predicate
    assert wrapped.rerun == 2


def test_check_explicit_knobs_still_override_declared_policy():
    shell = ShellVerifier("exit 1", required=False)
    assert check(shell, required=True).required is True
    assert check(shell, run_when=None).run_when is None


def test_check_fatal_over_a_declared_advisory_is_rejected():
    shell = ShellVerifier("exit 1", required=False)
    with pytest.raises(ValueError, match="fatal=True contradicts required=False"):
        check(shell, fatal=True)
