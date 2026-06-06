"""
TWZRD Agent Intel MCP
=============================

Demonstrates how to use the TWZRD Agent Intel MCP server with Agno to verify
AI agent trust scores and x402 payment readiness on Solana before transacting.

TWZRD Agent Intel provides:
- resolve_agent / score_agent: Trust score for a Solana wallet
- preflight_check: Verify x402 payment readiness (free)
- verify_trust_receipt: Validate an x402 trust receipt (free)
- get_trust_receipt: Get a signed trust receipt (paid via x402)

MCP endpoint: https://intel.twzrd.xyz/mcp (streamable-http, zero-install)
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    async with MCPTools(
        transport="streamable-http", url="https://intel.twzrd.xyz/mcp"
    ) as twzrd_intel:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-0"),
            tools=[twzrd_intel],
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Check the trust score for Solana wallet 4LkEFjKNy7TGDV9V6wWw7MxTheBEe9AY3V5bCFPRi4Y2 "
            "and verify if it is x402-ready."
        )
    )
