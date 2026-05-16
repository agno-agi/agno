"""
Coinbase Agentic Wallet MCP Tools
=================================
Connect an Agno agent to the installed Coinbase Agentic Wallet MCP bundle.

Install the MCP bundle once:
    npx @coinbase/payments-mcp

The installer creates ~/.payments-mcp/bundle.js. CDPWalletTools wraps that
installed bundle with Agno's MCPTools so agents can inspect wallet state,
discover x402 services, and pay for services within user-controlled wallet
limits.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.cdp_wallet import CDPWalletTools


async def run_agent(message: str) -> None:
    async with CDPWalletTools() as wallet:
        agent = Agent(
            model=OpenAIChat(id="gpt-5-mini"),
            tools=[wallet],
            markdown=True,
            instructions=[
                "Check wallet balance and spending limits before paid calls.",
                "Use x402 discovery before selecting a paid service.",
                "Do not exceed the wallet limits shown by the MCP tools.",
            ],
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Show me my wallet status and find x402 crypto data services under five cents."
        )
    )
