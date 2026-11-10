"""CodeMode — a persistent per-session Python kernel as a toolkit.

The model gets two tools: ``execute`` runs a cell in an IPython kernel that
lives as long as the session, and ``restart`` (optional) tears it down for a
fresh one. Variables, imports, helper functions, and parsed tool results
survive across turns. See ``agno.tools.code`` for the full surface.

CodeMode executes arbitrary Python and shell with the permissions of the
process running the agent. It is not a sandbox and does not pretend to be one:
use it with a trusted operator or inside an isolated container. Snapshots are
``dill`` pickles restored on resume, so restoring is also code execution — the
snapshot store inherits the trust level of the database that holds it.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import functools
import re
import weakref
from collections import OrderedDict
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple, Union

from agno.fs import FileSystem
from agno.run import RunContext
from agno.tools.code.bridge import ToolBridge
from agno.tools.code.errors import KernelBusyError, KernelDiedError
from agno.tools.code.kernel import RESET_NOTICE, KernelSession, LoopRunner, parse_marker_line
from agno.tools.code.naming import derive_handle_name, handle_names_for  # noqa: F401  (re-exported)
from agno.tools.code.snapshot import SnapshotManager
from agno.tools.code.types import CellResult
from agno.tools.function import Function, ToolResult
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning

try:
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal  # type: ignore[assignment]

_VARIABLES_MARKER = "__AGNO_CM_VARS__"
_VALUE_MARKER = "__AGNO_CM_VALUE__"

# Returned to the model when a run addresses a session owned by another user.
OWNER_REFUSAL = (
    "Error: the code environment for this session belongs to another user, so its "
    "variables and snapshot cannot be reached from this run. Continue in a new session."
)

# Upper bound on how long a run-end close() may block a plain (non-loop) thread
# waiting for snapshot flushes, when the debounce interval is shorter than this.
_CLOSE_FLUSH_FLOOR = 5.0

# How many evicted session ids are remembered, most recent kept.
_MAX_EVICTED_IDS = 1024

# Names the bridge bootstrap binds into the user namespace beside the tool
# handles: the result_store handle and the ResultTooLarge error class. Variable
# listing and snapshots treat them like the handles - environment, not state.
_BOOTSTRAP_NAMES = ("result_store", "ResultTooLarge")

_VARIABLES_CODE_TEMPLATE = (
    "import base64 as _cm_b64\n"
    "import builtins as _cm_b\n"
    "import json as _cm_json\n"
    "_cm_skip = _cm_b.set(_cm_json.loads(_cm_b64.b64decode('{skip_b64}').decode('utf-8')))\n"
    "_cm_skip.update(('In', 'Out', 'get_ipython', 'exit', 'quit'))\n"
    "_cm_base = _cm_b.globals().get('_agno_cm_baseline', {{}})\n"
    "_cm_vars = {{}}\n"
    "for _cm_k in _cm_b.list(_cm_b.globals()):\n"
    "    if _cm_k.startswith('_') or _cm_k in _cm_skip:\n"
    "        continue\n"
    "    _cm_v = _cm_b.globals()[_cm_k]\n"
    "    if _cm_k in _cm_base and _cm_base[_cm_k] is _cm_v:\n"
    "        continue\n"
    "    _cm_vars[_cm_k] = _cm_b.type(_cm_v).__name__\n"
    "_cm_b.print('\\n{marker}' + _cm_json.dumps(_cm_vars))\n"
)


def _owner_store(agent: Any, team: Any) -> Any:
    """The ResultStore of whichever owner the framework injected, or None."""
    owner = agent if agent is not None else team
    return getattr(owner, "_result_store", None)


def _in_event_loop() -> bool:
    """True when the calling thread is running an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@functools.lru_cache(maxsize=None)
def _warn() -> None:
    log_warning(
        "CodeMode runs arbitrary Python and shell with the permissions of this process. "
        "It is not a sandbox: provide human supervision or run the agent in an isolated container."
    )


