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
from agno.verify.verifiers import GuardedVerifier, coerce_verifier, run_sync

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


@pytest.mark.timeout(10)
@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_base_exception_in_async_verifier_propagates_through_bridge(exc_type):
    async def interrupt(run):
        raise exc_type

    with pytest.raises(exc_type):
        verifier(interrupt).verify(object())
    # The bridge survives: the next call still works.
    assert verifier(lambda run: True).verify(object()).passed is True


def test_adapter_exception_report_keeps_the_traceback_tail():
    def deep(run):
        def inner():
            raise RuntimeError("deep failure")

        inner()

    report = verifier(deep).verify(object()).report
    assert report.startswith("RuntimeError: deep failure")
    assert "in inner" in report and 'raise RuntimeError("deep failure")' in report


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


def test_full_verifier_satisfies_protocol_and_runs_behind_the_guard():
    full = FullVerifier()
    assert isinstance(full, Verifier)
    guarded = coerce_verifier(full)
    assert isinstance(guarded, GuardedVerifier) and guarded.inner is full
    assert guarded.name == "full"
    assert guarded.verify(object()).passed is True
    assert asyncio.run(guarded.averify(object())).passed is True


def test_full_verifier_exception_and_non_verdict_return_are_guarded():
    class Raises:
        name = "judge"

        def verify(self, run):
            raise ConnectionError("judge endpoint refused")

        async def averify(self, run):
            raise ConnectionError("judge endpoint refused")

    class ReturnsBool:
        name = "loose"

        def verify(self, run):
            return True

        async def averify(self, run):
            return None

    raising = coerce_verifier(Raises())
    assert "ConnectionError: judge endpoint refused" in raising.verify(object()).report
    assert "ConnectionError: judge endpoint refused" in asyncio.run(raising.averify(object())).report
    loose = coerce_verifier(ReturnsBool())
    assert loose.verify(object()).passed is True
    assert "returned None" in asyncio.run(loose.averify(object())).report


def test_half_verifiers_get_their_twin():
    sync_wrapped = coerce_verifier(SyncOnly())
    assert asyncio.run(sync_wrapped.averify(object())).report == "sync half"
    assert sync_wrapped.verify(object()).name == "sync_only"

    async_wrapped = coerce_verifier(AsyncOnly())
    assert async_wrapped.verify(object()).report == "async half"
    assert async_wrapped.name == "AsyncOnly"


def test_async_def_verify_is_treated_as_the_async_half():
    class AsyncUnderSyncName:
        async def verify(self, run):
            return "wrong name, right half"

    wrapped = coerce_verifier(AsyncUnderSyncName())
    assert wrapped.verify(object()).report == "wrong name, right half"
    assert asyncio.run(wrapped.averify(object())).report == "wrong name, right half"


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


def _grandchild_alive(marker: str) -> bool:
    ps = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    return ps.stdout.strip() != ""


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_shell_timeout_kills_group_and_keeps_partial_output():
    marker = f"sleep 30.{os.getpid()}"
    v = ShellVerifier(f"echo started; {marker}; echo finished", timeout_s=0.5, name="hang").verify(None)
    assert v.passed is False
    assert v.report.splitlines()[0].startswith("timed out after 0.5s")
    assert "started" in v.report
    assert "finished" not in v.report
    # The sleep grandchild must be gone, not just the shell.
    time.sleep(0.2)
    assert not _grandchild_alive(marker)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_shell_timeout_applies_after_child_closes_its_pipes():
    # A child that closes stdout/stderr and keeps running must still hit the deadline.
    marker = f"sleep 25.{os.getpid()}"
    started = time.monotonic()
    v = ShellVerifier(f"echo begin; exec 1>/dev/null 2>&1; {marker}", timeout_s=1.0).verify(None)
    assert time.monotonic() - started < 8
    assert v.passed is False and v.report.startswith("timed out after 1s") and "begin" in v.report
    time.sleep(0.2)
    assert not _grandchild_alive(marker)


def test_shell_env_is_merged_not_replaced(monkeypatch):
    monkeypatch.setenv("VERIFY_INHERITED", "from-parent")
    v = ShellVerifier(
        'test "$VERIFY_INHERITED" = from-parent && test "$VERIFY_X" = 1 && exit 0 || exit 9',
        env={"VERIFY_X": "1"},
    ).verify(None)
    assert v.passed is True, v.report


def test_shell_cwd_default_is_process_cwd_and_cwd_is_honoured(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.chdir(elsewhere)
    assert ShellVerifier(f'test "$(pwd -P)" = "{elsewhere.resolve()}"').verify(None).passed is True
    assert ShellVerifier(f'test "$(pwd -P)" = "{target.resolve()}"', cwd=str(target)).verify(None).passed is True
    assert ShellVerifier(f'test "$(pwd -P)" = "{target.resolve()}"').verify(None).passed is False


def test_shell_child_does_not_inherit_stdin(tmp_path):
    """Run the check inside a child that HAS real stdin. pytest's own stdin is already closed,
    so an in-process assertion passes whether or not the verifier redirects stdin at all."""
    import os
    import subprocess
    import sys
    import textwrap

    script = tmp_path / "stdin_probe.py"
    script.write_text(
        textwrap.dedent("""
        from agno.verify import ShellVerifier
        v = ShellVerifier("read -r line && exit 3 || exit 7", timeout_s=10).verify(None)
        print("RC", v.data["returncode"], flush=True)
        """)
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), os.getcwd()]))}
    proc = subprocess.run(
        [sys.executable, str(script)], input=b"a line the child must not see\n", capture_output=True, env=env
    )
    # exit 7 = the read found EOF. exit 3 = the child inherited the parent's stdin.
    assert b"RC 7" in proc.stdout, proc.stdout + proc.stderr


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


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
async def test_shell_async_timeout_applies_after_child_closes_its_pipes():
    marker = f"sleep 26.{os.getpid()}"
    started = time.monotonic()
    v = await ShellVerifier(f"echo begin; exec 1>/dev/null 2>&1; {marker}", timeout_s=1.0).averify(None)
    assert time.monotonic() - started < 8
    assert v.passed is False and v.report.startswith("timed out after 1s") and "begin" in v.report
    await asyncio.sleep(0.2)
    assert not _grandchild_alive(marker)


@pytest.mark.asyncio
async def test_shell_async_cwd_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFY_INHERITED", "from-parent")
    v = await ShellVerifier(
        f'test "$(pwd -P)" = "{tmp_path.resolve()}" && test "$VERIFY_INHERITED" = from-parent && test "$X" = 1',
        cwd=str(tmp_path),
        env={"X": "1"},
    ).averify(None)
    assert v.passed is True, v.report


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


def test_scorer_verifier_never_calls_the_scorers_own_score():
    class WithSyncScore(AscoreOnly):
        def score(self, run, expected=None):
            raise AssertionError("score() must not be used")

    v = ScorerVerifier(WithSyncScore(Score(value=1.0, passed=True)))
    assert v.verify(object()).passed is True


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


def test_a_real_averify_outranks_an_async_verify():
    """Classifying halves purely by what they ARE lets an `async def verify` claim the async
    slot and shadow a genuine averify, which is the half the author meant to be awaited."""
    called = []

    class Both:
        name = "both"

        async def verify(self, run):
            called.append("verify")
            return True

        async def averify(self, run):
            called.append("averify")
            return True

    verdict = asyncio.run(coerce_verifier(Both()).averify(None))
    assert verdict.passed is True
    assert called == ["averify"]
