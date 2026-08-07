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
"""

from __future__ import annotations

import asyncio
import base64
import json
from inspect import iscoroutinefunction
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from agno.run import RunContext
from agno.tools.code_mode.kernel import KernelSession
from agno.tools.code_mode.naming import derive_handle_name
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
    "    _agno_sig_params = []\n"
    "    for _agno_p in params:\n"
    "        _agno_default = _agno_inspect.Parameter.empty if _agno_p.get('required') else None\n"
    "        _agno_sig_params.append(\n"
    "            _agno_inspect.Parameter(_agno_p['name'], _agno_inspect.Parameter.POSITIONAL_OR_KEYWORD, default=_agno_default)\n"
    "        )\n"
    "    _agno_sig = _agno_inspect.Signature(_agno_sig_params)\n"
    "\n"
    "    async def _agno_stub(*args, **kwargs):\n"
    "        _agno_bound = _agno_sig.bind_partial(*args, **kwargs)\n"
    "        return await _agno_bridge_call(handle, method, _agno_b.dict(_agno_bound.arguments))\n"
    "\n"
    "    _agno_stub.__name__ = method\n"
    "    _agno_stub.__qualname__ = (handle + '.' + method) if handle else method\n"
    "    _agno_stub.__doc__ = doc\n"
    "    _agno_stub.__signature__ = _agno_sig\n"
    "    return _agno_stub\n"
    "\n"
    "\n"
    "_agno_spec = _agno_json.loads(_agno_b64.b64decode('{spec_b64}').decode('utf-8'))\n"
    "for _agno_t in _agno_spec['toolkits']:\n"
    "    if _agno_t.get('error'):\n"
    "        _agno_b.globals()[_agno_t['handle']] = _AgnoFailedBinding(_agno_t['name'], _agno_t['error'])\n"
    "        continue\n"
    "    _agno_members = {{'__doc__': _agno_t.get('doc') or ''}}\n"
    "    for _agno_m in _agno_t['functions']:\n"
    "        _agno_members[_agno_m['name']] = _agno_b.staticmethod(\n"
    "            _agno_make_stub(_agno_t['handle'], _agno_m['name'], _agno_m.get('doc') or '', _agno_m.get('params') or [])\n"
    "        )\n"
    "    _agno_b.globals()[_agno_t['handle']] = _agno_b.type(_agno_t['handle'], (), _agno_members)()\n"
    "for _agno_f in _agno_spec['functions']:\n"
    "    _agno_b.globals()[_agno_f['name']] = _agno_make_stub('', _agno_f['name'], _agno_f.get('doc') or '', _agno_f.get('params') or [])\n"
)


def _params_from_schema(function: Function) -> List[Dict[str, Any]]:
    """Flatten a Function's JSON-schema parameters into the stub's param spec."""
    schema = function.parameters or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return [{"name": name, "required": name in required} for name in properties]


def _stub_doc(function: Function) -> str:
    doc = function.description or ""
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
        # (handle, method) -> Function; top-level callables bind under handle "".
        self._registry: Dict[Tuple[str, str], Function] = {}
        self._spec: Dict[str, Any] = {"toolkits": [], "functions": []}
        # In-flight calls keyed by (session_id, call_id): call ids are a
        # per-kernel counter, so two sessions of one CodeMode collide on the
        # bare id and an interrupt in one must never cancel the other's calls.
        self._pending: Dict[Tuple[str, str], "asyncio.Task[None]"] = {}
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
                        specs.append(
                            {"name": name, "doc": _stub_doc(prepared), "params": _params_from_schema(prepared)}
                        )
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
                    prepared = self._prepare_function(function)
                    name = prepared.name
                    self._registry[("", name)] = prepared
                    self._spec["functions"].append(
                        {"name": name, "doc": _stub_doc(prepared), "params": _params_from_schema(prepared)}
                    )
                except Exception as e:
                    tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
                    log_warning(f"CodeMode could not bind callable '{tool_name}': {e}")

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
            key = (session.session_id, str(data.get("id")))
            task = asyncio.get_running_loop().create_task(self._serve(session, data))
            self._pending[key] = task
            task.add_done_callback(lambda _t, _key=key: self._pending.pop(_key, None))

    async def _serve(self, session: KernelSession, data: Dict[str, Any]) -> None:
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
        if function.requires_confirmation or function.external_execution or function.requires_user_input:
            raise RuntimeError(
                f"'{function.name}' requires human confirmation or external execution and "
                "cannot be called from the code environment."
            )
        prepared = function.model_copy(deep=True)
        run_context = getattr(session, "run_context", None)
        if run_context is None:
            run_context = RunContext(run_id=f"code-mode-{session.session_id}", session_id=session.session_id)
        prepared._run_context = run_context
        function_call = FunctionCall(function=prepared, arguments=kwargs)
        entrypoint = prepared.entrypoint
        # The normal call path: hooks and caching apply. Sync entrypoints run
        # through a worker thread so a slow tool cannot stall the kernel loop.
        if entrypoint is not None and iscoroutinefunction(entrypoint):
            execution_result = await function_call.aexecute()
        else:
            execution_result = await asyncio.to_thread(function_call.execute)
        if execution_result.status != "success":
            raise RuntimeError(str(function_call.error or execution_result.error or "tool call failed"))
        return self._marshal(execution_result.result)

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
