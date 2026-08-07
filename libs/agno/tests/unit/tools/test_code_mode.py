"""Unit tests for CodeMode that need no kernel.

Kernel-backed behavior lives in tests/integration/tools/test_code_mode_kernel.py.
"""

import pytest

from agno.tools import Function, Toolkit
from agno.tools.code_mode import CellResult, CodeMode, CodeModeError, KernelBusyError, ResultTooLarge
from agno.tools.code_mode.code_mode import build_instructions, derive_handle_name, handle_names_for
from agno.tools.code_mode.kernel import OutputAccumulator

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
        "outputs stay available in every later turn. Attached tools are awaitable calls in this "
        "environment: arcade, file_system. Tool calls are await expressions, so their return "
        "values can be bound to variables and composed into program logic like any other call. "
        "Do not invent wrappers such as call_tool(...); call the documented function, and use "
        "help(...) on a handle to inspect it."
        "\n\n"
        "This environment is your control environment, not the runtime of the thing you are "
        "investigating. A repository, service, dataset, or benchmark has its own environment and "
        "its own interface. Evaluate it through that interface and use this environment to "
        "coordinate and analyze what comes back. Do not install dependencies here to force an "
        "external project to import. Treat failures from the project's own environment as the "
        "relevant result."
        "\n\n"
        "Each %%bash cell is a throw-away subshell, so cd, export, and shell variables do not "
        "carry over. Keep dependent shell steps in one cell, or use %cd and os.environ[...], "
        "which are kernel-level and apply to every later %%bash cell."
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


def test_accumulator_caps_at_accumulation_and_appends_marker():
    acc = OutputAccumulator(10)
    acc.add("0123456789ABCDEF")
    assert acc.truncated
    assert acc.render() == "0123456789\n[... output truncated at 10 chars ...]"


def test_accumulator_drops_chunks_after_cap_without_growing():
    acc = OutputAccumulator(5)
    for _ in range(1000):
        acc.add("xxxxxxxxxx")
    # Bounded at the cap: the internal buffer never exceeds max_chars.
    assert sum(len(p) for p in acc._parts) == 5
    assert acc.render() == "xxxxx\n[... output truncated at 5 chars ...]"


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
    for name in ("execute", "restart", "run", "variables", "value", "shutdown"):
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

    saved = {k: v for k, v in sys.modules.items() if k.startswith("agno.tools.code_mode")}
    for k in saved:
        monkeypatch.delitem(sys.modules, k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="agno\\[code-mode\\]"):
        importlib.import_module("agno.tools.code_mode")
    monkeypatch.setattr(builtins, "__import__", real_import)
    sys.modules.update(saved)


# ------------------------------------------------------------------
# Failed-binding stub (kernel-side class, pinned host-side via exec)
# ------------------------------------------------------------------


def test_failed_binding_stub_raises_runtime_error_never_name_error():
    from agno.tools.code_mode.bridge import FAILED_BINDING_CLASS

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
    from agno.tools.code_mode.bridge import FAILED_BINDING_CLASS

    namespace = {}
    exec(FAILED_BINDING_CLASS, namespace)
    stub = namespace["_AgnoFailedBinding"]("t", "boom")
    for attr in ("anything", "at", "all"):
        with pytest.raises(RuntimeError):
            getattr(stub, attr)()


# ------------------------------------------------------------------
# Snapshot budget accounting (host-side, pure)
# ------------------------------------------------------------------


def test_budget_keeps_small_variables_and_cuts_the_oversized_one():
    from agno.tools.code_mode.snapshot import apply_snapshot_budget

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
    from agno.tools.code_mode.snapshot import apply_snapshot_budget

    entries = [{"name": "a", "bytes": 600, "data": ""}, {"name": "b", "bytes": 400, "data": ""}]
    kept, cut = apply_snapshot_budget(entries, max_snapshot_bytes=1_000)
    assert len(kept) == 2
    assert cut == []


def test_budget_orders_smallest_first_so_largest_is_cut():
    from agno.tools.code_mode.snapshot import apply_snapshot_budget

    entries = [{"name": "big", "bytes": 900, "data": ""}, {"name": "small", "bytes": 200, "data": ""}]
    kept, cut = apply_snapshot_budget(entries, max_snapshot_bytes=1_000)
    assert [e["name"] for e in kept] == ["small"]
    assert [c["name"] for c in cut] == ["big"]


# ------------------------------------------------------------------
# Restored-notice rendering
# ------------------------------------------------------------------


def test_restored_notice_full_shape():
    from agno.tools.code_mode.snapshot import build_restored_notice

    notice = build_restored_notice(["frames", "world_model"], ["arcade_client", "sock"])
    assert notice == (
        "<code_mode_restored>\n"
        "Restored 2 variables: frames, world_model.\n"
        "Not restored (unpicklable): arcade_client, sock.\n"
        "</code_mode_restored>"
    )


def test_restored_notice_omits_unpicklable_line_when_empty():
    from agno.tools.code_mode.snapshot import build_restored_notice

    notice = build_restored_notice(["x"], [])
    assert "Not restored" not in notice
    assert "Restored 1 variables: x." in notice


def test_restored_notice_none_when_nothing_happened():
    from agno.tools.code_mode.snapshot import build_restored_notice

    assert build_restored_notice([], []) is None
