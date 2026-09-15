"""Per-check policy through the real Agent gate: required, max_retries, run_condition, stop_on_failure.

Policy rides the check; the shared loop budget stays on the mount. These cases pin the
boundary between the two.
"""

import pytest

from agno.agent import Agent
from agno.run.base import RunStatus
from agno.verifiers import ShellVerifier, Verdict, VerificationConfig, verifier
from agno.verifiers._gate import run_checks

from .conftest import ScriptedModel, _reports, _run_variant, _text

RUN_MODES = pytest.mark.parametrize("mode", ["run", "arun"])


# ---------------------------------------------------------------------------
# required=False: advisory checks report but never gate
# ---------------------------------------------------------------------------


def test_advisory_failure_shows_as_warn_when_a_required_check_fails():
    calls = {"n": 0}

    def report_missing(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "report.md is missing"

    def lint(run_output):
        return "3 style findings"

    model = ScriptedModel([_text("claimed"), _text("done")])
    agent = Agent(model=model, verifiers=[report_missing, verifier(lint, required=False)])
    out = agent.run("go")
    assert out.verification.status == "verified"
    reports = _reports(out)
    assert len(reports) == 1
    body = str(reports[0].content)
    assert "[FAIL] report_missing: report.md is missing" in body
    assert "[WARN] lint: 3 style findings (advisory)" in body


def test_all_advisory_verifies_with_warnings_on_record():
    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[verifier(lambda run_output: "meh", name="style", required=False)])
    out = agent.run("go")
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    verdict = out.verification.attempts[0].verdicts[0]
    assert verdict.passed is False
    assert verdict.required is False


# ---------------------------------------------------------------------------
# max_retries: the check itself retries before a failure counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("passes", [True, False], ids=["passes-on-retry", "exhausted"])
@RUN_MODES
async def test_rerun_retries_a_flaky_check_within_one_attempt(mode, passes):
    calls = {"n": 0}

    def flaky(run_output):
        calls["n"] += 1
        return True if passes and calls["n"] >= 3 else "transient failure"

    model = ScriptedModel([_text("done")])
    agent = Agent(
        model=model,
        verifiers=[verifier(flaky, max_retries=2)],
        verification=VerificationConfig(max_attempts=1),
    )
    out = await _run_variant(agent, mode)
    assert model.calls == 1, "the model must not pay for a flaky check"
    assert calls["n"] == 3
    assert len(out.verification.attempts) == 1
    if passes:
        assert out.verification.status == "verified"
    else:
        assert out.status == RunStatus.unverified


# ---------------------------------------------------------------------------
# run_condition: gate expensive checks on earlier verdicts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cheap_passes", [False, True], ids=["predicate-false", "predicate-true"])
@RUN_MODES
async def test_run_when_skips_and_records_without_gating(mode, cheap_passes):
    judge_calls = {"n": 0}

    def cheap(run_output):
        return True if cheap_passes else "cheap check failing"

    def required_passing(verdicts):
        return all(v.passed for v in verdicts if v.required and not v.skipped)

    def judge(run_output):
        judge_calls["n"] += 1
        return True

    model = ScriptedModel([_text("done")])
    agent = Agent(
        model=model,
        verifiers=[cheap, verifier(judge, run_condition=required_passing)],
        verification=VerificationConfig(max_attempts=1),
    )
    out = await _run_variant(agent, mode)
    verdict = out.verification.attempts[0].verdicts[1]
    assert verdict.name == "judge"
    if cheap_passes:
        assert judge_calls["n"] == 1
        assert out.verification.status == "verified"
        assert verdict.skipped is False
    else:
        assert judge_calls["n"] == 0, "the judge must not run while the cheap check fails"
        assert out.status == RunStatus.unverified
        assert verdict.skipped is True
        assert verdict.passed is True


def test_broken_run_when_runs_the_check():
    ran = {"n": 0}

    def boom(verdicts):
        raise RuntimeError("broken predicate")

    def the_check(run_output):
        ran["n"] += 1
        return True

    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[verifier(the_check, run_condition=boom)])
    out = agent.run("go")
    assert ran["n"] == 1, "a broken predicate must not silently skip a gate"
    assert out.verification.status == "verified"


