"""
Cross-Provider Tool Messages: Gemini -> OpenAI Responses API
=============================================================

Demonstrates switching from Gemini to OpenAI Responses API mid-session.

The Responses API uses a different message format (function_call / function_call_output)
compared to the Chat API (role-based messages). Gemini combined tool messages need
special handling to emit one function_call_output per tool call.

Flow:
  1. Create agent with Gemini, use multiple tools that trigger parallel tool calls
  2. Switch to OpenAI Responses API (same session), continue conversation
  3. Verify the Responses API correctly receives all tool outputs

Requires: GOOGLE_API_KEY, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.calculator import CalculatorTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Storage Configuration
# ---------------------------------------------------------------------------
agent_db = SqliteDb(db_file="tmp/cross_provider.db", session_table="responses_sessions")

# ---------------------------------------------------------------------------
# Shared Configuration
# ---------------------------------------------------------------------------
tools = [
    CalculatorTools(),
    YFinanceTools(),
]
session_id = "cross-provider-responses"
instructions = """\
You are a financial math assistant. Use the calculator for math operations
and the finance tools for stock data. When asked to compare, fetch data
for all stocks in parallel.\
"""

# ---------------------------------------------------------------------------
# Step 1: Gemini performs parallel tool calls
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Step 2: OpenAI Responses API continues the same session
# ---------------------------------------------------------------------------
openai_agent = Agent(
    name="Finance Agent (OpenAI Responses)",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: Gemini fetches stock data (may trigger parallel tool calls)")
    print("=" * 60)
    gemini_agent.print_response(
        "Get the current stock price of AAPL and MSFT.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI Responses API continues with Gemini's history")
    print("=" * 60)
    openai_agent.print_response(
        "Based on the prices above, which stock is more expensive? Calculate the ratio.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Back to Gemini to verify round-trip")
    print("=" * 60)
    gemini_agent.print_response(
        "Summarize what we found about AAPL and MSFT.",
        session_id=session_id,
        stream=True,
    )
