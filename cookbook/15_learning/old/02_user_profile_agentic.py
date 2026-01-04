"""
User Profile Learning (Agentic Mode)
===========================================
In AGENTIC mode, the agent decides when to save memories using a tool.

This gives the agent control — it only saves what it judges important,
rather than extracting from every conversation automatically.

Use this when you want intentional, high-quality memories.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Create Learning Agent (Agentic Mode)
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,  # Agent decides when to save
            enable_agent_tools=True,  # Gives agent the update_user_memory tool
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show what the agent learned
# =============================================================================
def show_profile(user_id: str):
    """Display the stored user profile."""
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile:
        # Show profile fields
        if profile.name:
            print(f"\n👤 Name: {profile.name}")

        # Show memories
        if profile.memories:
            print("\n📝 Memories:")
            for mem in profile.memories:
                print(f"   > {mem.get('content', mem)}")
    else:
        print("\n📝 No profile stored yet.")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "bob@example.com"

    # --- Conversation 1: Casual chat (agent may not save anything) ---
    print("=" * 60)
    print("Conversation 1: Casual chat")
    print("=" * 60)
    agent.print_response(
        "What's the weather like today?",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    show_profile(user_id)

    # --- Conversation 2: Important info (agent should save) ---
    print("=" * 60)
    print("Conversation 2: User shares important context")
    print("=" * 60)
    agent.print_response(
        "I'm Bob, a backend engineer at Stripe. I work primarily with Go "
        "and PostgreSQL. I'm currently building a new payments API.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    show_profile(user_id)

    # --- Conversation 3: Explicit request to remember ---
    print("=" * 60)
    print("Conversation 3: Explicit memory request")
    print("=" * 60)
    agent.print_response(
        "Please remember that I prefer detailed code examples over high-level explanations.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    show_profile(user_id)

    # --- Conversation 4: Verify recall ---
    print("=" * 60)
    print("Conversation 4: Test recall")
    print("=" * 60)
    agent.print_response(
        "Can you help me with a database query? Use what you know about my preferences.",
        user_id=user_id,
        session_id="session_4",
        stream=True,
    )
