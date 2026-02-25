"""
Reverse Direction: OpenAI -> Gemini -> Claude
=============================================

All other cross-provider cookbooks start with Gemini. This one starts with
OpenAI so canonical (one-message-per-tool) format goes INTO Gemini, exercising
Gemini's handler for pre-normalized tool messages.

Flow:
  1. OpenAI fetches stock prices (canonical tool messages stored)
  2. Gemini reads those canonical messages from DB, does a follow-up calculation
  3. Claude summarizes all findings

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
    db_file="tmp/cross_provider.db", session_table="reverse_direction_sessions"
)

tools = [CalculatorTools(), YFinanceTools()]
session_id = "openai-to-gemini"
instructions = (
    "You are a financial math assistant. Use calculator for math and "
    "finance tools for stock data. Always show exact numbers."
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

if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: OpenAI fetches stock prices (canonical format)")
    print("=" * 60)
    openai_agent.print_response(
        "Get the current stock price of GOOGL and NVDA.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: Gemini reads OpenAI's canonical tool messages from DB")
    print("=" * 60)
    gemini_agent.print_response(
        "Using the stock prices from above, calculate the ratio of NVDA to GOOGL price.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Claude summarizes all findings")
    print("=" * 60)
    claude_agent.print_response(
        "Summarize all the stock data and calculations we have done so far.",
        session_id=session_id,
        stream=True,
    )
