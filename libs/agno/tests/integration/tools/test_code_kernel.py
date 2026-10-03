"""Kernel-backed CodeMode tests: a real ipykernel on sys.executable.

Every test runs against a live kernel subprocess and is marked integration.
"""

import asyncio
import os
import signal
import time
from typing import Optional

import pytest

pytest.importorskip("ipykernel")
pytest.importorskip("jupyter_client")
pytest.importorskip("dill")

from agno.run import RunContext  # noqa: E402
from agno.tools import Toolkit  # noqa: E402
from agno.tools.code import CodeMode, KernelBusyError, KernelDiedError  # noqa: E402
from agno.tools.code.code_mode import OWNER_REFUSAL  # noqa: E402
from agno.tools.code.kernel import RESET_NOTICE  # noqa: E402

pytestmark = pytest.mark.integration

_SESSION_COUNTER = iter(range(1_000_000))


def _ctx(session_id: str, user_id: Optional[str] = None) -> RunContext:
    return RunContext(run_id="run-1", session_id=session_id, user_id=user_id)


def _sid(prefix: str) -> str:
    return f"{prefix}-{next(_SESSION_COUNTER)}"


class SlowTools(Toolkit):
    """A bridged tool slow enough to still be running when the kernel goes away."""

    def __init__(self, **kwargs):
        super().__init__(name="slow_tools", tools=[self.nap], **kwargs)

    def nap(self, seconds: float, tag: str) -> str:
        """Sleep for the given seconds and return the tag.

        Args:
            seconds: How long to sleep.
            tag: The tag to return.
        """
        import time as _time

        _time.sleep(seconds)
        return f"napped:{tag}"


@pytest.fixture
def make_code_mode():
    instances = []

    def factory(**kwargs):
        cm = CodeMode(**kwargs)
        instances.append(cm)
        return cm

    yield factory
    for cm in instances:
        try:
            cm.shutdown()
        except Exception:
            pass


# ------------------------------------------------------------------
# State persistence and the model-facing surface
# ------------------------------------------------------------------


def test_state_persists_across_execute_calls(make_code_mode):
    cm = make_code_mode()
    sid = _sid("persist")
    first = cm.execute(_ctx(sid), "x = 41")
    assert "Error" not in first.content
    second = cm.execute(_ctx(sid), "x + 1")
    assert "42" in second.content


async def test_state_persists_across_aexecute_calls(make_code_mode):
    cm = make_code_mode()
    sid = _sid("apersist")
    await cm.aexecute(_ctx(sid), "y = [1, 2, 3]")
    result = await cm.aexecute(_ctx(sid), "sum(y)")
    assert "6" in result.content


def test_two_sessions_are_isolated(make_code_mode):
    cm = make_code_mode()
    sid_a, sid_b = _sid("iso-a"), _sid("iso-b")
    cm.execute(_ctx(sid_a), "secret = 'session-a'")
    result = cm.execute(_ctx(sid_b), "secret")
    assert "NameError" in result.content


def test_execution_count_increments(make_code_mode):
    cm = make_code_mode()
    sid = _sid("count")
    first = cm.run(sid, "1")
    second = cm.run(sid, "2")
    assert first.execution_count == 1
    assert second.execution_count == 2


def test_traceback_returns_error_and_kernel_survives(make_code_mode):
    cm = make_code_mode()
    sid = _sid("boom")
    cm.run(sid, "kept = 'still here'")
    result = cm.run(sid, "1 / 0")
    assert result.status == "error"
    assert result.traceback is not None and "ZeroDivisionError" in result.traceback
    after = cm.run(sid, "kept")
    assert after.status == "ok"
    assert after.result == "'still here'"


def test_input_fails_rather_than_hangs(make_code_mode):
    cm = make_code_mode()
    result = cm.run(_sid("stdin"), "input('are you there?')")
    assert result.status == "error"
    assert result.traceback is not None and "StdinNotImplementedError" in result.traceback


# ------------------------------------------------------------------
# Shell magics
# ------------------------------------------------------------------


def test_bash_works_and_its_cd_does_not_leak_while_percent_cd_does(make_code_mode):
    cm = make_code_mode()
    sid = _sid("shell")
    before = cm.run(sid, "import os; os.getcwd()")
    assert before.status == "ok"
    bash = cm.run(sid, "%%bash\ncd /\npwd")
    assert bash.status == "ok"
    assert bash.stdout.strip() == "/"
    after = cm.run(sid, "import os; os.getcwd()")
    assert after.result == before.result
    moved = cm.run(sid, "%cd /")
    assert moved.status == "ok"
    now = cm.run(sid, "import os; os.getcwd()")
    assert now.result == "'/'"


