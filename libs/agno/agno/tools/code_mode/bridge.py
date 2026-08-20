"""The RPC bridge: injected toolkits become awaitable calls inside the kernel.

Binding goes through comm messages, not by importing the toolkit into the
kernel — toolkit instances are live host objects holding clients, connections
and a ``RunContext``, and cannot be reconstructed kernel-side. The kernel-side
stub JSON-encodes its arguments, sends a comm message (which reaches the host
on iopub), and awaits the reply.

**The reply goes out on the control channel, never shell.** IPython processes
shell messages serially: the cell cannot finish until the reply arrives, and
the kernel will not read a shell-channel reply until the cell finishes —
answering on shell deadlocks, every time, silently. ipykernel registers its
comm handlers on the shell channel only, so the bootstrap patches them into
``control_handlers`` as well; the control thread then dispatches the reply
while the shell thread is still blocked inside the cell.

What a bridged call carries and what it does not:

* The tool's own ``FunctionCall`` runs, so the tool's ``tool_hooks`` (sync and
  async), ``pre_hook``, ``post_hook`` and result caching all apply.
* A tool that would pause the run — confirmation, user input, external
  execution, any ``@approval`` — is refused in the kernel. A cell cannot pause
  an agent run, so the call must not happen at all.
* Hooks attached by the agent (``Agent(tool_hooks=[...])``) wrap the
  ``execute`` cell as a whole, not each bridged call inside it, and
  ``tool_call_limit`` counts the cell as one call.
"""

from __future__ import annotations

import asyncio
import base64
import json
from inspect import isasyncgenfunction, iscoroutine, iscoroutinefunction
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Set, Tuple, Union

from agno.run import RunContext
from agno.tools.code_mode.kernel import KernelSession
from agno.tools.code_mode.naming import derive_handle_name, safe_param_name
from agno.tools.function import Function, FunctionCall, ToolResult
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning

# Kernel-side class for a toolkit that failed to bind: every attribute access
# returns a callable that raises a descriptive RuntimeError at call time —
# degrade to explanatory, never to NameError. Kept as a standalone constant so
# the unit suite can exec() and pin its behavior without a kernel.
FAILED_BINDING_CLASS = '''
class _AgnoFailedBinding:
    """Placeholder for a toolkit that could not be bound into this environment."""

    def __init__(self, name, error):
        object.__setattr__(self, "_agno_name", name)
        object.__setattr__(self, "_agno_error", error)

    def __getattr__(self, attr):
        name = object.__getattribute__(self, "_agno_name")
        error = object.__getattribute__(self, "_agno_error")

        def _raiser(*args, **kwargs):
            raise RuntimeError(
                "Toolkit '%s' is unavailable in this environment and '%s' cannot be called. "
                "Binding failed with: %s" % (name, attr, error)
            )

        return _raiser
'''

