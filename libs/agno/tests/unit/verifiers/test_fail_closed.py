"""Regression tests for the fail-closed and resource-safety rules.

A non-bool can never verify a run; a shell child can never outlive its verifier; a nested
sync verifier can never deadlock the bridge; the report caps hold for any input.
"""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
import tracemalloc
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.verifiers import (
    REPORT_CAP_BYTES,
    ScorerVerifier,
    ShellVerifier,
    Verdict,
    VerificationAttempt,
    VerificationConfig,
    check,
    verifier,
)
from agno.verifiers._gate import arun_checks, run_checks
from agno.verifiers.types import ELISION, cap_text

# ---------------------------------------------------------------------------
# Only a real bool decides a run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("garbage", ["false", "no", 1, 2, 0.42, [0], object()])
def test_non_bool_verdict_passed_fails_closed(garbage):
    v = Verdict(passed=garbage)
    assert v.passed is False
    assert "only a real bool decides a run" in v.report


def test_bool_verdict_passed_untouched():
    assert Verdict(passed=True).passed is True
    assert Verdict(passed=False).passed is False
    assert "only a real bool" not in Verdict(passed=True).report


@pytest.mark.parametrize("garbage", ["no", "false", 1, 0.42, [0]])
def test_scorer_verifier_non_bool_passed_fails_closed(garbage):
    class Sloppy:
        async def ascore(self, run_output, expected=None):
            class Score:
                value = 0.9
                passed = garbage
                reason = "judge said yes-ish"
                detail = None

            return Score()

    verdict = ScorerVerifier(Sloppy()).verify(object())
    assert verdict.passed is False
    assert "only a real bool decides a run" in verdict.report


def test_attempt_passed_is_strict_even_after_mutation():
    v = Verdict(passed=True)
    v.passed = "later-mutated"  # bypasses __post_init__
    attempt = VerificationAttempt(index=0, verdicts=[v])
    assert attempt.passed is False


# ---------------------------------------------------------------------------
# Caps hold for any input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap", [0, 1, 4, 8, 15, 16, 17, 40])
def test_cap_text_never_exceeds_the_cap(cap):
    for text in ("x" * 100, "é" * 100, "日本語テキスト" * 20):
        assert len(cap_text(text, cap).encode("utf-8")) <= cap


def test_cap_text_keeps_marker_when_it_fits():
    out = cap_text("x" * 100, 40)
    assert ELISION in out


# ---------------------------------------------------------------------------
# Bridge re-entrancy
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_nested_sync_verifier_inside_async_verifier_does_not_deadlock():
    from agno.scorer import Score

    class InnerScorer:
        async def ascore(self, run_output, expected=None):
            return Score(value=0.0, passed=False, reason="inner says no")

    inner = ScorerVerifier(InnerScorer(), name="inner")

    async def outer(run_output):
        verdict = inner.verify(run_output)  # sync path, from ON the bridge loop
        return verdict.report

    result = verifier(outer, name="outer").verify(object())
    assert result.passed is False
    assert "inner says no" in result.report
    # The bridge survives for later verifications.
    assert verifier(lambda run_output: True).verify(object()).passed is True


@pytest.mark.timeout(30)
def test_bridge_reentrancy_depth_three():
    async def level3(run_output):
        return "deep no"

    v3 = verifier(level3, name="l3")

    async def level2(run_output):
        return v3.verify(run_output).report

    v2 = verifier(level2, name="l2")

    async def level1(run_output):
        return v2.verify(run_output).report

    verdict = verifier(level1, name="l1").verify(object())
    assert verdict.report == "deep no"


# ---------------------------------------------------------------------------
# Bounded shell buffering
# ---------------------------------------------------------------------------


def _big_output_cmd(mib: int) -> str:
    return f'{sys.executable} -c "import sys; [sys.stdout.write(chr(65 + i % 26) * 65536) for i in range({mib * 16})]"; echo LAST-LINE; exit 1'


def test_shell_memory_stays_bounded_for_large_output():
    tracemalloc.start()
    verdict = ShellVerifier(_big_output_cmd(8), timeout_s=60).verify(None)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, f"peak {peak} bytes for an 8 MiB child"
    assert verdict.passed is False
    assert verdict.report.splitlines()[0] == "exit 1"
    assert "LAST-LINE" in verdict.report  # the tail survived the bounding
    assert len(verdict.report.encode("utf-8")) <= REPORT_CAP_BYTES


@pytest.mark.asyncio
async def test_shell_async_memory_stays_bounded_for_large_output():
    tracemalloc.start()
    verdict = await ShellVerifier(_big_output_cmd(8), timeout_s=60).averify(None)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    assert verdict.report.splitlines()[0] == "exit 1"
    assert "LAST-LINE" in verdict.report


def test_small_output_report_is_untouched_by_the_bounding():
    verdict = ShellVerifier("echo first; echo second; exit 3").verify(None)
    assert verdict.report == "exit 3\nfirst\nsecond"


# ---------------------------------------------------------------------------
# Process-group cleanup on cancellation and interruption
# ---------------------------------------------------------------------------


def _alive(marker: str) -> bool:
    ps = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    return ps.stdout.strip() != ""


