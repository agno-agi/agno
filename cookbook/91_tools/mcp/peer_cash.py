"""Peer Cash MCP Agent - Prepare custody-separated cash-outs

This example connects Agno to Peer Cash through its published MCP server. The
server discovers supported payout rails, reads live market-rate estimates,
prepares unsigned Base USDC cash-out transactions, and tracks existing orders.
It never accepts private keys, signs transactions, or broadcasts them.

Prerequisites:
- Node.js 22 or newer, including ``npx``
- ``uv pip install "agno[mcp]" openai``
- ``OPENAI_API_KEY`` in the environment

Peer Cash MCP: https://github.com/zkp2p/peer-cash-mcp
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from pydantic import BaseModel


class CashoutPlan(BaseModel):
    summary: str
    actions: list[str]
    signing_required: bool
    safety_note: str


async def run_agent(message: str) -> None:
    npx_command = "npx.cmd" if os.name == "nt" else "npx"

    async with MCPTools(
        command=f"{npx_command} -y peer-cash-mcp@0.1.2",
        timeout_seconds=60,
    ) as peer_cash:
        agent = Agent(
            name="Peer Cash Agent",
            model=OpenAIResponses(id="gpt-5.5"),
            tools=[peer_cash],
            output_schema=CashoutPlan,
            # Keep the final response structured without forcing OpenAI's strict
            # schema rules onto externally defined MCP tool schemas.
            use_json_mode=True,
            instructions=[
                "Use Peer Cash to help users move Base USDC to supported fiat payout rails.",
                "Read capabilities before assuming a platform, currency, amount, or payee format is supported.",
                "Treat estimates as approximate oracle readings, never locked quotes.",
                "For mutations, return the unsigned transaction plan for the user's wallet to inspect and sign.",
                "Never ask for a private key and never claim an unsigned transaction was submitted.",
                "After an externally signed create-deposit transaction confirms, finalize its receipt before reporting an order ID.",
            ],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Show the supported cash-out platforms and estimate the USD payout for 1000 Base USDC. Do not create an order."
        )
    )
