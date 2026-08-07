"""Bridge tests: injected toolkits as awaitable calls inside the kernel.

The first test is the control-channel regression test: a bridge call issued
from a cell must complete without deadlock. IPython processes shell messages
serially — the cell cannot finish until the bridge reply arrives, and the
kernel will not read a shell-channel reply until the cell finishes — so the
reply must travel on the control channel. A wrong implementation here does not
fail; it hangs forever. This test exists to make that hang a test failure.
"""

import asyncio
import time

import pytest

from agno.run import RunContext
from agno.tools import Function, Toolkit
from agno.tools.code_mode import CodeMode

pytestmark = pytest.mark.integration

_SESSION_COUNTER = iter(range(1_000_000))


def _sid(prefix: str) -> str:
    return f"bridge-{prefix}-{next(_SESSION_COUNTER)}"


def _ctx(session_id: str) -> RunContext:
    return RunContext(run_id="bridge-run", session_id=session_id, user_id="bridge-user")


class EchoTools(Toolkit):
    """One sync and one async function, a failer, and an oversized return."""

    def __init__(self, **kwargs):
        super().__init__(
            name="echo_tools",
            tools=[self.echo, self.fail, self.big],
            async_tools=[(self.aboost, "boost")],
            **kwargs,
        )

    def echo(self, text: str) -> str:
        """Echo the text back with a prefix.

        Args:
            text: The text to echo.
        """
        return "echo:" + text

    def fail(self) -> str:
        """Always raises a ValueError."""
        raise ValueError("deliberate failure")

    def big(self) -> str:
        """Return two megabytes of text."""
        return "x" * 2_000_000

    async def aboost(self, n: int) -> int:
        """Multiply n by ten.

        Args:
            n: The value to boost.
        """
        return n * 10


class ContextTools(Toolkit):
    """A tool that needs the framework-injected run context."""

    def __init__(self, **kwargs):
        super().__init__(name="context_tools", tools=[self.whoami], **kwargs)

    def whoami(self, run_context: RunContext) -> str:
        """Report the current session and user.

        Returns:
            str: session and user identifiers.
        """
        return f"{run_context.session_id}|{run_context.user_id}"


class BrokenTools(Toolkit):
    """A toolkit whose function resolution raises at binding time."""

    def __init__(self, **kwargs):
        super().__init__(name="broken_tools", tools=[], **kwargs)

    def get_async_functions(self):
        raise RuntimeError("client credentials missing")


def top_level_helper(x: int) -> int:
    """Double the given value.

    Args:
        x: The value to double.
    """
    return x * 2


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
# THE control-channel regression test. If the bridge reply ever moves to the
# shell channel, this test hangs and fails on its timeout instead of passing
# slowly. Do not weaken the time bound.
# ------------------------------------------------------------------


