"""
Cross-Provider Multi-Tool: Parallel Tool Calls Across Providers
===============================================================

Demonstrates parallel multi-tool calls (Calculator + YFinance) persisted
across provider switches. Gemini's combined tool message format is correctly
consumed by Claude and OpenAI.

Flow:
  1. Gemini fetches AAPL and MSFT stock prices (parallel tool calls)
  2. Claude calculates the price ratio
  3. OpenAI summarizes all findings

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from agno.tools.yfinance import YFinanceTools

agent_db = SqliteDb(
    db_file="tmp/cross_provider.db", session_table="multi_tool_sessions"
)

tools = [
    CalculatorTools(),
    YFinanceTools(),
]
session_id = "cross-provider-multi-tool"
instructions = """\
You are a financial math assistant. Use the calculator for math operations
and the finance tools for stock data. When asked to compare, fetch data
for all stocks in parallel.\
"""

gemini_agent = Agent(
    name="Finance Agent (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

claude_agent = Agent(
    name="Finance Agent (Claude)",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

openai_agent = Agent(
    name="Finance Agent (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: Gemini fetches stock prices (parallel tool calls)")
    print("=" * 60)
    gemini_agent.print_response(
        "Get the current stock price of AAPL and MSFT.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: Claude calculates price ratio")
    print("=" * 60)
    claude_agent.print_response(
        "Based on the stock prices above, calculate the ratio of AAPL to MSFT price. Which is more expensive?",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: OpenAI summarizes")
    print("=" * 60)
    openai_agent.print_response(
        "Summarize all the stock data and calculations we have done.",
        session_id=session_id,
        stream=True,
    )
