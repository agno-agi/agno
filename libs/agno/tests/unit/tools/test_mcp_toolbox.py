import importlib
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture
def mcp_toolbox_module(monkeypatch):
    """Import MCPToolbox with a lightweight toolbox_core stub."""
    toolbox_core = types.ModuleType("toolbox_core")
    toolbox_core.ToolboxClient = object
    monkeypatch.setitem(sys.modules, "toolbox_core", toolbox_core)

    import agno.tools.mcp_toolbox as mcp_toolbox

    return importlib.reload(mcp_toolbox)


def test_handle_auth_params_default_getters_are_not_shared(mcp_toolbox_module):
    toolbox = object.__new__(mcp_toolbox_module.MCPToolbox)

    first_getters = toolbox._handle_auth_params()
    first_getters["token"] = lambda: "first"
    second_getters = toolbox._handle_auth_params()

    assert second_getters == {}


@pytest.mark.asyncio
async def test_load_tool_default_dicts_are_not_shared(mcp_toolbox_module):
    class FakeCoreClient:
        def __init__(self):
            self.calls = []

        async def load_tool(self, name, auth_token_getters, bound_params):
            self.calls.append((dict(auth_token_getters), dict(bound_params), auth_token_getters, bound_params))
            auth_token_getters["token"] = lambda: "mutated"
            bound_params["limit"] = 10
            return SimpleNamespace(_name=name)

    toolbox = object.__new__(mcp_toolbox_module.MCPToolbox)
    toolbox.functions = {"search": object()}
    toolbox._MCPToolbox__core_client = FakeCoreClient()

    await toolbox.load_tool("search")
    await toolbox.load_tool("search")

    first_call, second_call = toolbox._MCPToolbox__core_client.calls
    assert first_call[:2] == ({}, {})
    assert second_call[:2] == ({}, {})
    assert first_call[2] is not second_call[2]
    assert first_call[3] is not second_call[3]


@pytest.mark.asyncio
async def test_load_toolset_default_dicts_are_not_shared(mcp_toolbox_module):
    class FakeCoreClient:
        def __init__(self):
            self.calls = []

        async def load_toolset(self, name, auth_token_getters, bound_params, strict):
            self.calls.append((dict(auth_token_getters), dict(bound_params), auth_token_getters, bound_params))
            auth_token_getters["token"] = lambda: "mutated"
            bound_params["limit"] = 10
            return [SimpleNamespace(_name="search")]

    toolbox = object.__new__(mcp_toolbox_module.MCPToolbox)
    toolbox.functions = {"search": object()}
    toolbox._MCPToolbox__core_client = FakeCoreClient()

    await toolbox.load_toolset("default")
    await toolbox.load_toolset("default")

    first_call, second_call = toolbox._MCPToolbox__core_client.calls
    assert first_call[:2] == ({}, {})
    assert second_call[:2] == ({}, {})
    assert first_call[2] is not second_call[2]
    assert first_call[3] is not second_call[3]