def test_allow_shell_false_rejects_bash_cells(make_code_mode):
    cm = make_code_mode(allow_shell=False)
    result = cm.execute(_ctx(_sid("noshell")), "%%bash\necho hi")
    assert result.content.startswith("Error:")
    assert "allow_shell=False" in result.content


def test_allow_shell_false_strips_the_magic_in_kernel(make_code_mode):
    cm = make_code_mode(allow_shell=False)
    # Reaching the magic through run_cell_magic bypasses the host-side cell
    # check; the magic itself must be gone from the kernel. IPython reports a
    # missing cell magic as UsageError.
    code = (
        "try:\n"
        "    get_ipython().run_cell_magic('bash', '', 'echo hi')\n"
        "except Exception as e:\n"
        "    print('CAUGHT', type(e).__name__)\n"
    )
    result = cm.run(_sid("stripped"), code)
    assert result.status == "ok"
    assert "CAUGHT UsageError" in result.stdout


def test_allow_shell_false_survives_a_sibling_script_magic_loading(make_code_mode):
    cm = make_code_mode(allow_shell=False)
    # IPython 9.17 registers the script magics lazily, and loading any one of
    # them instantiates the provider that owns every sibling. Running %%sh must
    # not bring bash back.
    code = (
        "get_ipython().run_cell_magic('sh', '', 'echo sibling')\n"
        "try:\n"
        "    get_ipython().run_cell_magic('bash', '', 'echo hi')\n"
        "except Exception as e:\n"
        "    print('CAUGHT', type(e).__name__)\n"
    )
    result = cm.run(_sid("sibling"), code)
    assert result.status == "ok"
    assert "CAUGHT UsageError" in result.stdout


# ------------------------------------------------------------------
# Serialization of concurrent cells
# ------------------------------------------------------------------


async def test_concurrent_aexecute_calls_serialize(make_code_mode):
    cm = make_code_mode()
    sid = _sid("serial")
    await cm.aexecute(_ctx(sid), "order = []")
    slow = "import time; order.append('slow-start'); time.sleep(0.8); order.append('slow-end')"
    fast = "order.append('fast')"
    await asyncio.gather(cm.aexecute(_ctx(sid), slow), cm.aexecute(_ctx(sid), fast))
    final = await cm.aexecute(_ctx(sid), "order")
    # Cells serialize: the slow cell's two entries are adjacent, never split
    # by the fast cell.
    assert (
        "['slow-start', 'slow-end', 'fast']" in final.content or "['fast', 'slow-start', 'slow-end']" in final.content
    )


# ------------------------------------------------------------------
# Output caps
# ------------------------------------------------------------------


def test_output_caps_apply_per_stream_with_markers(make_code_mode):
    cm = make_code_mode(max_output_chars=1_000)
    sid = _sid("caps")
    result = cm.run(sid, "import sys\nprint('o' * 50_000)\nprint('e' * 50_000, file=sys.stderr)")
    assert "stdout" in result.truncated
    assert "stderr" in result.truncated
    # The budget keeps a head and a tail; the marker names what fell between.
    assert "chars omitted; output capped at 1000" in result.stdout
    assert "chars omitted; output capped at 1000" in result.stderr
    assert result.stdout.startswith("o" * 100)
    assert "o" in result.stdout.rsplit("...]", 1)[-1]
    assert len(result.stdout) < 1_200
    assert len(result.stderr) < 1_200


def test_result_stream_has_its_own_budget(make_code_mode):
    cm = make_code_mode(max_output_chars=500)
    result = cm.run(_sid("result-cap"), "'r' * 50_000")
    assert "result" in result.truncated
    assert result.result is not None and "chars omitted; output capped at 500" in result.result


def test_display_data_png_is_promoted_to_images(make_code_mode):
    cm = make_code_mode()
    code = (
        "import base64\n"
        "from IPython.display import Image, display\n"
        "png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')\n"
        "display(Image(data=png))\n"
    )
    result = cm.run(_sid("png"), code)
    assert result.status == "ok"
    assert len(result.images) == 1
    assert result.images[0].content is not None and result.images[0].content.startswith(b"\x89PNG")
    assert result.images[0].mime_type == "image/png"


# ------------------------------------------------------------------
# Interrupts, timeouts, busy kernels, death
# ------------------------------------------------------------------


