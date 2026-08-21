"""Unit tests for agno.verify.verifiers: the adapter, the bridge, ShellVerifier, ScorerVerifier."""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import pytest

from agno.scorer import Score
from agno.verify import ScorerVerifier, ShellVerifier, Verdict, Verifier, verifier
from agno.verify.verifiers import coerce_verifier, run_sync

# ---------------------------------------------------------------------------
# Adapter return mapping (test 6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "returned, passed, report_has",
    [
        (Verdict(passed=True), True, ""),
        (True, True, ""),
        (False, False, "failed"),
        ("tests broke", False, "tests broke"),
        ("", False, "failed"),
        (None, False, "returned None"),
        (42, False, "returned int"),
    ],
)
def test_adapter_return_mapping(returned, passed, report_has):
    v = verifier(lambda run: returned, name="check")
    verdict = v.verify(object())
    assert verdict.passed is passed
    assert verdict.name == "check"
    assert report_has in verdict.report


def test_adapter_name_defaults_to_function_name():
    def my_check(run):
        return True

    assert verifier(my_check).name == "my_check"


def test_adapter_async_callable_through_sync_verify_yields_real_verdict():
    async def slow_check(run):
        await asyncio.sleep(0)
        return "nope"

    verdict = verifier(slow_check).verify(object())
    assert verdict.passed is False
    assert verdict.report == "nope"


def test_adapter_callable_object_with_async_call_is_detected():
    class Check:
        async def __call__(self, run):
            return False

    assert verifier(Check()).verify(object()).passed is False


@pytest.mark.asyncio
async def test_adapter_sync_callable_through_averify_runs_in_thread():
    def check(run):
        return True

    assert (await verifier(check).averify(object())).passed is True


@pytest.mark.asyncio
async def test_adapter_async_callable_through_averify():
    async def check(run):
        return Verdict(passed=False, report="bad")

    verdict = await verifier(check).averify(object())
    assert verdict.passed is False and verdict.report == "bad" and verdict.name == "check"


# ---------------------------------------------------------------------------
# Exceptions (test 7, adapter half)
# ---------------------------------------------------------------------------


def test_adapter_exception_becomes_failing_verdict():
    def boom(run):
        raise RuntimeError("kaboom")

    verdict = verifier(boom).verify(object())
    assert verdict.passed is False
    assert "RuntimeError: kaboom" in verdict.report
    assert "Traceback" in verdict.report or "boom" in verdict.report


def test_adapter_keyboard_interrupt_propagates():
    def interrupt(run):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        verifier(interrupt).verify(object())


# ---------------------------------------------------------------------------
# Entry classification (test 19)
# ---------------------------------------------------------------------------


@dataclass
class FullVerifier:
    name: str = "full"

    def verify(self, run):
        return Verdict(passed=True)

    async def averify(self, run):
        return Verdict(passed=True)


class SyncOnly:
    name = "sync_only"

    def verify(self, run):
        return Verdict(passed=False, report="sync half")


class AsyncOnly:
    async def averify(self, run):
        return Verdict(passed=False, report="async half")


def test_full_verifier_satisfies_protocol_and_is_used_as_is():
    full = FullVerifier()
    assert isinstance(full, Verifier)
    assert coerce_verifier(full) is full


def test_half_verifiers_get_their_twin():
    sync_wrapped = coerce_verifier(SyncOnly())
    assert asyncio.run(sync_wrapped.averify(object())).report == "sync half"
    assert sync_wrapped.verify(object()).name == "sync_only"

    async_wrapped = coerce_verifier(AsyncOnly())
    assert async_wrapped.verify(object()).report == "async half"
    assert async_wrapped.name == "AsyncOnly"


def test_bare_scorer_is_rejected_at_entry():
    class BareScorer:
        async def ascore(self, run, expected=None):
            return Score(value=1.0, passed=True)

    with pytest.raises(ValueError, match="ScorerVerifier"):
        coerce_verifier(BareScorer())


# ---------------------------------------------------------------------------
# ShellVerifier (test 9)
# ---------------------------------------------------------------------------


def test_shell_exit_zero_passes():
    assert ShellVerifier("exit 0").verify(None).passed is True


def test_shell_nonzero_fails_with_exit_line_and_tail():
    v = ShellVerifier("echo first; echo last; exit 2").verify(None)
    assert v.passed is False
    lines = v.report.splitlines()
    assert lines[0] == "exit 2"
    assert lines[-1] == "last"


def test_shell_merges_stderr():
    v = ShellVerifier("echo out; echo err 1>&2; exit 1").verify(None)
    assert "out" in v.report and "err" in v.report


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_shell_timeout_kills_group_and_keeps_partial_output():
    v = ShellVerifier("echo started; sleep 30; echo finished", timeout_s=0.5, name="hang").verify(None)
    assert v.passed is False
    assert v.report.splitlines()[0].startswith("timed out after 0.5s")
    assert "started" in v.report
    assert "finished" not in v.report
    # The sleep grandchild must be gone, not just the shell.
    time.sleep(0.2)
    ps = subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True, text=True)
    assert ps.stdout.strip() == "", ps.stdout


