"""Coinbase Agentic Wallet tools for autonomous x402 payments via MCP.

Wraps the local MCP bundle installed by `npx @coinbase/payments-mcp` so an
Agno agent can discover and pay for x402-monetized HTTP APIs in USDC with a
Coinbase-managed embedded wallet.
"""

from pathlib import Path
from typing import Optional

from agno.tools.mcp.mcp import MCPTools


class CDPWalletTools(MCPTools):
    """Coinbase Developer Platform Agentic Wallet MCP tools.

    Example:
        ```python
        from agno.agent import Agent
        from agno.tools.cdp import CDPWalletTools

        async with CDPWalletTools() as cdp:
            agent = Agent(tools=[cdp])
            await agent.aprint_response(
                "Find a paid weather API on the x402 bazaar and get the forecast for SF"
            )
        ```

    See https://docs.cdp.coinbase.com/agentic-wallet/mcp/welcome for the
    full tool catalog and supported chains.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = 60,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        **kwargs,
    ):
        bundle_path = Path.home() / ".payments-mcp" / "bundle.js"
        super().__init__(
            command=f'node "{bundle_path}"',
            timeout_seconds=timeout_seconds,
            include_tools=include_tools,
            exclude_tools=exclude_tools,
            **kwargs,
        )
