from agno.tools.cdp import CDPWalletTools
from agno.tools.mcp.mcp import MCPTools


def test_cdp_wallet_tools_is_mcp_tools_subclass():
    assert issubclass(CDPWalletTools, MCPTools)


def test_cdp_wallet_tools_default_command():
    tools = CDPWalletTools()

    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args is not None
    assert tools.server_params.args[0].endswith(".payments-mcp/bundle.js")
    assert tools.timeout_seconds == 60
    assert tools.tool_name_prefix == "cdp_wallet"


def test_cdp_wallet_tools_custom_bundle_path():
    tools = CDPWalletTools(bundle_path="/tmp/payments/bundle.js")

    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args == ["/tmp/payments/bundle.js"]


def test_cdp_wallet_tools_custom_command():
    tools = CDPWalletTools(command="node /tmp/custom-bundle.js")

    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args == ["/tmp/custom-bundle.js"]


def test_cdp_wallet_tools_passes_filters_and_timeout():
    tools = CDPWalletTools(
        timeout_seconds=30,
        include_tools=["pay"],
        exclude_tools=["get_balance"],
        tool_name_prefix=None,
    )

    assert tools.timeout_seconds == 30
    assert tools.include_tools == ["pay"]
    assert tools.exclude_tools == ["get_balance"]
    assert tools.tool_name_prefix is None