def test_bridge_call_issued_from_a_cell_completes_without_deadlock(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    sid = _sid("no-deadlock")
    started = time.monotonic()
    result = cm.run(sid, "out = await echo.echo(text='ping')\nout")
    elapsed = time.monotonic() - started
    assert result.status == "ok", f"bridged cell failed: {result.traceback}"
    assert result.result == "'echo:ping'"
    assert elapsed < 30, "bridge round trip took suspiciously long; shell-channel deadlock behavior"


async def test_bridge_call_completes_through_aexecute(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    result = await cm.aexecute(_ctx(_sid("async-no-deadlock")), "await echo.echo(text='pong')")
    assert "echo:pong" in result.content


# ------------------------------------------------------------------
# Sync and async functions are both awaitable
# ------------------------------------------------------------------


def test_sync_and_async_functions_are_both_awaitable(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    sid = _sid("both")
    sync_result = cm.run(sid, "await echo.echo(text='a')")
    async_result = cm.run(sid, "await echo.boost(n=4)")
    assert sync_result.result == "'echo:a'"
    assert async_result.result == "40"


def test_positional_arguments_bind_by_signature(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    result = cm.run(_sid("positional"), "await echo.echo('positional')")
    assert result.result == "'echo:positional'"


def test_return_values_compose_into_program_logic(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    result = cm.run(_sid("compose"), "first = await echo.echo(text='a')\nawait echo.echo(text=first)")
    assert result.result == "'echo:echo:a'"


def test_bare_callable_binds_at_top_level(make_code_mode):
    cm = make_code_mode(tools=[top_level_helper])
    result = cm.run(_sid("bare"), "await top_level_helper(21)")
    assert result.result == "42"


def test_function_object_binds_under_its_own_name(make_code_mode):
    fn = Function.from_callable(top_level_helper, name="doubler")
    cm = make_code_mode(tools=[fn])
    result = cm.run(_sid("fnobj"), "await doubler(5)")
    assert result.result == "10"


# ------------------------------------------------------------------
# help() support
# ------------------------------------------------------------------


def test_help_shows_description_and_signature(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    result = cm.run(_sid("help"), "help(echo.echo)")
    assert "Echo the text back with a prefix" in result.stdout
    assert "text" in result.stdout


def test_help_on_the_handle_lists_methods(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    result = cm.run(_sid("help-handle"), "help(echo)")
    assert "echo" in result.stdout
    assert "boost" in result.stdout


# ------------------------------------------------------------------
# Errors cross the bridge as raised exceptions
# ------------------------------------------------------------------


def test_raising_function_raises_in_the_kernel_not_silent_none(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    code = (
        "try:\n"
        "    await echo.fail()\n"
        "    outcome = 'SILENT-NONE'\n"
        "except Exception as e:\n"
        "    outcome = type(e).__name__ + ': ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("raise"), code)
    assert result.status == "ok"
    assert result.result is not None
    assert "SILENT-NONE" not in result.result
    assert "deliberate failure" in result.result


def test_two_megabyte_return_raises_result_too_large(make_code_mode):
    cm = make_code_mode(tools=[EchoTools()])
    code = (
        "try:\n"
        "    await echo.big()\n"
        "    outcome = 'NO-ERROR'\n"
        "except ResultTooLarge as e:\n"
        "    outcome = 'ResultTooLarge: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("too-large"), code)
    assert result.status == "ok"
    assert result.result is not None
    assert "ResultTooLarge" in result.result
    assert "big" in result.result
    assert "file" in result.result.lower()


# ------------------------------------------------------------------
# Failed bindings degrade to explanatory, never NameError
# ------------------------------------------------------------------


def test_failed_binding_raises_descriptive_runtime_error_not_name_error(make_code_mode):
    cm = make_code_mode(tools=[BrokenTools(auto_register=True)])
    code = (
        "try:\n"
        "    await broken.take_action(1)\n"
        "    outcome = 'NO-ERROR'\n"
        "except NameError:\n"
        "    outcome = 'NAME-ERROR'\n"
        "except RuntimeError as e:\n"
        "    outcome = 'RuntimeError: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("broken"), code)
    assert result.status == "ok"
    assert result.result is not None
    assert "NAME-ERROR" not in result.result
    assert "RuntimeError" in result.result
    assert "broken_tools" in result.result
    assert "client credentials missing" in result.result


# ------------------------------------------------------------------
# Framework injection: session identity comes from RunContext
# ------------------------------------------------------------------


def test_bridged_tool_receives_run_context_of_the_run(make_code_mode):
    cm = make_code_mode(tools=[ContextTools()])
    sid = _sid("context")
    result = cm.execute(_ctx(sid), "await context.whoami()")
    assert sid in result.content
    assert "bridge-user" in result.content


# ------------------------------------------------------------------
# Reviewer regressions: two sessions on one bridge
# ------------------------------------------------------------------


class SlowTools(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(name="slow_tools", tools=[self.nap, self.quick], **kwargs)

    def nap(self, seconds: float) -> str:
        """Sleep for the given seconds.

        Args:
            seconds: How long to sleep.
        """
        import time as _time

        _time.sleep(seconds)
        return f"napped {seconds}"

    def quick(self, tag: str) -> str:
        """Return the tag immediately.

        Args:
            tag: The tag to echo.
        """
        return "quick:" + tag


async def test_two_sessions_do_not_cross_talk_bridge_replies(make_code_mode):
    # Kernel-side call ids are a per-kernel counter, so two sessions both use
    # id "1"; the pending map must key by session or replies cross-talk.
    cm = make_code_mode(tools=[SlowTools()])
    sid_a, sid_b = _sid("xtalk-a"), _sid("xtalk-b")
    result_a, result_b = await asyncio.gather(
        cm.aexecute(_ctx(sid_a), "await slow.quick(tag='A')"),
        cm.aexecute(_ctx(sid_b), "await slow.quick(tag='B')"),
    )
    assert "quick:A" in result_a.content
    assert "quick:B" in result_b.content


async def test_interrupting_one_session_does_not_cancel_the_other(make_code_mode):
    cm = make_code_mode(tools=[SlowTools()], timeout=30, busy_wait=1.0)
    sid_a, sid_b = _sid("intr-a"), _sid("intr-b")
    # Warm both kernels so the timing below is deterministic.
    await asyncio.gather(cm.aexecute(_ctx(sid_a), "1"), cm.aexecute(_ctx(sid_b), "1"))
    # Both bridge calls in flight; cancelling A's run must abort only A's
    # pending tool call, never B's.
    task_a = asyncio.ensure_future(cm.aexecute(_ctx(sid_a), "await slow.nap(seconds=30)"))
    task_b = asyncio.ensure_future(cm.aexecute(_ctx(sid_b), "await slow.nap(seconds=3)"))
    await asyncio.sleep(1.0)
    task_a.cancel()
    result_b = await task_b
    assert "napped 3" in result_b.content, f"B was collateral damage: {result_b.content}"
    with pytest.raises(asyncio.CancelledError):
        await task_a
