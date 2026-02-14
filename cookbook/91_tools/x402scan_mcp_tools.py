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
from inspect import iscoroutinefunction
from typing import Any, Callable, Dict, List

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.mcp import MCPTools
from agno.utils.log import logger
from pydantic import BaseModel, Field

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


# Example 4: Tool hooks for spending tracking
async def spending_tracker_example() -> None:
    """
    Track spending with tool hooks.
    
    Tool hooks run before and after each tool call, enabling:
    - Real-time spending monitoring
    - Cost warnings before expensive operations
    - Transaction logging and auditing
    """
    
    total_spent = {"amount": 0.0}
    
    async def spending_hook(
        function_name: str, function_call: Callable, arguments: Dict[str, Any]
    ) -> Any:
        # Pre-hook: Log and warn before paid requests
        if function_name == "fetch":
            url = arguments.get("url", "unknown")
            logger.info(f"💰 Making paid request to: {url}")
            
            if total_spent["amount"] > 4.50:
                logger.warning(f"⚠️  Budget alert: ${total_spent['amount']:.2f} spent")
        
        # Execute the tool
        if iscoroutinefunction(function_call):
            result = await function_call(**arguments)
        else:
            result = function_call(**arguments)
        
        # Post-hook: Track transaction cost
        if function_name == "fetch" and isinstance(result, dict):
            cost = result.get("cost", 0)
            if cost:
                total_spent["amount"] += cost
                logger.info(f"✓ Transaction cost: ${cost:.4f} (Total: ${total_spent['amount']:.2f})")
        
        return result
    
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            tool_hooks=[spending_hook],
            instructions="""Research agent with spending tracking.
            
            Use paid APIs when needed but track all spending.
            Check balance before starting.""",
            markdown=True,
        )
        
        await agent.aprint_response(
            "Research top 5 AI companies and their recent funding rounds. Use paid APIs for accurate data.",
            stream=True,
        )
        
        print(f"\n{'='*60}")
        print(f"Total spent this session: ${total_spent['amount']:.2f}")
        print(f"{'='*60}\n")


# Example 5: Structured outputs with cost tracking
async def structured_research_example() -> None:
    """
    Research with structured outputs and cost tracking.
    
    Structured outputs ensure:
    - Type-safe results
    - Consistent schema
    - Easy parsing and storage
    - Cost attribution per source
    """
    
    class ResearchSource(BaseModel):
        provider: str = Field(description="API provider used")
        cost: float = Field(description="Cost in USD")
        data_quality: str = Field(description="Quality rating: high/medium/low")
    
    class ResearchReport(BaseModel):
        findings: List[str] = Field(description="Key findings from research")
        sources_used: List[ResearchSource] = Field(description="Paid sources consulted")
        total_cost: float = Field(description="Total cost in USD")
        recommendation: str = Field(description="Final recommendation")
    
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[x402],
            instructions="""You are a research agent that produces structured reports.
            
            For each paid API used, track:
            - Provider name (Apollo, Clado, Firecrawl, etc.)
            - Cost of the request
            - Data quality assessment
            
            Provide findings and a clear recommendation.""",
            markdown=True,
        )
        
        response = await agent.arun(
            "Research the CEO of Anthropic. What's their background and recent activities?",
            response_model=ResearchReport,
        )
        
        if response and response.content:
            report: ResearchReport = response.content
            print("\n" + "="*60)
            print("STRUCTURED RESEARCH REPORT")
            print("="*60)
            print(f"\nFindings ({len(report.findings)}):")
            for i, finding in enumerate(report.findings, 1):
                print(f"  {i}. {finding}")
            
            print(f"\nSources Used:")
            for source in report.sources_used:
                print(f"  • {source.provider}: ${source.cost:.4f} ({source.data_quality} quality)")
            
            print(f"\nTotal Cost: ${report.total_cost:.2f}")
            print(f"\nRecommendation:\n  {report.recommendation}")
            print("="*60 + "\n")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start here: Onboarding example shows how to get started
    asyncio.run(onboarding_example())
    
    # After funding, try these:
    # asyncio.run(research_agent())
    # asyncio.run(team_example())
    
    # Advanced: Agno-specific features
    # asyncio.run(spending_tracker_example())  # Tool hooks for cost tracking
    # asyncio.run(structured_research_example())  # Structured outputs with cost attribution