def test_timeout_interrupts_cell_and_preserves_namespace(make_code_mode):
    cm = make_code_mode(timeout=2)
    sid = _sid("interrupt")
    cm.run(sid, "marker = 'alive'")
    started = time.monotonic()
    result = cm.run(sid, "while True: pass")
    elapsed = time.monotonic() - started
    assert result.status == "error"
    assert result.traceback is not None and "KeyboardInterrupt" in result.traceback
    assert elapsed < 15
    after = cm.run(sid, "marker")
    assert after.result == "'alive'"


_UNINTERRUPTIBLE = "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\ntime.sleep(120)\n"


def test_busy_kernel_wait_policy_raises_kernel_busy(make_code_mode):
    cm = make_code_mode(timeout=1, busy_wait=1.0, on_busy_kernel="wait")
    sid = _sid("busy-wait")
    aborted = cm.run(sid, _UNINTERRUPTIBLE)
    assert aborted.status == "aborted"
    with pytest.raises(KernelBusyError):
        cm.run(sid, "1 + 1")


def test_busy_kernel_restart_policy_returns_reset_notice(make_code_mode):
    cm = make_code_mode(timeout=1, busy_wait=1.0, on_busy_kernel="restart")
    sid = _sid("busy-restart")
    aborted = cm.run(sid, _UNINTERRUPTIBLE)
    assert aborted.status == "aborted"
    result = cm.execute(_ctx(sid), "'fresh'")
    assert "<code_mode_reset>" in result.content
    assert "fresh" in result.content


def test_kernel_death_mid_cell_rejects_with_named_error(make_code_mode):
    cm = make_code_mode()
    sid = _sid("death")
    with pytest.raises(KernelDiedError):
        cm.run(sid, "import os; os._exit(7)")
    revived = cm.execute(_ctx(sid), "'back'")
    assert "<code_mode_reset>" in revived.content
    assert "back" in revived.content


def test_restart_tool_discards_state_and_returns_notice(make_code_mode):
    cm = make_code_mode()
    sid = _sid("restart")
    cm.execute(_ctx(sid), "gone = True")
    notice = cm.restart(_ctx(sid))
    assert notice == RESET_NOTICE
    result = cm.execute(_ctx(sid), "gone")
    assert "NameError" in result.content


async def test_arestart_matches_restart(make_code_mode):
    cm = make_code_mode()
    sid = _sid("arestart")
    await cm.aexecute(_ctx(sid), "gone = 1")
    notice = await cm.arestart(_ctx(sid))
    assert notice == RESET_NOTICE


def test_idle_ttl_evicts_and_next_execute_resets(make_code_mode):
    cm = make_code_mode(idle_ttl=1)
    sid = _sid("evict")
    cm.execute(_ctx(sid), "ephemeral = 1")
    session = cm._sessions[sid]
    deadline = time.monotonic() + 10
    while (session.running or cm._sessions.get(sid) is session) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not session.running, "kernel should have been evicted after idle_ttl"
    assert cm._sessions.get(sid) is None, "an evicted session is dropped from the registry"
    # The next cell starts a fresh kernel and is told the namespace was reset.
    revived = cm.execute(_ctx(sid), "'revived'")
    assert "<code_mode_reset>" in revived.content
    assert "revived" in revived.content


def test_eviction_forgets_the_session_and_its_run_context(make_code_mode):
    cm = make_code_mode(idle_ttl=1)
    sid = _sid("evict-forget")
    cm.execute(_ctx(sid), "ephemeral = 1")
    session = cm._sessions[sid]
    deadline = time.monotonic() + 15
    while cm._sessions.get(sid) is not None and time.monotonic() < deadline:
        time.sleep(0.2)
    # Nothing about a session survives its eviction: neither the registry entry
    # nor the RunContext of the run that last used it.
    assert cm._sessions.get(sid) is None, "eviction must drop the session entry"
    assert not session.running
    assert session.run_context is None
    # The id still works: the next execute starts a fresh kernel for it.
    revived = cm.execute(_ctx(sid), "'revived'")
    assert "revived" in revived.content
    assert cm._sessions.get(sid) is not None


# ------------------------------------------------------------------
# Developer-facing surface
# ------------------------------------------------------------------


def test_variables_and_value_round_trip(make_code_mode):
    cm = make_code_mode()
    sid = _sid("devsurface")
    cm.run(sid, "count = 7\nnames = ['a', 'b']\n_hidden = 'skip me'")
    variables = cm.variables(sid)
    assert variables == {"count": "int", "names": "list"}
    assert cm.value(sid, "count") == 7
    assert cm.value(sid, "names") == ["a", "b"]


