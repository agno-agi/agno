"""
Agent with State Management - Finance Agent with Watchlist
===========================================================
This example shows how to give your agent persistent state that it can
read and modify. The agent maintains a stock watchlist across conversations.

Different from storage (conversation history) and memory (user preferences),
state is structured data the agent actively manages: counters, lists, flags.

Key concepts:
- session_state: A dict that persists across runs
- Tools can read/write state via run_context.session_state
- State variables can be injected into instructions with {variable_name}

Example prompts to try:
- "Add NVDA and AMD to my watchlist"
- "What's on my watchlist?"
- "Remove AMD from the list"
- "How are my watched stocks doing today?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.run import RunContext
from agno.tools.yfinance import YFinanceTools

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")


# ============================================================================
# Custom Tools that Modify State
# ============================================================================
def add_to_watchlist(run_context: RunContext, ticker: str) -> str:
    """
    Add a stock ticker to the watchlist.

    Args:
        ticker: Stock ticker symbol (e.g., NVDA, AAPL)

    Returns:
        Confirmation message
    """
    ticker = ticker.upper().strip()
    watchlist = run_context.session_state.get("watchlist", [])

    if ticker in watchlist:
        return f"{ticker} is already on your watchlist"

    watchlist.append(ticker)
    run_context.session_state["watchlist"] = watchlist

    return f"Added {ticker} to watchlist. Current watchlist: {', '.join(watchlist)}"


def remove_from_watchlist(run_context: RunContext, ticker: str) -> str:
    """
    Remove a stock ticker from the watchlist.

    Args:
        ticker: Stock ticker symbol to remove

    Returns:
        Confirmation message
    """
    ticker = ticker.upper().strip()
    watchlist = run_context.session_state.get("watchlist", [])

    if ticker not in watchlist:
        return f"{ticker} is not on your watchlist"

    watchlist.remove(ticker)
    run_context.session_state["watchlist"] = watchlist

    if watchlist:
        return f"Removed {ticker}. Remaining watchlist: {', '.join(watchlist)}"
    return f"Removed {ticker}. Watchlist is now empty."


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent that manages a stock watchlist.

## Current Watchlist
{watchlist}

## Capabilities

1. Manage watchlist
   - Add stocks: use add_to_watchlist tool
   - Remove stocks: use remove_from_watchlist tool

2. Get stock data
   - Use YFinance tools to fetch prices and metrics for watched stocks
   - Compare stocks on the watchlist

## Rules

- Always confirm watchlist changes
- When asked about "my stocks" or "watchlist", refer to the current state
- Fetch fresh data when reporting on watchlist performance\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_state_management = Agent(
    name="Agent with State Management",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[
        add_to_watchlist,
        remove_from_watchlist,
        YFinanceTools(),
    ],
    session_state={"watchlist": []},
    add_session_state_to_context=True,
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
    # Add some stocks
    agent_with_state_management.print_response(
        "Add NVDA, AAPL, and GOOGL to my watchlist",
        stream=True,
    )

    # Check the watchlist
    agent_with_state_management.print_response(
        "How are my watched stocks doing today?",
        stream=True,
    )

    # View the state directly
    print("\n" + "=" * 60)
    print("Session State:")
    print(
        f"  Watchlist: {agent_with_state_management.get_session_state().get('watchlist', [])}"
    )
    print("=" * 60)

# ============================================================================
# More Examples
# ============================================================================
"""
State vs Storage vs Memory:

- State: Structured data the agent manages (watchlist, counters, flags)
- Storage: Conversation history ("what did we discuss?")
- Memory: User preferences ("what do I like?")

State is perfect for:
- Tracking items (watchlists, todos, carts)
- Counters and progress
- Multi-step workflows
- Any structured data that changes during conversation

Accessing state:

1. In tools: run_context.session_state["key"]
2. In instructions: {key} (with add_session_state_to_context=True)
3. After run: agent.get_session_state() or response.session_state
"""
