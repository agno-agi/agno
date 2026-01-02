"""
User Profile Learning — The Simplest Setup
===========================================
This is the simplest way to add learning to an agent.

Just set `learning=True` and provide a database. That's it!

What you get:
- ✅ User Profile: Remembers facts about users across sessions

The agent automatically:
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
model = OpenAIChat(id="gpt-4o")

# =============================================================================
# Create the Agent — Just set learning=True!
# =============================================================================

agent = Agent(
    name="Personal Assistant",
    model=model,
    db=db,
    # This is all you need! Enables UserProfileStore with:
    # - BACKGROUND extraction (auto-captures user info)
    # - update_user_memory tool (agent can save info on demand)
    learning=True,
    # Standard agent settings
    add_datetime_to_context=True,
    markdown=True,
)


# =============================================================================
# Demo: User Memory Across Sessions
# =============================================================================


def demo_user_memory():
    """Show how the agent remembers user information across sessions."""
    print("=" * 60)
    print("Demo: User Memory Across Sessions")
    print("=" * 60)

    user_id = "alice@example.com"

    # --- Session 1: User introduces themselves ---
    print("\n📝 Session 1: Introduction")
    print("-" * 40)

    agent.print_response(
        "Hi! I'm Alice. I'm a data scientist at Netflix working on "
        "recommendation systems. I prefer Python and love visualization libraries.",
        user_id=user_id,
        session_id="session_intro",
        stream=True,
    )

    # --- Session 2: New session, agent should remember Alice ---
    print("\n\n📝 Session 2: New conversation (agent remembers!)")
    print("-" * 40)

    agent.print_response(
        "What visualization library would you recommend for my work?",
        user_id=user_id,
        session_id="session_followup",  # Different session!
        stream=True,
    )

    # --- Session 3: Ask about what the agent remembers ---
    print("\n\n📝 Session 3: What do you know about me?")
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

    print("\n📝 User shares preferences (agent should save them)")
    print("-" * 40)

    agent.print_response(
        "By the way, I hate getting super long responses. "
        "Keep things brief and to the point. Also, I'm colorblind "
        "so avoid red/green color schemes in any examples.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n📝 Later: Testing if preferences were saved")
    print("-" * 40)

    agent.print_response(
        "Can you explain how async/await works in Python?",
        user_id=user_id,
        session_id="later_session",  # Different session
        stream=True,
    )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    demos = {
        "memory": demo_user_memory,
        "tool": demo_agent_tool,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]

        if demo_name == "all":
            demo_user_memory()
            demo_agent_tool()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🧠 User Profile Learning — The Simplest Setup")
        print("=" * 60)
        print("\nThis cookbook shows learning=True in action.")
        print("\nAvailable demos:")
        print("  memory   - User memory persists across sessions")
        print("  tool     - Agent uses update_user_memory tool")
        print("  all      - Run all demos")
        print("\nUsage: python 01_user_profile_learning.py <demo>")
        print("\nRunning 'memory' demo by default...\n")
        demo_user_memory()