_BOOTSTRAP_TEMPLATE = (
    "import asyncio as _agno_asyncio\n"
    "import base64 as _agno_b64\n"
    "import builtins as _agno_b\n"
    "import inspect as _agno_inspect\n"
    "import json as _agno_json\n"
    "import threading as _agno_threading\n"
    "import comm as _agno_comm_pkg\n"
    "\n"
    "\n"
    "class ResultTooLarge(RuntimeError):\n"
    '    """Raised when a bridged tool call returns a payload over the bridge limit."""\n'
    "\n"
    "\n"
    "{failed_binding_class}\n"
    "\n"
    "_agno_kernel = get_ipython().kernel\n"
    "# ipykernel registers comm handlers on the shell channel only; route them\n"
    "# on the control channel too so replies arrive while a cell is executing.\n"
    "_agno_kernel.control_handlers['comm_msg'] = _agno_kernel.comm_manager.comm_msg\n"
    "\n"
    "_agno_pending = {{}}\n"
    "_agno_seq = [0]\n"
    "_agno_comm = _agno_comm_pkg.create_comm(target_name='agno_code_mode', data={{}})\n"
    "\n"
    "\n"
    "def _agno_on_msg(msg):\n"
    "    _agno_data = msg['content']['data']\n"
    "    _agno_entry = _agno_pending.pop(_agno_data.get('id'), None)\n"
    "    if _agno_entry is not None:\n"
    "        _agno_entry[1]['reply'] = _agno_data\n"
    "        _agno_entry[0].set()\n"
    "\n"
    "\n"
    "_agno_comm.on_msg(_agno_on_msg)\n"
    "\n"
    "\n"
    "async def _agno_bridge_call(handle, method, kwargs):\n"
    "    _agno_ev = _agno_threading.Event()\n"
    "    _agno_box = {{}}\n"
    "    _agno_seq[0] += 1\n"
    "    _agno_id = _agno_b.str(_agno_seq[0])\n"
    "    _agno_pending[_agno_id] = (_agno_ev, _agno_box)\n"
    "    _agno_comm.send({{'id': _agno_id, 'handle': handle, 'method': method, 'kwargs': kwargs}})\n"
    "    _agno_loop = _agno_asyncio.get_running_loop()\n"
    "    await _agno_loop.run_in_executor(None, _agno_ev.wait)\n"
    "    _agno_reply = _agno_box['reply']\n"
    "    if _agno_reply.get('ok'):\n"
    "        return _agno_reply.get('value')\n"
    "    _agno_err = _agno_reply.get('error') or {{}}\n"
    "    if _agno_err.get('type') == 'ResultTooLarge':\n"
    "        raise ResultTooLarge(_agno_err.get('message') or 'result too large')\n"
    "    raise RuntimeError(_agno_err.get('message') or 'tool call failed')\n"
    "\n"
    "\n"
    "def _agno_make_stub(handle, method, doc, params):\n"
    "    # The host orders required parameters first and renames the ones Python\n"
    "    # cannot use; 'wire' carries the schema name the tool expects back.\n"
    "    _agno_sig_params = []\n"
    "    _agno_wire = {{}}\n"
    "    for _agno_p in params:\n"
    "        _agno_name = _agno_p['name']\n"
    "        _agno_wire[_agno_name] = _agno_p.get('wire') or _agno_name\n"
    "        _agno_default = _agno_inspect.Parameter.empty if _agno_p.get('required') else None\n"
    "        _agno_sig_params.append(\n"
    "            _agno_inspect.Parameter(_agno_name, _agno_inspect.Parameter.POSITIONAL_OR_KEYWORD, default=_agno_default)\n"
    "        )\n"
    "    _agno_sig = _agno_inspect.Signature(_agno_sig_params)\n"
    "\n"
    "    async def _agno_stub(*args, **kwargs):\n"
    "        _agno_bound = _agno_sig.bind_partial(*args, **kwargs)\n"
    "        _agno_kwargs = {{}}\n"
    "        for _agno_k, _agno_v in _agno_bound.arguments.items():\n"
    "            _agno_kwargs[_agno_wire.get(_agno_k, _agno_k)] = _agno_v\n"
    "        return await _agno_bridge_call(handle, method, _agno_kwargs)\n"
    "\n"
    "    _agno_stub.__name__ = method\n"
    "    _agno_stub.__qualname__ = (handle + '.' + method) if handle else method\n"
    "    _agno_stub.__doc__ = doc\n"
    "    _agno_stub.__signature__ = _agno_sig\n"
    "    return _agno_stub\n"
    "\n"
    "\n"
    "def _agno_unbound_stub(label, error):\n"
    "    async def _agno_unbound(*args, **kwargs):\n"
    "        raise RuntimeError(\n"
    "            \"'%s' could not be bound into this environment and cannot be called: %s\"\n"
    "            % (label, error)\n"
    "        )\n"
    "\n"
    "    _agno_unbound.__name__ = label.split('.')[-1]\n"
    "    _agno_unbound.__doc__ = 'Unavailable: %s' % error\n"
    "    return _agno_unbound\n"
    "\n"
    "\n"
    "# One try/except per binding: a function whose schema the kernel cannot turn\n"
    "# into a signature becomes a stub that raises, and every other handle in the\n"
    "# spec still binds.\n"
    "_agno_spec = _agno_json.loads(_agno_b64.b64decode('{spec_b64}').decode('utf-8'))\n"
    "for _agno_t in _agno_spec['toolkits']:\n"
    "    if _agno_t.get('error'):\n"
    "        _agno_b.globals()[_agno_t['handle']] = _AgnoFailedBinding(_agno_t['name'], _agno_t['error'])\n"
    "        continue\n"
    "    _agno_members = {{'__doc__': _agno_t.get('doc') or ''}}\n"
    "    for _agno_m in _agno_t['functions']:\n"
    "        try:\n"
    "            _agno_fn = _agno_make_stub(\n"
    "                _agno_t['handle'], _agno_m['name'], _agno_m.get('doc') or '', _agno_m.get('params') or []\n"
    "            )\n"
    "        except _agno_b.Exception as _agno_error:\n"
    "            _agno_fn = _agno_unbound_stub(\n"
    "                _agno_t['handle'] + '.' + _agno_m['name'], _agno_b.repr(_agno_error)\n"
    "            )\n"
    "        _agno_members[_agno_m['name']] = _agno_b.staticmethod(_agno_fn)\n"
    "    try:\n"
    "        _agno_b.globals()[_agno_t['handle']] = _agno_b.type(_agno_t['handle'], (), _agno_members)()\n"
    "    except _agno_b.Exception as _agno_error:\n"
    "        _agno_b.globals()[_agno_t['handle']] = _AgnoFailedBinding(_agno_t['name'], _agno_b.repr(_agno_error))\n"
    "for _agno_f in _agno_spec['functions']:\n"
    "    if _agno_f.get('error'):\n"
    "        _agno_b.globals()[_agno_f['name']] = _agno_unbound_stub(_agno_f['name'], _agno_f['error'])\n"
    "        continue\n"
    "    try:\n"
    "        _agno_b.globals()[_agno_f['name']] = _agno_make_stub(\n"
    "            '', _agno_f['name'], _agno_f.get('doc') or '', _agno_f.get('params') or []\n"
    "        )\n"
    "    except _agno_b.Exception as _agno_error:\n"
    "        _agno_b.globals()[_agno_f['name']] = _agno_unbound_stub(_agno_f['name'], _agno_b.repr(_agno_error))\n"
)


