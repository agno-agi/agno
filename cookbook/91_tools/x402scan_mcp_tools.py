"""
x402scan MCP Tools
==================
Give your agent money. Agents pay for APIs autonomously using USDC on Base.
Access 100+ paid data sources: enrichment, scraping, maps, social media, media generation.

Installation: npx @x402scan/mcp install
Documentation: https://x402scan.com/mcp

First run auto-generates a wallet at ~/.x402scan-mcp/wallet.json.
Fund with USDC on Base to start using paid APIs.
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
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


async def run_team(message: str) -> None:
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        researcher = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            name="Researcher",
            role="Data Researcher",
            instructions=(
                "Gather data from paid APIs.\n"
                "Check balance before spending.\n"
                "Stay under $2 per task."
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
    asyncio.run(run_agent("Show me my wallet info and available APIs"))

    # People enrichment (Apollo)
    # asyncio.run(run_agent("Find information about the CEO of Anthropic"))

    # Web scraping (Firecrawl)
    # asyncio.run(run_agent("Scrape the content of https://docs.agno.com/introduction"))

    # Search (Exa)
    # asyncio.run(run_agent("Search for recent AI agent framework comparisons"))

    # Google Maps
    # asyncio.run(run_agent("Find coffee shops near Times Square, New York"))

    # Social media (Grok/Twitter)
    # asyncio.run(run_agent("Search Twitter for recent posts about AI agents"))

    # Multi-agent team: researcher + analyst sharing a wallet
    # asyncio.run(run_team("Research VC funding trends in AI agents over the past 6 months"))
