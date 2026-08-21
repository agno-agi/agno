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

from agno.approval import approval
from agno.run import RunContext
from agno.tools import Function, Toolkit, tool
from agno.tools.code import CodeMode

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


# ------------------------------------------------------------------
# Awkward schemas: optional before required, keyword and non-identifier names
# ------------------------------------------------------------------


def _raw_schema_function(name, properties, required):
    """A Function carrying a hand-written schema, as an MCP tool does."""

    def _entrypoint(**kwargs):
        import json as _json

        return _json.dumps(kwargs, sort_keys=True)

    return Function(
        name=name,
        description=f"{name} description.",
        parameters={"type": "object", "properties": properties, "required": required},
        entrypoint=_entrypoint,
        skip_entrypoint_processing=True,
    )


class AwkwardTools(Toolkit):
    """Schemas a generator emits: declaration order, and names Python rejects."""

    def __init__(self, **kwargs):
        super().__init__(
            name="awkward_tools",
            tools=[
                _raw_schema_function("search", {"limit": {"type": "integer"}, "query": {"type": "string"}}, ["query"]),
                _raw_schema_function("fetch", {"from": {"type": "string"}, "start-date": {"type": "string"}}, ["from"]),
            ],
            **kwargs,
        )


def test_optional_property_before_a_required_one_still_binds(make_code_mode):
    cm = make_code_mode(tools=[AwkwardTools()])
    result = cm.run(_sid("awkward-order"), "await awkward.search(query='q')")
    assert result.status == "ok", f"bootstrap failed: {result.traceback}"
    assert result.result is not None
    assert '"query": "q"' in result.result


def test_keyword_and_non_identifier_parameters_map_back_to_schema_names(make_code_mode):
    cm = make_code_mode(tools=[AwkwardTools()])
    result = cm.run(_sid("awkward-names"), "await awkward.fetch(from_='a', start_date='b')")
    assert result.status == "ok", f"bootstrap failed: {result.traceback}"
    assert result.result is not None
    assert '"from": "a"' in result.result
    assert '"start-date": "b"' in result.result


def test_an_awkward_toolkit_does_not_unbind_the_ones_after_it(make_code_mode):
    cm = make_code_mode(tools=[AwkwardTools(), EchoTools(), top_level_helper])
    sid = _sid("awkward-others")
    assert cm.run(sid, "await echo.echo(text='ok')").result == "'echo:ok'"
    assert cm.run(sid, "await top_level_helper(3)").result == "6"


