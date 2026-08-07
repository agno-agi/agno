"""CodeMode — a persistent per-session Python kernel as a toolkit.

The model gets two tools: ``execute`` runs a cell in an IPython kernel that
lives as long as the session, and ``restart`` (optional) tears it down for a
fresh one. Variables, imports, helper functions, and parsed tool results
survive across turns. See ``agno.tools.code_mode`` for the full surface.

CodeMode executes arbitrary Python and shell with the permissions of the
process running the agent. It is not a sandbox and does not pretend to be one:
use it with a trusted operator or inside an isolated container. Snapshots are
``dill`` pickles restored on resume, so restoring is also code execution — the
snapshot store inherits the trust level of the database that holds it.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import weakref
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Union

from agno.fs import FileSystem
from agno.run import RunContext
from agno.tools.code_mode.bridge import ToolBridge
from agno.tools.code_mode.errors import KernelDiedError
from agno.tools.code_mode.kernel import KernelSession, LoopRunner, parse_marker_line
from agno.tools.code_mode.naming import derive_handle_name, handle_names_for  # noqa: F401  (re-exported)
from agno.tools.code_mode.snapshot import SnapshotManager
from agno.tools.code_mode.types import CellResult
from agno.tools.function import Function, ToolResult
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning

try:
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal  # type: ignore[assignment]

_VARIABLES_MARKER = "__AGNO_CM_VARS__"
_VALUE_MARKER = "__AGNO_CM_VALUE__"

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


@functools.lru_cache(maxsize=None)
def _warn() -> None:
    log_warning(
        "CodeMode runs arbitrary Python and shell with the permissions of this process. "
        "It is not a sandbox: provide human supervision or run the agent in an isolated container."
    )


def build_instructions(handles: List[str], allow_shell: bool, allow_restart: bool) -> str:
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
        "outputs stay available in every later turn."
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
        "This environment is your control environment, not the runtime of the thing you are "
        "investigating. A repository, service, dataset, or benchmark has its own environment and "
        "its own interface. Evaluate it through that interface and use this environment to "
        "coordinate and analyze what comes back. Do not install dependencies here to force an "
        "external project to import. Treat failures from the project's own environment as the "
        "relevant result."
    )
    if allow_shell:
        paragraphs.append(
            "Each %%bash cell is a throw-away subshell, so cd, export, and shell variables do not "
            "carry over. Keep dependent shell steps in one cell, or use %cd and os.environ[...], "
            "which are kernel-level and apply to every later %%bash cell."
        )
    if allow_restart:
        paragraphs.append(
            "If the environment is corrupted or wedged, call restart to tear it down and start "
            "fresh; every variable and import is lost."
        )
    return "\n\n".join(paragraphs)


def _cleanup_kernels(runner: LoopRunner, sessions: Dict[str, KernelSession]) -> None:
    """Best-effort kernel teardown at garbage collection or interpreter exit."""
    try:
        if runner.started and sessions:

            async def _shutdown_all() -> None:
                for session in list(sessions.values()):
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
        startup_code: Optional[str] = None,
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
        self.startup_code = startup_code

        self.handles = handle_names_for(self.injected_tools)

        registered = ["execute"] + (["restart"] if allow_restart else [])
        sync_tools = [getattr(self, name) for name in registered]
        async_tools = [(getattr(self, "a" + name), name) for name in registered]

        super().__init__(
            name=kwargs.pop("name", "code_mode"),
            tools=sync_tools,
            async_tools=async_tools,
            instructions=kwargs.pop(
                "instructions",
                build_instructions(self.handles, allow_shell=allow_shell, allow_restart=allow_restart),
            ),
            add_instructions=kwargs.pop("add_instructions", True),
            **kwargs,
        )

        # Surface-drift guard: every model-facing and developer-facing method
        # must exist with its async twin.
        for method_name in ("execute", "restart", "run", "variables", "value", "shutdown"):
            assert callable(getattr(self, method_name, None)), f"CodeMode missing sync method '{method_name}'"
            assert callable(getattr(self, "a" + method_name, None)), f"CodeMode missing async method 'a{method_name}'"

        self._runner = LoopRunner()
        self._sessions: Dict[str, KernelSession] = {}
        self._bridge: Optional[ToolBridge] = (
            ToolBridge(self.injected_tools, max_result_bytes=max_result_bytes) if self.injected_tools else None
        )
        self._snapshots: Optional[SnapshotManager] = (
            SnapshotManager(
                fs,
                debounce=snapshot_debounce,
                max_variable_bytes=max_variable_bytes,
                max_snapshot_bytes=max_snapshot_bytes,
                skip_names=self.handles,
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
        """No-op: the session is unknown at connect time; kernels start lazily."""

    def close(self) -> None:
        """Flush a final snapshot for every kernel this process touched.

        Kernels are NOT killed: a resumed run inside ``idle_ttl`` reattaches to
        a warm kernel and skips the restore entirely.
        """
        if not self._runner.started:
            return
        try:
            self._runner.submit(self._aflush_all()).result(timeout=60)
        except Exception as e:
            log_warning(f"CodeMode close: snapshot flush failed: {e}")

    async def _aflush_all(self) -> None:
        for session in list(self._sessions.values()):
            if session.running and session.flush_hook is not None:
                async with session.lock:
                    await session.flush_hook(session)

    # ------------------------------------------------------------------
    # Model-facing tools
    # ------------------------------------------------------------------

    def execute(self, run_context: RunContext, code: str) -> ToolResult:
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
        return self._run_on_loop_sync(self._aexecute_impl(self._session_key(run_context), code, run_context))

    async def aexecute(self, run_context: RunContext, code: str) -> ToolResult:
        """Async variant of ``execute``."""
        _warn()
        return await self._run_on_loop(self._aexecute_impl(self._session_key(run_context), code, run_context))

    def restart(self, run_context: RunContext) -> str:
        """Restart the code environment for this session.

        Tears the kernel down and starts a fresh one. Every variable, import,
        async task, and open resource is lost. Use this when the environment is
        corrupted or stuck.

        Returns:
            A notice confirming the environment was reset.
        """
        _warn()
        return self._run_on_loop_sync(self._arestart_impl(self._session_key(run_context)))

    async def arestart(self, run_context: RunContext) -> str:
        """Async variant of ``restart``."""
        _warn()
        return await self._run_on_loop(self._arestart_impl(self._session_key(run_context)))

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

    def _run_on_loop_sync(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self._runner.submit(coro).result()

    async def _run_on_loop(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return await asyncio.wrap_future(self._runner.submit(coro))

    def _session_for(self, session_id: str) -> KernelSession:
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
                flush_hook=self._snapshots.flush_locked if self._snapshots is not None else None,
                setup_hook=self._asetup_session,
            )
            if self._bridge is not None:
                self._bridge.attach(session)
            self._sessions[session_id] = session
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
                return None
        return restore_notice

    def _rejects_shell(self, code: str) -> bool:
        return not self.allow_shell and code.lstrip().startswith("%%bash")

    async def _aexecute_impl(self, session_id: str, code: str, run_context: Optional[RunContext] = None) -> ToolResult:
        if self._rejects_shell(code):
            return ToolResult(content="Error: %%bash cells are disabled (allow_shell=False).")
        session = self._session_for(session_id)
        if run_context is not None:
            session.run_context = run_context
        cell = await session.execute_cell(code, timeout=self.cell_timeout)
        if cell.status == "ok" and self._snapshots is not None:
            self._snapshots.schedule(session)
        notice = session.take_notice()
        content = self._format_cell(cell)
        if notice:
            content = f"{notice}\n{content}"
        return ToolResult(content=content, images=cell.images or None)

    async def _arestart_impl(self, session_id: str) -> str:
        session = self._session_for(session_id)
        # A deliberate restart discards state everywhere: a later resume must
        # not resurrect pre-restart variables from the snapshot store.
        if self._snapshots is not None:
            await self._snapshots.clear(session_id)
        return await session.restart()

    async def _arun_impl(self, session_id: str, code: str) -> CellResult:
        if self._rejects_shell(code):
            return CellResult(status="error", stderr="Error: %%bash cells are disabled (allow_shell=False).")
        session = self._session_for(session_id)
        cell = await session.execute_cell(code, timeout=self.cell_timeout)
        if cell.status == "ok" and self._snapshots is not None:
            self._snapshots.schedule(session)
        return cell

    async def _avariables_impl(self, session_id: str) -> Dict[str, str]:
        import json

        session = self._sessions.get(session_id)
        if session is None or not session.running:
            return {}
        skip_b64 = base64.b64encode(json.dumps(self.handles).encode("utf-8")).decode("ascii")
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
