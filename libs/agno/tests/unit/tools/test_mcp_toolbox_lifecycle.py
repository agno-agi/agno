"""Lifecycle tests for MCPToolbox's core-client filter state.

MCPToolbox registers the full unfiltered tool set through the base MCP
connect, then filters it through toolbox-core -- and connect() early-returns
on _core_client_initialized. These tests pin that the flag can never outlive
the filtering it certifies: a failed filter must not latch it, and close()
must reset it, or a reconnect would skip filtering and serve (and let Studio
persist) the unfiltered superset.

toolbox_core is an optional dependency imported at module level, so the REAL
MCPToolbox class is exercised against a stub toolbox_core injected into
sys.modules; every code path under test (connect's early return, the filter
latch, teardown) is agno's own.
"""

import asyncio
import importlib
import sys
import types

import pytest

from agno.tools.function import Function


@pytest.fixture
def toolbox_env(monkeypatch):
    pytest.importorskip("mcp")

    created = []

    class StubToolboxClient:
        def __init__(self, url=None, client_headers=None):
            self.closed = False
            created.append(self)

        async def close(self):
            self.closed = True

    stub_module = types.ModuleType("toolbox_core")
    stub_module.ToolboxClient = StubToolboxClient  # type: ignore[attr-defined]

    previous_core = sys.modules.get("toolbox_core")
    previous_toolbox = sys.modules.get("agno.tools.mcp_toolbox")
    sys.modules["toolbox_core"] = stub_module
    sys.modules.pop("agno.tools.mcp_toolbox", None)
    module = importlib.import_module("agno.tools.mcp_toolbox")

    yield module, created

    sys.modules.pop("agno.tools.mcp_toolbox", None)
    if previous_toolbox is not None:
        sys.modules["agno.tools.mcp_toolbox"] = previous_toolbox
    if previous_core is not None:
        sys.modules["toolbox_core"] = previous_core
    else:
        sys.modules.pop("toolbox_core", None)


def _fake_base_connect(tool_names):
    """Stand in for MCPTools.connect: register the unfiltered superset the
    way the real base connect does, without any network."""

    async def fake_connect(self, force=False):
        for name in tool_names:
            self.functions[name] = Function(
                name=name,
                parameters={"type": "object", "properties": {}},
                skip_entrypoint_processing=True,
            )
        self._initialized = True

    return fake_connect


def _install_filter(monkeypatch, module, fail_first=False):
    """Replace the toolbox-core load with one that filters to allowed_tool,
    optionally failing on the first pass. Returns the call counter."""
    calls = {"count": 0}

    async def load_multiple_toolsets(self, toolset_names):
        calls["count"] += 1
        if fail_first and calls["count"] == 1:
            raise RuntimeError("transient filter failure")
        return [self.functions["allowed_tool"]]

    monkeypatch.setattr(module.MCPToolbox, "load_multiple_toolsets", load_multiple_toolsets)
    return calls


def test_failed_filter_does_not_latch_and_reconnect_refilters(toolbox_env, monkeypatch):
    module, created = toolbox_env
    from agno.tools.mcp import MCPTools

    monkeypatch.setattr(MCPTools, "connect", _fake_base_connect(["allowed_tool", "admin_tool"]))
    calls = _install_filter(monkeypatch, module, fail_first=True)
    toolbox = module.MCPToolbox(url="http://toolbox.local", toolsets=["allowed"])

    async def scenario():
        with pytest.raises(RuntimeError, match="ToolboxClient"):
            await toolbox.connect()
        # The failure must not certify filtering, and the failed pass's core
        # client must not leak.
        assert toolbox._core_client_initialized is False
        assert created and created[0].closed

        # Studio's on-demand release after a failed connect.
        await toolbox.close()
        toolbox.functions.clear()

        await toolbox.connect()

    asyncio.run(scenario())

    assert calls["count"] == 2  # the reconnect re-filtered
    assert list(toolbox.functions) == ["allowed_tool"]  # not the superset


def test_cancelled_filter_does_not_latch(toolbox_env, monkeypatch):
    """A hung filter cancelled from outside (Studio bounds each connect with
    wait_for) surfaces as CancelledError, which the toolbox's own error
    handling does not catch -- so no cleanup path runs. Only latching the flag
    AFTER a successful filter keeps a later reconnect from skipping filtering."""
    module, created = toolbox_env
    from agno.tools.mcp import MCPTools

    monkeypatch.setattr(MCPTools, "connect", _fake_base_connect(["allowed_tool", "admin_tool"]))

    async def load_multiple_toolsets(self, toolset_names):
        raise asyncio.CancelledError()

    monkeypatch.setattr(module.MCPToolbox, "load_multiple_toolsets", load_multiple_toolsets)
    toolbox = module.MCPToolbox(url="http://toolbox.local", toolsets=["allowed"])

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await toolbox.connect()

    asyncio.run(scenario())

    assert toolbox._core_client_initialized is False


def test_close_resets_filter_state_so_reconnect_refilters(toolbox_env, monkeypatch):
    module, created = toolbox_env
    from agno.tools.mcp import MCPTools

    monkeypatch.setattr(MCPTools, "connect", _fake_base_connect(["allowed_tool", "admin_tool"]))
    calls = _install_filter(monkeypatch, module)
    toolbox = module.MCPToolbox(url="http://toolbox.local", toolsets=["allowed"])

    async def scenario():
        await toolbox.connect()
        assert toolbox._core_client_initialized is True
        assert list(toolbox.functions) == ["allowed_tool"]

        await toolbox.close()
        assert toolbox._core_client_initialized is False
        assert created[0].closed
        toolbox.functions.clear()

        # The base connect re-registers the unfiltered superset; a latched
        # flag would early-return past filtering and keep it.
        await toolbox.connect()

    asyncio.run(scenario())

    assert calls["count"] == 2
    assert list(toolbox.functions) == ["allowed_tool"]
    assert len(created) == 2  # a fresh core client per filtering pass


def test_get_client_refuses_after_close(toolbox_env, monkeypatch):
    module, created = toolbox_env
    from agno.tools.mcp import MCPTools

    monkeypatch.setattr(MCPTools, "connect", _fake_base_connect(["allowed_tool"]))
    _install_filter(monkeypatch, module)
    toolbox = module.MCPToolbox(url="http://toolbox.local", toolsets=["allowed"])

    async def scenario():
        await toolbox.connect()
        assert toolbox.get_client() is created[0]
        await toolbox.close()

    asyncio.run(scenario())

    with pytest.raises(RuntimeError, match="not initialized"):
        toolbox.get_client()