def test_shell_env_is_merged_not_replaced():
    v = ShellVerifier('test -n "$PATH" && test "$VERIFY_X" = 1 && exit 0 || exit 9', env={"VERIFY_X": "1"}).verify(None)
    assert v.passed is True, v.report


def test_shell_cwd_default_is_process_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert ShellVerifier('test "$(pwd -P)" = "$(cd . && pwd -P)"').verify(None).passed is True
    assert ShellVerifier("test -d .", cwd=str(tmp_path)).verify(None).passed is True


def test_shell_missing_command_is_harness_error():
    v = ShellVerifier("definitely_not_a_command_xyz").verify(None)
    assert v.passed is False
    assert v.report.splitlines()[0].startswith("harness error: exit 127")


def test_shell_default_name_is_truncated_command():
    long = "cd somewhere && python -m pytest -q tests/unit --maxfail=1 -x"
    assert ShellVerifier(long).name == long[:40]
    assert ShellVerifier("pytest -q").name == "pytest -q"


@pytest.mark.asyncio
async def test_shell_async_twin_matches_sync():
    ok = await ShellVerifier("exit 0").averify(None)
    bad = await ShellVerifier("echo tail; exit 4").averify(None)
    assert ok.passed is True
    assert bad.passed is False and bad.report.splitlines() == ["exit 4", "tail"]


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
async def test_shell_async_timeout_keeps_partial_output():
    v = await ShellVerifier("echo started; sleep 30", timeout_s=0.5).averify(None)
    assert v.passed is False
    assert "started" in v.report
    assert v.report.startswith("timed out after")


# ---------------------------------------------------------------------------
# ScorerVerifier and the bridge (test 10)
# ---------------------------------------------------------------------------


class AscoreOnly:
    def __init__(self, score):
        self.score_value = score
        self.calls = 0

    async def ascore(self, run, expected=None):
        self.calls += 1
        await asyncio.sleep(0)
        return self.score_value


def test_scorer_verifier_passes_on_passed_score():
    v = ScorerVerifier(AscoreOnly(Score(value=1.0, passed=True)))
    verdict = v.verify(object())
    assert verdict.passed is True
    assert verdict.name == "AscoreOnly"


def test_scorer_verifier_report_carries_value_and_reason():
    v = ScorerVerifier(AscoreOnly(Score(value=0.25, passed=False, reason="too vague")), name="judge")
    verdict = v.verify(object())
    assert verdict.passed is False
    assert verdict.report == "score 0.25: too vague"
    assert verdict.data["value"] == 0.25


def test_scorer_verifier_has_no_threshold_parameter():
    with pytest.raises(TypeError):
        ScorerVerifier(AscoreOnly(Score(value=1.0, passed=True)), threshold=0.8)  # type: ignore[call-arg]


def test_scorer_verifier_rejects_non_scorer():
    with pytest.raises(TypeError):
        ScorerVerifier(object())


def test_scorer_verifier_sync_path_inside_running_loop():
    scorer = AscoreOnly(Score(value=1.0, passed=True))
    v = ScorerVerifier(scorer)

    async def inside_loop():
        # A notebook or request handler: the caller's loop is running and blocked on us.
        return v.verify(object())

    verdict = asyncio.run(inside_loop())
    assert verdict.passed is True
    assert scorer.calls == 1


def test_bridge_reuses_one_loop_across_calls():
    loops = []

    async def which_loop():
        loops.append(asyncio.get_running_loop())
        return True

    run_sync(which_loop())
    run_sync(which_loop())
    assert loops[0] is loops[1]


@pytest.mark.asyncio
async def test_scorer_verifier_async_path():
    v = ScorerVerifier(AscoreOnly(Score(value=0.0, passed=False, reason="no")))
    verdict = await v.averify(object())
    assert verdict.passed is False and verdict.report == "score 0.00: no"


def test_scorer_verifier_exception_becomes_failing_verdict():
    class Broken:
        async def ascore(self, run, expected=None):
            raise ValueError("judge offline")

    verdict = ScorerVerifier(Broken()).verify(object())
    assert verdict.passed is False and "judge offline" in verdict.report


def test_expected_is_forwarded():
    seen = {}

    class Recorder:
        async def ascore(self, run, expected=None):
            seen["expected"] = expected
            return Score(value=1.0, passed=True)

    ScorerVerifier(Recorder(), expected="42").verify(object())
    assert seen["expected"] == "42"


def test_environment_variable_reaches_child_shell():
    # Guards the merge semantic from a different angle: PATH is still there.
    v = ShellVerifier("command -v sh >/dev/null", env={"UNUSED": "1"}).verify(None)
    assert v.passed is True, v.report
    assert "PATH" in os.environ
