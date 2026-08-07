"""Kernel lifecycle and cell execution for CodeMode.

One ``KernelSession`` owns one IPython kernel subprocess (launched with
``python -m ipykernel_launcher`` so no kernelspec is needed and the ``python=``
override works). All kernel I/O — ZMQ channels, locks, timers — lives on one
background event loop owned by ``LoopRunner``, so the sync and async toolkit
surfaces share a single client and a single per-session ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import re
import sys
import threading
import time
from queue import Empty
from typing import Any, Callable, Coroutine, List, Literal, Optional

from agno.media import Image
from agno.tools.code_mode.errors import KernelBusyError, KernelDiedError
from agno.tools.code_mode.types import CellResult
from agno.utils.log import log_debug, log_warning

try:
    from jupyter_client.manager import AsyncKernelManager
except ImportError:
    raise ImportError(
        "`jupyter_client` and `ipykernel` are not installed. Please install them using `pip install 'agno[code-mode]'`"
    )

# The in-band notice prefixed to the next execute result after the kernel was
# restarted, died, or was evicted without a restorable snapshot.
RESET_NOTICE = (
    "<code_mode_reset>\n"
    "The code environment was restarted. Variables, imports, async tasks, and open "
    "resources from before the restart are gone. Recreate them before use.\n"
    "</code_mode_reset>"
)

# Strips ANSI CSI sequences (color codes, cursor moves) from kernel tracebacks.
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Records the names IPython itself put in the user namespace (open, display,
# ...) so variable listing and snapshots can tell them from user state. A name
# still bound to its baseline object is IPython's; a rebound name is a user
# shadow worth keeping. Builtins are reached through the _cm_b alias so a user
# variable named ``list`` or ``open`` cannot break introspection.
BASELINE_CODE = (
    "import builtins as _cm_b\n"
    "_agno_cm_baseline = {\n"
    "    _cm_k: _cm_b.globals()[_cm_k]\n"
    "    for _cm_k in _cm_b.list(_cm_b.globals())\n"
    "    if not _cm_k.startswith('_')\n"
    "}\n"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class OutputAccumulator:
    """Accumulates one output stream under a hard character budget.

    The cap applies at accumulation time: once the budget is spent, further
    chunks are dropped (only their arrival is noted), so a runaway loop bounds
    host memory and not just the returned payload.
    """

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.truncated = False
        self._parts: List[str] = []
        self._length = 0

    def add(self, text: str) -> None:
        if not text:
            return
        remaining = self.max_chars - self._length
        if remaining <= 0:
            self.truncated = True
            return
        if len(text) > remaining:
            self._parts.append(text[:remaining])
            self._length = self.max_chars
            self.truncated = True
        else:
            self._parts.append(text)
            self._length += len(text)

    def render(self) -> str:
        text = "".join(self._parts)
        if self.truncated:
            text += f"\n[... output truncated at {self.max_chars} chars ...]"
        return text


class LoopRunner:
    """Owns the background event loop thread all kernel I/O runs on."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def started(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(ready.set)
                loop.run_forever()

            thread = threading.Thread(target=_run, name="agno-code-mode", daemon=True)
            thread.start()
            ready.wait()
            self._loop = loop
            self._thread = thread
            return loop

    def submit(self, coro: Coroutine[Any, Any, Any]) -> "concurrent.futures.Future[Any]":
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())

    def stop(self) -> None:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
            self._thread = None


