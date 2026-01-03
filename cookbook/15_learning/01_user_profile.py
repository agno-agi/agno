"""
User Profile Learning
===========================================
The simplest way to add learning to an agent.

Set `learning=True` and provide a database.
The agent automatically extracts user info from conversations (BACKGROUND mode).

Memories persist across sessions — the agent on conversation 100
knows everything it learned in conversations 1-99.
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
# Create Learning Agent
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=True,  # Enables UserProfileStore in BACKGROUND mode
    markdown=True,
)


# =============================================================================
# Helper: Show what the agent learned
# =============================================================================
def show_profile(user_id: str):
    """Display the stored user profile."""
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print("\n📝 Stored memories:")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print("\n📝 No memories stored yet.")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "alice@example.com"

    # --- Session 1: User introduces themselves ---
    print("=" * 60)
    print("Session 1: Introduction")
    print("=" * 60)
    agent.print_response(
        "Hi! I'm Alice. I'm a data scientist at Netflix working on "
        "recommendation systems. I prefer Python and love visualization libraries.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    show_profile(user_id)

    # --- Session 2: New session, agent remembers ---
    print("=" * 60)
    print("Session 2: New conversation (agent remembers)")
    print("=" * 60)
    agent.print_response(
        "What visualization library would you recommend for my work?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    # --- Session 3: Verify recall ---
    print("=" * 60)
    print("Session 3: What do you know about me?")
    print("=" * 60)
    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    show_profile(user_id)