def test_one_unbindable_function_leaves_every_other_handle_bound(make_code_mode):
    # A spec entry the host-side name mapping would never emit. Each binding is
    # isolated, so this one degrades to a raising stub instead of taking the
    # bootstrap cell - and every other handle - down with it.
    cm = make_code_mode(tools=[EchoTools(), top_level_helper])
    cm._bridge._spec["toolkits"][0]["functions"].append(
        {"name": "broken", "doc": "", "params": [{"name": "class", "wire": "class", "required": True}]}
    )
    sid = _sid("isolated")
    assert cm.run(sid, "await echo.echo(text='ok')").result == "'echo:ok'"
    assert cm.run(sid, "await top_level_helper(4)").result == "8"
    code = (
        "try:\n"
        "    await echo.broken(1)\n"
        "    outcome = 'NO-ERROR'\n"
        "except NameError:\n"
        "    outcome = 'NAME-ERROR'\n"
        "except RuntimeError as e:\n"
        "    outcome = 'RuntimeError: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(sid, code)
    assert result.result is not None
    assert "NO-ERROR" not in result.result
    assert "NAME-ERROR" not in result.result
    assert "echo.broken" in result.result


# ------------------------------------------------------------------
# Hooks and approvals on a bridged call
# ------------------------------------------------------------------

_hook_log: list = []
_deleted: list = []


async def _async_policy_gate(function_name, function_call, arguments):
    _hook_log.append("async:" + function_name)
    if arguments.get("target") == "prod":
        raise ValueError("blocked by policy")
    return await function_call(**arguments)


def _sync_audit_hook(function_name, function_call, arguments):
    _hook_log.append("sync:" + function_name)
    return function_call(**arguments)


@tool(tool_hooks=[_async_policy_gate])
def delete_everything(target: str) -> str:
    """Delete the target.

    Args:
        target: What to delete.
    """
    _deleted.append(target)
    return "DELETED " + target


@tool(tool_hooks=[_sync_audit_hook])
def rename_everything(target: str) -> str:
    """Rename the target.

    Args:
        target: What to rename.
    """
    return "RENAMED " + target


@approval(type="required")
def wire_money(amount: int) -> str:
    """Wire money out.

    Args:
        amount: How much to wire.
    """
    _deleted.append(f"wired {amount}")
    return f"SENT {amount}"


@pytest.fixture(autouse=True)
def _reset_hook_log():
    _hook_log.clear()
    _deleted.clear()
    yield


def test_async_tool_hook_runs_on_a_bridged_sync_tool(make_code_mode):
    cm = make_code_mode(tools=[delete_everything])
    code = (
        "try:\n"
        "    outcome = await delete_everything(target='prod')\n"
        "except RuntimeError as e:\n"
        "    outcome = 'RuntimeError: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("async-hook"), code)
    assert result.result is not None
    assert "DELETED" not in result.result, "the async hook was skipped and the tool ran"
    assert "blocked by policy" in result.result
    assert _deleted == []
    assert _hook_log == ["async:delete_everything"]


def test_async_tool_hook_passes_an_allowed_call_through(make_code_mode):
    cm = make_code_mode(tools=[delete_everything])
    result = cm.run(_sid("async-hook-ok"), "await delete_everything(target='scratch')")
    assert result.result == "'DELETED scratch'"
    assert _deleted == ["scratch"]


def test_sync_tool_hook_still_runs_on_a_bridged_call(make_code_mode):
    cm = make_code_mode(tools=[rename_everything])
    result = cm.run(_sid("sync-hook"), "await rename_everything(target='scratch')")
    assert result.result == "'RENAMED scratch'"
    assert _hook_log == ["sync:rename_everything"]


def test_tool_needing_approval_is_refused_in_the_kernel(make_code_mode):
    cm = make_code_mode(tools=[wire_money])
    code = (
        "try:\n"
        "    outcome = await wire_money(amount=1000)\n"
        "except RuntimeError as e:\n"
        "    outcome = 'RuntimeError: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("approval"), code)
    assert result.result is not None
    assert "SENT" not in result.result, "an approval-gated tool executed from a cell"
    assert "approval" in result.result
    assert _deleted == []


# ------------------------------------------------------------------
# Async tools run on the loop their toolkit was connected on
# ------------------------------------------------------------------


class LoopProbeTools(Toolkit):
    """A toolkit whose client belongs to the loop that connected it."""

    _requires_connect = True

    def __init__(self, **kwargs):
        self.connect_loop = None
        self.closed = False
        super().__init__(
            name="probe_tools",
            tools=[self.status],
            async_tools=[(self.awhere, "where")],
            **kwargs,
        )

    def connect(self) -> None:
        self.connect_loop = asyncio.get_running_loop()

    def close(self) -> None:
        self.closed = True

    def status(self) -> str:
        """Report whether this toolkit is connected."""
        return "connected" if self.connect_loop is not None else "not-connected"

    async def awhere(self) -> str:
        """Report whether this call ran on the loop that connected the toolkit."""
        await asyncio.sleep(0)
        return "same-loop" if asyncio.get_running_loop() is self.connect_loop else "other-loop"


async def test_bridged_async_tool_runs_on_the_connecting_loop(make_code_mode):
    probe = LoopProbeTools()
    cm = make_code_mode(tools=[probe])
    cm.connect()
    assert probe.connect_loop is asyncio.get_running_loop()
    result = await cm.aexecute(_ctx(_sid("loop-affinity")), "await probe.where()")
    assert "same-loop" in result.content, "the tool ran on CodeMode's private loop, not the agent's"


async def test_bridged_async_tool_without_a_host_loop_still_answers(make_code_mode):
    # No connect(), so there is no captured host loop: the call is served on
    # CodeMode's own loop rather than failing.
    probe = LoopProbeTools()
    cm = make_code_mode(tools=[probe])
    result = await cm.aexecute(_ctx(_sid("no-host-loop")), "await probe.where()")
    assert "loop" in result.content


@approval(type="audit")
def audit_without_a_hitl_flag(amount: int) -> str:
    """Pay out, with an audit record and no HITL flag to hang it on.

    Args:
        amount: How much to pay.
    """
    _deleted.append(f"paid {amount}")
    return f"PAID {amount}"


def test_a_callable_that_cannot_bind_raises_instead_of_name_error(make_code_mode):
    # The instructions advertise the name either way, so the kernel must hold
    # something that explains itself.
    cm = make_code_mode(tools=[audit_without_a_hitl_flag])
    code = (
        "try:\n"
        "    outcome = await audit_without_a_hitl_flag(amount=5)\n"
        "except NameError:\n"
        "    outcome = 'NAME-ERROR'\n"
        "except RuntimeError as e:\n"
        "    outcome = 'RuntimeError: ' + str(e)\n"
        "outcome\n"
    )
    result = cm.run(_sid("unbindable-callable"), code)
    assert result.result is not None
    assert "PAID" not in result.result
    assert "NAME-ERROR" not in result.result
    assert "audit_without_a_hitl_flag" in result.result
    assert _deleted == []


async def test_sync_execute_from_inside_the_host_loop_does_not_wait_on_it(make_code_mode):
    # A synchronous execute() started from inside the host loop blocks that
    # loop until the cell finishes, so the tool call cannot be scheduled there:
    # it would wait on the cell that is waiting on it.
    probe = LoopProbeTools()
    cm = make_code_mode(tools=[probe], timeout=25)
    cm.connect()
    cm.run(_sid("warm"), "1")
    started = time.monotonic()
    result = cm.execute(_ctx(_sid("blocked-host")), "await probe.where()")
    elapsed = time.monotonic() - started
    assert "other-loop" in result.content, f"cell did not answer: {result.content}"
    assert elapsed < 15, "the call waited on a loop that was blocked by this very call"
