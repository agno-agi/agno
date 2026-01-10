"""
User Profile: Agentic Mode
==========================
Agent-driven profile updates via tools.

In AGENTIC mode, the agent decides when to save information using
tools. This gives the agent control over what gets saved.

Advantages:
- Agent is selective (less noise)
- User sees when info is saved
- No hidden LLM calls
- More transparent

The agent gets tools:
- `update_user_profile`: Update profile fields (name, preferred_name, custom fields)

Note: For unstructured memories, use MemoriesConfig with AGENTIC mode.
See: 2b_memories_agentic.py for memories.

Run:
    python cookbook/15_learning/02_user_profile/02_agentic_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# ============================================================================
# Agent with AGENTIC mode
# ============================================================================
agent = Agent(
    name="Agentic Profile Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant with the ability to update user profiles.

When a user shares their name or how they prefer to be addressed,
use the `update_user_profile` tool to save it.

What to save in profile:
- Name and how they prefer to be addressed
- Other structured profile fields

Note: This agent only handles structured profile fields.
For unstructured observations, use MemoriesConfig separately.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_update_profile=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Agent Updates Profile
# ============================================================================
def demo_profile_update():
    """Show agent updating profile fields."""
    print("=" * 60)
    print("Demo: Agent Updates Profile Fields")
    print("=" * 60)

    user = "agentic_demo@example.com"

    # Share name info - should update profile
    print("\n--- Share name (should update profile) ---\n")
    agent.print_response(
        "Hi! I'm Jordan Chen, but everyone calls me JC.",
        user_id=user,
        session_id="agentic_1",
        stream=True,
    )

    # Check what was saved
    print("\n--- Profile check ---\n")
    agent.print_response(
        "What's my name and what should you call me?",
        user_id=user,
        session_id="agentic_2",
        stream=True,
    )


# ============================================================================
# Demo: Explicit Profile Update
# ============================================================================
def demo_explicit_update():
    """Show user explicitly asking agent to update profile."""
    print("\n" + "=" * 60)
    print("Demo: Explicit Profile Update")
    print("=" * 60)

    user = "explicit_update@example.com"

    print("\n--- Explicit request ---\n")
    agent.print_response(
        "My name is Alexandra Williams, but please always call me Alex.",
        user_id=user,
        session_id="explicit_1",
        stream=True,
    )

    print("\n--- Later conversation ---\n")
    agent.print_response(
        "How should you address me?",
        user_id=user,
        session_id="explicit_2",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_profile_update()
    demo_explicit_update()

    print("\n" + "=" * 60)
    print("✅ AGENTIC mode: Agent controls profile updates")
    print("   - update_user_profile tool for name, preferred_name, etc.")
    print("   - More transparent, no hidden LLM calls")
    print("   - For memories, use MemoriesConfig separately")
    print("=" * 60)
