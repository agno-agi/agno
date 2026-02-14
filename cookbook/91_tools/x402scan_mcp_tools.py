"""
x402scan MCP Tools - Give Your Agent Money
=============================

Enables agents to autonomously pay for API calls using USDC on Base.
Unlocks access to 100+ premium data sources: enrichment, scraping, search, and media generation.

Installation: `npx @x402scan/mcp install`
Documentation: https://x402scan.com/mcp

Getting Started:
1. Run the onboarding example (wallet auto-generated, balance will be $0)
2. Agent shows your deposit address
3. Fund wallet with USDC on Base
4. Run research/team examples to access paid APIs

Configuration:
- Wallet location: ~/.x402scan-mcp/wallet.json (auto-generated)
- Environment variable: X402_PRIVATE_KEY (optional, use existing wallet)
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: First run - onboarding and setup
async def onboarding_example() -> None:
    """
    First-time setup: Check balance, get deposit address, and discover APIs.
    
    On first run:
    - Wallet auto-generated at ~/.x402scan-mcp/wallet.json
    - Balance will be $0
    - Agent shows you how to fund it
    
    To use an existing wallet, set X402_PRIVATE_KEY environment variable.
    """
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            instructions="""You help users get started with x402scan-mcp.
            
            Steps:
            1. Check wallet balance with get_wallet_info
            2. Show the deposit address (users can fund with USDC on Base)
            3. Discover available paid APIs with discover_api_endpoints
            
            Be helpful and encouraging - this is their first time.""",
            markdown=True,
        )
        
        await agent.aprint_response(
            "I just installed x402scan-mcp. Show me my wallet info and how to get started.",
            stream=True,
        )


# Example 2: Research agent with spending limits
async def research_agent() -> None:
    """Agent that can autonomously access premium data sources."""
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            name="ResearchAgent",
            instructions="""You are a research agent with paid API access.
            
            Capabilities:
            - Search the web for free (general knowledge)
            - Access premium data APIs for detailed research
            - Keep spending under $5 per task
            
            Workflow:
            1. Start with free research
            2. Identify gaps requiring paid data
            3. Check wallet balance
            4. Use paid APIs strategically
            5. Provide sources for all paid data
            
            Note: Spending limits are guidance only. Track spending yourself.""",
            markdown=True,
        )
        
        await agent.aprint_response(
            "Research the top 3 AI agent frameworks by GitHub stars and recent funding",
            stream=True,
        )


# Example 3: Multi-agent team sharing a wallet
async def team_example() -> None:
    """Team of agents sharing a wallet for research and analysis."""
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        researcher = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            name="Researcher",
            role="Data Researcher",
            instructions="""Gather data from paid APIs.
            - Check balance before spending
            - Stay under $2 per task
            - Document all sources and costs""",
        )
        
        analyst = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            name="Analyst",
            role="Data Analyst",
            instructions="""Analyze data from the researcher.
            - Identify patterns and insights
            - Create summaries and recommendations
            - You cannot access paid APIs directly""",
        )
        
        team = Team(
            members=[researcher, analyst],
            instructions="""Collaborate to produce research reports.
            Researcher: gather data from paid sources
            Analyst: synthesize findings into insights""",
        )
        
        await team.aprint_response(
            "Research VC funding trends in AI agents over the past 6 months",
            stream=True,
        )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start here: Onboarding example shows how to get started
    asyncio.run(onboarding_example())
    
    # After funding, try these:
    # asyncio.run(research_agent())
    # asyncio.run(team_example())
