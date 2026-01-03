"""
User Profile Learning
===========================================
This is the simplest way to add learning to an agent.

Just set `learning=True` and provide a database.
The agent automatically extracts user info from interactions in BACKGROUND mode.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Create Agent
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    # learning=True enables UserProfileStore with BACKGROUND extraction
    learning=True,
    # Respond in markdown format
    markdown=True,
)

# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Demo: User Profile Learning across Sessions")
    print("=" * 60)

    user_id = "alice@example.com"

    # --- Session 1: User introduces themselves ---
    print("\nSession 1: Introduction")
    print("-" * 40)

    agent.print_response(
        "Hi! I'm Alice. I'm a data scientist at Netflix working on "
        "recommendation systems. I prefer Python and love visualization libraries.",
        user_id=user_id,
        session_id="session_intro",
        stream=True,
    )

    # --- Session 2: New session, agent should remember Alice ---
    print("\nSession 2: New conversation (agent remembers!)")
    print("-" * 40)

    agent.print_response(
        "What visualization library would you recommend for my work?",
        user_id=user_id,
        session_id="session_followup",
        stream=True,
    )

    # --- Session 3: Ask about what the agent remembers ---
    print("\nSession 3: What do you know about me?")
    print("-" * 40)

    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="session_recall",
        stream=True,
    )
