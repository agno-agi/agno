"""
Learning Modes Comparison
===========================================
LearningMachine supports three modes for controlling when learning happens:

BACKGROUND: Automatic extraction after each response
- Best for: User profiles, session summaries
- Pros: No user action needed, comprehensive capture
- Cons: May save unnecessary info, extra LLM calls

AGENTIC: Agent decides via tools when to save
- Best for: Learnings, agent-controlled memory
- Pros: Agent judgment on what's valuable
- Cons: Agent might miss important info

PROPOSE: Agent proposes, user confirms before saving
- Best for: High-value insights, quality control
- Pros: Human validation, highest quality
- Cons: Requires user interaction

This cookbook demonstrates all three side-by-side.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="mode_comparison_learnings"),
)

# =============================================================================
# BACKGROUND Mode Agent
# =============================================================================
background_agent = Agent(
    name="Background Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Automatic extraction
        ),
    ),
    markdown=True,
)

# =============================================================================
# AGENTIC Mode Agent
# =============================================================================
agentic_agent = Agent(
    name="Agentic Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,  # Agent decides
            enable_agent_tools=True,  # Updated from enable_tool
        ),
    ),
    markdown=True,
)

# =============================================================================
# PROPOSE Mode Agent (for learnings)
# =============================================================================
propose_agent = Agent(
    name="Propose Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,  # Proposes, waits for confirmation
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def show_profile(agent, user_id: str, label: str):
    """Display what an agent learned about a user."""
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print(f"\n📝 {label} memories:")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print(f"\n📝 {label}: No memories yet")


# =============================================================================
# Demo: Compare modes
# =============================================================================
if __name__ == "__main__":
    user_message = (
        "Hi! I'm a senior software engineer at Google working on search infrastructure. "
        "I specialize in distributed systems and love writing Go code. "
        "I prefer detailed technical explanations."
    )

    # --- BACKGROUND mode ---
    print("=" * 60)
    print("BACKGROUND Mode: Automatic extraction")
    print("=" * 60)
    print("The agent will automatically extract user info after responding.\n")

    background_agent.print_response(
        user_message,
        user_id="mode_test_user",
        session_id="background_session",
        stream=True,
    )
    show_profile(background_agent, "mode_test_user", "BACKGROUND")

    # --- AGENTIC mode ---
    print("\n" + "=" * 60)
    print("AGENTIC Mode: Agent decides when to save")
    print("=" * 60)
    print("The agent chooses whether to call update_user_memory.\n")

    agentic_agent.print_response(
        user_message,
        user_id="mode_test_user",
        session_id="agentic_session",
        stream=True,
    )
    show_profile(agentic_agent, "mode_test_user", "AGENTIC")

    # --- PROPOSE mode ---
    print("\n" + "=" * 60)
    print("PROPOSE Mode: Agent proposes, user confirms")
    print("=" * 60)
    print("The agent will propose a learning and wait for 'yes'.\n")

    propose_agent.print_response(
        "What's the best way to handle distributed consensus? "
        "I've been researching Raft vs Paxos.",
        user_id="mode_test_user",
        session_id="propose_session",
        stream=True,
    )

    print("\n--- Simulating user confirmation ---")
    propose_agent.print_response(
        "yes",
        user_id="mode_test_user",
        session_id="propose_session",
        stream=True,
    )

    # --- Summary ---
    print("\n" + "=" * 60)
    print("Summary: When to use each mode")
    print("=" * 60)
    print("""
    BACKGROUND:
    - User profiles (capture everything automatically)
    - Session summaries (no user action needed)
    - High recall, lower precision

    AGENTIC:
    - Learnings (agent judges what's valuable)
    - When you trust the agent's judgment
    - Balanced recall and precision

    PROPOSE:
    - High-value insights
    - When quality matters more than quantity
    - Human validation ensures accuracy
    """)
