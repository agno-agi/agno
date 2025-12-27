"""
Agent with Memory - Finance Agent that Remembers You
=====================================================
This example shows how to give your agent memory of user preferences.
The agent remembers facts about you across all conversations.

Different from storage (which persists conversation history), memory
persists user-level information: preferences, facts, context.

Key concepts:
- MemoryManager: Extracts and stores user memories from conversations
- enable_agentic_memory: Agent decides when to store/recall via tool calls (efficient)
- enable_user_memories: Memory manager runs after every response (guaranteed capture)
- user_id: Links memories to a specific user

Example prompts to try:
- "I'm interested in tech stocks, especially AI companies"
- "My risk tolerance is moderate"
- "What stocks would you recommend for me?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from rich.pretty import pprint

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Memory Manager Configuration
# ============================================================================
memory_manager = MemoryManager(
    model=Gemini(id="gemini-3-flash-preview"),
    db=agent_db,
    additional_instructions="""
    Capture the user's favorite stocks, their risk tolerance, and their investment goals.
    """,
)

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent — a data-driven analyst who retrieves market data,
computes key ratios, and produces concise, decision-ready insights.

## Memory

You have memory of user preferences (automatically provided in context). Use this to:
- Tailor recommendations to their interests
- Consider their risk tolerance
- Reference their investment goals

## Workflow

1. Retrieve
   - Fetch: price, change %, market cap, P/E, EPS, 52-week range
   - For comparisons, pull the same fields for each ticker

2. Analyze
   - Compute ratios (P/E, P/S, margins) when not already provided
   - Key drivers and risks — 2-3 bullets max
   - Facts only, no speculation

3. Present
   - Lead with a one-line summary
   - Use tables for multi-stock comparisons
   - Keep it tight

## Rules

- Source: Yahoo Finance. Always note the timestamp.
- Missing data? Say "N/A" and move on.
- No personalized advice — add disclaimer when relevant.
- No emojis.\
"""

# ============================================================================
# Create the Agent
# ============================================================================
user_id = "investor@example.com"

agent_with_memory = Agent(
    name="Agent with Memory",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[YFinanceTools()],
    db=agent_db,
    memory_manager=memory_manager,
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Tell the agent about yourself
    agent_with_memory.print_response(
        "I'm interested in AI and semiconductor stocks. My risk tolerance is moderate.",
        user_id=user_id,
        stream=True,
    )

    # The agent now knows your preferences
    agent_with_memory.print_response(
        "What stocks would you recommend for me?",
        user_id=user_id,
        stream=True,
    )

    # View stored memories
    memories = agent_with_memory.get_user_memories(user_id=user_id)
    print("\n" + "=" * 60)
    print("Stored Memories:")
    print("=" * 60)
    pprint(memories)

# ============================================================================
# More Examples
# ============================================================================
"""
Memory vs Storage:

- Storage: "What did we discuss?" (conversation history)
- Memory: "What do you know about me?" (user preferences)

Memory persists across sessions:

1. Run this script — agent learns your preferences
2. Start a NEW session with the same user_id
3. Agent still remembers you like AI stocks

Useful for:
- Personalized recommendations
- Remembering user context (job, goals, constraints)
- Building rapport across conversations

Two ways to enable memory:

1. enable_agentic_memory=True (used in this example)
   - Agent decides when to store/recall via tool calls
   - More efficient — only runs when needed

2. enable_user_memories=True
   - Memory manager runs after every agent response
   - Guaranteed capture — never misses user info
   - Higher latency and cost
"""
