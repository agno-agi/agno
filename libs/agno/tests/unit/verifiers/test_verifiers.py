"""Unit tests for agno.verifiers: the adapter, the guard, ShellVerifier, ScorerVerifier."""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
import tracemalloc

import pytest

from agno.agent import Agent
from agno.scorer import Score
from agno.team import Team
from agno.verifiers import MAX_REPORT_BYTES, ScorerVerifier, ShellVerifier, Verdict, check
from agno.verifiers.base import coerce_verifier
from agno.workflow import Workflow

USE_ASYNC = pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])


async def _check(v, use_async, *args, **kwargs):
    return await v.averify(*args, **kwargs) if use_async else v.verify(*args, **kwargs)


# ---------------------------------------------------------------------------
# Adapter return mapping
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
    v = check(lambda run_output: returned, name="check")
    verdict = v.verify(object())
    assert verdict.passed is passed
    assert verdict.name == "check"
    assert report_has in verdict.report


async def test_adapter_sync_callable_through_averify_runs_in_thread():
    def probe(run_output):
        return True

    assert (await check(probe).averify(object())).passed is True


# ---------------------------------------------------------------------------
# Callable signatures: by-name routing, strict at construction
# ---------------------------------------------------------------------------


def _unknown_required(run):
    return True


def _unknown_with_default(run_output, extra="left-alone"):
    return extra == "left-alone"


class _ObjectWithUnknownParam:
    def verify(self, output):
        return True


@pytest.mark.parametrize(
    "entry, unknown",
    [
        (_unknown_required, "'run'"),
        (_unknown_with_default, None),
        (_ObjectWithUnknownParam(), "'output'"),
    ],
    ids=["callable-unknown", "callable-with-default", "object-method-unknown"],
)
def test_unknown_required_param_raises_at_construction(entry, unknown):
    if unknown is None:
        # A parameter with a default is allowed and never filled.
        assert coerce_verifier(entry).verify(object()).passed is True
        return
    with pytest.raises(TypeError) as excinfo:
        coerce_verifier(entry)
    message = str(excinfo.value)
    assert unknown in message
    if not isinstance(entry, _ObjectWithUnknownParam):
        assert "run_output, run_context, agent, team, workflow, session" in message


# ---------------------------------------------------------------------------
# Owner-named parameters are kind-matched, never aliased
# ---------------------------------------------------------------------------


OWNER_NAMES = ("agent", "team", "workflow")


def _owner(kind: str):
    if kind == "agent":
        return Agent(name="agent")
    if kind == "team":
        return Team(name="team", members=[Agent(name="member")])
    return Workflow(name="workflow")


def _declares_every_owner(seen):
    def probe(run_output, agent, team, workflow):
        seen.update(agent=agent, team=team, workflow=workflow)
        return True

    return check(probe)


def _catch_all(seen):
    def probe(**kwargs):
        seen.update(kwargs)
        return True

    return check(probe)


@pytest.mark.parametrize("build", [_declares_every_owner, _catch_all], ids=["declared", "kwargs"])
@pytest.mark.parametrize("kind", OWNER_NAMES)
def test_owner_arrives_only_under_its_kind(build, kind):
    seen: dict = {}
    owner = _owner(kind)
    session = object()
    assert build(seen).verify(object(), owner=owner, session=session).passed is True
    assert seen[kind] is owner
    for name in OWNER_NAMES:
        if name == kind:
            continue
        if build is _declares_every_owner:
            # A declared owner name of another kind arrives as None.
            assert seen[name] is None
        else:
            # A catch-all only receives the owner under its own kind.
            assert name not in seen
    if build is _catch_all:
        assert seen["session"] is session
        assert "run_output" in seen and "run_context" in seen


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


def _deep(run_output):
    def inner():
        raise RuntimeError("deep failure")

    inner()


async def _aexits(run_output):
    raise SystemExit(2)


class _Raises:
    name = "judge"

    def verify(self, run_output):
        raise ConnectionError("judge endpoint refused")

    async def averify(self, run_output):
        raise ConnectionError("judge endpoint refused")


