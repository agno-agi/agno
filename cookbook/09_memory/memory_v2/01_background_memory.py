"""
Memory V2 Background Memory Extraction
================================================
This example shows background memory extraction without explicit tools.
The agent learns user information after each response.

Different from agentic memory (02_agentic_memory.py), background memory
runs a separate extraction pass after each response. Guaranteed capture.

Key concepts:
- update_memory_on_run: Memory extracted automatically after every run
- No explicit tools needed - extraction happens silently
- MemoryCompiler: Configures how memory is extracted

Example prompts to try:
- "I'm migrating from Flask to FastAPI"
- "I prefer structured error responses"
- "My team has 4 engineers"
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/user_memory.db")

# ============================================================================
# User Configuration
# ============================================================================
user_id = "sarah"

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Auto-Learning Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    update_memory_on_run=True,  # Automatic extraction
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Show existing memory if any
    existing = agent.get_user_memory_v2(user_id)
    if existing:
        print("Existing profile:")
        print_json(json.dumps(existing.to_dict()))
        print()

    # Conversation naturally reveals user information
    agent.print_response(
        "We're migrating our legacy Flask services to FastAPI for better async support. "
        "The payment API I mentioned is the first one we're converting.",
        user_id=user_id,
        stream=True,
    )

    agent.print_response(
        "By the way, I prefer seeing error handling patterns rather than just try/except blocks. "
        "Show me structured error responses with proper HTTP status codes.",
        user_id=user_id,
        stream=True,
    )

    agent.print_response(
        "How should I implement rate limiting for our payment API?",
        user_id=user_id,
        stream=True,
    )

    # View updated memory
    print("\n" + "=" * 60)
    print("Updated Memory")
    print("=" * 60)

    user = agent.get_user_memory_v2(user_id)
    if user:
        print_json(json.dumps(user.to_dict()))

# ============================================================================
# More Examples
# ============================================================================
"""
When to use automatic vs agentic memory:

Automatic (update_memory_on_run=True):
- Guaranteed capture of user info
- Good for onboarding flows
- Higher latency (extra LLM call)
- User doesn't need to say "remember"

Agentic (enable_agentic_memory_v2=True):
- Agent decides when to save
- More efficient
- User can explicitly ask "remember X"
- May miss implicit information

Memory accumulates across multiple runs with the same user_id.
"""
