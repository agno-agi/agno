"""
User Profile Learning
===========================================
This is the simplest way to add learning to an agent.

Just set `learning=True` and provide a database. The agent automatically:
- Extracts user info from conversations (BACKGROUND mode)
- Has an `update_user_memory` tool to save info on demand

Run this example:
    python cookbook/learning/01_user_profile_learning.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Database for storing user profiles and session context
db = PostgresDb(db_url=db_url)

# Model for the agent
model = OpenAIChat(id="gpt-5.2")

# =============================================================================
# Create the Agent
# =============================================================================

agent = Agent(
    model=model,
    db=db,
    # learning=True is all you need!
    # It enables UserProfileStore with:
    # - BACKGROUND extraction (auto-captures user info)
    # - update_user_memory tool (agent can save info on demand)
    learning=True,
)


# =============================================================================
# Demo
# =============================================================================


def demo_user_memory():
    """Show how the agent remembers user information across sessions."""
    print("=" * 60)
    print("Demo: User Memory Across Sessions")
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


def demo_agent_tool():
    """Show the agent using update_user_memory tool."""
    print("\n" + "=" * 60)
    print("Demo: Agent Using Memory Tool")
    print("=" * 60)

    user_id = "carol@example.com"
    session_id = "preferences_session"

    print("\nUser shares preferences (agent should save them)")
    print("-" * 40)

    agent.print_response(
        "By the way, I hate getting super long responses. "
        "Keep things brief and to the point. Also, I'm colorblind "
        "so avoid red/green color schemes in any examples.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\nLater: Testing if preferences were saved")
    print("-" * 40)

    agent.print_response(
        "Can you explain how async/await works in Python?",
        user_id=user_id,
        session_id="later_session",
        stream=True,
    )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    demo_user_memory()
    demo_agent_tool()
