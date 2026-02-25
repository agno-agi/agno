"""
Broadcast Mode: Competing Hypotheses Debate
============================================

Demonstrates the broadcast pattern where the same task is sent to ALL members
simultaneously, and each provides an independent perspective. The team lead
then synthesizes potentially conflicting viewpoints.

Inspired by Claude Code's "competing hypotheses" pattern:
"Spawn 5 agent teammates to investigate different hypotheses. Have them talk
to each other to try to disprove each other's theories, like a scientific debate."

Key patterns:
- Same exact prompt sent to all members in parallel
- Each member independently analyzes from their unique perspective
- Lead identifies areas of agreement and disagreement
- Debate structure fights anchoring bias and finds the strongest theory

Run with: .venvs/demo/bin/python cookbook/05_agent_os/team_modes/broadcast_mode.py
Access at: http://localhost:7777
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
db = PostgresDb(
    id="team-modes-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Investment Analysts with Different Methodologies
# ---------------------------------------------------------------------------

fundamental_analyst = Agent(
    name="Fundamental Analyst",
    id="fundamental-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Evaluate investments based on financial fundamentals and intrinsic value",
    instructions=[
        "Analyze revenue growth, margins, cash flow, and balance sheet strength.",
        "Calculate valuation metrics: P/E, EV/EBITDA, DCF.",
        "Compare against industry peers and historical averages.",
        "Identify red flags in financial statements.",
        "Provide a BUY/HOLD/SELL recommendation with price target.",
        "Challenge any thesis that ignores financial fundamentals.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

technical_analyst = Agent(
    name="Technical Analyst",
    id="technical-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Evaluate investments based on price patterns and market technicals",
    instructions=[
        "Analyze price trends, support/resistance levels, and momentum.",
        "Identify chart patterns and volume indicators.",
        "Assess relative strength vs market and sector.",
        "Consider institutional money flow and sentiment indicators.",
        "Provide entry/exit timing recommendations.",
        "Challenge any thesis that ignores price action signals.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

macro_analyst = Agent(
    name="Macro Analyst",
    id="macro-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Evaluate investments based on macroeconomic and geopolitical context",
    instructions=[
        "Analyze interest rate environment and Fed policy impact.",
        "Assess currency risks and global trade dynamics.",
        "Consider sector rotation and economic cycle positioning.",
        "Evaluate regulatory and political risks.",
        "Provide macro-level thesis for or against the investment.",
        "Challenge any thesis that ignores systemic risks.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

contrarian_analyst = Agent(
    name="Contrarian Analyst",
    id="contrarian-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Challenge consensus views and identify overlooked risks or opportunities",
    instructions=[
        "Identify what the market is pricing in and what it might be missing.",
        "Play devil's advocate against the prevailing narrative.",
        "Look for asymmetric risk/reward that others overlook.",
        "Question assumptions in other analysts' theses.",
        "Highlight scenarios where consensus could be catastrophically wrong.",
        "Your job is to stress-test, not to agree.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

quant_analyst = Agent(
    name="Quantitative Analyst",
    id="quant-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Evaluate investments using quantitative models and statistical analysis",
    instructions=[
        "Analyze factor exposures: value, momentum, quality, size.",
        "Calculate risk metrics: volatility, beta, max drawdown, Sharpe ratio.",
        "Identify statistical anomalies or mean-reversion opportunities.",
        "Back-test similar historical scenarios.",
        "Provide probability-weighted outcome scenarios.",
        "Challenge qualitative theses with quantitative evidence.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Investment Committee (Broadcast Mode)
# ---------------------------------------------------------------------------

investment_committee = Team(
    name="Investment Committee",
    id="investment-committee",
    description="Multi-perspective investment analysis with parallel debate pattern",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[
        fundamental_analyst,
        technical_analyst,
        macro_analyst,
        contrarian_analyst,
        quant_analyst,
    ],
    mode=TeamMode.broadcast,
    instructions=[
        "You are the Chief Investment Officer synthesizing the Investment Committee debate.",
        "",
        "Committee Protocol:",
        "1. Each analyst independently evaluates the same investment opportunity",
        "2. Analysts may not see each other's work (independent analysis)",
        "3. You must identify where analysts AGREE and DISAGREE",
        "4. Pay special attention to the Contrarian's objections",
        "",
        "Synthesis Framework:",
        "- CONSENSUS: Areas where 3+ analysts align",
        "- CONFLICT: Areas of significant disagreement (explore both sides)",
        "- KEY RISKS: Combine all identified risks, prioritized by severity",
        "- KEY OPPORTUNITIES: Combine bullish arguments, weighted by conviction",
        "",
        "Final Output:",
        "- Investment Decision: BUY / HOLD / SELL / PASS",
        "- Conviction Level: HIGH / MEDIUM / LOW",
        "- Position Sizing: % of portfolio (if BUY)",
        "- Key Conditions: What would change the thesis",
        "",
        "The strongest thesis survives scrutiny from ALL perspectives.",
    ],
    markdown=True,
    show_members_responses=True,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# AgentOS Setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Investment Committee with Broadcast Mode - Parallel multi-perspective debate",
    agents=[fundamental_analyst, technical_analyst, macro_analyst, contrarian_analyst, quant_analyst],
    teams=[investment_committee],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Access the API at: http://localhost:7777
    View configuration at: http://localhost:7777/config

    Example investment memo to try:
    "Should we invest in NovaTech AI (NVAI)? Revenue +67% YoY, Forward P/S 13.5x, down 23% from highs"
    """
    agent_os.serve(app="broadcast_mode:app", reload=True)
