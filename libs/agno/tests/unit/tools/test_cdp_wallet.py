from pathlib import Path

from agno.tools.cdp_wallet import CDPWalletTools


def test_cdp_wallet_defaults_to_installed_bundle(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/tester"))

    tools = CDPWalletTools()

    assert tools.name == "cdp_wallet_tools"
    assert tools.transport == "stdio"
    assert tools.tool_name_prefix == "cdp_wallet"
    assert tools.bundle_path == Path("/Users/tester/.payments-mcp/bundle.js")
    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args == ["/Users/tester/.payments-mcp/bundle.js"]


def test_cdp_wallet_accepts_bundle_path_override(tmp_path):
    bundle_path = tmp_path / "payments mcp" / "bundle.js"

    tools = CDPWalletTools(bundle_path=bundle_path, timeout_seconds=45)

    assert tools.timeout_seconds == 45
    assert tools.bundle_path == bundle_path
    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args == [str(bundle_path)]


def test_cdp_wallet_accepts_command_override():
    tools = CDPWalletTools(command="node /tmp/custom-payments-mcp.js", tool_name_prefix=None)

    assert tools.tool_name_prefix is None
    assert tools.server_params is not None
    assert tools.server_params.command == "node"
    assert tools.server_params.args == ["/tmp/custom-payments-mcp.js"]