def build_instructions(
    handles: List[str],
    allow_shell: bool,
    allow_restart: bool,
    snapshot_caps: Optional[Tuple[int, int]] = None,
) -> str:
    """Render the CodeMode instruction block for the given capabilities."""
    paragraphs = [
        (
            "You have a persistent Python environment. Use it as your long-lived notebook: "
            "keep intermediate variables, inspect and transform outputs, write small helper "
            "functions, and preserve useful state across turns."
        ),
        (
            "Always assign read, search, and tool results to named variables so you can revisit "
            "them later instead of re-reading them into your context. Print summaries, not raw data."
        ),
    ]
    state_paragraph = (
        "State persists across cells: variables, functions, classes, imports, notes, and parsed "
        "outputs stay available in every later turn. The environment outlives your visible "
        "conversation: variables created in turns you can no longer see are still live, and "
        "%whos lists everything that exists."
    )
    if snapshot_caps is not None:
        variable_cap, snapshot_cap = snapshot_caps
        state_paragraph += (
            f" State is saved between processes; a single variable over {variable_cap} bytes "
            f"or total state over {snapshot_cap} bytes is not saved and must be rebuilt."
        )
    if handles:
        state_paragraph += (
            " Attached tools are awaitable calls in this environment: "
            + ", ".join(handles)
            + ". Tool calls are await expressions, so their return values can be bound to variables "
            "and composed into program logic like any other call. Do not invent wrappers such as "
            "call_tool(...); call the documented function, and use help(...) on a handle to inspect it."
        )
    paragraphs.append(state_paragraph)
    paragraphs.append(
        "When result offloading is enabled, stored tool results are values here, not just "
        "envelopes: text = await result_store.get('res_...') binds the whole payload to a "
        "variable, await result_store.search('res_...', pattern) and "
        "await result_store.read('res_...', start_line=...) stay bounded, and "
        "await result_store.ids() lists what this session has stored. Compute over the "
        "variable and print summaries; never print the payload."
    )
    paragraphs.append(
        "This environment is your control environment, not the runtime of the thing you are "
        "investigating. A repository, service, dataset, or benchmark has its own environment and "
        "its own interface. Evaluate it through that interface and use this environment to "
        "coordinate and analyze what comes back. Do not install dependencies here to force an "
        "external project to import. Treat failures from the project's own environment as the "
        "relevant result."
    )
    if allow_shell:
        paragraphs.append(
            "%%bash must be the first line of its cell - no comment, import, or statement before "
            "it. Each %%bash cell is a throw-away subshell, so cd, export, and shell variables do "
            "not carry over. Keep dependent shell steps in one cell, or use %cd and "
            "os.environ[...], which are kernel-level and apply to every later %%bash cell."
        )
    if allow_restart:
        paragraphs.append(
            "If the environment is corrupted or wedged, call restart to tear it down and start "
            "fresh; every variable and import is lost."
        )
    return "\n\n".join(paragraphs)


async def _flush_locked_session(session: KernelSession) -> None:
    """Snapshot one session under its lock."""
    async with session.lock:
        if session.running and session.flush_hook is not None:
            await session.flush_hook(session)
            session.snapshot_pending = False


def _cleanup_kernels(runner: LoopRunner, sessions: Dict[str, KernelSession]) -> None:
    """Best-effort kernel teardown at garbage collection or interpreter exit."""
    try:
        if runner.started and sessions:

            async def _shutdown_all() -> None:
                for session in list(sessions.values()):
                    # A cell that ran after the last flush lives only in the
                    # kernel; save it before the kernel goes away. Bounded so a
                    # slow store cannot cost the shutdown its own budget.
                    if session.running and session.snapshot_pending and session.flush_hook is not None:
                        try:
                            await asyncio.wait_for(_flush_locked_session(session), timeout=5)
                        except Exception:
                            pass
                    await session.shutdown()

            runner.submit(_shutdown_all()).result(timeout=15)
    except Exception:
        pass
    finally:
        try:
            runner.stop()
        except Exception:
            pass