class KernelSession:
    """One live kernel bound to one ``session_id``.

    Every coroutine on this class must run on the owning ``LoopRunner`` loop;
    the per-session ``asyncio.Lock`` serializes cells there.
    """

    def __init__(
        self,
        session_id: str,
        *,
        python: Optional[str] = None,
        startup_code: Optional[str] = None,
        allow_shell: bool = True,
        max_output_chars: int = 65_536,
        busy_wait: float = 5.0,
        on_busy_kernel: str = "wait",
        interrupt_grace: float = 1.0,
        idle_ttl: int = 1800,
        flush_hook: Optional[Callable[["KernelSession"], Coroutine[Any, Any, None]]] = None,
        setup_hook: Optional[Callable[["KernelSession"], Coroutine[Any, Any, Optional[str]]]] = None,
    ) -> None:
        self.session_id = session_id
        self.python = python or sys.executable
        self.startup_code = startup_code
        self.allow_shell = allow_shell
        self.max_output_chars = max_output_chars
        self.busy_wait = busy_wait
        self.on_busy_kernel = on_busy_kernel
        self.interrupt_grace = interrupt_grace
        self.idle_ttl = idle_ttl
        # Called before the kernel is killed (eviction, close): flushes snapshots.
        self.flush_hook = flush_hook
        # Called after the kernel is ready: restore + bootstrap. Returns a notice or None.
        self.setup_hook = setup_hook

        self.km: Optional[AsyncKernelManager] = None
        self.kc: Any = None
        self.lock = asyncio.Lock()
        self.execution_count = 0
        self.last_used = time.monotonic()
        self.maybe_busy = False
        self.pending_notice: Optional[str] = None
        self._ever_started = False
        self._evict_task: Optional[asyncio.Task] = None
        # Bridge wiring (set by ToolBridge.attach): comm messages seen on iopub
        # are routed to comm_handler; interrupt_hook unblocks in-flight bridged
        # tool calls when the cell is interrupted or cancelled.
        self.comm_handler: Optional[Callable[[dict], None]] = None
        self.interrupt_hook: Optional[Callable[[], Coroutine[Any, Any, None]]] = None
        self.bridge_comm_id: Optional[str] = None
        # The RunContext of the run whose cell is currently executing.
        self.run_context: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.kc is not None

    def touch(self) -> None:
        self.last_used = time.monotonic()

    async def ensure_started(self) -> None:
        if self.kc is not None:
            return
        km = AsyncKernelManager()
        # kernel_cmd is a traitlets attribute mypy cannot see. Launching by
        # explicit command needs no installed kernelspec and honors python=.
        km.kernel_cmd = [self.python, "-m", "ipykernel_launcher", "-f", "{connection_file}"]  # type: ignore[attr-defined]
        await km.start_kernel()
        kc = km.client()
        kc.start_channels()
        try:
            await kc.wait_for_ready(timeout=60)
        except Exception:
            kc.stop_channels()
            try:
                await km.shutdown_kernel(now=True)
            except Exception:
                pass
            raise
        self.km = km
        self.kc = kc
        self.execution_count = 0
        self.maybe_busy = False
        if not self.allow_shell:
            # Footgun reducer, not a boundary: remove the bash cell magic so a
            # cell cannot reach it through run_cell_magic either.
            await self._run_silent("get_ipython().magics_manager.magics['cell'].pop('bash', None)")
        if self.startup_code:
            await self._run_silent(self.startup_code)
        await self._run_silent(BASELINE_CODE)
        notice: Optional[str] = None
        if self.setup_hook is not None:
            notice = await self.setup_hook(self)
        if notice is not None:
            self.pending_notice = notice
        elif self._ever_started and self.pending_notice is None:
            # A prior kernel existed in this process and nothing was restored.
            self.pending_notice = RESET_NOTICE
        self._ever_started = True
        self.touch()
        if self.idle_ttl and self._evict_task is None:
            self._evict_task = asyncio.get_running_loop().create_task(self._evict_loop())
        log_debug(f"CodeMode kernel started for session {self.session_id}")

    async def shutdown(self) -> None:
        """Kill the kernel and stop the eviction timer. Idempotent."""
        if self._evict_task is not None:
            self._evict_task.cancel()
            self._evict_task = None
        await self._teardown_kernel()

    async def _teardown_kernel(self) -> None:
        kc, km = self.kc, self.km
        self.kc = None
        self.km = None
        if kc is not None:
            try:
                kc.stop_channels()
            except Exception:
                pass
        if km is not None:
            try:
                await km.shutdown_kernel(now=True)
            except Exception:
                pass
        self.maybe_busy = False

    async def restart(self) -> str:
        """Tear the kernel down, start a fresh one, and return the reset notice."""
        async with self.lock:
            await self._teardown_kernel()
            self.pending_notice = None
            await self.ensure_started()
            # A deliberate restart discards state: the reset notice wins over
            # anything ensure_started queued.
            self.pending_notice = None
            return RESET_NOTICE

    def take_notice(self) -> Optional[str]:
        notice = self.pending_notice
        self.pending_notice = None
        return notice

    async def _evict_loop(self) -> None:
        interval = min(max(self.idle_ttl / 4.0, 0.2), 30.0)
        while True:
            await asyncio.sleep(interval)
            if self.kc is None:
                continue
            if self.lock.locked():
                continue
            if time.monotonic() - self.last_used < self.idle_ttl:
                continue
            async with self.lock:
                if self.kc is None or time.monotonic() - self.last_used < self.idle_ttl:
                    continue
                log_debug(f"CodeMode kernel for session {self.session_id} idle past {self.idle_ttl}s; evicting")
                if self.flush_hook is not None:
                    try:
                        await self.flush_hook(self)
                    except Exception as e:
                        log_warning(f"CodeMode snapshot flush on eviction failed: {e}")
                await self._teardown_kernel()
                self._evict_task = None
                return

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_cell(self, code: str, timeout: Optional[float] = None) -> CellResult:
        """Run one cell, serialized on the per-session lock."""
        async with self.lock:
            await self.ensure_started()
            if self.maybe_busy:
                cleared = await self._clear_busy()
                if not cleared:
                    if self.on_busy_kernel == "restart":
                        await self._teardown_kernel()
                        await self.ensure_started()
                        self.pending_notice = RESET_NOTICE
                    else:
                        raise KernelBusyError()
            await self._drain_channels()
            try:
                result = await self._execute_locked(code, timeout)
            except asyncio.CancelledError:
                # The run was cancelled mid-cell: interrupt the kernel, flag it
                # possibly busy for the next cell, and propagate.
                await self._interrupt_quietly()
                self.maybe_busy = True
                raise
            self.touch()
            return result

    async def _execute_locked(self, code: str, timeout: Optional[float]) -> CellResult:
        assert self.kc is not None and self.km is not None
        msg_id = self.kc.execute(code, silent=False, store_history=True, allow_stdin=False, stop_on_error=True)

        stdout = OutputAccumulator(self.max_output_chars)
        stderr = OutputAccumulator(self.max_output_chars)
        result_acc = OutputAccumulator(self.max_output_chars)
        has_result = False
        images: List[Image] = []
        traceback_text: Optional[str] = None
        status: Literal["ok", "error", "aborted"] = "ok"
        started_at = time.monotonic()
        deadline = started_at + timeout if timeout else None
        interrupted = False
        interrupt_deadline: Optional[float] = None

        while True:
            now = time.monotonic()
            if interrupt_deadline is not None and now >= interrupt_deadline:
                # Interrupt did not land within the grace window: stop waiting.
                self.maybe_busy = True
                self.execution_count += 1
                return CellResult(
                    stdout=stdout.render(),
                    stderr=self._with_timeout_note(stderr, timeout),
                    result=None,
                    traceback=traceback_text,
                    status="aborted",
                    truncated=self._truncated_streams(stdout, stderr, result_acc),
                    execution_count=self.execution_count,
                    images=images,
                )
            if deadline is not None and now >= deadline and not interrupted:
                await self._interrupt_quietly()
                interrupted = True
                interrupt_deadline = now + self.interrupt_grace
            wait = 1.0
            if deadline is not None and not interrupted:
                wait = min(wait, max(deadline - now, 0.01))
            if interrupt_deadline is not None:
                wait = min(wait, max(interrupt_deadline - now, 0.01))
            try:
                msg = await self.kc.get_iopub_msg(timeout=wait)
            except (Empty, asyncio.TimeoutError):
                if not await self.km.is_alive():
                    await self._on_kernel_death()
                    raise KernelDiedError(
                        f"The kernel for session {self.session_id} died while executing the cell. "
                        "A fresh kernel will start on the next execute; previous state is gone."
                    )
                continue
            if self._route_comm(msg):
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = msg["msg_type"]
            content = msg["content"]
            if msg_type == "stream":
                if content.get("name") == "stderr":
                    stderr.add(content.get("text", ""))
                else:
                    stdout.add(content.get("text", ""))
            elif msg_type == "execute_result":
                has_result = True
                result_acc.add(content.get("data", {}).get("text/plain", ""))
            elif msg_type == "display_data":
                png = content.get("data", {}).get("image/png")
                if png:
                    try:
                        images.append(Image(content=base64.b64decode(png), mime_type="image/png", format="png"))
                    except Exception as e:
                        log_warning(f"CodeMode could not decode display_data image: {e}")
            elif msg_type == "error":
                traceback_text = _strip_ansi("\n".join(content.get("traceback", [])))
                status = "error"
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        execution_count = await self._consume_shell_reply(msg_id)
        if execution_count is not None:
            self.execution_count = execution_count
        else:
            self.execution_count += 1
        return CellResult(
            stdout=stdout.render(),
            stderr=self._with_timeout_note(stderr, timeout) if interrupted else stderr.render(),
            result=result_acc.render() if has_result else None,
            traceback=traceback_text,
            status=status,
            truncated=self._truncated_streams(stdout, stderr, result_acc),
            execution_count=self.execution_count,
            images=images,
        )

    def _with_timeout_note(self, stderr: OutputAccumulator, timeout: Optional[float]) -> str:
        text = stderr.render()
        note = f"[cell interrupted: exceeded timeout of {timeout}s]"
        return f"{text}\n{note}" if text else note

    @staticmethod
    def _truncated_streams(
        stdout: OutputAccumulator, stderr: OutputAccumulator, result: OutputAccumulator
    ) -> List[str]:
        truncated = []
        if stdout.truncated:
            truncated.append("stdout")
        if stderr.truncated:
            truncated.append("stderr")
        if result.truncated:
            truncated.append("result")
        return truncated

    async def _consume_shell_reply(self, msg_id: str, timeout: float = 10.0) -> Optional[int]:
        """Read the execute_reply for ``msg_id``; returns its execution_count."""
        assert self.kc is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply = await self.kc.get_shell_msg(timeout=max(deadline - time.monotonic(), 0.01))
            except (Empty, asyncio.TimeoutError):
                return None
            if reply.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            count = reply.get("content", {}).get("execution_count")
            return int(count) if isinstance(count, int) else None
        return None

    def _route_comm(self, msg: dict) -> bool:
        """Route comm traffic (the tool bridge) out of the normal message flow."""
        if not str(msg.get("msg_type", "")).startswith("comm"):
            return False
        if self.comm_handler is not None:
            try:
                self.comm_handler(msg)
            except Exception as e:
                log_warning(f"CodeMode bridge handler failed: {e}")
        return True

    async def _interrupt_quietly(self) -> None:
        if self.km is None:
            return
        try:
            await self.km.interrupt_kernel()
        except Exception as e:
            log_warning(f"CodeMode interrupt failed for session {self.session_id}: {e}")
        if self.interrupt_hook is not None:
            try:
                await self.interrupt_hook()
            except Exception as e:
                log_warning(f"CodeMode interrupt hook failed: {e}")

    async def _clear_busy(self) -> bool:
        """Wait up to ``busy_wait`` for a busy kernel to go idle, re-interrupting.

        Returns True when the kernel is idle again. Raises ``KernelDiedError``
        never — a kernel that died while busy is torn down and reported clear,
        so the caller's ``ensure_started`` brings up a fresh one.
        """
        assert self.km is not None and self.kc is not None
        deadline = time.monotonic() + self.busy_wait
        next_interrupt = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_interrupt:
                await self._interrupt_quietly()
                next_interrupt = time.monotonic() + 0.5
            try:
                msg = await self.kc.get_iopub_msg(timeout=0.25)
            except (Empty, asyncio.TimeoutError):
                if not await self.km.is_alive():
                    await self._on_kernel_death()
                    await self.ensure_started()
                    return True
                continue
            if msg["msg_type"] == "status" and msg["content"].get("execution_state") == "idle":
                self.maybe_busy = False
                await self._drain_channels()
                return True
        return False

    async def _drain_channels(self) -> None:
        """Discard stale messages left over from an aborted or interrupted cell."""
        if self.kc is None:
            return
        for getter, route in ((self.kc.get_iopub_msg, True), (self.kc.get_shell_msg, False)):
            while True:
                try:
                    msg = await getter(timeout=0)
                    if route:
                        # A bridge request from a kernel background task must
                        # still be answered, or its stub waits forever.
                        self._route_comm(msg)
                except (Empty, asyncio.TimeoutError):
                    break
                except Exception:
                    break

    async def _on_kernel_death(self) -> None:
        log_warning(f"CodeMode kernel for session {self.session_id} died")
        await self._teardown_kernel()
        self.pending_notice = RESET_NOTICE

    # ------------------------------------------------------------------
    # Introspection helpers (silent cells)
    # ------------------------------------------------------------------

    async def _run_silent(self, code: str, timeout: float = 30.0, max_chars: int = 10_000_000) -> CellResult:
        """Run a hidden cell: no history, no execution_count bump."""
        assert self.kc is not None and self.km is not None
        msg_id = self.kc.execute(code, silent=True, store_history=False, allow_stdin=False)
        stdout = OutputAccumulator(max_chars)
        stderr = OutputAccumulator(self.max_output_chars)
        traceback_text: Optional[str] = None
        status: Literal["ok", "error", "aborted"] = "ok"
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return CellResult(status="aborted", stdout=stdout.render(), stderr=stderr.render())
            try:
                msg = await self.kc.get_iopub_msg(timeout=min(remaining, 1.0))
            except (Empty, asyncio.TimeoutError):
                if not await self.km.is_alive():
                    await self._on_kernel_death()
                    raise KernelDiedError(f"The kernel for session {self.session_id} died during an internal cell.")
                continue
            if self._route_comm(msg):
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = msg["msg_type"]
            content = msg["content"]
            if msg_type == "stream":
                (stderr if content.get("name") == "stderr" else stdout).add(content.get("text", ""))
            elif msg_type == "error":
                traceback_text = _strip_ansi("\n".join(content.get("traceback", [])))
                status = "error"
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break
        await self._consume_shell_reply(msg_id, timeout=5.0)
        return CellResult(stdout=stdout.render(), stderr=stderr.render(), traceback=traceback_text, status=status)


def parse_marker_line(stdout: str, marker: str) -> Optional[str]:
    """Extract the payload following ``marker`` from a silent cell's stdout."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            return line[len(marker) :]
    return None
