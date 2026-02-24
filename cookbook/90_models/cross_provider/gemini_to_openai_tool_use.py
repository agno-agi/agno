"""
Cross-Provider Tool Messages: Gemini -> OpenAI
===============================================

Demonstrates switching model providers mid-session while preserving tool call history.

Gemini stores tool results in a combined format (content=list), while OpenAI expects
content=str with one tool message per tool_call_id. The normalization layer in
_format_messages handles this automatically.

Flow:
  1. Create agent with Gemini, use calculator tools, store in SQLite
  2. Switch to OpenAI (same session), continue conversation using stored history
  3. Verify OpenAI can read and build on Gemini's tool call results

Requires: GOOGLE_API_KEY, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Storage Configuration
# ---------------------------------------------------------------------------
agent_db = SqliteDb(db_file="tmp/cross_provider.db", session_table="agent_sessions")

# ---------------------------------------------------------------------------
# Shared Configuration
# ---------------------------------------------------------------------------
tools = [CalculatorTools()]
session_id = "cross-provider-calculator"
instructions = "You are a math assistant. Use the calculator tools to compute results."

# ---------------------------------------------------------------------------
# Step 1: Gemini performs tool calls
# ---------------------------------------------------------------------------
gemini_agent = Agent(
    name="Math Agent (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Step 2: OpenAI continues the same session
# ---------------------------------------------------------------------------
openai_agent = Agent(
    name="Math Agent (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
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
    print("Turn 1: Gemini calculates")
    print("=" * 60)
    gemini_agent.print_response(
        "What is 42 * 17? Then add 100 to that result.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI continues with Gemini's history")
    print("=" * 60)
    openai_agent.print_response(
        "What was the final result from the previous calculation? Now divide it by 3.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Gemini reads back OpenAI's results")
    print("=" * 60)
    gemini_agent.print_response(
        "Summarize all calculations we have done so far.",
        session_id=session_id,
        stream=True,
    )
