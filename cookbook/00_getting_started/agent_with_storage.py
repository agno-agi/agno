"""
Agent with Storage - Finance Agent with Storage
====================================================
Building on the Finance Agent from 01, this example adds persistent storage.
Your agent now remembers conversations across runs.

Ask about NVDA, close the script, come back later — pick up where you left off.
The conversation history is saved to SQLite and restored automatically.

Key concepts:
- Run: Each time you run the agent (via agent.print_response() or agent.run())
- Session: A conversation thread, identified by session_id
- Same session_id = continuous conversation, even across runs

Example prompts to try:
- "What's the current price of AAPL?"
- "Compare that to Microsoft" (it remembers AAPL)
- "Based on our discussion, which looks better?"
- "What stocks have we analyzed so far?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent — a data-driven analyst who retrieves market data,
computes key ratios, and produces concise, decision-ready insights.

## Workflow

1. Clarify
   - Identify tickers from company names (e.g., Apple → AAPL)
   - If ambiguous, ask

2. Retrieve
   - Fetch: price, change %, market cap, P/E, EPS, 52-week range
   - For comparisons, pull the same fields for each ticker

3. Analyze
   - Compute ratios (P/E, P/S, margins) when not already provided
   - Key drivers and risks — 2-3 bullets max
   - Facts only, no speculation

4. Present
   - Lead with a one-line summary
   - Use tables for multi-stock comparisons
   - Keep it tight

## Rules

- Source: Yahoo Finance. Always note the timestamp.
- Missing data? Say "N/A" and move on.
- No personalized advice — add disclaimer when relevant.
- No emojis.
- Reference previous analyses when relevant.\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_storage = Agent(
    name="Agent with Storage",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[YFinanceTools()],
    db=agent_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Use a consistent session_id to persist conversation across runs
    # Note: session_id is auto-generated if not set
    session_id = "finance-agent-session"

    # Turn 1: Analyze a stock
    agent_with_storage.print_response(
        "Give me a quick investment brief on NVIDIA",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Compare — the agent remembers NVDA from turn 1
    agent_with_storage.print_response(
        "Compare that to Tesla",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Ask for a recommendation based on the full conversation
    agent_with_storage.print_response(
        "Based on our discussion, which looks like the better investment?",
        session_id=session_id,
        stream=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Try this flow:

1. Run the script — it analyzes NVDA, compares to TSLA, then recommends
2. Comment out all three prompts above
3. Add: agent.print_response("What about AMD?", session_id=session_id, stream=True)
4. Run again — it remembers the full NVDA vs TSLA conversation

The storage layer persists your conversation history to SQLite.
Restart the script anytime and pick up where you left off.
"""
