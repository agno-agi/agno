"""Regression tests for the fail-closed and resource-safety round.

A non-bool can never verify a run; a shell child can never outlive its verifier; a nested
sync verifier can never deadlock the bridge; a giant name can never defeat the block cap.
"""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
import tracemalloc

import pytest

from agno.verify import (
    REPORT_CAP_BYTES,
    ScorerVerifier,
    ShellVerifier,
    Verdict,
    VerifierLimits,
    arun_verified,
    run_verified,
    verifier,
)
from agno.verify.runner import BLOCK_CAP_BYTES
from agno.verify.types import ELISION, cap_text

from .conftest import StubAgent

# ---------------------------------------------------------------------------
# F1: only a real bool decides a run
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


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_garbage_verdict_through_the_runner_is_unverified(mode):
    def sloppy(run):
        return Verdict(passed="false", report="looked fine to me")

    agent = StubAgent()
    if mode == "sync":
        result = run_verified(agent, "task", [sloppy], limits=VerifierLimits(max_continuations=1))
    else:
        result = asyncio.run(arun_verified(agent, "task", [sloppy], limits=VerifierLimits(max_continuations=1)))
    assert result.status == "unverified"
    assert "only a real bool decides a run" in result.attempts[0].verdicts[0].report


@pytest.mark.parametrize("garbage", ["no", "false", 1, 0.42, [0]])
def test_scorer_verifier_non_bool_passed_fails_closed(garbage):
    class Sloppy:
        async def ascore(self, run, expected=None):
            class Score:
                value = 0.9
                passed = garbage
                reason = "judge said yes-ish"
                detail = None

            return Score()

    verdict = ScorerVerifier(Sloppy()).verify(object())
    assert verdict.passed is False
    assert "only a real bool decides a run" in verdict.report


def test_non_str_verdict_name_is_normalised_and_renders():
    v = Verdict(passed=False, report="r", name=123)
    assert v.name == "123"
    agent = StubAgent()

    def named(run):
        return Verdict(passed=False, report="r", name=(1, 2))

    result = run_verified(agent, "task", [named], limits=VerifierLimits(max_continuations=1))
    assert result.status == "unverified"  # no crash
    assert "(1, 2)" in agent.continue_calls[0]["input"]


def test_attempt_passed_is_strict_even_after_mutation():
    from agno.verify import VerificationAttempt

    v = Verdict(passed=True)
    v.passed = "later-mutated"  # bypasses __post_init__
    attempt = VerificationAttempt(index=0, run_id="r", status="COMPLETED", verdicts=[v])
    assert attempt.passed is False


# ---------------------------------------------------------------------------
# F10: caps hold for any input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap", [0, 1, 4, 8, 15, 16, 17, 40])
def test_cap_text_never_exceeds_the_cap(cap):
    for text in ("x" * 100, "é" * 100, "日本語テキスト" * 20):
        assert len(cap_text(text, cap).encode("utf-8")) <= cap


def test_cap_text_keeps_marker_when_it_fits():
    out = cap_text("x" * 100, 40)
    assert ELISION in out


def test_one_giant_name_cannot_defeat_the_block_cap():
    def fail(run):
        return "nope"

    agent = StubAgent()
    run_verified(agent, "task", [verifier(fail, name="x" * 30000)], limits=VerifierLimits(max_continuations=1))
    block = agent.continue_calls[0]["input"]
    assert len(block.encode("utf-8")) <= BLOCK_CAP_BYTES
    assert block.rstrip().endswith("</verification>")


def test_hundreds_of_verifiers_cannot_defeat_the_block_cap():
    def fail(run):
        return "detail " * 30

    agent = StubAgent()
    names = [verifier(fail, name=f"check-number-{i}") for i in range(400)]
    run_verified(agent, "task", names, limits=VerifierLimits(max_continuations=1))
    block = agent.continue_calls[0]["input"]
    assert len(block.encode("utf-8")) <= BLOCK_CAP_BYTES
    assert block.rstrip().endswith("</verification>")
    assert "then end your turn again" in block


# ---------------------------------------------------------------------------
# F7: bridge re-entrancy
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_nested_sync_verifier_inside_async_verifier_does_not_deadlock():
    from agno.scorer import Score

    class InnerScorer:
        async def ascore(self, run, expected=None):
            return Score(value=0.0, passed=False, reason="inner says no")

    inner = ScorerVerifier(InnerScorer(), name="inner")

    async def outer(run):
        verdict = inner.verify(run)  # sync path, from ON the bridge loop
        return verdict.report

    result = verifier(outer, name="outer").verify(object())
    assert result.passed is False
    assert "inner says no" in result.report
    # The bridge survives for later verifications.
    assert verifier(lambda run: True).verify(object()).passed is True


@pytest.mark.timeout(30)
def test_bridge_reentrancy_depth_three():
    async def level3(run):
        return "deep no"

    v3 = verifier(level3, name="l3")

    async def level2(run):
        return v3.verify(run).report

    v2 = verifier(level2, name="l2")

    async def level1(run):
        return v2.verify(run).report

    verdict = verifier(level1, name="l1").verify(object())
    assert verdict.report == "deep no"


# ---------------------------------------------------------------------------
# F5: bounded shell buffering
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
# F6: process-group cleanup on cancellation and interruption
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
        from agno.verify import ShellVerifier
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
