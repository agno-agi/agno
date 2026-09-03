"""
Coinbase Agentic Wallet (CDP) Tools Example

Lets your agent autonomously discover and pay for x402-monetized HTTP APIs
in USDC, using a Coinbase-managed embedded wallet.

Setup:
1. Install Node.js 24+
2. Install dependencies:
       uv pip install agno mcp
3. Install the Coinbase MCP bundle:
       npx @coinbase/payments-mcp install --client other
4. First run will prompt for email and OTP sign-in via the Agentic Wallet companion window.

Docs: https://docs.cdp.coinbase.com/agentic-wallet/mcp/welcome
"""

import asyncio

from agno.agent import Agent
from agno.tools.cdp import CDPWalletTools


async def main():
    async with CDPWalletTools() as cdp:
        agent = Agent(tools=[cdp])
        await agent.aprint_response(
            "Search the x402 bazaar for a paid weather API, "
            "inspect the cheapest one, then pay and return today's forecast for San Francisco."
        )


if __name__ == "__main__":
    asyncio.run(main())
