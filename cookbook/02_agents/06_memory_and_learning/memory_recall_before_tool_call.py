"""
Memory Recall Before Tool Call
==============================

Demonstrates recalling user memories before calling a domain tool.

The agent is instructed to call `get_memories` first so `recommend_activity`
can use stored preferences instead of guessing.

Key concepts:
- MemoryTools: exposes `get_memories` as an agent tool
- Tool ordering via instructions (recall, then act)
- user_id scopes memories to the current person

Example prompts to try:
- "I prefer outdoor activities and I am afraid of heights."
- "Suggest an activity for this weekend."
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.memory import MemoryTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/memory_recall_before_tool.db")
user_id = "weekend-planner"

memory_tools = MemoryTools(db=db)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def recommend_activity(activity_type: str, reason: str) -> str:
    """Recommend a weekend activity based on the user's preferences.

    Args:
        activity_type: Short name of the recommended activity.
        reason: Why this activity fits the user (reference their preferences).
    """
    return f"Recommendation: {activity_type}. Reason: {reason}"


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = [
    "You help users plan weekend activities.",
    "Before calling recommend_activity, always call get_memories to load user preferences.",
    "If no preferences exist yet, ask the user or store what they tell you with add_memory.",
    "Never recommend activities that conflict with stored preferences.",
]

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    tools=[memory_tools, recommend_activity],
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Store preferences ===")
    agent.print_response(
        "I prefer outdoor activities and I am afraid of heights.",
        user_id=user_id,
        stream=True,
    )

    print("\n=== Recall memories, then recommend ===")
    agent.print_response(
        "Suggest an activity for this weekend.",
        user_id=user_id,
        stream=True,
    )