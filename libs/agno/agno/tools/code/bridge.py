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
* Every call runs under the ``RunContext`` of the cell whose task made it: the
  host stamps a token per user cell, the kernel carries it in a contextvar
  that ``asyncio`` tasks copy at creation, and the call sends it back — so a
  background task that outlives its cell keeps the run that created it.
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
from agno.tools.code.kernel import KernelSession
from agno.tools.code.naming import derive_handle_name, safe_param_name
from agno.tools.function import Function, FunctionCall, ToolResult
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning

# How long a synchronous close waits for an async close() running on another
# thread's loop before it gives up and reports it.
_ASYNC_CLOSE_TIMEOUT = 10.0

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
    "import contextvars as _agno_cv\n"
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
    "# Each user cell runs with the context token the host stamped for it, and\n"
    "# asyncio tasks copy the context they are created in, so a bridged call\n"
    "# from a background task still names the cell that created the task.\n"
    "# Silent cells fire no pre_run_cell and leave the binding alone.\n"
    "_agno_ctx_token = _agno_cv.ContextVar('agno_ctx_token', default=None)\n"
    "_agno_cm_next_token = None\n"
    "\n"
    "\n"
    "def _agno_pre_run_cell(_agno_info):\n"
    "    _agno_ctx_token.set(_agno_b.globals().get('_agno_cm_next_token'))\n"
    "\n"
    "\n"
    "get_ipython().events.register('pre_run_cell', _agno_pre_run_cell)\n"
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
    "    _agno_comm.send(\n"
    "        {{'id': _agno_id, 'handle': handle, 'method': method, 'kwargs': kwargs, 'token': _agno_ctx_token.get()}}\n"
    "    )\n"
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
    "            \"'%s' cannot be called in this environment: %s\" % (label, error)\n"
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
    "        if _agno_m.get('error'):\n"
    "            _agno_fn = _agno_unbound_stub(\n"
    "                _agno_t['handle'] + '.' + _agno_m['name'], _agno_m['error']\n"
    "            )\n"
    "        else:\n"
    "            try:\n"
    "                _agno_fn = _agno_make_stub(\n"
    "                    _agno_t['handle'], _agno_m['name'], _agno_m.get('doc') or '', _agno_m.get('params') or []\n"
    "                )\n"
    "            except _agno_b.Exception as _agno_error:\n"
    "                _agno_fn = _agno_unbound_stub(\n"
    "                    _agno_t['handle'] + '.' + _agno_m['name'], _agno_b.repr(_agno_error)\n"
    "                )\n"
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
        prop = properties.get(name) or {}
        entry: Dict[str, Any] = {"name": safe, "wire": name, "required": name in required}
        # Carried for the docstring only; the kernel stub reads name/wire/required.
        for key in ("type", "description", "enum", "default"):
            if key in prop:
                entry[key] = prop[key]
        params.append(entry)
    return params


def _stub_doc(function: Function, params: Sequence[Dict[str, Any]], bound_as: Optional[str] = None) -> str:
    """The stub's docstring: the description, an argument block, and every adapted name.

    ``help(handle.method)`` in a cell is the model's only schema view once a
    tool lives in the kernel, so the argument types, choices, defaults and
    descriptions the JSON schema carried are rendered here.
    """
    doc = function.description or ""
    argument_lines = []
    for p in params:
        pieces = [p["name"]]
        if p.get("type"):
            pieces.append(f"({p['type']})")
        line = " ".join(pieces) + ":"
        details = []
        if p.get("description"):
            details.append(str(p["description"]).strip())
        if p.get("enum"):
            details.append("one of " + ", ".join(repr(v) for v in p["enum"]))
        if not p["required"]:
            details.append(f"default {p['default']!r}" if "default" in p else "optional")
        argument_lines.append(f"    {line} {' - '.join(details)}" if details else f"    {line}")
    if argument_lines:
        doc = (
            f"{doc}\n\nArguments:\n" + "\n".join(argument_lines) if doc else "Arguments:\n" + "\n".join(argument_lines)
        )
    notes = []
    if bound_as is not None and bound_as != function.name:
        notes.append(f"Bound as '{bound_as}'; the tool's own name is '{function.name}'.")
    renamed = [f"{p['name']} for '{p['wire']}'" for p in params if p["name"] != p["wire"]]
    if renamed:
        notes.append("Parameter names adapted for Python: " + ", ".join(renamed) + ".")
    if notes:
        note = "\n".join(notes)
        doc = f"{doc}\n\n{note}" if doc else note
    return doc


