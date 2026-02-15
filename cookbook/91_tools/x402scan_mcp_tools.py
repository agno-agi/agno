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

Skills: https://github.com/merit-systems/x402scan-skills
"""

import asyncio
from inspect import iscoroutinefunction
from pathlib import Path
from typing import Any, Callable, Dict, List

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.skills import LocalSkills, Skills
from agno.team import Team
from agno.db.json import JsonDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
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
    - Wallet auto-generated at ~/.x402scan-mcp/wallet.json (unique per user)
    - Balance will be $0
    - Agent shows your unique deposit address + deposit link
    - Each user gets a different address
    
    To fund: Send USDC on Base to the address shown.
    To use existing wallet: Set X402_PRIVATE_KEY environment variable.
    """
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-opus-4-6"),
            tools=[x402],
            instructions="""You help users get started with x402scan-mcp.
            
            Steps:
            1. Check wallet balance with get_wallet_info
            2. Show the unique deposit address (each user gets a different one)
            3. Show the deposit link: https://x402scan.com/mcp/deposit/{address}
            4. Explain: Send USDC on Base network to this address
            5. Discover available paid APIs with discover_api_endpoints
            
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
            model=Claude(id="claude-opus-4-6"),
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
            model=Claude(id="claude-opus-4-6"),
            tools=[x402],
            name="Researcher",
            role="Data Researcher",
            instructions="""Gather data from paid APIs.
            - Check balance before spending
            - Stay under $2 per task
            - Document all sources and costs""",
        )
        
        analyst = Agent(
            model=Claude(id="claude-opus-4-6"),
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
            model=Claude(id="claude-opus-4-6"),
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
            model=Claude(id="claude-opus-4-6"),
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


# Example 6: Agent with x402 skills
async def skills_example() -> None:
    """
    Load x402 skills for structured API guidance.
    
    Skills provide:
    - Pre-built workflows for common tasks
    - Endpoint discovery and documentation
    - Pricing guidance and cost optimization
    - Best practices for each API provider
    
    Setup:
        git clone https://github.com/merit-systems/x402scan-skills ~/x402scan-skills
    
    Then pass skills directory to agent.
    """
    # Check if skills directory exists
    skills_dir = Path.home() / "x402scan-skills" / "skills"
    if not skills_dir.exists():
        print(f"⚠️  Skills not found at {skills_dir}")
        print("Install: git clone https://github.com/merit-systems/x402scan-skills ~/x402scan-skills")
        return
    
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-opus-4-6"),
            tools=[x402],
            skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
            instructions="""You are a research agent with access to x402 skills.
            
            Available skills provide guidance for:
            - data-enrichment: Person/company profiles (Apollo, Clado)
            - web-research: Web scraping and semantic search (Exa, Firecrawl)
            - local-search: Google Maps places and businesses
            - social-intelligence: X/Twitter and Reddit data (Grok)
            - media-generation: AI image/video generation (StableStudio)
            - news-shopping: Google News and Shopping (Serper)
            - people-property: People and property search (Whitepages)
            - wallet: Balance, deposits, and wallet management
            
            Follow skill workflows for optimal results and cost efficiency.""",
            markdown=True,
        )
        
        await agent.aprint_response(
            "Find the CEO of Anthropic and enrich their profile with recent activity. Use the data-enrichment skill.",
            stream=True,
        )




# Example 7: Learning Machine - agent learns cost optimization
async def learning_example() -> None:
    """
    Agent that learns from experience and optimizes spending over time.
    
    Learning Machine tracks:
    - User preferences (data quality vs cost)
    - Provider performance (which APIs work best for what)
    - Historical decisions (what worked, what didn't)
    - Cost patterns (optimize future spending based on past success)
    
    After a few sessions, agent gets smarter about how it spends your money.
    Storage: JSON files in ~/.x402_learning/ (no database server needed)
    """
    from pathlib import Path
    
    # Create filesystem-based storage
    learning_db_path = Path.home() / ".x402_learning"
    learning_db_path.mkdir(exist_ok=True)
    
    db = JsonDb(db_path=str(learning_db_path))
    
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-opus-4-5"),
            tools=[x402],
            db=db,
            learning=LearningMachine(
                user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC)
            ),
            instructions="""Research agent with learning capabilities.
            
            Learn from experience and store observations:
            - Which APIs provide better data quality
            - Which providers are more cost-effective
            - User preferences (speed vs quality vs cost)
            - What worked well in past tasks
            
            Use memory to optimize spending:
            "Last time Apollo had better CEO data than Clado, so using Apollo again"
            "User prefers quality over cost, so choosing premium endpoints"
            "Exa semantic search was more accurate than Firecrawl for company research"
            
            Store learnings with update_user_memory tool.""",
            markdown=True,
        )
        
        # Session 1: Agent learns preferences
        print("\n" + "="*60)
        print("SESSION 1: Agent learns your preferences")
        print("="*60 + "\n")
        
        await agent.aprint_response(
            "Research 3 AI infrastructure companies. "
            "I care more about data quality than cost. "
            "Use whatever sources give the best information.",
            user_id="user@company.com",
            session_id="research_1",
            stream=True,
        )
        
        # Show stored memories
        if agent.learning_machine and agent.learning_machine.user_memory_store:
            print("\n" + "="*60)
            print("WHAT AGENT LEARNED (Session 1)")
            print("="*60)
            agent.learning_machine.user_memory_store.print(user_id="user@company.com")
        
        # Session 2: Agent applies learned preferences
        print("\n" + "="*60)
        print("SESSION 2: Agent remembers and optimizes")
        print("="*60 + "\n")
        
        await agent.aprint_response(
            "Research 3 more companies in the same space.",
            user_id="user@company.com",
            session_id="research_2",
            stream=True,
        )
        
        # Show updated memories
        if agent.learning_machine and agent.learning_machine.user_memory_store:
            print("\n" + "="*60)
            print("WHAT AGENT LEARNED (Session 2)")
            print("="*60)
            agent.learning_machine.user_memory_store.print(user_id="user@company.com")
        
        print("\n" + "="*60)
        print(f"Memories stored at: {learning_db_path}")
        print("Agent will remember these preferences in future sessions.")
        print("="*60 + "\n")


# Example 8: Production-ready with cost controls
async def production_example() -> None:
    """
    Production-ready agent with real cost controls and error handling.
    
    Features:
    - Hard spending limits (rejects requests over limit)
    - Graceful error handling
    - Transaction logging
    - Balance checks before operations
    - Session cost reporting
    """
    
    class CostController:
        def __init__(self, max_spend: float = 5.0):
            self.max_spend = max_spend
            self.total_spent = 0.0
            self.transactions = []
        
        def can_spend(self, estimated_cost: float) -> bool:
            return (self.total_spent + estimated_cost) <= self.max_spend
        
        def record_transaction(self, url: str, cost: float, success: bool):
            self.transactions.append({
                "url": url,
                "cost": cost,
                "success": success,
            })
            if success:
                self.total_spent += cost
        
        def get_report(self) -> str:
            successful = [t for t in self.transactions if t["success"]]
            failed = [t for t in self.transactions if not t["success"]]
            return f"""Cost Report:
- Total Spent: ${self.total_spent:.2f} / ${self.max_spend:.2f}
- Successful Transactions: {len(successful)}
- Failed Transactions: {len(failed)}
- Remaining Budget: ${self.max_spend - self.total_spent:.2f}"""
    
    cost_controller = CostController(max_spend=5.0)
    
    async def production_hook(
        function_name: str, function_call: Callable, arguments: Dict[str, Any]
    ) -> Any:
        if function_name == "fetch":
            url = arguments.get("url", "")
            estimated_cost = 0.05
            
            # Hard limit enforcement
            if not cost_controller.can_spend(estimated_cost):
                logger.error(f"Budget exceeded. Cannot make request to {url}")
                return {
                    "error": "Budget limit reached",
                    "spent": cost_controller.total_spent,
                    "limit": cost_controller.max_spend
                }
            
            # Execute with error handling
            try:
                if iscoroutinefunction(function_call):
                    result = await function_call(**arguments)
                else:
                    result = function_call(**arguments)
                
                actual_cost = result.get("cost", estimated_cost) if isinstance(result, dict) else estimated_cost
                cost_controller.record_transaction(url, actual_cost, True)
                logger.info(f"✓ {url}: ${actual_cost:.4f}")
                return result
            
            except Exception as e:
                logger.error(f"✗ {url}: {str(e)}")
                cost_controller.record_transaction(url, 0, False)
                return {"error": str(e)}
        
        # Non-fetch calls pass through
        if iscoroutinefunction(function_call):
            return await function_call(**arguments)
        return function_call(**arguments)
    
    async with MCPTools("npx -y @x402scan/mcp@latest") as x402:
        agent = Agent(
            model=Claude(id="claude-opus-4-6"),
            tools=[x402],
            tool_hooks=[production_hook],
            instructions="""Production research agent with strict cost controls.
            
            Rules:
            - $5.00 hard limit per session
            - Check balance before starting
            - Use free sources first, paid only when necessary
            - Always provide sources for paid data
            - Gracefully handle errors
            
            If budget is exhausted, stop and report findings so far.""",
            markdown=True,
        )
        
        print("\n" + "="*60)
        print("PRODUCTION AGENT SESSION")
        print("="*60)
        
        await agent.aprint_response(
            "Research the top 3 companies in AI infrastructure. "
            "Find funding, key people, and recent news. "
            "Optimize for cost - use paid APIs only for critical data.",
            stream=True,
        )
        
        print("\n" + "="*60)
        print(cost_controller.get_report())
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
    # asyncio.run(skills_example())  # Load x402 skills for structured workflows
    # asyncio.run(learning_example())  # Learning Machine - agent optimizes spending over time
    # asyncio.run(production_example())  # Production-ready with hard cost limits