@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_cancelling_averify_kills_the_process_group():
    marker = f"sleep 27.{os.getpid()}"

    async def scenario():
        task = asyncio.ensure_future(ShellVerifier(f"echo go; {marker}", timeout_s=120).averify(None))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    time.sleep(0.3)
    assert not _alive(marker)


@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform == "win32", reason="signals are POSIX here")
def test_sigint_during_sync_verify_kills_the_process_group(tmp_path):
    marker = f"sleep 28.{os.getpid()}"
    script = tmp_path / "runner.py"
    script.write_text(
        textwrap.dedent(f"""
        from agno.verifiers import ShellVerifier
        print("READY", flush=True)
        try:
            ShellVerifier("echo go; {marker}", timeout_s=120).verify(None)
        except KeyboardInterrupt:
            print("INTERRUPTED", flush=True)
            raise SystemExit(3)
        """)
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), os.getcwd()]))}
    child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True, env=env)
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "READY"
    time.sleep(0.8)
    child.send_signal(signal.SIGINT)
    out, _ = child.communicate(timeout=15)
    assert "INTERRUPTED" in out
    time.sleep(0.3)
    assert not _alive(marker)


def test_mixed_nesting_through_to_thread_does_not_deadlock_the_bridge(tmp_path):
    """Async verifier on the bridge -> a sync call that escapes to a private loop (parking the
    bridge thread in join) -> that loop's `to_thread` running a sync-only verifier -> a sync
    call back out. The escape marker has to survive `asyncio.to_thread`, which copies the
    context but not thread-locals; if it does not, the submission lands on the parked bridge
    loop and the process hangs with no message.

    Bounded by the subprocess deadline rather than @pytest.mark.timeout, so it fails the run
    instead of wedging it even where pytest-timeout is not installed.
    """
    script = tmp_path / "nested.py"
    script.write_text(
        textwrap.dedent("""
        from agno.verifiers import verifier
        from agno.verifiers.base import coerce_verifier

        async def leaf(run_output):
            return True
        v_leaf = verifier(leaf, name="leaf")

        class SyncOnlyC:                       # reached through the derived async half
            name = "C"
            def verify(self, run_output):
                return v_leaf.verify(run_output)   # run_sync from a to_thread worker
        v_c = coerce_verifier(SyncOnlyC())

        async def b(run_output):
            return await v_c.averify(run_output)   # -> asyncio.to_thread on the private loop
        v_b = verifier(b, name="B")

        async def outer(run_output):
            return v_b.verify(run_output)          # sync call while ON the bridge thread
        print("RESULT", verifier(outer, name="outer").verify(object()).passed, flush=True)
        """)
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), os.getcwd()]))}
    child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True, env=env)
    try:
        out, _ = child.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise AssertionError("the bridge deadlocked on mixed sync/async nesting through to_thread")
    assert "RESULT True" in out, out


# ---------------------------------------------------------------------------
# A check cannot skip itself: only the loop's run_when branch marks a skip
# ---------------------------------------------------------------------------


class _ScriptedModel(Model):
    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "_ScriptedModel":
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


def test_check_returned_skipped_failure_still_gates_through_the_agent():
    def sneaky(run_output):
        return Verdict(passed=False, report="broken, but claims it was skipped", skipped=True)

    model = _ScriptedModel(
        [ModelResponse(role="assistant", content="claimed"), ModelResponse(role="assistant", content="claimed again")]
    )
    agent = Agent(model=model, verifiers=[sneaky], verification=VerificationConfig(max_attempts=2))
    out = agent.run("go")
    assert model.calls == 2, "a required failure must re-enter the model, however the check flagged itself"
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    for attempt in out.verification.attempts:
        assert attempt.passed is False
        assert attempt.verdicts[0].skipped is False
    reports = [m for m in (out.messages or []) if m.role == "user" and "<verification" in str(m.content)]
    assert len(reports) == 1
    assert "[FAIL] sneaky: broken, but claims it was skipped" in str(reports[0].content)
    assert "[SKIP]" not in str(reports[0].content)


def test_run_when_skip_is_still_recorded_and_non_gating():
    def never_runs(run_output):
        raise AssertionError("run_when said no; the check must not run")

    model = _ScriptedModel([ModelResponse(role="assistant", content="done")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: True, check(never_runs, run_when=lambda verdicts: False)],
    )
    out = agent.run("go")
    assert model.calls == 1
    assert out.verification.status == "verified"
    skipped_verdict = out.verification.attempts[0].verdicts[1]
    assert skipped_verdict.skipped is True
    assert skipped_verdict.passed is True


def test_run_checks_stamps_skipped_false_on_a_verdict_the_check_returned():
    def sneaky(run_output):
        return Verdict(passed=False, report="failing", skipped=True)

    result = run_checks([verifier(sneaky)], run_output=object())
    assert result.passed is False
    assert result.verdicts[0].skipped is False
    assert result.verdicts[0].gates is True


@pytest.mark.asyncio
async def test_arun_checks_stamps_skipped_false_on_a_verdict_the_check_returned():
    async def sneaky(run_output):
        return Verdict(passed=False, report="failing", skipped=True)

    result = await arun_checks([verifier(sneaky)], run_output=object())
    assert result.passed is False
    assert result.verdicts[0].skipped is False
    assert result.verdicts[0].gates is True
