"""
Create the Showcase Finance Team
================================

Combine Sage's current research with a focused market-data specialist. The
Team delegates both perspectives and returns one sourced finance brief.

Prerequisites: Postgres on port 5532, OPENAI_API_KEY, and ANTHROPIC_API_KEY
Run: .venvs/demo/bin/python -m cookbook.05_agent_os.24_showcase.demo
Try: ask the Finance Team to compare a company's news with its fundamentals
"""

from importlib import import_module

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.yfinance import YFinanceTools

agents_module = import_module("cookbook.05_agent_os.24_showcase._agents")
sage = agents_module.sage
showcase_db = agents_module.showcase_db

# ---------------------------------------------------------------------------
# Create Finance Specialist
# ---------------------------------------------------------------------------

market_analyst = Agent(
    id="market-analyst",
    name="Market Analyst",
    role="Retrieve and interpret company fundamentals and price data.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=showcase_db,
    tools=[
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_stock_fundamentals=True,
            enable_income_statements=True,
            enable_key_financial_ratios=True,
            enable_analyst_recommendations=True,
        )
    ],
    instructions=[
        "Use the financial tools before stating prices or fundamentals.",
        "State the ticker and currency for every company.",
        "Use a compact table when comparing metrics.",
        "Do not present the analysis as investment advice.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Finance Team
# ---------------------------------------------------------------------------

finance_team = Team(
    id="finance-team",
    name="Finance Team",
    description="Current research and market data combined in one finance brief.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=showcase_db,
    members=[sage, market_analyst],
    instructions=[
        "Delegate current news and broad context to Sage.",
        "Delegate exact market and fundamentals work to the Market Analyst.",
        "Reconcile the two member responses into one concise, sourced brief.",
        "Distinguish facts, interpretation, and material uncertainty.",
        "Do not present the response as investment advice.",
    ],
    delegate_to_all_members=True,
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run through the Showcase App
# ---------------------------------------------------------------------------

# demo.py registers this Team beside the two standalone showcase Agents.
