"""
Hello Learning
==============
The simplest possible Learning Machine example.

This demonstrates:
- Enabling learning with a single boolean
- Automatic user profile extraction
- Memory persistence across sessions

Run:
    python cookbook/15_learning/basics/01_hello_learning.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# The Simplest Learning Agent
# ============================================================================
# Just set learning=True and get sensible defaults:
# - User profile extraction in BACKGROUND mode
# - Automatic memory persistence
# - Context injection into system prompt

agent = Agent(
    name="Hello Learning Agent",
    model=model,
    db=db,
    learning=True,  # That's it!
    markdown=True,
)

# ============================================================================
# Demo: Memory Across Sessions
# ============================================================================
if __name__ == "__main__":
    user_id = "hello_user@example.com"

    print("=" * 60)
    print("Session 1: Introduce yourself")
    print("=" * 60)

    agent.print_response(
        "Hi! I'm Alice, I work at Anthropic as a research scientist. "
        "I love hiking and prefer dark mode in all my apps.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Session 2: Test memory recall")
    print("=" * 60)

    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("✅ That's it! The agent remembered Alice across sessions.")
    print("=" * 60)