def test_value_of_missing_variable_raises(make_code_mode):
    cm = make_code_mode()
    sid = _sid("missing")
    cm.run(sid, "present = 1")
    with pytest.raises(KeyError):
        cm.value(sid, "absent")


def test_value_rejects_non_identifier(make_code_mode):
    cm = make_code_mode()
    sid = _sid("badname")
    cm.run(sid, "present = 1")
    with pytest.raises(ValueError):
        cm.value(sid, "present; import os")


async def test_async_dev_surface(make_code_mode):
    cm = make_code_mode()
    sid = _sid("adev")
    result = await cm.arun(sid, "z = 3.5\nz")
    assert result.status == "ok"
    assert result.result == "3.5"
    assert await cm.avariables(sid) == {"z": "float"}
    assert await cm.avalue(sid, "z") == 3.5
    await cm.ashutdown(sid)
    assert cm._sessions.get(sid) is None


def test_shutdown_kills_kernel_and_forgets_session(make_code_mode):
    cm = make_code_mode()
    sid = _sid("shutdown")
    cm.run(sid, "1")
    assert cm._sessions[sid].running
    cm.shutdown(sid)
    assert cm._sessions.get(sid) is None


def test_shutdown_all_sessions(make_code_mode):
    cm = make_code_mode()
    cm.run(_sid("all-a"), "1")
    cm.run(_sid("all-b"), "1")
    assert len(cm._sessions) == 2
    cm.shutdown()
    assert cm._sessions == {}


# ------------------------------------------------------------------
# Session ownership: a session id is not proof of access
# ------------------------------------------------------------------


def test_same_user_reuses_the_warm_kernel(make_code_mode):
    cm = make_code_mode()
    sid = _sid("own-same")
    cm.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    again = cm.execute(_ctx(sid, user_id="user-a"), "token")
    assert "secret-a" in again.content


def test_another_users_run_is_refused_and_never_reaches_the_kernel(make_code_mode):
    cm = make_code_mode()
    sid = _sid("own-other")
    cm.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    intruder = cm.execute(_ctx(sid, user_id="user-b"), "print(token)")
    assert intruder.content == OWNER_REFUSAL
    assert "secret-a" not in intruder.content
    # The owner's environment is untouched by the refusal.
    kept = cm.execute(_ctx(sid, user_id="user-a"), "token")
    assert "secret-a" in kept.content


def test_another_user_cannot_restart_the_session(make_code_mode):
    cm = make_code_mode()
    sid = _sid("own-restart")
    cm.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    assert cm.restart(_ctx(sid, user_id="user-b")) == OWNER_REFUSAL
    kept = cm.execute(_ctx(sid, user_id="user-a"), "token")
    assert "secret-a" in kept.content


async def test_async_surface_refuses_another_user(make_code_mode):
    cm = make_code_mode()
    sid = _sid("own-async")
    await cm.aexecute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    refused = await cm.aexecute(_ctx(sid, user_id="user-b"), "token")
    assert refused.content == OWNER_REFUSAL
    assert await cm.arestart(_ctx(sid, user_id="user-b")) == OWNER_REFUSAL
    kept = await cm.aexecute(_ctx(sid, user_id="user-a"), "token")
    assert "secret-a" in kept.content


def test_session_without_a_user_is_claimed_by_the_first_one(make_code_mode):
    cm = make_code_mode()
    sid = _sid("own-claim")
    # A run without an identity carries nothing to compare, so it keeps the
    # unauthenticated behavior and reuses the same kernel.
    cm.execute(_ctx(sid), "shared = 1")
    claimed = cm.execute(_ctx(sid, user_id="user-a"), "shared + 1")
    assert "2" in claimed.content
    # The first identity to arrive owns the session from then on.
    assert cm.execute(_ctx(sid, user_id="user-b"), "shared").content == OWNER_REFUSAL


# ------------------------------------------------------------------
# Teardown and in-flight bridged tool calls
# ------------------------------------------------------------------


