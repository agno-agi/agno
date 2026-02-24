"""
Code Mode — Team with Tool-Writing Agent
==========================================
A team where the "Data Analyst" member uses tool_execute_mode to orchestrate
heavy data operations, while the "Researcher" stays in normal mode
for web search. The team leader routes tasks to the right agent.

This is the "tool-writing agent" pattern: one team member specializes
in writing Python programs that call multiple tools efficiently.

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_tool_execute_mode/team.py
"""

import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

model = Claude(id="claude-sonnet-4-20250514")

researcher = Agent(
    name="Researcher",
    role="Web research specialist",
    model=model,
    tools=[DuckDuckGoTools()],
    instructions=[
        "You search the web for qualitative information.",
        "Focus on news, trends, and analyst opinions.",
    ],
    markdown=True,
)

data_analyst = Agent(
    name="Data Analyst",
    role="Quantitative data specialist using code mode",
    model=model,
    tools=[
        YFinanceTools(
            enable_stock_price=True,
            enable_analyst_recommendations=True,
            enable_stock_fundamentals=True,
        ),
        CalculatorTools(),
    ],
    tool_execute_mode=True,
    instructions=[
        "You write Python programs to fetch and analyze financial data.",
        "Always present results in markdown tables.",
    ],
    markdown=True,
)

team = Team(
    name="Investment Research Team",
    mode="coordinate",
    model=model,
    members=[researcher, data_analyst],
    instructions=[
        "You lead an investment research team.",
        "Delegate web research to the Researcher.",
        "Delegate quantitative analysis to the Data Analyst.",
        "Combine their findings into a final recommendation.",
    ],
    markdown=True,
)

TASK = (
    "Research NVDA as an investment:\n"
    "1. Search the web for recent NVIDIA news and analyst sentiment.\n"
    "2. Get the actual stock price, P/E ratio, and analyst recommendations.\n"
    "3. Calculate what $10,000 invested would buy (whole shares + leftover).\n"
    "4. Combine everything into a buy/hold/sell recommendation."
)

if __name__ == "__main__":
    t0 = time.time()
    response = team.run(TASK)
    elapsed = time.time() - t0

    print(response.content)
    print(f"\nDuration: {elapsed:.1f}s")