class CodeMode(Toolkit):
    """A persistent code environment: one IPython kernel per ``session_id``.

    Attach it like any toolkit: ``Agent(tools=[CodeMode()])``. Kernels start
    lazily on the first ``execute`` of a session, are reused across runs in the
    same process, and are evicted after ``idle_ttl`` seconds of inactivity.

    ``timeout`` bounds every cell; ``timeout=None`` removes the bound, and a
    cell that never finishes then blocks the calling thread (and any shutdown
    behind it) until the process is killed. Keep a timeout in any deployment
    that cannot afford a wedged worker.

    The kernel and its snapshot are keyed by ``session_id`` alone. A team
    leader and its members share the team session id, so members sharing one
    CodeMode instance share one kernel namespace, and two CodeMode instances
    snapshotting into one FileSystem restore each other's variables for the
    same session id. Give each its own FileSystem namespace when that sharing
    is not wanted.
    """

    _requires_connect = True

    def __init__(
        self,
        tools: Optional[Sequence[Union[Toolkit, Callable[..., Any], Function]]] = None,
        fs: Optional[FileSystem] = None,
        snapshot: bool = True,
        snapshot_debounce: float = 1.5,
        max_variable_bytes: int = 2_000_000,
        max_snapshot_bytes: int = 64_000_000,
        max_output_chars: int = 65_536,
        max_result_bytes: int = 1_000_000,
        allow_restart: bool = True,
        allow_shell: bool = True,
        on_busy_kernel: Literal["wait", "restart"] = "wait",
        busy_wait: float = 5.0,
        idle_ttl: int = 1800,
        timeout: Optional[int] = 300,
        python: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        startup_code: Optional[str] = None,
        max_images_per_cell: int = 8,
        max_image_bytes: int = 5_000_000,
        max_kernels: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.injected_tools: List[Union[Toolkit, Callable[..., Any], Function]] = list(tools or [])
        self.fs = fs
        self.snapshot = snapshot
        self.snapshot_debounce = snapshot_debounce
        self.max_variable_bytes = max_variable_bytes
        self.max_snapshot_bytes = max_snapshot_bytes
        self.max_output_chars = max_output_chars
        self.max_result_bytes = max_result_bytes
        self.allow_restart = allow_restart
        self.allow_shell = allow_shell
        self.on_busy_kernel: str = on_busy_kernel
        self.busy_wait = busy_wait
        self.idle_ttl = idle_ttl
        self.cell_timeout = timeout
        self.python = python
        self.cwd = cwd
        self.env = env
        self.startup_code = startup_code
        self.max_images_per_cell = max_images_per_cell
        self.max_image_bytes = max_image_bytes
        # Live kernels this CodeMode keeps at once. A new session past the
        # cap evicts the least recently used idle one, snapshot flushed
        # first. None keeps every session until its idle_ttl.
        self.max_kernels = max_kernels

        self.handles = handle_names_for(self.injected_tools)

        # The instruction text names the real snapshot caps, which the file
        # store may lower below the constructor arguments.
        snapshot_caps: Optional[Tuple[int, int]] = None
        if fs is not None and snapshot:
            from agno.tools.code.snapshot import reconcile_caps

            variable_cap, snapshot_cap, _ = reconcile_caps(
                max_variable_bytes,
                max_snapshot_bytes,
                getattr(fs, "max_file_bytes", None),
                getattr(fs, "max_namespace_bytes", None),
            )
            snapshot_caps = (variable_cap, snapshot_cap)

        registered = ["execute"] + (["restart"] if allow_restart else [])
        sync_tools = [getattr(self, name) for name in registered]
        async_tools = [(getattr(self, "a" + name), name) for name in registered]

        super().__init__(
            name=kwargs.pop("name", "code_mode"),
            tools=sync_tools,
            async_tools=async_tools,
            instructions=kwargs.pop(
                "instructions",
                build_instructions(
                    self.handles,
                    allow_shell=allow_shell,
                    allow_restart=allow_restart,
                    snapshot_caps=snapshot_caps,
                ),
            ),
            add_instructions=kwargs.pop("add_instructions", True),
            **kwargs,
        )

        # Surface-drift guard: every model-facing and developer-facing method
        # must exist with its async twin.
        for method_name in ("execute", "restart", "run", "variables", "value", "shutdown", "close"):
            assert callable(getattr(self, method_name, None)), f"CodeMode missing sync method '{method_name}'"
            assert callable(getattr(self, "a" + method_name, None)), f"CodeMode missing async method 'a{method_name}'"

        self._runner = LoopRunner()
        self._sessions: Dict[str, KernelSession] = {}
        # Ids of sessions evicted for idleness, oldest first, so a later cell
        # for one of them is told its namespace was reset. Ids only; the
        # sessions are gone. Bounded at _MAX_EVICTED_IDS: a server that mints
        # a session id per conversation would otherwise hold every id it ever
        # evicted for the life of the process. Past the bound the oldest id is
        # dropped, which costs a returning session only the reset notice.
        self._evicted: OrderedDict[str, None] = OrderedDict()
        self._background_flush: Optional["concurrent.futures.Future[Any]"] = None
        # Always constructed: the results handle binds even with no injected
        # tools, so a store's payloads are reachable from any cell.
        self._bridge: Optional[ToolBridge] = ToolBridge(self.injected_tools, max_result_bytes=max_result_bytes)
        self._snapshots: Optional[SnapshotManager] = (
            SnapshotManager(
                fs,
                debounce=snapshot_debounce,
                max_variable_bytes=max_variable_bytes,
                max_snapshot_bytes=max_snapshot_bytes,
                skip_names=[*self.handles, *_BOOTSTRAP_NAMES],
            )
            if fs is not None and snapshot
            else None
        )
        # Kernels are subprocesses: make sure they die with this object/process
        # even when the developer never calls shutdown().
        self._finalizer = weakref.finalize(self, _cleanup_kernels, self._runner, self._sessions)

    # ------------------------------------------------------------------
    # Toolkit lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect the injected toolkits that manage their own connections.

        The agent walks its own tools and sees CodeMode, not the toolkits
        bridged into the kernel, so those are connected from here. No kernel is
        started: the session is unknown at connect time and kernels start
        lazily on the first ``execute``.
        """
        if self._bridge is not None:
            self._bridge.connect_tools()

    async def aconnect(self) -> None:
        """Async variant of ``connect``."""
        if self._bridge is not None:
            await self._bridge.aconnect_tools()

    def close(self) -> None:
        """Close the injected toolkits and flush a snapshot for the sessions that ran a cell since their last one.

        The agent calls this at the end of every run, so it touches only
        sessions with unsaved work and never waits on a session whose lock
        another run holds. Kernels are NOT killed: a resumed run inside
        ``idle_ttl`` reattaches to a warm kernel and skips the restore
        entirely. ``shutdown`` is the explicit flush-everything path.

        Called from inside an event loop, the flush is handed to the kernel
        loop and this returns; a one-shot async script that exits immediately
        after its run can lose the last cell's snapshot. Await ``aclose()``
        (or call ``shutdown()``) before exiting such a script.
        """
        if self._bridge is not None:
            self._bridge.close_tools()
        if not self._runner.started or self._snapshots is None:
            return
        if _in_event_loop():
            # An async run ends on the caller's event loop. Blocking it would
            # stall every other request sharing that loop, so the flush is
            # handed to the kernel loop and this call returns.
            self._submit_background_flush()
            return
        try:
            self._runner.submit(self._aflush_pending()).result(timeout=max(self.snapshot_debounce, _CLOSE_FLUSH_FLOOR))
        except concurrent.futures.TimeoutError:
            log_warning(
                "CodeMode close: snapshot flush is taking longer than the close bound; it continues in the background"
            )
        except Exception as e:
            log_warning(f"CodeMode close: snapshot flush failed: {e}")

    async def aclose(self) -> None:
        """Async variant of ``close``."""
        if self._bridge is not None:
            await self._bridge.aclose_tools()
        if not self._runner.started or self._snapshots is None:
            return
        try:
            await self._run_on_loop(self._aflush_pending())
        except Exception as e:
            log_warning(f"CodeMode close: snapshot flush failed: {e}")

    def _submit_background_flush(self) -> None:
        """Queue one flush pass on the kernel loop; never more than one at a time."""
        pending = self._background_flush
        if pending is not None and not pending.done():
            return
        future = self._runner.submit(self._aflush_pending())
        self._background_flush = future

        def _report(finished: "concurrent.futures.Future[Any]") -> None:
            error = finished.exception()
            if error is not None:
                log_warning(f"CodeMode close: snapshot flush failed: {error}")

        future.add_done_callback(_report)

    async def _aflush_pending(self) -> None:
        """Snapshot the sessions with an unsaved cell. Used by ``close``."""
        await self._aflush(list(self._sessions.values()), only_pending=True)

    async def _aflush(self, sessions: List[KernelSession], *, only_pending: bool) -> None:
        """Snapshot the given live kernels.

        Under ``only_pending`` the pass covers sessions with an unsaved cell
        and skips any whose lock is held or whose kernel stopped answering: a
        run that ends must not wait on another run's kernel. Without it every
        live kernel is snapshotted, pending cell or not.
        """
        for session in sessions:
            if not session.running or session.flush_hook is None:
                continue
            if only_pending and (not session.snapshot_pending or session.lock.locked() or session.maybe_busy):
                continue
            try:
                await _flush_locked_session(session)
            except Exception as e:
                log_warning(f"CodeMode snapshot flush for session {session.session_id} failed: {e}")

    # ------------------------------------------------------------------
    # Model-facing tools
    # ------------------------------------------------------------------

    def execute(self, run_context: RunContext, code: str, agent: Any = None, team: Any = None) -> ToolResult:
        """Run a cell of Python code in your persistent environment and return its output.

        State persists across cells: variables, imports, functions, and results
        from earlier cells stay available in later ones. The output contains
        stdout, stderr, the repr of the last expression, and the traceback if
        the cell raised. Long streams are truncated at a fixed cap.

        Args:
            code: The Python code to run as one cell.

        Returns:
            The cell output, prefixed with an environment notice when state was
            restored or reset.
        """
        _warn()
        return self._run_on_loop_sync(
            self._aexecute_impl(self._session_key(run_context), code, run_context, _owner_store(agent, team))
        )

    async def aexecute(self, run_context: RunContext, code: str, agent: Any = None, team: Any = None) -> ToolResult:
        """Async variant of ``execute``."""
        _warn()
        return await self._run_on_loop(
            self._aexecute_impl(self._session_key(run_context), code, run_context, _owner_store(agent, team))
        )

    def restart(self, run_context: RunContext) -> str:
        """Restart the code environment for this session.

        Tears the kernel down and starts a fresh one. Every variable, import,
        async task, and open resource is lost. Use this when the environment is
        corrupted or stuck.

        Returns:
            A notice confirming the environment was reset.
        """
        _warn()
        return self._run_on_loop_sync(self._arestart_impl(self._session_key(run_context), run_context))

    async def arestart(self, run_context: RunContext) -> str:
        """Async variant of ``restart``."""
        _warn()
        return await self._run_on_loop(self._arestart_impl(self._session_key(run_context), run_context))

    # ------------------------------------------------------------------
    # Developer-facing surface
    # ------------------------------------------------------------------

    def run(self, session_id: str, code: str) -> CellResult:
        """Run a cell in the given session's kernel and return the raw ``CellResult``."""
        _warn()
        return self._run_on_loop_sync(self._arun_impl(session_id, code))

    async def arun(self, session_id: str, code: str) -> CellResult:
        """Async variant of ``run``."""
        _warn()
        return await self._run_on_loop(self._arun_impl(session_id, code))

    def variables(self, session_id: str) -> Dict[str, str]:
        """Map of top-level variable name to type name for a live kernel.

        Returns an empty dict when the session has no running kernel.
        Underscore-prefixed names and IPython internals are skipped.
        """
        return self._run_on_loop_sync(self._avariables_impl(session_id))

    async def avariables(self, session_id: str) -> Dict[str, str]:
        """Async variant of ``variables``."""
        return await self._run_on_loop(self._avariables_impl(session_id))

    def value(self, session_id: str, name: str) -> Any:
        """Fetch one top-level variable from the kernel via a dill round-trip."""
        return self._run_on_loop_sync(self._avalue_impl(session_id, name))

    async def avalue(self, session_id: str, name: str) -> Any:
        """Async variant of ``value``."""
        return await self._run_on_loop(self._avalue_impl(session_id, name))

    def shutdown(self, session_id: Optional[str] = None) -> None:
        """Kill the kernel for one session, or for all sessions when ``None``."""
        if not self._runner.started:
            return
        self._run_on_loop_sync(self._ashutdown_impl(session_id))

    async def ashutdown(self, session_id: Optional[str] = None) -> None:
        """Async variant of ``shutdown``."""
        if not self._runner.started:
            return
        await self._run_on_loop(self._ashutdown_impl(session_id))

    # ------------------------------------------------------------------
    # Implementation (runs on the LoopRunner loop)
    # ------------------------------------------------------------------

    @staticmethod
    def _session_key(run_context: RunContext) -> str:
        # session_id comes from RunContext, injected by the framework — never
        # from a model-supplied argument. A model cannot address another
        # session's kernel.
        return run_context.session_id

    @staticmethod
    def _user_key(run_context: Optional[RunContext]) -> Optional[str]:
        """This run's identity, as text.

        The one point identity enters CodeMode, so the session, the manifest
        and both comparison sites hold the same type. An application whose
        user ids are ints would otherwise be refused from its own session
        after a restart, and an id that is not JSON-serializable would cost
        the session its manifest.
        """
        user_id = run_context.user_id if run_context is not None else None
        return str(user_id) if user_id is not None else None

    async def _refuse_foreign_user(self, session_id: str, user_id: Optional[str]) -> bool:
        """True when this run's user may not touch this session.

        A session id is client-supplied in AgentOS, so it is not proof of
        access: the warm kernel holds the previous run's variables and the
        snapshot holds them durably. The owner is the user of the run the
        session was created for, in memory and in the snapshot manifest. A run
        without a user_id carries no identity to compare and is left alone; it
        takes the recorded owner when it restores, so the record survives it
        and the next named user is still measured against it.
        """
        if user_id is None:
            return False
        session = self._sessions.get(session_id)
        owner = session.owner_user_id if session is not None else None
        if owner is None and self._snapshots is not None:
            # First run for this id in this process: the durable snapshot is
            # the only record of who owns the state it would restore.
            owner = await self._snapshots.owner(session_id)
        if owner is None or str(owner) == user_id:
            return False
        log_warning(
            f"CodeMode refused session '{session_id}' for user '{user_id}': "
            f"the code environment belongs to user '{owner}'"
        )
        return True

    def _forget_session(self, session: KernelSession) -> None:
        """Drop an evicted session, unless the id already maps to a newer one."""
        if self._sessions.get(session.session_id) is session:
            del self._sessions[session.session_id]
            self._evicted[session.session_id] = None
            self._evicted.move_to_end(session.session_id)
            while len(self._evicted) > _MAX_EVICTED_IDS:
                self._evicted.popitem(last=False)
            log_debug(f"CodeMode forgot evicted session {session.session_id}")

    def _run_on_loop_sync(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self._runner.submit(coro).result()

    async def _run_on_loop(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return await asyncio.wrap_future(self._runner.submit(coro))

    async def _evict_past_the_cap(self) -> None:
        """Evict least-recently-used idle sessions until the cap has room.

        Only a session whose lock is free and whose kernel is not busy is
        taken: evicting one mid-cell would tear the kernel down under the
        cell. When every session is busy the cap is exceeded rather than
        deadlocked, with a warning naming the count. The evicted session's
        snapshot is flushed first, so a returning session id restores its
        state; the reset notice tells its model either way.
        """
        if self.max_kernels is None:
            return
        # A dead kernel's session stays registered until its id returns; it
        # holds no process, so it leaves the count before any live kernel is
        # considered - otherwise a corpse could cost a working kernel its slot.
        for corpse in [s for s in self._sessions.values() if not s.running and not s.lock.locked()]:
            self._forget_session(corpse)
        while len(self._sessions) >= self.max_kernels:
            candidates = [s for s in self._sessions.values() if s.running and not s.lock.locked() and not s.maybe_busy]
            if not candidates:
                log_warning(
                    f"CodeMode is over max_kernels={self.max_kernels} with every kernel busy; "
                    f"{len(self._sessions) + 1} kernels will be live until one goes idle"
                )
                return
            oldest = min(candidates, key=lambda s: s.last_used)
            async with oldest.lock:
                if oldest.running and oldest.flush_hook is not None:
                    try:
                        await oldest.flush_hook(oldest)
                        oldest.snapshot_pending = False
                    except Exception as e:
                        log_warning(f"CodeMode snapshot flush while evicting past max_kernels failed: {e}")
                await oldest._teardown_kernel()
            self._forget_session(oldest)
            log_debug(f"CodeMode evicted session {oldest.session_id}: past max_kernels={self.max_kernels}")

    def _session_for(self, session_id: str, user_id: Optional[str] = None) -> KernelSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = KernelSession(
                session_id,
                python=self.python,
                startup_code=self.startup_code,
                allow_shell=self.allow_shell,
                max_output_chars=self.max_output_chars,
                busy_wait=self.busy_wait,
                on_busy_kernel=self.on_busy_kernel,
                idle_ttl=self.idle_ttl,
                cwd=self.cwd,
                env=self.env,
                max_images_per_cell=self.max_images_per_cell,
                max_image_bytes=self.max_image_bytes,
                owner_user_id=user_id,
                flush_hook=self._snapshots.flush_locked if self._snapshots is not None else None,
                setup_hook=self._asetup_session,
                on_evict=self._forget_session,
                served_before=session_id in self._evicted,
            )
            self._evicted.pop(session_id, None)
            if self._bridge is not None:
                self._bridge.attach(session)
            self._sessions[session_id] = session
        elif session.owner_user_id is None:
            # A session first served without an identity is claimed by the
            # first run that brings one; every later run is checked against it.
            session.owner_user_id = user_id
        return session

    async def _asetup_session(self, session: KernelSession) -> Optional[str]:
        """Restore variables, then bootstrap live handles, in that order.

        Restore runs BEFORE the bootstrap cell so a stale pickled handle loses
        to this run's live one. The restored notice is returned only when
        bootstrap succeeded — a notice claiming restored state must never
        outlive a failed bootstrap.
        """
        restore_notice: Optional[str] = None
        if self._snapshots is not None:
            restore_notice = await self._snapshots.restore(session)
        if self._bridge is not None and self._bridge.has_bindings:
            bootstrap_ok = await self._bridge.bootstrap(session)
            if not bootstrap_ok:
                # A notice claiming restored state must never outlive a failed
                # bootstrap. The no-persist notice claims the opposite - that
                # nothing was restored and nothing will be saved - and staying
                # silent about that would leave the model working on state it
                # wrongly believes durable, so it survives.
                from agno.tools.code.snapshot import NO_PERSIST_NOTICE

                return NO_PERSIST_NOTICE if restore_notice == NO_PERSIST_NOTICE else None
        return restore_notice

    def _rejects_shell(self, code: str) -> bool:
        return not self.allow_shell and code.lstrip().startswith("%%bash")

    def _snapshot_clear_hook(self, session_id: str) -> Optional[Callable[[], Coroutine[Any, Any, None]]]:
        if self._snapshots is None:
            return None
        snapshots = self._snapshots

        async def _clear() -> None:
            await snapshots.clear(session_id)

        return _clear

    async def _execute_with_busy_policy(
        self,
        session: KernelSession,
        code: str,
        run_context: Optional[RunContext],
        result_store: Optional[Any] = None,
    ) -> CellResult:
        """One cell, applying on_busy_kernel. The restart policy lives here —
        beside the snapshot store a restart must also clear — not in the
        kernel session."""
        try:
            return await session.execute_cell(
                code, timeout=self.cell_timeout, run_context=run_context, result_store=result_store
            )
        except KernelBusyError:
            if self.on_busy_kernel != "restart":
                raise
            await session.restart(before_start=self._snapshot_clear_hook(session.session_id))
            session.pending_notice = RESET_NOTICE
            return await session.execute_cell(
                code, timeout=self.cell_timeout, run_context=run_context, result_store=result_store
            )

    async def _aexecute_impl(
        self,
        session_id: str,
        code: str,
        run_context: Optional[RunContext] = None,
        result_store: Optional[Any] = None,
    ) -> ToolResult:
        if self._rejects_shell(code):
            return ToolResult(content="Error: %%bash cells are disabled (allow_shell=False).")
        user_id = self._user_key(run_context)
        if await self._refuse_foreign_user(session_id, user_id):
            return ToolResult(content=OWNER_REFUSAL)
        if session_id not in self._sessions:
            await self._evict_past_the_cap()
        session = self._session_for(session_id, user_id)
        cell = await self._execute_with_busy_policy(session, code, run_context, result_store)
        # An idle eviction can drop the registry entry while this cell waits
        # for the lock; the kernel it started must stay reachable.
        self._sessions.setdefault(session_id, session)
        if cell.status == "ok" and self._snapshots is not None:
            session.snapshot_pending = True
            self._snapshots.schedule(session)
        notice = session.take_notice()
        content = self._format_cell(cell)
        misplaced_bash = re.search(r"^\s*%%bash", code, re.MULTILINE) and not code.lstrip().startswith("%%bash")
        if cell.status == "error" and misplaced_bash:
            content += (
                "\n[hint: %%bash must be the first line of its cell - move any comment, "
                "import, or statement into a separate cell]"
            )
        if notice:
            content = f"{notice}\n{content}"
        return ToolResult(content=content, images=cell.images or None)

    async def _arestart_impl(self, session_id: str, run_context: Optional[RunContext] = None) -> str:
        user_id = self._user_key(run_context)
        if await self._refuse_foreign_user(session_id, user_id):
            return OWNER_REFUSAL
        session = self._session_for(session_id, user_id)
        # The snapshot clear runs under the session lock (before_start) so a
        # debounced flush can never land after it and resurrect state.
        notice = await session.restart(before_start=self._snapshot_clear_hook(session_id))
        self._sessions.setdefault(session_id, session)
        # The snapshot was cleared with the state it held: nothing to flush.
        session.snapshot_pending = False
        return notice

    async def _arun_impl(self, session_id: str, code: str) -> CellResult:
        if self._rejects_shell(code):
            return CellResult(status="error", stderr="Error: %%bash cells are disabled (allow_shell=False).")
        if session_id not in self._sessions:
            await self._evict_past_the_cap()
        session = self._session_for(session_id)
        cell = await self._execute_with_busy_policy(session, code, run_context=None)
        self._sessions.setdefault(session_id, session)
        if cell.status == "ok" and self._snapshots is not None:
            session.snapshot_pending = True
            self._snapshots.schedule(session)
        return cell

    async def _avariables_impl(self, session_id: str) -> Dict[str, str]:
        import json

        session = self._sessions.get(session_id)
        if session is None or not session.running:
            return {}
        skip_b64 = base64.b64encode(json.dumps([*self.handles, *_BOOTSTRAP_NAMES]).encode("utf-8")).decode("ascii")
        code = _VARIABLES_CODE_TEMPLATE.format(skip_b64=skip_b64, marker=_VARIABLES_MARKER)
        async with session.lock:
            if not session.running:
                return {}
            result = await session._run_silent(code)
        payload = parse_marker_line(result.stdout, _VARIABLES_MARKER)
        if payload is None:
            return {}
        return dict(json.loads(payload))

    async def _avalue_impl(self, session_id: str, name: str) -> Any:
        import dill

        if not name.isidentifier():
            raise ValueError(f"'{name}' is not a valid variable name")
        session = self._sessions.get(session_id)
        if session is None or not session.running:
            raise KernelDiedError(f"No running kernel for session '{session_id}'")
        code = (
            "import builtins as _cm_b\n"
            "import base64 as _cm_b64\n"
            "import dill as _cm_dill\n"
            f"_cm_payload = _cm_b64.b64encode(_cm_dill.dumps({name})).decode('ascii')\n"
            f"_cm_b.print('\\n{_VALUE_MARKER}' + _cm_payload)\n"
        )
        async with session.lock:
            if not session.running:
                raise KernelDiedError(f"No running kernel for session '{session_id}'")
            result = await session._run_silent(code)
        if result.status == "error":
            raise KeyError(f"Could not read variable '{name}' from session '{session_id}': {result.traceback}")
        payload = parse_marker_line(result.stdout, _VALUE_MARKER)
        if payload is None:
            raise KeyError(f"Variable '{name}' produced no value in session '{session_id}'")
        return dill.loads(base64.b64decode(payload))

    async def _ashutdown_impl(self, session_id: Optional[str] = None) -> None:
        if session_id is None:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        else:
            popped = self._sessions.pop(session_id, None)
            sessions = [popped] if popped is not None else []
        # Shutdown is explicit and kills the kernel, so it snapshots whatever
        # each namespace holds, pending cell or not.
        await self._aflush(sessions, only_pending=False)
        for session in sessions:
            await session.shutdown()

    @staticmethod
    def _format_cell(cell: CellResult) -> str:
        parts: List[str] = []
        if cell.stdout:
            parts.append(cell.stdout.rstrip("\n"))
        if cell.stderr:
            parts.append("stderr:\n" + cell.stderr.rstrip("\n"))
        if cell.result is not None:
            parts.append(f"Out[{cell.execution_count}]: {cell.result}")
        if cell.traceback:
            parts.append(cell.traceback)
        if cell.status == "aborted":
            parts.append(
                "[cell aborted: the kernel did not respond to the interrupt in time and may "
                "still be running. Wait and retry, or call restart to discard state.]"
            )
        if not parts:
            return "(cell executed; no output)"
        return "\n".join(parts)


# The async twins delegate to the same implementation, but agno builds the
# async agent's tool schema from the ASYNC method's docstring. Copy the sync
# docstrings so both surfaces ship the same prompt text (the fs.toolkit
# convention).
CodeMode.aexecute.__doc__ = CodeMode.execute.__doc__
CodeMode.arestart.__doc__ = CodeMode.restart.__doc__
