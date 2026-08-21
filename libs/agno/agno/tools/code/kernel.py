"""Kernel lifecycle and cell execution for CodeMode.

One ``KernelSession`` owns one IPython kernel subprocess, launched from an
explicit ``KernelSpec`` built around ``python``, so no installed kernelspec is
ever consulted and the interpreter is exactly the one asked for. All kernel I/O — ZMQ channels, locks, timers — lives on one
background event loop owned by ``LoopRunner``, so the sync and async toolkit
surfaces share a single client and a single per-session ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import os
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict, deque
from queue import Empty
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools.code.errors import KernelBusyError, KernelDiedError
from agno.tools.code.types import CellResult
from agno.utils.log import log_debug, log_warning

try:
    from jupyter_client.kernelspec import KernelSpec
    from jupyter_client.manager import AsyncKernelManager
except ImportError:
    raise ImportError(
        "`jupyter_client` and `ipykernel` are not installed. Please install them using `pip install 'agno[code]'`"
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

# How many cell context tokens a session keeps. Each user cell gets a token
# that maps a bridged call back to the run that created it; a background task
# older than this window falls back to the current run's context.
_MAX_CONTEXT_TOKENS = 8

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

    The cap applies at accumulation time, so a runaway loop bounds host
    memory and not just the returned payload. Three quarters of the budget
    keep the head of the stream and the last quarter keeps a rolling tail:
    the end of a long stream is where the traceback or the summary lives,
    and a head-only cut loses exactly that.
    """

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self._head_limit = max(1, max_chars * 3 // 4)
        self._tail_limit = max(1, max_chars - self._head_limit)
        self._head: List[str] = []
        self._head_length = 0
        self._tail: "deque[str]" = deque()
        self._tail_length = 0
        self._seen = 0

    def add(self, text: str) -> None:
        if not text:
            return
        self._seen += len(text)
        room = self._head_limit - self._head_length
        if room > 0:
            piece = text[:room]
            self._head.append(piece)
            self._head_length += len(piece)
            text = text[room:]
            if not text:
                return
        if len(text) >= self._tail_limit:
            self._tail.clear()
            self._tail.append(text[-self._tail_limit :])
            self._tail_length = self._tail_limit
            return
        self._tail.append(text)
        self._tail_length += len(text)
        while self._tail_length > self._tail_limit and len(self._tail) > 1:
            dropped = self._tail.popleft()
            self._tail_length -= len(dropped)
        if self._tail_length > self._tail_limit:
            only = self._tail.popleft()
            keep = only[-self._tail_limit :]
            self._tail.append(keep)
            self._tail_length = len(keep)

    @property
    def truncated(self) -> bool:
        # Truncated means characters were actually lost, not merely that the
        # stream spilled from the head budget into the tail ring.
        return self._seen > self._head_length + self._tail_length

    def render(self) -> str:
        head = "".join(self._head)
        tail = "".join(self._tail)
        if not self.truncated:
            return head + tail
        omitted = self._seen - len(head) - len(tail)
        return f"{head}\n[... {omitted} chars omitted; output capped at {self.max_chars} ...]\n{tail}"


class StderrTail:
    """Keeps the last bytes a kernel wrote to stderr, and keeps the pipe drained.

    The kernel's stderr is piped so it stays out of the host's console, but a
    pipe nobody reads deadlocks the child once its buffer fills, so a daemon
    thread drains it continuously into a bounded ring. The tail is what a
    startup or death error can actually show: the reason a kernel refused to
    start is one of these lines, never in the exception jupyter_client raises.
    """

    def __init__(self, stream: Any, max_bytes: int = 4096) -> None:
        self.max_bytes = max_bytes
        self._chunks: "deque[bytes]" = deque()
        self._length = 0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, args=(stream,), name="agno-kernel-stderr", daemon=True)
        self._thread.start()

    def _drain(self, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", "replace")
                with self._lock:
                    self._chunks.append(chunk)
                    self._length += len(chunk)
                    while self._length > self.max_bytes and len(self._chunks) > 1:
                        dropped = self._chunks.popleft()
                        self._length -= len(dropped)
        except Exception:
            return

    def tail(self) -> str:
        with self._lock:
            text = b"".join(self._chunks).decode("utf-8", "replace")
        return text[-self.max_bytes :].strip()

    def settle(self, timeout: float = 0.25) -> None:
        """Give the drain thread a moment to read the final bytes at EOF."""
        self._thread.join(timeout)

    def describe(self) -> str:
        text = self.tail()
        return f" Kernel stderr tail:\n{text}" if text else ""


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
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        max_images_per_cell: int = 8,
        max_image_bytes: int = 5_000_000,
        owner_user_id: Optional[str] = None,
        flush_hook: Optional[Callable[["KernelSession"], Coroutine[Any, Any, None]]] = None,
        setup_hook: Optional[Callable[["KernelSession"], Coroutine[Any, Any, Optional[str]]]] = None,
        on_evict: Optional[Callable[["KernelSession"], None]] = None,
        served_before: bool = False,
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
        # Working directory and extra environment for the kernel process. The
        # extras are laid over the parent environment, never replacing it.
        self.cwd = cwd
        self.env = env
        # Bounds on images promoted from display_data into the cell result;
        # max_output_chars covers the text streams, never the image bytes.
        self.max_images_per_cell = max_images_per_cell
        self.max_image_bytes = max_image_bytes
        # The user_id of the run this session was created for. A warm kernel
        # holds that run's variables, so a run of a different user is refused
        # by the owner of this session (CodeMode) before it reaches the kernel.
        self.owner_user_id = owner_user_id
        # Called before the kernel is killed (eviction, close): flushes snapshots.
        self.flush_hook = flush_hook
        # Called after the kernel is ready: restore + bootstrap. Returns a notice or None.
        self.setup_hook = setup_hook
        # Called after an idle eviction has flushed and torn down the kernel,
        # so the owner can drop its registry entry and the RunContext with it.
        self.on_evict = on_evict

        self.km: Optional[AsyncKernelManager] = None
        self.kc: Any = None
        self._stderr_tail: Optional[StderrTail] = None
        self.lock = asyncio.Lock()
        self.execution_count = 0
        self.last_used = time.monotonic()
        self.maybe_busy = False
        self.pending_notice: Optional[str] = None
        # A cell has run since the last snapshot flush.
        self.snapshot_pending = False
        # False when this kernel did not take over the stored snapshot: it
        # belongs to another user, or it could not be read, or its restore did
        # not finish. This namespace is then not the stored state, so flushing
        # it would overwrite and delete state this kernel never read. Every
        # restore recomputes it, so a fresh kernel starts writable again.
        self.snapshot_writable = True
        # Incremented for every kernel this session starts. A bridged tool call
        # carries the generation it was issued in: the replacement kernel's call
        # ids restart at 1, so a reply from an older generation would otherwise
        # resolve to a live call of the new one.
        self.generation = 0
        # True when this process served the session id before: the first cell
        # of the new kernel then carries the reset notice unless a snapshot
        # restores the namespace.
        self._ever_started: bool = served_before
        self._evict_task: Optional[asyncio.Task] = None
        self._cell_idle_seen = False
        # Bridge wiring (set by ToolBridge.attach): comm messages seen on iopub
        # are routed to comm_handler; interrupt_hook unblocks in-flight bridged
        # tool calls when the cell is interrupted or cancelled.
        self.comm_handler: Optional[Callable[[dict], None]] = None
        self.interrupt_hook: Optional[Callable[[], Coroutine[Any, Any, None]]] = None
        self.bridge_comm_id: Optional[str] = None
        # The RunContext of the run whose cell is currently executing.
        self.run_context: Optional[Any] = None
        # And that run's ResultStore, the fallback for a bridged call whose
        # cell token has left the window.
        self.current_result_store: Optional[Any] = None
        # Set by the bridge when injected tools are bound: only then do
        # background tasks need per-cell context tokens.
        self.needs_context_tokens = False
        # Cell token -> the RunContext of the run that executed that cell. A
        # bridged call carries the token of the cell that created its task, so
        # a background task that calls a tool after its cell finished still
        # resolves to the run that started it, not to whichever run is
        # executing when the call is drained. Bounded and cleared on teardown
        # so no RunContext outlives its kernel. The parallel store map gives
        # the bridge's results handle the run's ResultStore the same way.
        self.context_tokens: "OrderedDict[str, Any]" = OrderedDict()
        self.context_stores: "OrderedDict[str, Any]" = OrderedDict()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.kc is not None

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def _make_kernel_manager(self) -> AsyncKernelManager:
        """A manager that launches exactly ``python``, and nothing else.

        The interpreter is an explicit spec object. Assigning km.kernel_cmd
        does nothing on jupyter_client 8 - it is not a trait there - so the
        kernel would come from whatever installed kernelspec the environment
        resolves, ignoring ``python`` and, with a stray JUPYTER_PATH, running
        a foreign interpreter whose dill cannot restore this session's
        snapshots. The spec below is the whole launch: no kernelspec on disk
        is ever consulted.
        """
        km = AsyncKernelManager()
        km._kernel_spec = KernelSpec(
            argv=[self.python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            display_name="agno-code-mode",
            language="python",
        )
        return km

    async def ensure_started(self) -> None:
        if self.kc is not None:
            return
        km = self._make_kernel_manager()
        launch_kwargs: Dict[str, Any] = {"stderr": subprocess.PIPE}
        if self.cwd is not None:
            launch_kwargs["cwd"] = self.cwd
        if self.env:
            launch_kwargs["env"] = {**os.environ, **self.env}
        await km.start_kernel(**launch_kwargs)
        stderr_stream = getattr(getattr(km, "provisioner", None), "process", None)
        stderr_stream = getattr(stderr_stream, "stderr", None)
        self._stderr_tail = StderrTail(stderr_stream) if stderr_stream is not None else None
        kc = km.client()
        kc.start_channels()
        try:
            await kc.wait_for_ready(timeout=60)
        except Exception as e:
            kc.stop_channels()
            try:
                await km.shutdown_kernel(now=True)
            except Exception:
                pass
            tail = self._stderr_tail.describe() if self._stderr_tail is not None else ""
            raise KernelDiedError(f"The kernel for session {self.session_id} did not become ready: {e}.{tail}") from e
        self.km = km
        self.kc = kc
        self.generation += 1
        self.execution_count = 0
        self.maybe_busy = False
        notice: Optional[str] = None
        try:
            if not self.allow_shell:
                # Footgun reducer, not a boundary: remove the bash cell magic so a
                # cell cannot reach it through run_cell_magic either.
                await self._run_silent("get_ipython().magics_manager.magics['cell'].pop('bash', None)")
            if self.startup_code:
                await self._run_silent(self.startup_code)
            await self._run_silent(BASELINE_CODE)
            if self.setup_hook is not None:
                notice = await self.setup_hook(self)
        except BaseException:
            # A cancellation or failure mid-setup must not leave a kernel that
            # looks started but skipped restore and bootstrap — the next flush
            # would snapshot an empty namespace over the durable state.
            await asyncio.shield(self._teardown_kernel())
            raise
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
        """Kill the kernel and stop the eviction timer. Idempotent.

        Takes the session lock so an in-flight cell finishes (or aborts)
        before the channels vanish under it.
        """
        if self._evict_task is not None:
            self._evict_task.cancel()
            self._evict_task = None
        async with self.lock:
            await self._teardown_kernel()

    async def _teardown_kernel(self) -> None:
        # In-flight bridged tool calls belong to the kernel being torn down.
        # Cancel them here, while their comm is still alive, so no task from
        # this generation survives to answer a call id of the next one.
        if self.interrupt_hook is not None and self.kc is not None:
            try:
                await self.interrupt_hook()
            except Exception as e:
                log_warning(f"CodeMode bridge cancel on teardown failed for session {self.session_id}: {e}")
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
        self.bridge_comm_id = None
        self._stderr_tail = None
        # The RunContext carries the run's whole message list. A torn-down
        # session must not pin it until the next run stamps a new one; the
        # token map holds the same contexts and dies with the kernel too.
        self.run_context = None
        self.current_result_store = None
        self.context_tokens.clear()
        self.context_stores.clear()

    async def restart(self, before_start: Optional[Callable[[], Coroutine[Any, Any, None]]] = None) -> str:
        """Tear the kernel down, start a fresh one, and return the reset notice.

        ``before_start`` runs under the session lock after teardown — the
        snapshot clear goes here so a debounced flush can never land between
        the clear and the fresh start and resurrect discarded state.
        """
        async with self.lock:
            await self._teardown_kernel()
            if before_start is not None:
                await before_start()
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
                        self.snapshot_pending = False
                    except Exception as e:
                        log_warning(f"CodeMode snapshot flush on eviction failed: {e}")
                await self._teardown_kernel()
                self._evict_task = None
                # The snapshot is durable and the kernel is gone: nothing about
                # this session is worth keeping in memory. The next execute for
                # the id starts a fresh kernel and restores from the snapshot.
                if self.on_evict is not None:
                    try:
                        self.on_evict(self)
                    except Exception as e:
                        log_warning(f"CodeMode eviction callback failed for session {self.session_id}: {e}")
                return

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_cell(
        self,
        code: str,
        timeout: Optional[float] = None,
        run_context: Optional[Any] = None,
        result_store: Optional[Any] = None,
    ) -> CellResult:
        """Run one cell, serialized on the per-session lock.

        A busy kernel that does not clear within ``busy_wait`` raises
        ``KernelBusyError``; the on_busy_kernel="restart" policy is applied by
        the caller (CodeMode), which owns the snapshot store the restart must
        also clear.
        """
        async with self.lock:
            # Stamp the run context under the lock: bridged tool calls of THIS
            # cell must see this run's context, not a later queued run's.
            if run_context is not None:
                self.run_context = run_context
            self.current_result_store = result_store
            await self.ensure_started()
            if self.maybe_busy:
                cleared = await self._clear_busy()
                if not cleared:
                    raise KernelBusyError()
            await self._drain_channels()
            await self._stamp_context_token(run_context, result_store)
            self._cell_idle_seen = False
            try:
                result = await self._execute_locked(code, timeout)
            except asyncio.CancelledError:
                # The run was cancelled mid-cell. If the kernel already went
                # idle (cancellation landed between idle and the shell reply),
                # it is NOT busy — flagging it would spuriously wedge or, under
                # the restart policy, wipe a healthy namespace.
                if not self._cell_idle_seen:
                    self.maybe_busy = True
                    await self._interrupt_quietly()
                raise
            self.touch()
            return result

    async def _stamp_context_token(self, run_context: Optional[Any], result_store: Optional[Any] = None) -> None:
        """Bind the coming cell, and every task it spawns, to this run's context.

        The bridge bootstrap reads the token into a contextvar in a
        pre_run_cell hook, and asyncio tasks copy the context they are created
        in, so a bridged call made by a background task carries the token of
        the cell that created the task. Silent cells fire no pre_run_cell, so
        internal cells never disturb the binding. Without a bridge there is
        nothing to bind.
        """
        if self.comm_handler is None or self.kc is None:
            return
        # A plain CodeMode with no injected tools and no store has nothing a
        # token could resolve, so its cells skip the extra silent round trip.
        if not self.needs_context_tokens and result_store is None:
            return
        token = uuid4().hex[:16]
        self.context_tokens[token] = run_context
        self.context_stores[token] = result_store
        while len(self.context_tokens) > _MAX_CONTEXT_TOKENS:
            dropped, _ = self.context_tokens.popitem(last=False)
            self.context_stores.pop(dropped, None)
        await self._run_silent(f"_agno_cm_next_token = '{token}'")

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
                    tail = self._stderr_tail.describe() if self._stderr_tail is not None else ""
                    raise KernelDiedError(
                        f"The kernel for session {self.session_id} died while executing the cell. "
                        f"A fresh kernel will start on the next execute; previous state is gone.{tail}"
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
                    if len(images) >= self.max_images_per_cell:
                        stderr.add(f"[image dropped: more than {self.max_images_per_cell} images in one cell]\n")
                    elif len(png) * 3 // 4 > self.max_image_bytes:
                        stderr.add(
                            f"[image dropped: about {len(png) * 3 // 4} bytes, "
                            f"over the {self.max_image_bytes}-byte limit]\n"
                        )
                    else:
                        try:
                            images.append(Image(content=base64.b64decode(png), mime_type="image/png", format="png"))
                        except Exception as e:
                            log_warning(f"CodeMode could not decode display_data image: {e}")
            elif msg_type == "error":
                traceback_text = _strip_ansi("\n".join(content.get("traceback", [])))
                status = "error"
            elif msg_type == "status" and content.get("execution_state") == "idle":
                self._cell_idle_seen = True
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
            if self._route_comm(msg):
                # A busy cell can still issue bridge calls; eating one here
                # would leave its stub blocked forever and the kernel wedged.
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
        if self._stderr_tail is not None:
            self._stderr_tail.settle()
        tail = self._stderr_tail.describe() if self._stderr_tail is not None else ""
        log_warning(f"CodeMode kernel for session {self.session_id} died.{tail}")
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
                    tail = self._stderr_tail.describe() if self._stderr_tail is not None else ""
                    raise KernelDiedError(
                        f"The kernel for session {self.session_id} died during an internal cell.{tail}"
                    )
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