@pytest.mark.parametrize(
    "entry, paths, prefix, tail",
    [
        (_deep, (False,), "RuntimeError: deep failure", 'raise RuntimeError("deep failure")'),
        # argparse, click and pytest.main all exit through SystemExit; a check that does must
        # fail closed, not unwind the run.
        (_aexits, (True,), "SystemExit: 2", "raise SystemExit(2)"),
        (_Raises(), (False, True), "ConnectionError: judge endpoint refused", 'raise ConnectionError("judge'),
    ],
    ids=["callable-sync", "system-exit-async", "object-both"],
)
async def test_adapter_exception_report_keeps_the_traceback_tail(entry, paths, prefix, tail):
    guarded = coerce_verifier(entry)
    for use_async in paths:
        verdict = await _check(guarded, use_async, object())
        assert verdict.passed is False
        assert verdict.report.startswith(prefix)
        assert "Traceback" in verdict.report and tail in verdict.report


def test_adapter_keyboard_interrupt_propagates():
    def interrupt(run_output):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        check(interrupt).verify(object())


# ---------------------------------------------------------------------------
# Entry classification
# ---------------------------------------------------------------------------


class AsyncUnderSyncName:
    async def verify(self, run_output):
        return "awaited on the async path"


class PlainAverify:
    name = "plain_averify"

    def averify(self, run_output):
        return "plain averify on a worker thread"


class AsyncVerifyAndAverify:
    name = "both"

    async def verify(self, run_output):
        return "async verify"

    async def averify(self, run_output):
        return "averify outranks an async verify"


class AsyncCall:
    async def __call__(self, run_output):
        return "async __call__"


@pytest.mark.parametrize(
    "entry, async_report",
    [
        (AsyncUnderSyncName, "awaited on the async path"),
        (PlainAverify, "plain averify on a worker thread"),
        (AsyncVerifyAndAverify, "averify outranks an async verify"),
        (AsyncCall, "async __call__"),
    ],
)
async def test_one_sided_verifier_classification(entry, async_report):
    """`run()` refuses an object with no plain sync `verify`; `arun()` awaits `averify` when
    there is one (even beside an async `verify`), else the async `verify` or `__call__`."""
    guarded = coerce_verifier(entry())
    with pytest.raises(ValueError, match="an async verifier"):
        guarded.verify(object())
    assert (await guarded.averify(object())).report == async_report


def test_bare_scorer_is_rejected_at_entry():
    class BareScorer:
        async def ascore(self, run_output, expected=None):
            return Score(value=1.0, passed=True)

    with pytest.raises(ValueError, match="ScorerVerifier"):
        coerce_verifier(BareScorer())


# ---------------------------------------------------------------------------
# ShellVerifier
# ---------------------------------------------------------------------------


def test_shell_exit_code_decides_and_report_keeps_exit_line_and_tail():
    assert ShellVerifier("exit 0").verify(None).passed is True
    v = ShellVerifier("echo first; echo err 1>&2; exit 3").verify(None)
    assert v.passed is False
    # The exit line, then stdout and stderr merged in order.
    assert v.report == "exit 3\nfirst\nerr"


def _grandchild_alive(marker: str) -> bool:
    ps = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    return ps.stdout.strip() != ""


def _grandchild_gone(marker: str, within: float = 60.0) -> bool:
    """Poll until no process matches the marker: a killed group is reaped asynchronously,
    and under a loaded machine that takes longer than a fixed sleep."""
    deadline = time.monotonic() + within
    while _grandchild_alive(marker):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_shell_timeout_kills_group_and_keeps_partial_output():
    marker = f"sleep 30.{os.getpid()}"
    v = ShellVerifier(f"echo started; {marker}; echo finished", timeout=0.5, name="hang").verify(None)
    assert v.passed is False
    assert v.report.splitlines()[0].startswith("timed out after 0.5s")
    assert "started" in v.report
    assert "finished" not in v.report
    # The sleep grandchild must be gone, not just the shell.
    assert _grandchild_gone(marker)


