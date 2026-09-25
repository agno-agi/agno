"""
Nano (XNO) x402 MCP Tools
=========================
Give your agent money. Agents pay for x402 APIs autonomously using Nano (XNO) —
feeless and sub-second, straight from a self-custodied local wallet.

The feeless402 MCP server exposes a self-custodied Nano wallet plus an x402 payment
client. The agent can quote any paid API, price it on every rail it offers, and pay
with Nano (XNO) at zero fee and sub-second finality.

Installation: pip install "feeless402[mcp]"
Documentation: https://feeless402.com/docs

First run auto-generates a wallet at ~/.nano-pay/wallet.json; a faucet claim can fund
it with free starter XNO (nano-pay claim --auto).
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    async with MCPTools("uvx feeless402[mcp] mcp") as nano:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[nano],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


async def run_team(message: str) -> None:
    async with MCPTools("uvx feeless402[mcp] mcp") as nano:
        researcher = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[nano],
            name="Researcher",
            role="Data Researcher",
            instructions=(
                "Quote paid APIs before spending any XNO.\n"
                "Keep every payment under the spend cap.\n"
                "Use the feeless Nano (XNO) rail when it is offered."
            ),
        )
        analyst = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            name="Analyst",
            role="Data Analyst",
            instructions="Analyze data from the researcher. Create summaries and recommendations.",
        )
        team = Team(
            members=[researcher, analyst],
            instructions="Researcher gathers paid data, Analyst synthesizes findings.",
        )
        await team.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Onboarding: wallet setup and API discovery
    asyncio.run(run_agent("Show me my Nano wallet performance and available APIs"))

    # Quote a paid API without spending (x402_quote)
    # asyncio.run(run_agent("Quote extracting data from https://example.com/api"))

    # Pay a paid API with Nano (x402_pay)
    # asyncio.run(run_agent("Pay for and call https://nano-gpt.com/api/v1/chat/completions"))

    # Multi-agent team: researcher + analyst sharing a Nano wallet
    # asyncio.run(run_team("Research AI agent framework pricing trends across paid APIs"))

    # Top up the wallet from another asset into XNO (topup_quote)
    # asyncio.run(run_agent("Quote swapping $5 USDC on Base into XNO"))
