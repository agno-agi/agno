"""Unit tests for CodeMode that need no kernel.

Kernel-backed behavior lives in tests/integration/tools/test_code_kernel.py.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("ipykernel")
pytest.importorskip("jupyter_client")
pytest.importorskip("dill")

from agno.tools import Function, Toolkit  # noqa: E402
from agno.tools.code import CellResult, CodeMode, CodeModeError, KernelBusyError, ResultTooLarge  # noqa: E402
from agno.tools.code.code_mode import (  # noqa: E402
    _MAX_EVICTED_IDS,
    build_instructions,
    derive_handle_name,
    handle_names_for,
)
from agno.tools.code.kernel import KernelSession, OutputAccumulator  # noqa: E402

# ------------------------------------------------------------------
# Handle-name derivation
# ------------------------------------------------------------------


def test_trailing_tools_suffix_is_stripped():
    assert derive_handle_name("arcade_tools") == "arcade"
    assert derive_handle_name("file_system_tools") == "file_system"


def test_name_without_suffix_is_kept():
    assert derive_handle_name("filesystem") == "filesystem"
    assert derive_handle_name("workspace") == "workspace"


def test_bare_suffix_is_not_stripped_to_nothing():
    assert derive_handle_name("_tools") == "_tools"


def test_non_identifier_characters_are_sanitized():
    assert derive_handle_name("my-weird name") == "my_weird_name"
    assert derive_handle_name("9lives_tools") == "_9lives"


def test_handle_names_for_mixed_tools():
    class ArcadeTools(Toolkit):
        def __init__(self):
            super().__init__(name="arcade_tools", tools=[self.take_action])

        def take_action(self, action: int) -> str:
            """Take an action.

            Args:
                action: The action id.
            """
            return str(action)

    def helper(x: int) -> int:
        """Double x.

        Args:
            x: value.
        """
        return x * 2

    fn = Function(name="named_function")
    handles = handle_names_for([ArcadeTools(), helper, fn])
    assert handles == ["arcade", "helper", "named_function"]


# ------------------------------------------------------------------
# Instruction rendering (pinned per capability combination)
# ------------------------------------------------------------------


def test_instructions_name_the_snapshot_caps_when_given():
    text = build_instructions([], allow_shell=False, allow_restart=False, snapshot_caps=(2_000_000, 64_000_000))
    assert "a single variable over 2000000 bytes" in text
    assert "total state over 64000000 bytes is not saved" in text


def test_instructions_full_surface_pinned():
    text = build_instructions(["arcade", "file_system"], allow_shell=True, allow_restart=True)
    assert text == (
        "You have a persistent Python environment. Use it as your long-lived notebook: "
        "keep intermediate variables, inspect and transform outputs, write small helper "
        "functions, and preserve useful state across turns."
        "\n\n"
        "Always assign read, search, and tool results to named variables so you can revisit "
        "them later instead of re-reading them into your context. Print summaries, not raw data."
        "\n\n"
        "State persists across cells: variables, functions, classes, imports, notes, and parsed "
        "outputs stay available in every later turn. The environment outlives your visible "
        "conversation: variables created in turns you can no longer see are still live, and "
        "%whos lists everything that exists. Attached tools are awaitable calls in this "
        "environment: arcade, file_system. Tool calls are await expressions, so their return "
        "values can be bound to variables and composed into program logic like any other call. "
        "Do not invent wrappers such as call_tool(...); call the documented function, and use "
        "help(...) on a handle to inspect it."
        "\n\n"
        "When result offloading is enabled, stored tool results are values here, not just "
        "envelopes: text = await result_store.get('res_...') binds the whole payload to a "
        "variable, await result_store.search('res_...', pattern) and "
        "await result_store.read('res_...', start_line=...) stay bounded, and "
        "await result_store.ids() lists what this session has stored. Compute over the "
        "variable and print summaries; never print the payload."
        "\n\n"
        "This environment is your control environment, not the runtime of the thing you are "
        "investigating. A repository, service, dataset, or benchmark has its own environment and "
        "its own interface. Evaluate it through that interface and use this environment to "
        "coordinate and analyze what comes back. Do not install dependencies here to force an "
        "external project to import. Treat failures from the project's own environment as the "
        "relevant result."
        "\n\n"
        "%%bash must be the first line of its cell - no comment, import, or statement before "
        "it. Each %%bash cell is a throw-away subshell, so cd, export, and shell variables do "
        "not carry over. Keep dependent shell steps in one cell, or use %cd and "
        "os.environ[...], which are kernel-level and apply to every later %%bash cell."
        "\n\n"
        "If the environment is corrupted or wedged, call restart to tear it down and start "
        "fresh; every variable and import is lost."
    )


def test_instructions_omit_shell_paragraph_when_shell_disabled():
    text = build_instructions([], allow_shell=False, allow_restart=True)
    assert "%%bash" not in text
    assert "restart" in text


def test_instructions_omit_restart_sentence_when_restart_disabled():
    text = build_instructions([], allow_shell=True, allow_restart=False)
    assert "call restart" not in text
    assert "%%bash" in text


def test_instructions_omit_handles_sentence_without_tools():
    text = build_instructions([], allow_shell=True, allow_restart=True)
    assert "Attached tools" not in text
    assert "State persists across cells" in text


def test_instructions_name_the_actual_handles():
    text = build_instructions(["arcade"], allow_shell=False, allow_restart=False)
    assert "arcade" in text
    assert "%%bash" not in text
    assert "call restart" not in text


# ------------------------------------------------------------------
# Output caps at accumulation time
# ------------------------------------------------------------------


def test_accumulator_under_cap_is_untouched():
    acc = OutputAccumulator(100)
    acc.add("hello ")
    acc.add("world")
    assert acc.render() == "hello world"
    assert not acc.truncated


def test_accumulator_keeps_the_head_and_the_tail():
    acc = OutputAccumulator(100)
    acc.add("H" * 75)
    acc.add("M" * 1000)
    acc.add("the traceback lives here")
    assert acc.truncated
    text = acc.render()
    assert text.startswith("H" * 75)
    assert text.endswith("the traceback lives here"[-25:])
    assert "chars omitted; output capped at 100" in text


def test_accumulator_stays_bounded_after_the_cap():
    acc = OutputAccumulator(100)
    for _ in range(1000):
        acc.add("xxxxxxxxxx")
    # Bounded at the cap: head plus tail never exceed max_chars.
    assert acc._head_length + acc._tail_length <= 100
    assert "chars omitted; output capped at 100" in acc.render()


def test_accumulator_one_huge_chunk_keeps_its_own_tail():
    acc = OutputAccumulator(100)
    acc.add("A" * 75 + "B" * 10_000 + "END")
    text = acc.render()
    assert text.startswith("A" * 75)
    assert text.endswith("END")


def test_accumulator_exact_cap_is_not_truncated():
    acc = OutputAccumulator(5)
    acc.add("12345")
    assert not acc.truncated
    assert acc.render() == "12345"


# ------------------------------------------------------------------
# Toolkit surface
# ------------------------------------------------------------------


def test_registered_tools_default_surface():
    cm = CodeMode()
    assert list(cm.functions.keys()) == ["execute", "restart"]
    assert list(cm.async_functions.keys()) == ["execute", "restart"]


def test_restart_not_registered_when_disallowed():
    cm = CodeMode(allow_restart=False)
    assert list(cm.functions.keys()) == ["execute"]
    assert list(cm.async_functions.keys()) == ["execute"]


def test_toolkit_defaults_add_instructions():
    cm = CodeMode()
    assert cm.add_instructions is True
    assert cm.instructions == build_instructions([], allow_shell=True, allow_restart=True)


def test_requires_connect_lifecycle():
    cm = CodeMode()
    assert cm.requires_connect is True
    # connect is a no-op and close without a started loop is a no-op.
    cm.connect()
    cm.close()


def test_async_docstrings_match_sync():
    assert CodeMode.aexecute.__doc__ == CodeMode.execute.__doc__
    assert CodeMode.arestart.__doc__ == CodeMode.restart.__doc__


def test_every_public_method_has_async_twin():
    for name in ("execute", "restart", "run", "variables", "value", "shutdown", "close"):
        assert callable(getattr(CodeMode, name))
        assert callable(getattr(CodeMode, "a" + name))


def test_shell_rejection_without_kernel():
    cm = CodeMode(allow_shell=False)
    result = cm.run("no-kernel-session", "%%bash\necho hi")
    assert isinstance(result, CellResult)
    assert result.status == "error"
    assert "allow_shell=False" in result.stderr
    # No kernel was started for the rejected cell.
    assert not cm._sessions or not cm._sessions.get("no-kernel-session", None)


def test_variables_of_unknown_session_is_empty():
    cm = CodeMode()
    assert cm.variables("never-started") == {}


def test_shutdown_without_sessions_is_safe():
    cm = CodeMode()
    cm.shutdown()
    cm.shutdown("nothing")


def test_evicted_session_ids_are_bounded():
    cm = CodeMode()
    ids = [f"evicted-{i}" for i in range(_MAX_EVICTED_IDS + 10)]
    for session_id in ids:
        session = SimpleNamespace(session_id=session_id)
        cm._sessions[session_id] = session
        cm._forget_session(session)
    assert cm._sessions == {}
    assert len(cm._evicted) == _MAX_EVICTED_IDS
    # The oldest ids go first: a session evicted long ago loses only the
    # reset notice, while the recent ones still get it.
    assert ids[0] not in cm._evicted
    assert ids[9] not in cm._evicted
    assert ids[10] in cm._evicted
    assert ids[-1] in cm._evicted


def test_a_session_owner_that_is_not_a_str_is_compared_as_text():
    cm = CodeMode()
    session_id = "typed-owner"
    cm._sessions[session_id] = KernelSession(session_id, owner_user_id=42)
    try:
        assert cm._run_on_loop_sync(cm._refuse_foreign_user(session_id, "42")) is False
        assert cm._run_on_loop_sync(cm._refuse_foreign_user(session_id, "43")) is True
    finally:
        cm.shutdown()


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------


def test_kernel_busy_error_tells_the_model_what_to_do():
    err = KernelBusyError()
    assert "busy" in str(err)
    assert "restart" in str(err)
    assert isinstance(err, CodeModeError)


def test_result_too_large_carries_structured_fields():
    err = ResultTooLarge("too big", tool_name="take_action", size_bytes=2_000_000, limit=1_000_000)
    assert err.tool_name == "take_action"
    assert err.size_bytes == 2_000_000
    assert err.limit == 1_000_000
    assert isinstance(err, CodeModeError)


def test_cell_timeout_does_not_leak_into_toolkit_timeout():
    cm = CodeMode(timeout=42)
    assert cm.cell_timeout == 42
    # Toolkit.timeout stays unset (None): the cell timeout is enforced by the
    # interrupt flow, not by the framework's tool-call timeout.
    assert cm.timeout is None


def test_import_error_message_names_the_extra(monkeypatch):
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("ipykernel", "jupyter_client", "dill"):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved = {k: v for k, v in sys.modules.items() if k.startswith("agno.tools.code")}
    for k in saved:
        monkeypatch.delitem(sys.modules, k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="agno\\[code\\]"):
        importlib.import_module("agno.tools.code")
    monkeypatch.setattr(builtins, "__import__", real_import)
    sys.modules.update(saved)


# ------------------------------------------------------------------
# Failed-binding stub (kernel-side class, pinned host-side via exec)
# ------------------------------------------------------------------


def test_failed_binding_stub_raises_runtime_error_never_name_error():
    from agno.tools.code.bridge import FAILED_BINDING_CLASS

    namespace = {}
    exec(FAILED_BINDING_CLASS, namespace)
    stub = namespace["_AgnoFailedBinding"]("arcade_tools", "connection refused")
    raiser = stub.take_action
    assert callable(raiser)
    with pytest.raises(RuntimeError) as exc_info:
        raiser(1, key="value")
    message = str(exc_info.value)
    assert "arcade_tools" in message
    assert "take_action" in message
    assert "connection refused" in message


def test_failed_binding_stub_every_attribute_returns_a_callable():
    from agno.tools.code.bridge import FAILED_BINDING_CLASS

    namespace = {}
    exec(FAILED_BINDING_CLASS, namespace)
    stub = namespace["_AgnoFailedBinding"]("t", "boom")
    for attr in ("anything", "at", "all"):
        with pytest.raises(RuntimeError):
            getattr(stub, attr)()


# ------------------------------------------------------------------
# Bridge replies are tied to the kernel that asked
# ------------------------------------------------------------------


class _FakeChannel:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class _FakeKernelClient:
    def __init__(self):
        self.control_channel = _FakeChannel()

        class _Session:
            @staticmethod
            def msg(msg_type, content):
                return {"msg_type": msg_type, "content": content}

        self.session = _Session()


class _FakeSession:
    """The KernelSession surface the bridge touches."""

    def __init__(self):
        self.session_id = "fake-session"
        self.generation = 1
        self.bridge_comm_id = "comm-1"
        self.run_context = None
        self.kc = _FakeKernelClient()


def _bridge_call(bridge, session, method, **kwargs):
    """Serve one call the way _on_comm does: tagged with the asking kernel."""
    return bridge._serve(session, {"id": "1", "handle": "", "method": method, "kwargs": kwargs}, session.generation)


async def test_bridge_reply_reaches_the_kernel_that_asked():
    from agno.tools.code.bridge import ToolBridge

    def double(x: int) -> int:
        """Double x.

        Args:
            x: value.
        """
        return x * 2

    session = _FakeSession()
    bridge = ToolBridge([double])
    await _bridge_call(bridge, session, "double", x=2)
    assert len(session.kc.control_channel.sent) == 1
    assert session.kc.control_channel.sent[0]["content"]["data"] == {"id": "1", "ok": True, "value": 4}


async def test_bridge_reply_from_a_replaced_kernel_is_dropped():
    from agno.tools.code.bridge import ToolBridge

    session = _FakeSession()

    def double_after_restart(x: int) -> int:
        """Double x, with the kernel replaced while the call is in flight.

        Args:
            x: value.
        """
        session.generation += 1
        return x * 2

    bridge = ToolBridge([double_after_restart])
    await _bridge_call(bridge, session, "double_after_restart", x=2)
    # Call ids restart at 1 in the replacement kernel, so this reply would
    # answer a different call than the one that asked for it.
    assert session.kc.control_channel.sent == []


async def test_a_call_id_reused_by_the_next_kernel_gets_its_own_entry():
    import asyncio

    from agno.tools.code.bridge import ToolBridge

    released = asyncio.Event()

    async def wait_for_release(x: int) -> int:
        """Return x once the test releases it.

        Args:
            x: value.
        """
        await released.wait()
        return x

    session = _FakeSession()
    bridge = ToolBridge([wait_for_release])
    request = {
        "msg_type": "comm_msg",
        "content": {
            "comm_id": "comm-1",
            "data": {"id": "1", "handle": "", "method": "wait_for_release", "kwargs": {"x": 1}},
        },
    }
    bridge._on_comm(session, request)
    # The kernel is replaced; the fresh one numbers its first call "1" too.
    session.generation += 1
    bridge._on_comm(session, request)
    assert len(bridge._pending) == 2, "the two kernels' calls must be tracked apart"
    released.set()
    await asyncio.gather(*list(bridge._pending.values()))
    # Only the live kernel's call is answered.
    assert len(session.kc.control_channel.sent) == 1

    serving = list(bridge._pending.values())
    released.set()
    await asyncio.gather(*serving)
    assert bridge._pending == {}
    # Only the live kernel is answered; the replaced one's reply is dropped.
    assert len(session.kc.control_channel.sent) == 1


# ------------------------------------------------------------------
# Snapshot budget accounting (host-side, pure)
# ------------------------------------------------------------------


def test_budget_keeps_small_variables_and_cuts_the_oversized_one():
    from agno.tools.code.snapshot import apply_snapshot_budget

    entries = [
        {"name": "huge_df", "bytes": 40_000_000, "data": "..."},
        {"name": "small_a", "bytes": 100, "data": "..."},
        {"name": "small_b", "bytes": 200, "data": "..."},
    ]
    kept, cut = apply_snapshot_budget(entries, max_snapshot_bytes=1_000_000)
    assert [e["name"] for e in kept] == ["small_a", "small_b"]
    assert len(cut) == 1
    assert cut[0]["name"] == "huge_df"
    assert "snapshot budget" in cut[0]["reason"]


def test_budget_exact_fit_is_kept():
    from agno.tools.code.snapshot import apply_snapshot_budget

    entries = [{"name": "a", "bytes": 600, "data": ""}, {"name": "b", "bytes": 400, "data": ""}]
    kept, cut = apply_snapshot_budget(entries, max_snapshot_bytes=1_000)
    assert len(kept) == 2
    assert cut == []


def test_budget_orders_smallest_first_so_largest_is_cut():
    from agno.tools.code.snapshot import apply_snapshot_budget

    entries = [{"name": "big", "bytes": 900, "data": ""}, {"name": "small", "bytes": 200, "data": ""}]
    kept, cut = apply_snapshot_budget(entries, max_snapshot_bytes=1_000)
    assert [e["name"] for e in kept] == ["small"]
    assert [c["name"] for c in cut] == ["big"]


# ------------------------------------------------------------------
# Restored-notice rendering
# ------------------------------------------------------------------


def test_restored_notice_full_shape():
    from agno.tools.code.snapshot import build_restored_notice

    notice = build_restored_notice(
        ["frames", "world_model"],
        [
            ("arcade_client", "TypeError: cannot pickle 'socket' object"),
            ("scores", "too large to store: 1066680 bytes, over the 1000000-byte limit"),
        ],
    )
    assert notice == (
        "<code_mode_restored>\n"
        "Restored 2 variables: frames, world_model.\n"
        "Not restored:\n"
        "- arcade_client: TypeError: cannot pickle 'socket' object\n"
        "- scores: too large to store: 1066680 bytes, over the 1000000-byte limit\n"
        "</code_mode_restored>"
    )


def test_restored_notice_never_calls_a_size_refusal_unpicklable():
    from agno.tools.code.snapshot import build_restored_notice

    notice = build_restored_notice([], [("scores", "too large to store: 1066680 bytes, over the 1000000-byte limit")])
    assert "unpicklable" not in notice
    assert "- scores: too large to store: 1066680 bytes, over the 1000000-byte limit" in notice


def test_restored_notice_omits_unpicklable_line_when_empty():
    from agno.tools.code.snapshot import build_restored_notice

    notice = build_restored_notice(["x"], [])
    assert "Not restored" not in notice
    assert "Restored 1 variables: x." in notice


def test_restored_notice_none_when_nothing_happened():
    from agno.tools.code.snapshot import build_restored_notice

    assert build_restored_notice([], []) is None


# ------------------------------------------------------------------
# Snapshot caps against the file store's own limits
# ------------------------------------------------------------------


def test_caps_are_lowered_to_the_store_limits():
    from agno.tools.code.snapshot import reconcile_caps

    variable_bytes, snapshot_bytes, notes = reconcile_caps(2_000_000, 64_000_000, 1_000_000, 20_000_000)
    assert (variable_bytes, snapshot_bytes) == (1_000_000, 20_000_000)
    assert len(notes) == 2
    assert "max_file_bytes" in notes[0]
    assert "max_namespace_bytes" in notes[1]


def test_caps_below_the_store_limits_are_left_alone():
    from agno.tools.code.snapshot import reconcile_caps

    assert reconcile_caps(10_000, 50_000, 4_000_000, 128_000_000) == (10_000, 50_000, [])


def test_caps_survive_a_store_that_publishes_no_limits():
    from agno.tools.code.snapshot import reconcile_caps

    assert reconcile_caps(2_000_000, 64_000_000, None, None) == (2_000_000, 64_000_000, [])


def test_snapshot_manager_binds_the_store_limits_and_warns_once(tmp_path, monkeypatch):
    from agno.fs import FileSystem
    from agno.fs.local import LocalFileSystem
    from agno.tools.code import snapshot as snapshot_module

    warnings = []
    monkeypatch.setattr(snapshot_module, "log_warning", lambda message: warnings.append(message))

    fs = FileSystem(
        backend=LocalFileSystem(root=tmp_path),
        max_file_bytes=1_000_000,
        max_namespace_bytes=20_000_000,
    )
    manager = snapshot_module.SnapshotManager(fs, max_variable_bytes=2_000_000, max_snapshot_bytes=64_000_000)

    assert manager.max_variable_bytes == 1_000_000
    assert manager.max_snapshot_bytes == 20_000_000
    assert len(warnings) == 1
    assert "max_file_bytes" in warnings[0]


def test_snapshot_manager_is_quiet_when_the_store_fits_the_caps(tmp_path, monkeypatch):
    from agno.fs import FileSystem
    from agno.fs.local import LocalFileSystem
    from agno.tools.code import snapshot as snapshot_module

    warnings = []
    monkeypatch.setattr(snapshot_module, "log_warning", lambda message: warnings.append(message))

    fs = FileSystem(
        backend=LocalFileSystem(root=tmp_path),
        max_file_bytes=4_000_000,
        max_namespace_bytes=128_000_000,
    )
    manager = snapshot_module.SnapshotManager(fs, max_variable_bytes=2_000_000, max_snapshot_bytes=64_000_000)

    assert manager.max_variable_bytes == 2_000_000
    assert manager.max_snapshot_bytes == 64_000_000
    assert warnings == []


# Parameter names: Python-safe, required first
# ------------------------------------------------------------------


def test_safe_param_name_keeps_a_usable_name():
    from agno.tools.code.naming import safe_param_name

    assert safe_param_name("query") == "query"
    assert safe_param_name("_private") == "_private"


def test_safe_param_name_escapes_keywords_and_non_identifiers():
    from agno.tools.code.naming import safe_param_name

    assert safe_param_name("from") == "from_"
    assert safe_param_name("class") == "class_"
    assert safe_param_name("start-date") == "start_date"
    assert safe_param_name("2fa") == "_2fa"
    assert safe_param_name("") == "_"


def test_safe_param_name_disambiguates_a_collision():
    from agno.tools.code.naming import safe_param_name

    assert safe_param_name("start-date", taken={"start_date"}) == "start_date_2"
    assert safe_param_name("start.date", taken={"start_date", "start_date_2"}) == "start_date_3"


def _raw_schema_function(name, properties, required):
    """A Function carrying a hand-written schema, as an MCP tool does."""

    def _entrypoint(**kwargs):
        return kwargs

    return Function(
        name=name,
        description=f"{name} description.",
        parameters={"type": "object", "properties": properties, "required": required},
        entrypoint=_entrypoint,
        skip_entrypoint_processing=True,
    )


def test_params_from_schema_puts_required_parameters_first():
    from agno.tools.code.bridge import _params_from_schema

    function = _raw_schema_function("search", {"limit": {"type": "integer"}, "query": {"type": "string"}}, ["query"])
    params = _params_from_schema(function)
    assert [p["name"] for p in params] == ["query", "limit"]
    assert [p["required"] for p in params] == [True, False]


def test_params_from_schema_maps_unusable_names_and_keeps_the_wire_name():
    from agno.tools.code.bridge import _params_from_schema

    function = _raw_schema_function("fetch", {"from": {"type": "string"}, "start-date": {"type": "string"}}, ["from"])
    params = _params_from_schema(function)
    assert [(p["name"], p["wire"], p["required"]) for p in params] == [
        ("from_", "from", True),
        ("start_date", "start-date", False),
    ]
    # The schema details ride along for the docstring.
    assert params[0]["type"] == "string"


def test_stub_doc_records_the_renamed_parameters():
    from agno.tools.code.bridge import _params_from_schema, _stub_doc

    function = _raw_schema_function("fetch", {"from": {"type": "string"}}, ["from"])
    doc = _stub_doc(function, _params_from_schema(function))
    assert "fetch description." in doc
    assert "from_ for 'from'" in doc


# ------------------------------------------------------------------
# Approval sentinel on a bridged callable
# ------------------------------------------------------------------


def test_approval_sentinel_on_a_bare_callable_reaches_the_bridged_function():
    from agno.approval import approval
    from agno.tools.code.bridge import ToolBridge

    @approval(type="required")
    def wire_money(amount: int) -> str:
        """Wire money.

        Args:
            amount: How much to wire.
        """
        return f"sent {amount}"

    bridge = ToolBridge([wire_money])
    bridge._ensure_built()
    function = bridge._registry[("", "wire_money")]
    assert function.approval_type == "required"
    assert function.requires_confirmation is True


# ------------------------------------------------------------------
# Injected toolkits are connected and closed with the run
# ------------------------------------------------------------------


class ConnectProbeTools(Toolkit):
    """A toolkit that manages its own connection, as a database toolkit does."""

    _requires_connect = True

    def __init__(self, **kwargs):
        self.connects = 0
        self.closes = 0
        super().__init__(name="probe_tools", tools=[self.ping], **kwargs)

    def connect(self) -> None:
        self.connects += 1

    def close(self) -> None:
        self.closes += 1

    def ping(self) -> str:
        """Return pong."""
        return "pong"


def test_connect_and_close_reach_the_injected_toolkits():
    probe = ConnectProbeTools()
    code_mode = CodeMode(tools=[probe], snapshot=False)
    code_mode.connect()
    assert probe.connects == 1
    assert probe.closes == 0
    code_mode.close()
    assert probe.closes == 1
    # The next run connects again.
    code_mode.connect()
    assert probe.connects == 2


def test_a_second_run_keeps_the_toolkits_open_until_it_ends():
    # One CodeMode serves every session, so the first run to end must not
    # disconnect a toolkit the other run's cell is still calling.
    probe = ConnectProbeTools()
    code_mode = CodeMode(tools=[probe], snapshot=False)
    code_mode.connect()
    code_mode.connect()
    assert probe.connects == 1, "an open toolkit was reconnected"
    code_mode.close()
    assert probe.closes == 0, "the toolkit was closed under the run still holding it"
    code_mode.close()
    assert probe.closes == 1


async def test_aconnect_and_aclose_reach_the_injected_toolkits():
    probe = ConnectProbeTools()
    code_mode = CodeMode(tools=[probe], snapshot=False)
    await code_mode.aconnect()
    assert probe.connects == 1
    await code_mode.aclose()
    assert probe.closes == 1


def test_close_of_an_unconnected_toolkit_is_not_attempted():
    probe = ConnectProbeTools()
    code_mode = CodeMode(tools=[probe], snapshot=False)
    code_mode.close()
    assert probe.closes == 0


async def test_cancel_pending_answers_with_the_call_id_the_kernel_waits_on():
    import asyncio

    from agno.tools.code.bridge import ToolBridge

    blocked = asyncio.Event()

    async def wait_for_the_test() -> str:
        """Block until the test cancels the call."""
        await blocked.wait()
        return "never"

    session = _FakeSession()
    bridge = ToolBridge([wait_for_the_test])
    bridge._on_comm(
        session,
        {
            "msg_type": "comm_msg",
            "content": {
                "comm_id": "comm-1",
                "data": {"id": "7", "handle": "", "method": "wait_for_the_test", "kwargs": {}},
            },
        },
    )
    await asyncio.sleep(0)
    serving = list(bridge._pending.values())
    await bridge.cancel_pending(session, "the cell was interrupted")
    # The kernel pops its pending entry by the call id, so an abort addressed
    # to anything else — the kernel generation, say — reaches no one.
    abort = session.kc.control_channel.sent[0]["content"]["data"]
    assert abort["id"] == "7"
    assert abort["ok"] is False
    assert "aborted" in abort["error"]["message"]
    blocked.set()
    await asyncio.gather(*serving, return_exceptions=True)


async def test_an_async_pre_hook_on_a_sync_tool_is_awaited():
    from agno.tools.code.bridge import ToolBridge

    gated = []

    async def gate(fc) -> None:
        gated.append(fc.function.name)

    def stamp(value: str) -> str:
        """Stamp a value.

        Args:
            value: What to stamp.
        """
        return "stamped:" + value

    function = Function.from_callable(stamp)
    function.pre_hook = gate
    session = _FakeSession()
    bridge = ToolBridge([function])
    await _bridge_call(bridge, session, "stamp", value="v")
    reply = session.kc.control_channel.sent[0]["content"]["data"]
    assert reply["value"] == "stamped:v"
    assert gated == ["stamp"], "an async pre_hook was called and its coroutine dropped"


def test_a_toolkit_named_mcptools_is_treated_as_connectable():
    from agno.tools.code.bridge import ToolBridge

    class MCPTools(Toolkit):
        """agno identifies MCPTools by class name; it sets no _requires_connect."""

        def __init__(self):
            super().__init__(name="mcp_tools", tools=[])

        async def connect(self) -> None:
            pass

    mcp = MCPTools()
    assert mcp.requires_connect is False
    bridge = ToolBridge([mcp])
    assert bridge._connectable == [mcp]


def test_a_tool_name_python_cannot_use_binds_under_one_it_can():
    from agno.tools.code.bridge import ToolBridge

    def _entrypoint(**kwargs):
        return kwargs

    dashed = Function(
        name="get-forecast",
        description="Forecast.",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        entrypoint=_entrypoint,
        skip_entrypoint_processing=True,
    )
    bridge = ToolBridge([dashed])
    bridge._ensure_built()
    assert [entry["name"] for entry in bridge._spec["functions"]] == ["get_forecast"]
    assert ("", "get_forecast") in bridge._registry
    # The wire name the tool is dispatched under is unchanged.
    assert bridge._registry[("", "get_forecast")].name == "get-forecast"
    assert "the tool's own name is 'get-forecast'" in bridge._spec["functions"][0]["doc"]
    assert handle_names_for([dashed]) == ["get_forecast"]


# ------------------------------------------------------------------
# Handle collisions bind under distinct names
# ------------------------------------------------------------------


def test_two_toolkits_reducing_to_one_handle_bind_under_distinct_names():
    def alpha() -> str:
        """Alpha."""
        return "alpha"

    def beta() -> str:
        """Beta."""
        return "beta"

    first = Toolkit(name="foo_tools", tools=[alpha])
    second = Toolkit(name="foo", tools=[beta])
    assert handle_names_for([first, second]) == ["foo", "foo_2"]

    from agno.tools.code.bridge import ToolBridge

    bridge = ToolBridge([first, second])
    assert bridge.handle_names == ["foo", "foo_2"]
    assert ("foo", "alpha") in bridge._registry
    assert ("foo_2", "beta") in bridge._registry


def test_a_toolkit_and_a_callable_share_one_kernel_namespace():
    def foo() -> str:
        """Foo."""
        return "foo"

    kit = Toolkit(name="foo_tools", tools=[])
    assert handle_names_for([kit, foo]) == ["foo", "foo_2"]


# ------------------------------------------------------------------
# The kernel launches exactly the interpreter it was given
# ------------------------------------------------------------------


def test_kernel_manager_launches_the_given_interpreter():
    session = KernelSession("spec-test", python="/opt/custom/python")
    km = session._make_kernel_manager()
    argv = km.format_kernel_cmd()
    assert argv[0] == "/opt/custom/python"
    assert argv[1:3] == ["-m", "ipykernel_launcher"]


def test_kernel_manager_never_consults_installed_kernelspecs(monkeypatch):
    session = KernelSession("spec-test-2")
    km = session._make_kernel_manager()

    def _boom(*args, **kwargs):
        raise AssertionError("an installed kernelspec was consulted")

    monkeypatch.setattr(km.kernel_spec_manager, "get_kernel_spec", _boom)
    assert km.format_kernel_cmd()[0] == session.python


def test_stderr_tail_keeps_only_the_last_bytes():
    import io

    from agno.tools.code.kernel import StderrTail

    tail = StderrTail(io.BytesIO(b"A" * 10_000 + b"the reason it died"), max_bytes=64)
    tail._thread.join(timeout=5)
    assert tail.tail().endswith("the reason it died")
    assert len(tail.tail()) <= 64