@pytest.mark.parametrize("inherit_env", [True, False])
def test_shell_env_is_merged_not_replaced(monkeypatch, inherit_env):
    monkeypatch.setenv("VERIFY_INHERITED", "from-parent")
    if inherit_env:
        shell = ShellVerifier(
            'test "$VERIFY_INHERITED" = from-parent && test "$VERIFY_X" = 1 && exit 0 || exit 9',
            env={"VERIFY_X": "1"},
        )
        v = shell.verify(None)
        assert v.passed is True, v.report
    else:
        v = ShellVerifier("env; exit 1", inherit_env=False, env={"ONLY": "this"}, timeout=30).verify(None)
        assert "VERIFY_INHERITED" not in v.report
        assert "ONLY=this" in v.report


@pytest.mark.parametrize(
    "command, cwd, prefix",
    [
        ("definitely_not_a_command_xyz", None, "harness error: exit 127"),
        ("echo hi", "/nonexistent-dir-for-this-test", "harness error: FileNotFoundError"),
    ],
    ids=["missing-command", "missing-cwd"],
)
def test_shell_missing_cwd_is_harness_error(command, cwd, prefix):
    v = ShellVerifier(command, cwd=cwd).verify(None)
    assert v.passed is False
    assert v.report.startswith(prefix)
    assert v.fatal is True


@pytest.mark.parametrize(
    "command, hidden, expected_name",
    [
        ("PGPASSWORD=s3cret psql -c 'select 1'", "s3cret", "PGPASSWORD=*** psql -c select 1"),
        ("curl -H 'Authorization: Bearer tok123' https://x", "tok123", None),
        ("psql postgres://svc:SUPERSECRET@db.internal/app -c 'select 1'", "SUPERSECRET", None),
        (
            "cd somewhere && python -m pytest -q tests/unit --maxfail=1 -x",
            None,
            "cd somewhere && python -m pytest -q tests/unit --maxfail=1 -x"[:40],
        ),
        ("pytest -q", None, "pytest -q"),
    ],
    ids=["assigned-secret", "bearer", "url-userinfo", "truncated", "short"],
)
def test_shell_default_name_hides_assigned_secrets_and_bearer_tokens(command, hidden, expected_name):
    name = ShellVerifier(command).name
    if hidden is not None:
        assert hidden not in name
    if "svc:" in command:
        assert "svc" not in name
    if expected_name is not None:
        assert name == expected_name


def test_shell_async_child_does_not_inherit_stdin_and_matches_sync(tmp_path):
    """verify must hand the child a closed stdin. Run it inside a child that has real stdin:
    pytest's own stdin is already closed, so an in-process assertion passes whether or not
    the verifier redirects stdin at all."""
    script = tmp_path / "stdin.py"
    script.write_text(
        textwrap.dedent("""
        from agno.verifiers import ShellVerifier
        v = ShellVerifier("read -r line && exit 3 || exit 7", timeout=10)
        print("SYNC", v.verify(None).detail["returncode"], flush=True)
        """)
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), os.getcwd()]))}
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=b"a line the child may not consume\n",
        capture_output=True,
        env=env,
        timeout=60,
    )
    # exit 7 = the read hit EOF. exit 3 = the child got real stdin.
    assert b"SYNC 7" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"command": "exit 0", "timeout": 0}, ValueError),
        ({"command": "exit 0", "timeout": -1}, ValueError),
        ({"command": "exit 0", "timeout": float("nan")}, ValueError),
        ({"command": ""}, ValueError),
        ({"command": "   "}, ValueError),
        ({"command": "# only a comment"}, ValueError),
        ({"command": None}, TypeError),
    ],
    ids=["timeout-zero", "timeout-negative", "timeout-nan", "empty", "blank", "comment", "non-str"],
)
def test_shell_timeout_must_be_positive(kwargs, error):
    with pytest.raises(error):
        ShellVerifier(**kwargs)


def _big_output_cmd(mib: int) -> str:
    return f'{sys.executable} -c "import sys; [sys.stdout.write(chr(65 + i % 26) * 65536) for i in range({mib * 16})]"; echo LAST-LINE; exit 1'