def _params_from_schema(function: Function) -> List[Dict[str, Any]]:
    """Flatten a Function's JSON-schema parameters into the stub's param spec.

    Required parameters come first: a Python signature cannot carry a
    defaulted parameter before a required one, and schema property order is
    whatever the tool's author or generator emitted. Each entry holds the
    Python-safe name the signature uses and the ``wire`` name the tool is
    called with.
    """
    schema = function.parameters or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    ordered = [name for name in properties if name in required]
    ordered += [name for name in properties if name not in required]
    taken: Set[str] = set()
    params: List[Dict[str, Any]] = []
    for name in ordered:
        safe = safe_param_name(name, taken)
        taken.add(safe)
        params.append({"name": safe, "wire": name, "required": name in required})
    return params


def _stub_doc(function: Function, params: Sequence[Dict[str, Any]]) -> str:
    """The stub's docstring: the tool description plus any renamed parameters."""
    doc = function.description or ""
    renamed = [f"{p['name']} for '{p['wire']}'" for p in params if p["name"] != p["wire"]]
    if renamed:
        note = "Parameter names adapted for Python: " + ", ".join(renamed) + "."
        doc = f"{doc}\n\n{note}" if doc else note
    return doc


class ToolBridge:
    """Host side of the bridge: binding specs, dispatch, and control replies."""

    def __init__(
        self,
        tools: Sequence[Union[Toolkit, Callable[..., Any], Function]],
        *,
        max_result_bytes: int = 1_000_000,
    ) -> None:
        self.max_result_bytes = max_result_bytes
        # How long a no-op may take on the host loop before the loop counts as
        # blocked and the call is served on CodeMode's own loop instead.
        self.host_loop_probe_timeout = 1.0
        # (handle, method) -> Function; top-level callables bind under handle "".
        self._registry: Dict[Tuple[str, str], Function] = {}
        self._spec: Dict[str, Any] = {"toolkits": [], "functions": []}
        # In-flight calls keyed by (session_id, kernel generation, call_id):
        # call ids are a per-kernel counter, so two sessions of one CodeMode
        # collide on the bare id and so do two kernels of one session — an
        # interrupt in one must never cancel the other's calls.
        self._pending: Dict[Tuple[str, int, str], "asyncio.Task[None]"] = {}
        # Toolkits that manage their own connections, and the ones this bridge
        # has connected and still owes a close().
        self._connectable: List[Any] = [
            tool for tool in tools if getattr(tool, "requires_connect", False) and hasattr(tool, "connect")
        ]
        self._connected: List[Any] = []
        # The loop the injected toolkits were connected on: their clients and
        # transports are bound to it. None on a synchronous run.
        self._host_loop: Optional[asyncio.AbstractEventLoop] = None
        self._build(tools)

    # ------------------------------------------------------------------
    # Binding specs
    # ------------------------------------------------------------------

    @property
    def has_bindings(self) -> bool:
        return bool(self._spec["toolkits"] or self._spec["functions"])

    @property
    def handle_names(self) -> List[str]:
        names = [t["handle"] for t in self._spec["toolkits"]]
        names.extend(f["name"] for f in self._spec["functions"])
        return names

    def _build(self, tools: Sequence[Union[Toolkit, Callable[..., Any], Function]]) -> None:
        for tool in tools:
            if isinstance(tool, Toolkit):
                handle = derive_handle_name(tool.name)
                try:
                    functions = dict(tool.get_async_functions())
                    specs = []
                    for name, function in functions.items():
                        prepared = self._prepare_function(function)
                        self._registry[(handle, name)] = prepared
                        params = _params_from_schema(prepared)
                        specs.append({"name": name, "doc": _stub_doc(prepared, params), "params": params})
                    self._spec["toolkits"].append(
                        {
                            "handle": handle,
                            "name": tool.name,
                            "doc": (
                                f"Tools from '{tool.name}', bridged from the host agent. Every method is awaitable."
                            ),
                            "functions": specs,
                        }
                    )
                except Exception as e:
                    log_warning(f"CodeMode could not bind toolkit '{tool.name}': {e}")
                    self._spec["toolkits"].append({"handle": handle, "name": tool.name, "error": str(e)})
            else:
                try:
                    if isinstance(tool, Function):
                        function = tool
                        if function.entrypoint is None:
                            raise ValueError("Function has no entrypoint")
                    else:
                        function = Function.from_callable(tool)
                        _apply_approval_sentinel(function, tool)
                    prepared = self._prepare_function(function)
                    name = prepared.name
                    self._registry[("", name)] = prepared
                    params = _params_from_schema(prepared)
                    self._spec["functions"].append({"name": name, "doc": _stub_doc(prepared, params), "params": params})
                except Exception as e:
                    tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
                    log_warning(f"CodeMode could not bind callable '{tool_name}': {e}")
                    # The instructions advertise every attached name, so a name
                    # that failed to bind still has to exist in the kernel and
                    # say why it cannot be called.
                    already_bound = any(entry["name"] == tool_name for entry in self._spec["functions"])
                    if isinstance(tool_name, str) and tool_name.isidentifier() and not already_bound:
                        self._spec["functions"].append({"name": tool_name, "error": str(e)})

    @staticmethod
    def _prepare_function(function: Function) -> Function:
        prepared = function.model_copy(deep=True)
        try:
            prepared.process_entrypoint(strict=False)
        except Exception as e:
            log_debug(f"CodeMode: process_entrypoint failed for '{function.name}': {e}")
        return prepared

    def bootstrap_code(self) -> str:
        spec_b64 = base64.b64encode(json.dumps(self._spec).encode("utf-8")).decode("ascii")
        return _BOOTSTRAP_TEMPLATE.format(failed_binding_class=FAILED_BINDING_CLASS, spec_b64=spec_b64)

    async def bootstrap(self, session: KernelSession) -> bool:
        """Run the bootstrap cell; True when it succeeded."""
        result = await session._run_silent(self.bootstrap_code())
        if result.status != "ok":
            log_warning(
                f"CodeMode bridge bootstrap failed for session {session.session_id}: "
                f"{result.traceback or result.stderr}"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Injected-toolkit lifecycle
    # ------------------------------------------------------------------

    def connect_tools(self) -> None:
        """Connect the injected toolkits that manage their own connections.

        Toolkits reached only through the bridge are never walked by the
        agent, which sees CodeMode and not what is inside it, so their
        connect() is called from here.

        This also captures the loop it runs on as the host loop: the clients
        those toolkits build belong to it, and their coroutines have to be
        awaited there. A synchronous run has no loop and captures none.
        """
        self._capture_host_loop()
        for tool in self._connectable:
            if any(connected is tool for connected in self._connected):
                continue
            try:
                result = tool.connect()
                if iscoroutine(result):
                    result.close()
                    log_warning(
                        f"CodeMode: toolkit '{_tool_label(tool)}' has an async connect(); "
                        "connect it before the run, or use an async run."
                    )
                    continue
                self._connected.append(tool)
            except Exception as e:
                log_warning(f"CodeMode could not connect toolkit '{_tool_label(tool)}': {e}")

    async def aconnect_tools(self) -> None:
        """Async variant of ``connect_tools``; awaits an async ``connect()``."""
        self._capture_host_loop()
        for tool in self._connectable:
            if any(connected is tool for connected in self._connected):
                continue
            try:
                result = tool.connect()
                if iscoroutine(result):
                    await result
                self._connected.append(tool)
            except Exception as e:
                log_warning(f"CodeMode could not connect toolkit '{_tool_label(tool)}': {e}")

    def close_tools(self) -> None:
        """Close the injected toolkits this bridge connected."""
        for tool in self._connected:
            try:
                result = tool.close()
                if iscoroutine(result):
                    result.close()
                    log_warning(
                        f"CodeMode: toolkit '{_tool_label(tool)}' has an async close(); "
                        "close it yourself, or use an async run."
                    )
            except Exception as e:
                log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")
        self._connected = []

    async def aclose_tools(self) -> None:
        """Async variant of ``close_tools``; awaits an async ``close()``."""
        for tool in self._connected:
            try:
                result = tool.close()
                if iscoroutine(result):
                    await result
            except Exception as e:
                log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")
        self._connected = []

    def _capture_host_loop(self) -> None:
        try:
            self._host_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._host_loop = None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def attach(self, session: KernelSession) -> None:
        session.comm_handler = lambda msg: self._on_comm(session, msg)
        session.interrupt_hook = lambda: self.cancel_pending(session, "the cell was interrupted")

    def _on_comm(self, session: KernelSession, msg: Dict[str, Any]) -> None:
        msg_type = msg.get("msg_type")
        content = msg.get("content", {})
        if msg_type == "comm_open" and content.get("target_name") == "agno_code_mode":
            session.bridge_comm_id = content.get("comm_id")
            return
        if msg_type == "comm_msg" and content.get("comm_id") == getattr(session, "bridge_comm_id", None):
            data = content.get("data") or {}
            key = (session.session_id, session.generation, str(data.get("id")))
            task = asyncio.get_running_loop().create_task(self._serve(session, data, session.generation))
            self._pending[key] = task

            def _forget(_finished: "asyncio.Task[None]", _key: Tuple[str, int, str] = key) -> None:
                self._pending.pop(_key, None)

            task.add_done_callback(_forget)

    async def _serve(self, session: KernelSession, data: Dict[str, Any], generation: int) -> None:
        """Run one bridged call. ``generation`` is the kernel that asked for it."""
        call_id = data.get("id")
        handle = data.get("handle") or ""
        method = data.get("method") or ""
        kwargs = data.get("kwargs") or {}
        tool_label = f"{handle}.{method}" if handle else method
        try:
            value = await self._call_tool(session, handle, method, kwargs)
            reply: Dict[str, Any] = {"id": call_id, "ok": True, "value": value}
            payload_bytes = len(json.dumps(reply, default=str).encode("utf-8"))
            if payload_bytes > self.max_result_bytes:
                reply = self._too_large_reply(call_id, tool_label, payload_bytes)
        except asyncio.CancelledError:
            reply = {
                "id": call_id,
                "ok": False,
                "error": {"type": "ToolError", "message": f"{tool_label} was cancelled"},
            }
        except Exception as e:
            reply = {"id": call_id, "ok": False, "error": {"type": "ToolError", "message": f"{tool_label}: {e}"}}
        if generation != session.generation:
            # The kernel that asked is gone. Its call ids restart at 1 in the
            # replacement, so this reply would answer a different call.
            log_debug(f"CodeMode bridge dropped a reply for {tool_label} from a torn-down kernel")
            return
        self._send_reply(session, reply)

    def _too_large_reply(self, call_id: Any, tool_label: str, size_bytes: int) -> Dict[str, Any]:
        return {
            "id": call_id,
            "ok": False,
            "error": {
                "type": "ResultTooLarge",
                "message": (
                    f"The result of {tool_label} is {size_bytes} bytes, over the "
                    f"{self.max_result_bytes}-byte bridge limit. Have the tool write large payloads "
                    "to the agent's file system and return a path instead of the payload."
                ),
            },
        }

    async def _call_tool(self, session: KernelSession, handle: str, method: str, kwargs: Dict[str, Any]) -> Any:
        function = self._registry.get((handle, method))
        if function is None:
            raise RuntimeError(f"unknown tool '{handle}.{method}'" if handle else f"unknown tool '{method}'")
        if (
            function.requires_confirmation
            or function.external_execution
            or function.requires_user_input
            or function.approval_type is not None
        ):
            raise RuntimeError(
                f"'{function.name}' requires human approval or external execution. Those pause the "
                "agent run, which a cell cannot do, so it cannot be called from the code environment. "
                "Ask for it as a regular tool call instead."
            )
        prepared = function.model_copy(deep=True)
        run_context = getattr(session, "run_context", None)
        if run_context is None:
            run_context = RunContext(run_id=f"code-mode-{session.session_id}", session_id=session.session_id)
        prepared._run_context = run_context
        function_call = FunctionCall(function=prepared, arguments=kwargs)
        entrypoint = prepared.entrypoint
        # The tool's own call path, so its hooks and caching apply. Anything
        # async — the entrypoint or one of the hooks — has to go through
        # aexecute, which is the only path that awaits async hooks; execute()
        # logs them as skipped and runs without them. A fully synchronous call
        # runs in a worker thread so a slow tool cannot stall the kernel loop.
        hooks = prepared.tool_hooks or []
        entrypoint_is_async = entrypoint is not None and (
            iscoroutinefunction(entrypoint) or isasyncgenfunction(entrypoint)
        )
        if entrypoint_is_async or any(iscoroutinefunction(hook) for hook in hooks):
            execution_result = await self._await_on_host_loop(function_call.aexecute())
        else:
            execution_result = await asyncio.to_thread(function_call.execute)
        if execution_result.status != "success":
            raise RuntimeError(str(function_call.error or execution_result.error or "tool call failed"))
        return self._marshal(execution_result.result)

    async def _await_on_host_loop(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Await a tool coroutine on the loop its toolkit was connected on.

        A toolkit's transport — an MCP ClientSession, an httpx client, an
        asyncpg pool — is bound to the loop that created it. CodeMode serves
        cells on its own loop in a private thread, and awaiting there waits on
        an event only the owning loop will ever set: the call hangs until the
        cell times out. With no host loop (a synchronous run) the coroutine is
        awaited here.
        """
        loop = self._host_loop
        try:
            current: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if loop is None or loop is current or loop.is_closed() or not loop.is_running():
            return await coro
        if not await self._host_loop_is_turning(loop):
            return await coro
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            return await coro
        return await asyncio.wrap_future(future)

    async def _host_loop_is_turning(self, loop: asyncio.AbstractEventLoop) -> bool:
        """Whether the host loop is free to run work right now.

        A synchronous run started from inside that loop blocks it in
        ``result()`` until the cell finishes, so anything scheduled there would
        wait on the cell that is waiting on this call. A no-op that comes back
        proves the loop is turning; one that does not sends the call back to
        the loop serving the cell.
        """

        async def _noop() -> None:
            return None

        try:
            probe = asyncio.run_coroutine_threadsafe(_noop(), loop)
        except RuntimeError:
            return False
        try:
            await asyncio.wait_for(asyncio.wrap_future(probe), self.host_loop_probe_timeout)
        except Exception:
            probe.cancel()
            return False
        return True

    @staticmethod
    def _marshal(result: Any) -> Any:
        """JSON-serializable values cross natively; everything else as its string form."""
        if isinstance(result, ToolResult):
            result = result.content
        if result is None:
            return None
        try:
            json.dumps(result)
            return result
        except (TypeError, ValueError):
            return str(result)

    def _send_reply(self, session: KernelSession, reply: Dict[str, Any]) -> None:
        kc = session.kc
        comm_id = getattr(session, "bridge_comm_id", None)
        if kc is None or comm_id is None:
            log_warning("CodeMode bridge: no live channel to answer a tool call")
            return
        # The reply goes out on the CONTROL channel, never shell (see module
        # docstring). The control thread dispatches it mid-cell.
        message = kc.session.msg("comm_msg", {"comm_id": comm_id, "data": reply})
        kc.control_channel.send(message)

    async def cancel_pending(self, session: KernelSession, reason: str) -> None:
        """Cancel THIS session's in-flight tool calls and unblock their stubs."""
        for key, task in list(self._pending.items()):
            if key[0] != session.session_id:
                continue
            task.cancel()
            self._send_reply(
                session,
                {"id": key[1], "ok": False, "error": {"type": "ToolError", "message": f"tool call aborted: {reason}"}},
            )
            self._pending.pop(key, None)


def _tool_label(tool: Any) -> str:
    return getattr(tool, "name", None) or type(tool).__name__


def _apply_approval_sentinel(function: Function, tool: Any) -> None:
    """Carry an ``@approval`` sentinel from a raw callable onto its Function.

    ``@approval`` below ``@tool``, and ``@approval`` on a bare callable, stamp
    the attribute and leave the Function untouched; the agent reads it when it
    builds its tools. A bridged callable never passes through that step, so
    without this the approval is invisible and the call runs unapproved.
    """
    approval_type = getattr(tool, "_agno_approval_type", None)
    if approval_type is None:
        return
    function.approval_type = approval_type
    if not any([function.requires_user_input, function.requires_confirmation, function.external_execution]):
        if approval_type == "required":
            function.requires_confirmation = True
        elif approval_type == "audit":
            raise ValueError(
                "@approval(type='audit') requires at least one HITL flag "
                "('requires_confirmation', 'requires_user_input', or 'external_execution') "
                "to be set on @tool()."
            )
