import shlex
from pathlib import Path
from typing import Optional, Union

from agno.tools.mcp import MCPTools


class CDPWalletTools(MCPTools):
    """Connect Agno agents to Coinbase Agentic Wallet MCP."""

    def __init__(
        self,
        bundle_path: Optional[Union[str, Path]] = None,
        command: Optional[str] = None,
        timeout_seconds: int = 30,
        tool_name_prefix: Optional[str] = "cdp_wallet",
        **kwargs,
    ):
        """Initialize the Coinbase Agentic Wallet MCP toolkit.

        Args:
            bundle_path: Path to the installed payments-mcp bundle. Defaults to
                ~/.payments-mcp/bundle.js after running `npx @coinbase/payments-mcp`.
            command: Full stdio command to run. Overrides bundle_path when set.
            timeout_seconds: Read timeout for MCP calls.
            tool_name_prefix: Prefix applied to exposed MCP tool names.
            **kwargs: Additional MCPTools arguments such as include_tools, exclude_tools, or env.
        """
        self.bundle_path = Path(bundle_path).expanduser() if bundle_path is not None else self.default_bundle_path()

        super().__init__(
            command=command or f"node {shlex.quote(str(self.bundle_path))}",
            transport="stdio",
            timeout_seconds=timeout_seconds,
            tool_name_prefix=tool_name_prefix,
            **kwargs,
        )
        self.name = "cdp_wallet_tools"

    @staticmethod
    def default_bundle_path() -> Path:
        """Return the default local bundle path created by the Coinbase installer."""
        return Path.home() / ".payments-mcp" / "bundle.js"
