"""
User Profile: Agentic Mode
==========================
User Profile captures long-term information about users:
- Name and preferences
- Work context
- Communication style
- Any memorable facts

AGENTIC mode gives the agent explicit tools to save and update memories.
The agent decides when to store information - you can see the tool calls.

Compare with: 02a_user_profile_background.py for automatic extraction.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# AGENTIC mode: Agent gets memory tools and decides when to use them.
# You'll see tool calls like "add_memory", "update_memory" in responses.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    instructions="Remember important information about users using your memory tools.",
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show user profile
# =============================================================================
def show_profile(user_id: str) -> None:
    """Display the stored user profile."""
    from rich.pretty import pprint

    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None
    pprint(profile) if profile else print("\nNo profile stored yet.")


# ============================================================================
# Demo: Explicit Memory Tool Calls
# ============================================================================
if __name__ == "__main__":
    user_id = "agentic@example.com"

    # Session 1: Agent explicitly saves memories
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (watch for tool calls)")
    print("=" * 60 + "\n")
    agent.print_response(
        "Hi! I'm Bob, a backend engineer at Stripe. "
        "I specialize in distributed systems and prefer Rust over Go.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Profile ---")
    show_profile(user_id)

    # Session 2: Agent uses stored memories
    print("\n" + "=" * 60)
    print("SESSION 2: New session, test memory")
    print("=" * 60 + "\n")
    agent.print_response(
        "What programming language would you recommend for my next project?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Updated Profile ---")
    show_profile(user_id)

    # Session 3: Explicit memory update
    print("\n" + "=" * 60)
    print("SESSION 3: Update information")
    print("=" * 60 + "\n")
    agent.print_response(
        "Actually, I just switched jobs - I'm now at Cloudflare working on Workers.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Updated Profile ---")
    show_profile(user_id)
