import inspect

from agno.tools.mcp_toolbox import MCPToolbox


def test_mcp_toolbox_auth_params_defaults_are_none():
    """Regression test for mutable default arguments (B006).

    The auth/dict parameters on MCPToolbox auth helpers must default to None,
    not a shared mutable ``{}`` instance, so calls do not leak state between
    each other (including a latent credentials-leakage path on auth_token_getters).
    """
    handle_default = inspect.signature(MCPToolbox._handle_auth_params).parameters["auth_token_getters"].default
    assert handle_default is None

    for fn_name in ("load_tool", "load_toolset", "load_multiple_toolsets"):
        sig = inspect.signature(getattr(MCPToolbox, fn_name))
        assert sig.parameters["auth_token_getters"].default is None
        assert sig.parameters["bound_params"].default is None


def test_handle_auth_params_without_args_returns_none():
    """Calling _handle_auth_params with no args must return None, not a shared dict."""
    assert MCPToolbox._handle_auth_params(None) is None