async def test_run_refuses_an_async_run_condition_and_arun_awaits_it():
    async def only_when_ready(verdicts):
        return True

    check = verifier(lambda run_output: True, name="gated", run_condition=only_when_ready)
    agent = Agent(model=ScriptedModel([_text("done")]), verifiers=[check])
    with pytest.raises(ValueError, match=r"Cannot use only_when_ready \(an async run_condition\) with `run\(\)`"):
        agent.run("go")
    assert (await agent.arun("go")).verification.status == "verified"


# ---------------------------------------------------------------------------
# A check cannot skip itself: only the run_condition branch marks a skip
# ---------------------------------------------------------------------------


def test_shared_runner_stamps_skipped_false_on_a_verdict_the_check_returned():
    def self_skipping(run_output):
        return Verdict(passed=False, report="failing", skipped=True)

    result = run_checks([verifier(self_skipping)], run_output=object())
    assert result.passed is False
    assert result.verdicts[0].skipped is False
    assert result.verdicts[0].gates is True


# ---------------------------------------------------------------------------
# stop_on_failure and fatal verdicts: retrying is pointless
# ---------------------------------------------------------------------------


def _repo_gone():
    def repo_gone(run_output):
        return "the repository no longer exists"

    return verifier(repo_gone, stop_on_failure=True)


@pytest.mark.parametrize(
    "build, fatal_verdict",
    [(_repo_gone, False), (lambda: ShellVerifier("definitely-not-a-command-9818"), True)],
    ids=["stop_on_failure", "fatal-verdict"],
)
@RUN_MODES
async def test_stop_on_failure_ends_the_run_immediately(mode, build, fatal_verdict):
    model = ScriptedModel([_text("claimed"), _text("again"), _text("again")])
    agent = Agent(model=model, verifiers=[build()], verification=VerificationConfig(max_attempts=5))
    out = await _run_variant(agent, mode)
    assert model.calls == 1, "no re-entry after a stop"
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "fatal"
    assert len(out.verification.attempts) == 1
    assert out.verification.attempts[0].verdicts[0].fatal is fatal_verdict


# ---------------------------------------------------------------------------
# The wrapper and construction errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build, error, match",
    [
        (lambda: verifier(lambda run_output: True, max_retries=-1), ValueError, None),
        (lambda: verifier(lambda run_output: True, run_condition=lambda unknown_name: True), TypeError, None),
        (
            lambda: verifier(ShellVerifier("exit 1", required=False), stop_on_failure=True),
            ValueError,
            "stop_on_failure=True contradicts required=False",
        ),
    ],
    ids=["negative-max-retries", "bad-run-condition-signature", "stop-on-failure-over-advisory"],
)
def test_check_wrapper_construction_errors(build, error, match):
    with pytest.raises(error, match=match):
        build()


def test_check_wrapper_is_not_double_wrapped_by_the_agent():
    seen = {}

    def probe(run_output, agent, session):
        seen["agent"] = agent
        seen["session"] = session
        return True

    model = ScriptedModel([_text("done")])
    a = Agent(model=model, verifiers=[verifier(probe, required=True)])
    out = a.run("go")
    assert out.verification.status == "verified"
    assert seen["agent"] is a, "owner routing must survive the verifier() wrapper"
    assert seen["session"] is not None


# ---------------------------------------------------------------------------
# verifier() overrides only the knobs it was passed
# ---------------------------------------------------------------------------


def test_check_preserves_declared_policy_for_knobs_not_passed():
    shell = ShellVerifier("exit 1", required=False, name="advisory shell")
    wrapped = verifier(shell, max_retries=1)
    assert wrapped.required is False, "a knob not passed to verifier() must keep the target's declaration"
    assert wrapped.max_retries == 1
    assert wrapped.stop_on_failure is False

    def predicate(verdicts):
        return True

    def lint(run_output):
        return True

    lint.required = False
    lint.run_condition = predicate
    wrapped = verifier(lint, max_retries=2)
    assert wrapped.required is False
    assert wrapped.run_condition is predicate
    assert wrapped.max_retries == 2

    # Explicit knobs still override the declared policy.
    assert verifier(shell, required=True).required is True
    assert verifier(shell, run_condition=None).run_condition is None