def _pause_refusal(function: Function) -> Optional[str]:
    """Why this tool cannot be called from a cell, or None when it can.

    Confirmation, user input and external execution all pause the agent run,
    and a cell cannot pause a run. A tool that requires user input also has
    those fields stripped out of its parameter schema, so a stub built from
    that schema would reject the very argument the tool documents: the tool is
    bound as a stub that answers with this reason instead.
    """
    if (
        function.requires_confirmation
        or function.external_execution
        or function.requires_user_input
        or function.approval_type is not None
    ):
        return (
            f"'{function.name}' requires human approval or external execution. Those pause the "
            "agent run, which a cell cannot do, so it cannot be called from the code environment. "
            "Ask for it as a regular tool call instead."
        )
    return None


def _is_connectable(tool: Any) -> bool:
    """Whether this bridge owns the toolkit's connection lifecycle.

    MCPTools is recognised by class name across the MRO, the way agno
    recognises it everywhere else: it never sets ``_requires_connect``, and
    importing it here would pull the mcp package into every import of CodeMode.
    """
    if not hasattr(tool, "connect"):
        return False
    if getattr(tool, "requires_connect", False):
        return True
    return hasattr(type(tool), "__mro__") and any(cls.__name__ == "MCPTools" for cls in type(tool).__mro__)


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
        # Toolkits that manage their own connections; the ones this bridge has
        # connected and still owes a close(); and the ones whose connect() is a
        # coroutine function and so waits for a kernel bootstrap to await it.
        self._connectable: List[Any] = [tool for tool in tools if _is_connectable(tool)]
        self._connected: List[Any] = []
        self._deferred: List[Any] = []
        # id(toolkit) -> the loop its connect() ran on, so its close() runs
        # there too. The toolkits are held in self._tools, so no id is reused.
        self._connect_loops: Dict[int, Optional[asyncio.AbstractEventLoop]] = {}
        # Runs currently holding the injected toolkits open. One CodeMode
        # serves every session, so only the last run to end may close them.
        self._holders: int = 0
        # The loop the injected toolkits were connected on: their clients and
        # transports are bound to it. None on a synchronous run.
        self._host_loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools: List[Union[Toolkit, Callable[..., Any], Function]] = list(tools)
        self._built = False

    # ------------------------------------------------------------------
    # Binding specs
    # ------------------------------------------------------------------

    @property
    def has_bindings(self) -> bool:
        """True when there is anything to bind into a kernel.

        Answered without building the spec: the spec is built at bootstrap,
        after the injected toolkits have been connected.
        """
        if not self._built:
            return bool(self._tools)
        return bool(self._spec["toolkits"] or self._spec["functions"])

    @property
    def handle_names(self) -> List[str]:
        self._ensure_built()
        names = [t["handle"] for t in self._spec["toolkits"]]
        names.extend(f["name"] for f in self._spec["functions"])
        return names

    def _ensure_built(self) -> None:
        """Build the binding spec once, after the injected toolkits are connected.

        A toolkit that registers its functions in connect() — MCPTools does —
        carries none at construction, so a spec built there binds a handle with
        no methods. Connecting a toolkit clears this, so the next kernel binds
        what the connection brought.
        """
        if self._built:
            return
        self._built = True
        self._registry = {}
        self._spec = {"toolkits": [], "functions": []}
        self._build(self._tools)

    def _build(self, tools: Sequence[Union[Toolkit, Callable[..., Any], Function]]) -> None:
        # Toolkits and top-level callables share one kernel namespace; the
        # names are deduplicated in input order, matching handle_names_for,
        # so the instructions and the snapshot skip list name what is bound.
        bound_names: Set[str] = set()
        for tool in tools:
            if isinstance(tool, Toolkit):
                handle = derive_handle_name(tool.name, bound_names)
                if handle != derive_handle_name(tool.name):
                    log_warning(
                        f"CodeMode: toolkit '{tool.name}' binds as '{handle}' because an earlier "
                        "binding took its handle"
                    )
                bound_names.add(handle)
                try:
                    functions = dict(tool.get_async_functions())
                    specs: List[Dict[str, Any]] = []
                    bound: Set[str] = set()
                    for name, function in functions.items():
                        prepared = self._prepare_function(function)
                        # A tool name carries no Python constraints: an MCP
                        # server may call a tool 'get-forecast', which no
                        # expression in a cell can reference. The registry is
                        # keyed by the bound name; the Function it maps to
                        # still carries the tool's own name for dispatch.
                        bind = safe_param_name(name, bound)
                        bound.add(bind)
                        self._registry[(handle, bind)] = prepared
                        refusal = _pause_refusal(prepared)
                        if refusal is not None:
                            specs.append({"name": bind, "error": refusal})
                            continue
                        params = _params_from_schema(prepared)
                        specs.append({"name": bind, "doc": _stub_doc(prepared, params, bind), "params": params})
                    if not specs:
                        # The instructions advertise this handle, so an object
                        # with nothing on it is a silent dead end.
                        log_warning(f"CodeMode bound toolkit '{tool.name}' with no functions on it")
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
                    name = safe_param_name(prepared.name, bound_names)
                    bound_names.add(name)
                    self._registry[("", name)] = prepared
                    refusal = _pause_refusal(prepared)
                    if refusal is not None:
                        self._spec["functions"].append({"name": name, "error": refusal})
                        continue
                    params = _params_from_schema(prepared)
                    self._spec["functions"].append(
                        {"name": name, "doc": _stub_doc(prepared, params, name), "params": params}
                    )
                except Exception as e:
                    tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
                    log_warning(f"CodeMode could not bind callable '{tool_name}': {e}")
                    # The instructions advertise every attached name, so a name
                    # that failed to bind still has to exist in the kernel and
                    # say why it cannot be called.
                    if isinstance(tool_name, str) and tool_name:
                        bind = safe_param_name(tool_name, bound_names)
                        bound_names.add(bind)
                        if not any(entry["name"] == bind for entry in self._spec["functions"]):
                            self._spec["functions"].append({"name": bind, "error": str(e)})

    @staticmethod
    def _prepare_function(function: Function) -> Function:
        prepared = function.model_copy(deep=True)
        try:
            prepared.process_entrypoint(strict=False)
        except Exception as e:
            log_debug(f"CodeMode: process_entrypoint failed for '{function.name}': {e}")
        return prepared

    def bootstrap_code(self) -> str:
        self._ensure_built()
        spec_b64 = base64.b64encode(json.dumps(self._spec).encode("utf-8")).decode("ascii")
        return _BOOTSTRAP_TEMPLATE.format(failed_binding_class=FAILED_BINDING_CLASS, spec_b64=spec_b64)

    async def bootstrap(self, session: KernelSession) -> bool:
        """Run the bootstrap cell; True when it succeeded.

        Any toolkit still waiting for an async connect() is connected first:
        the functions a connection registers have to be in the spec this cell
        binds from.
        """
        await self._connect_deferred()
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
        connect() is called from here. agno calls this from a synchronous
        frame on both ``run`` and ``arun``, so a toolkit whose ``connect()``
        is a coroutine function is left to the first kernel bootstrap, which
        can await it.

        This also captures the loop it runs on as the host loop: the clients
        those toolkits build belong to it, and their coroutines have to be
        awaited there. A synchronous run has no loop and captures none.

        The toolkits are shared by every session of one CodeMode, so each run
        takes a hold on them here and gives it back in ``close_tools``.
        """
        self._capture_host_loop()
        self._holders += 1
        for tool in self._connectable:
            if self._is_open(tool):
                continue
            if iscoroutinefunction(tool.connect):
                self._defer(tool)
                continue
            try:
                result = tool.connect()
                if iscoroutine(result):
                    # A connect() that is not declared async but still returns
                    # a coroutine: this frame cannot await that either.
                    result.close()
                    self._defer(tool)
                    continue
            except Exception as e:
                log_warning(f"CodeMode could not connect toolkit '{_tool_label(tool)}': {e}")
                continue
            self._record_connected(tool, self._host_loop)

    async def aconnect_tools(self) -> None:
        """Async variant of ``connect_tools``, for a developer driving CodeMode directly.

        agno's own connectable-tool path is synchronous on both ``run`` and
        ``arun``, so nothing in the framework calls this. It awaits an async
        ``connect()`` here instead of leaving it to the first bootstrap.
        """
        self._capture_host_loop()
        self._holders += 1
        for tool in self._connectable:
            if self._is_open(tool):
                continue
            self._deferred = [pending for pending in self._deferred if pending is not tool]
            try:
                result = tool.connect()
                if iscoroutine(result):
                    await result
            except Exception as e:
                log_warning(f"CodeMode could not connect toolkit '{_tool_label(tool)}': {e}")
                continue
            self._record_connected(tool, self._host_loop)

    def close_tools(self) -> None:
        """Close the injected toolkits this bridge connected.

        Only the last run holding them open closes them. One CodeMode serves
        every session, so an earlier run's end must not disconnect a toolkit
        another session's cell is in the middle of calling.
        """
        if self._release_holder():
            return
        self._deferred = []
        for tool in self._connected:
            try:
                result = tool.close()
                if iscoroutine(result):
                    self._close_coroutine(tool, result)
            except Exception as e:
                log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")
        self._connected = []
        self._connect_loops = {}

    async def aclose_tools(self) -> None:
        """Async variant of ``close_tools``, for a developer driving CodeMode directly.

        agno closes toolkits from a synchronous frame, so nothing in the
        framework calls this. It awaits an async ``close()`` here instead of
        scheduling it on the loop the toolkit was connected on.
        """
        if self._release_holder():
            return
        self._deferred = []
        for tool in self._connected:
            try:
                result = tool.close()
                if iscoroutine(result):
                    loop = self._connect_loops.get(id(tool))
                    current = asyncio.get_running_loop()
                    if loop is not None and loop is not current and loop.is_running() and not loop.is_closed():
                        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(result, loop))
                    else:
                        await result
            except Exception as e:
                log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")
        self._connected = []
        self._connect_loops = {}

    async def _connect_deferred(self) -> None:
        """Connect the toolkits whose ``connect()`` is a coroutine function.

        A synchronous frame cannot await, so the connect waits for the first
        kernel bootstrap. It runs on the loop that will also serve this
        toolkit's calls, because a client, a session or a pool belongs to
        whichever loop created it.
        """
        while self._deferred:
            tool = self._deferred.pop(0)
            if self._is_open(tool):
                continue
            loop = await self._coroutine_loop()
            try:
                if loop is None:
                    await tool.connect()
                    loop = asyncio.get_running_loop()
                else:
                    await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(tool.connect(), loop))
            except Exception as e:
                log_warning(f"CodeMode could not connect toolkit '{_tool_label(tool)}': {e}")
                continue
            self._record_connected(tool, loop)

    def _defer(self, tool: Any) -> None:
        """Leave a toolkit for the first kernel bootstrap to connect."""
        if not any(pending is tool for pending in self._deferred):
            self._deferred.append(tool)

    def _record_connected(self, tool: Any, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        """Take ownership of a toolkit's connection and rebuild the spec around it."""
        self._connected.append(tool)
        self._connect_loops[id(tool)] = loop
        # A connection may register the toolkit's functions, so the spec built
        # before it is stale.
        self._built = False

    def _is_open(self, tool: Any) -> bool:
        """Whether this toolkit already holds a live connection."""
        if any(connected is tool for connected in self._connected):
            return True
        # MCPTools opened by the developer, typically `async with MCPTools(...)`.
        return bool(getattr(tool, "initialized", False))

    def _release_holder(self) -> bool:
        """Drop one run's hold. True while another run still holds the toolkits open."""
        if self._holders > 0:
            self._holders -= 1
        return self._holders > 0

    def _close_coroutine(self, tool: Any, coro: Coroutine[Any, Any, Any]) -> None:
        """Run an async ``close()`` on the loop the toolkit was connected on.

        Nothing in agno awaits a toolkit's close, so this frame is
        synchronous. On that loop's own thread the close is scheduled and this
        returns — waiting here would wait on the loop this frame runs on; from
        any other thread it waits for the close to finish. With no live loop
        the close cannot run at all, and the toolkit is left open.
        """
        loop = self._connect_loops.get(id(tool))
        if loop is None or loop.is_closed() or not loop.is_running():
            coro.close()
            log_warning(
                f"CodeMode: toolkit '{_tool_label(tool)}' has an async close() and no live event "
                "loop to run it on; close it yourself after the run."
            )
            return
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError as e:
            coro.close()
            log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")
            return
        try:
            running: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            return
        try:
            future.result(timeout=_ASYNC_CLOSE_TIMEOUT)
        except Exception as e:
            log_warning(f"CodeMode could not close toolkit '{_tool_label(tool)}': {e}")

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
        token = data.get("token")
        tool_label = f"{handle}.{method}" if handle else method
        try:
            value = await self._call_tool(session, handle, method, kwargs, token=token)
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

    async def _call_tool(
        self, session: KernelSession, handle: str, method: str, kwargs: Dict[str, Any], token: Optional[str] = None
    ) -> Any:
        self._ensure_built()
        function = self._registry.get((handle, method))
        if function is None:
            raise RuntimeError(f"unknown tool '{handle}.{method}'" if handle else f"unknown tool '{method}'")
        refusal = _pause_refusal(function)
        if refusal is not None:
            raise RuntimeError(refusal)
        prepared = function.model_copy(deep=True)
        # The token names the cell whose task made this call, so a background
        # task that outlives its cell still runs under the run that created it.
        # Without one (a thread, a cell outside the token window, an old
        # kernel), the currently executing run's context applies.
        run_context = session.context_tokens.get(token) if token else None
        if run_context is None:
            run_context = getattr(session, "run_context", None)
        if run_context is None:
            run_context = RunContext(run_id=f"code-mode-{session.session_id}", session_id=session.session_id)
        prepared._run_context = run_context
        function_call = FunctionCall(function=prepared, arguments=kwargs)
        entrypoint = prepared.entrypoint
        # The tool's own call path, so its hooks and caching apply. Anything
        # async — the entrypoint, a tool hook, the pre_hook or the post_hook —
        # has to go through aexecute, which is the only path that awaits them;
        # execute() calls a coroutine function and drops the coroutine, so an
        # async pre_hook written as a policy gate would never run. A fully
        # synchronous call runs in a worker thread so a slow tool cannot stall
        # the kernel loop.
        hooks = list(prepared.tool_hooks or [])
        hooks.extend(hook for hook in (prepared.pre_hook, prepared.post_hook) if hook is not None)
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
        loop = await self._coroutine_loop()
        if loop is None:
            return await coro
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            return await coro
        return await asyncio.wrap_future(future)

    async def _coroutine_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """The loop an injected toolkit's coroutines belong on, or None for this one."""
        loop = self._host_loop
        try:
            current: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if loop is None or loop is current or loop.is_closed() or not loop.is_running():
            return None
        if not await self._host_loop_is_turning(loop):
            return None
        return loop

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
            # Media cannot cross the bridge; say so instead of dropping it
            # silently, so the model knows to call the tool the regular way.
            dropped = [
                f"{len(media)} {label}(s)"
                for label, media in (
                    ("image", result.images),
                    ("video", result.videos),
                    ("audio", result.audios),
                    ("file", result.files),
                )
                if media
            ]
            content = result.content
            if dropped:
                note = (
                    f"[{', '.join(dropped)} attached; media does not cross the code bridge - "
                    "call the tool as a regular tool call to receive it]"
                )
                content = f"{content}\n{note}" if content else note
            result = content
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
            # key is (session_id, kernel generation, call id); the kernel pops
            # its pending entry by the call id.
            self._send_reply(
                session,
                {"id": key[2], "ok": False, "error": {"type": "ToolError", "message": f"tool call aborted: {reason}"}},
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
