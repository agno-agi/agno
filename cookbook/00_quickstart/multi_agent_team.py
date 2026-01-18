"""
Multi-Agent Team - Investment Research Team
============================================
This example shows how to create a team of agents that work together.
Each agent has a specialized role, and the team leader coordinates.

We'll build an investment research team with opposing perspectives:
- Bull Agent: Makes the case FOR investing
- Bear Agent: Makes the case AGAINST investing
- Lead Analyst: Synthesizes into a balanced recommendation

This adversarial approach produces better analysis than a single agent.

Key concepts:
- Team: A group of agents coordinated by a leader
- Members: Specialized agents with distinct roles
- The leader delegates, synthesizes, and produces final output

Example prompts to try:
- "Should I invest in NVIDIA?"
- "Analyze Tesla as a long-term investment"
- "Is Apple overvalued right now?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools

# ============================================================================
# Storage Configuration
# ============================================================================
team_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Bull Agent — Makes the Case FOR
# ============================================================================
bull_agent = Agent(
    name="Bull Analyst",
    role="Make the investment case FOR a stock",
    model=Gemini(id="gemini-3-flash-preview"),
    tools=[YFinanceTools()],
    db=team_db,
    instructions="""\
You are a bull analyst. Your job is to make the strongest possible case
FOR investing in a stock. Find the positives:
- Growth drivers and catalysts
- Competitive advantages
- Strong financials and metrics
- Market opportunities

Be persuasive but grounded in data. Use the tools to get real numbers.\
""",
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)

# ============================================================================
# Bear Agent — Makes the Case AGAINST
# ============================================================================
bear_agent = Agent(
    name="Bear Analyst",
    role="Make the investment case AGAINST a stock",
    model=Gemini(id="gemini-3-flash-preview"),
    tools=[YFinanceTools()],
    db=team_db,
    instructions="""\
You are a bear analyst. Your job is to make the strongest possible case
AGAINST investing in a stock. Find the risks:
- Valuation concerns
- Competitive threats
- Weak spots in financials
- Market or macro risks

Be critical but fair. Use the tools to get real numbers to support your concerns.\
""",
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)

# ============================================================================
# Team Leader — Synthesizes Both Views
# ============================================================================
multi_agent_team = Team(
    name="Multi-Agent Team",
    model=Gemini(id="gemini-3-flash-preview"),
    members=[bull_agent, bear_agent],
    instructions="""\
You lead an investment research team with a Bull Analyst and Bear Analyst.

## Process

1. Send the stock to BOTH analysts
2. Let each make their case independently
3. Synthesize their arguments into a balanced recommendation

## Output Format

After hearing from both analysts, provide:
- **Bull Case Summary**: Key points from the bull analyst
- **Bear Case Summary**: Key points from the bear analyst
- **Synthesis**: Where do they agree? Where do they disagree?
- **Recommendation**: Your balanced view (Buy/Hold/Sell) with confidence level
- **Key Metrics**: A table of the important numbers

Be decisive but acknowledge uncertainty.\
""",
    db=team_db,
    show_members_responses=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Team
# ============================================================================
if __name__ == "__main__":
    # First analysis
    multi_agent_team.print_response(
        "Should I invest in NVIDIA (NVDA)?",
        stream=True,
    )

    # Follow-up question — team remembers the previous analysis
    multi_agent_team.print_response(
        "How does AMD compare to that?",
        stream=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
When to use Teams vs single Agent:

Single Agent:
- One coherent task
- No need for opposing views
- Simpler is better

Team:
- Multiple perspectives needed
- Specialized expertise
- Complex tasks that benefit from division of labor
- Adversarial reasoning (like this example)

Other team patterns:

1. Research → Analysis → Writing pipeline
   researcher = Agent(role="Gather information")
   analyst = Agent(role="Analyze data")
   writer = Agent(role="Write report")

2. Checker pattern
   worker = Agent(role="Do the task")
   checker = Agent(role="Verify the work")

3. Specialist routing
   classifier = Agent(role="Route to specialist")
   specialists = [finance_agent, legal_agent, tech_agent]
"""