async def test_kernel_death_cancels_the_in_flight_bridged_call(make_code_mode):
    cm = make_code_mode(tools=[SlowTools()], timeout=120)
    sid = _sid("death-inflight")
    await cm.aexecute(_ctx(sid), "1")
    session = cm._sessions[sid]
    call = asyncio.ensure_future(cm.aexecute(_ctx(sid), "await slow.nap(seconds=5, tag='old')"))
    for _ in range(200):
        if any(key[0] == sid for key in cm._bridge._pending):
            break
        await asyncio.sleep(0.05)
    assert any(key[0] == sid for key in cm._bridge._pending), "the bridged call never reached the host"
    generation_before = session.generation
    os.kill(session.km.provisioner.pid, signal.SIGKILL)
    with pytest.raises(KernelDiedError):
        await call
    # The task serving that call belongs to the destroyed kernel: leaving it
    # running lets its reply land on a call id of the replacement.
    assert not any(key[0] == sid for key in cm._bridge._pending), (
        "teardown must cancel the bridged calls of the kernel it destroyed"
    )
    # The replacement kernel starts a new generation and its own call ids.
    revived = await cm.aexecute(_ctx(sid), "await slow.nap(seconds=0.1, tag='new')")
    assert "napped:new" in revived.content
    assert "old" not in revived.content
    assert session.generation > generation_before


# ------------------------------------------------------------------
# Interpreter selection, stderr on failure, cwd/env, image caps, max_kernels
# ------------------------------------------------------------------


def test_python_argument_launches_that_exact_interpreter(tmp_path):
    import stat
    import sys

    # A wrapper that stamps the environment and execs the real interpreter:
    # the stamp can only appear in the kernel if OUR argv[0] actually ran.
    wrapper = tmp_path / "agno-test-python"
    wrapper.write_text(f'#!/bin/sh\nAGNO_WRAPPER_MARK=used exec "{sys.executable}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    cm = CodeMode(python=str(wrapper), snapshot=False, allow_restart=False)
    try:
        result = cm.run("kernel-python-arg", "import os; print(os.environ.get('AGNO_WRAPPER_MARK'))")
        assert result.stdout.strip() == "used"
    finally:
        cm.shutdown()


def test_a_broken_interpreter_fails_with_its_stderr_in_the_error(tmp_path):
    import stat

    fake = tmp_path / "broken-python"
    fake.write_text("#!/bin/sh\necho 'this interpreter is broken on purpose' >&2\nexit 3\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cm = CodeMode(python=str(fake), snapshot=False, allow_restart=False, timeout=30)
    try:
        with pytest.raises(Exception) as excinfo:
            cm.run("kernel-broken-python", "print('never runs')")
        assert "broken on purpose" in str(excinfo.value)
    finally:
        cm.shutdown()


def test_cwd_and_env_reach_the_kernel(tmp_path):
    import os

    cm = CodeMode(cwd=str(tmp_path), env={"AGNO_KERNEL_PROBE": "present"}, snapshot=False)
    try:
        result = cm.run("kernel-cwd-env", "import os; print(os.getcwd()); print(os.environ['AGNO_KERNEL_PROBE'])")
        lines = result.stdout.strip().split("\n")
        assert os.path.realpath(lines[0]) == os.path.realpath(str(tmp_path))
        assert lines[1] == "present"
    finally:
        cm.shutdown()


_TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_images_per_cell_are_capped_with_a_note():
    cm = CodeMode(max_images_per_cell=2, snapshot=False)
    try:
        cell = (
            "import base64\n"
            "from IPython.display import display, Image\n"
            f"png = base64.b64decode('{_TINY_PNG}')\n"
            "for _ in range(5): display(Image(data=png))\n"
        )
        result = cm.run("kernel-image-cap", cell)
        assert len(result.images) == 2
        assert "image dropped" in result.stderr
    finally:
        cm.shutdown()


def test_an_oversized_image_is_dropped_by_name_not_silently():
    cm = CodeMode(max_image_bytes=10, snapshot=False)
    try:
        cell = (
            "import base64\n"
            "from IPython.display import display, Image\n"
            f"display(Image(data=base64.b64decode('{_TINY_PNG}')))\n"
        )
        result = cm.run("kernel-image-size", cell)
        assert result.images == []
        assert "over the 10-byte limit" in result.stderr
    finally:
        cm.shutdown()


def test_max_kernels_evicts_the_least_recent_idle_session():
    cm = CodeMode(max_kernels=2, snapshot=False)
    try:
        for i in range(1, 4):
            cm.run(f"kernel-cap-{i}", f"marker = {i}")
        assert len(cm._sessions) == 2
        assert "kernel-cap-1" not in cm._sessions
        assert "kernel-cap-1" in cm._evicted
        # The evicted id comes back as a fresh kernel with the reset notice.
        out = cm.execute(RunContext(run_id="r", session_id="kernel-cap-1"), "print('back')")
        assert "code_mode_reset" in (out.content or "")
    finally:
        cm.shutdown()