def test_shell_memory_stays_bounded_for_large_output():
    tracemalloc.start()
    verdict = ShellVerifier(_big_output_cmd(8), timeout=60).verify(None)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, f"peak {peak} bytes for an 8 MiB child"
    assert verdict.passed is False
    assert verdict.report.splitlines()[0] == "exit 1"
    assert "LAST-LINE" in verdict.report  # the tail survived the bounding
    assert len(verdict.report.encode("utf-8")) <= MAX_REPORT_BYTES


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
async def test_cancelling_averify_kills_the_process_group():
    marker = f"sleep 27.{os.getpid()}"
    task = asyncio.ensure_future(ShellVerifier(f"echo go; {marker}", timeout=120).averify(None))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _grandchild_gone(marker)


@pytest.mark.skipif(sys.platform == "win32", reason="signals are POSIX here")
def test_sigint_during_sync_verify_kills_the_process_group(tmp_path):
    marker = f"sleep 28.{os.getpid()}"
    script = tmp_path / "runner.py"
    script.write_text(
        textwrap.dedent(f"""
        import signal
        from agno.verifiers import ShellVerifier
        # A suite started as a background job inherits SIGINT as ignored, so Python never
        # installs its handler; restore it or the signal below is silently dropped.
        signal.signal(signal.SIGINT, signal.default_int_handler)
        print("READY", flush=True)
        try:
            ShellVerifier("echo go; {marker}", timeout=120).verify(None)
        except KeyboardInterrupt:
            print("INTERRUPTED", flush=True)
            raise SystemExit(3)
        """)
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), os.getcwd()]))}
    child = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "READY"
    time.sleep(0.8)
    child.send_signal(signal.SIGINT)
    try:
        out, err = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
    assert "INTERRUPTED" in out, (child.returncode, out, err)
    assert _grandchild_gone(marker)


# ---------------------------------------------------------------------------
# ScorerVerifier
# ---------------------------------------------------------------------------


class CountingScorer:
    def __init__(self, score):
        self.score_value = score
        self.calls = {"score": 0, "ascore": 0}
        self.expected = []

    def score(self, run_output, expected=None):
        self.calls["score"] += 1
        self.expected.append(expected)
        return self.score_value

    async def ascore(self, run_output, expected=None):
        self.calls["ascore"] += 1
        self.expected.append(expected)
        await asyncio.sleep(0)
        return self.score_value


@USE_ASYNC
async def test_scorer_verifier_verify_calls_score_and_averify_calls_ascore(use_async):
    scorer = CountingScorer(Score(value=0.25, passed=False, reason="too vague"))
    verdict = await _check(ScorerVerifier(scorer, expected="42"), use_async, object())
    assert verdict.passed is False
    assert verdict.name == "CountingScorer"
    assert verdict.report == "score 0.25: too vague"
    assert verdict.detail["value"] == 0.25
    assert scorer.expected == ["42"]
    assert scorer.calls == ({"score": 0, "ascore": 1} if use_async else {"score": 1, "ascore": 0})
    passing = CountingScorer(Score(value=1.0, passed=True))
    assert (await _check(ScorerVerifier(passing), use_async, object())).passed is True


async def test_scorer_verifier_without_a_sync_score_is_refused_by_verify():
    class AsyncOnlyScorer:
        async def ascore(self, run_output, expected=None):
            return Score(value=1.0, passed=True)

    v = ScorerVerifier(AsyncOnlyScorer(), name="judge")
    with pytest.raises(ValueError, match=r"Cannot use judge \(an async verifier\)"):
        v.verify(object())
    assert (await v.averify(object())).passed is True
    with pytest.raises(TypeError):
        ScorerVerifier(object())


def test_scorer_verifier_non_bool_passed_fails_closed():
    class Score:
        value = 0.9
        passed = "false"
        reason = "judge said yes-ish"
        detail = None

    class Sloppy:
        def score(self, run_output, expected=None):
            return Score()

        async def ascore(self, run_output, expected=None):
            return Score()

    verdict = ScorerVerifier(Sloppy()).verify(object())
    assert verdict.passed is False
    assert "only a real bool decides a run" in verdict.report
