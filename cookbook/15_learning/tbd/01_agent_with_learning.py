"""
Agent with Learning — The Simplest Way
=======================================
This is the simplest way to add learning capabilities to an agent.

Just provide a database, set learning=True, and LearningMachine auto-enables:
- ✅ User Profile: Remembers facts about users across sessions
- ✅ Session Context: Tracks what's happening in the current session

Provide a knowledge base, and LearningMachine will also capture:
- ✅ Learnings: Saves and recalls reusable insights

Run this example:
    python cookbook/learning/01_agent_with_learning.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import LearningMachine
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Database for storing user profiles and session context
db = PostgresDb(db_url=db_url)

# Knowledge base for storing learnings (semantic search)
learnings_kb = Knowledge(
    name="Agent Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Model for the agent and for extraction
model = OpenAIChat(id="gpt-5.2")

# =============================================================================
# Create the Agent — Dead Simple!
# =============================================================================

user_profile_agent = Agent(
    name="User Profile Learning Agent",
    model=model,
    db=db,
    # This is all you need to enable user profile learnings!
    learning=True,
    # Standard agent settings
    add_datetime_to_context=True,
    add_history_to_context=True,
    markdown=True,
)

learning_agent = Agent(
    name="Learning Agent",
    model=model,
    db=db,
    # This is all you need to enable knowledge learnings!
    learning=LearningMachine(knowledge=learnings_kb),
    # Standard agent settings
    add_datetime_to_context=True,
    add_history_to_context=True,
    markdown=True,
)


# =============================================================================
# Demo: Show Learning in Action
# =============================================================================


def demo_user_memory():
    """Show how the agent remembers user information."""
    print("=" * 60)
    print("Demo: User Memory")
    print("=" * 60)

    user_id = "alice@example.com"
    session_1 = "session_1"
    session_2 = "session_2"

    # First session — introduce yourself
    print("\n--- First Message ---")
    user_profile_agent.print_response(
        "Hi! I'm Alice, a data scientist at Netflix. "
        "I work on recommendation systems and prefer Python.",
        user_id=user_id,
        session_id=session_1,
        stream=True,
    )

    # Second session — agent should remember Alice
    # Note: because we change the session_id, the agent does not use conversation history, but uses the user profile to answer the question.
    print("\n--- Second Message (agent remembers!) ---")
    user_profile_agent.print_response(
        "Can you suggest a good approach for A/B testing recommendations?",
        user_id=user_id,
        session_id=session_2,
        stream=True,
    )


# def demo_session_context():
#     """Show how session context tracks conversation state."""
#     print("\n" + "=" * 60)
#     print("Demo: Session Context")
#     print("=" * 60)

#     user_id = "bob@example.com"
#     session_id = "planning_session_001"

#     # Start a multi-step task
#     print("\n--- Starting a project ---")
#     agent.print_response(
#         "I want to build a CLI tool for managing Docker containers. "
#         "Can you help me plan it out?",
#         user_id=user_id,
#         session_id=session_id,
#         stream=True,
#     )

#     # Continue the conversation
#     print("\n--- Continuing the plan ---")
#     agent.print_response(
#         "Great! Let's start with listing containers. What commands do I need?",
#         user_id=user_id,
#         session_id=session_id,
#         stream=True,
#     )

#     # Ask about progress
#     print("\n--- Checking context ---")
#     agent.print_response(
#         "What have we covered so far?",
#         user_id=user_id,
#         session_id=session_id,
#         stream=True,
#     )


# def demo_learnings():
#     """Show how learnings are saved and recalled."""
#     print("\n" + "=" * 60)
#     print("Demo: Learnings")
#     print("=" * 60)

#     user_id = "carol@example.com"

#     # Ask something that might generate a learning
#     print("\n--- Query that might generate insights ---")
#     agent.print_response(
#         "What are the key metrics to evaluate when comparing cloud providers? "
#         "I'm deciding between AWS, GCP, and Azure for a startup.",
#         user_id=user_id,
#         stream=True,
#     )

#     # Later, ask something related — should recall the learning
#     print("\n--- Related query (should recall learning) ---")
#     agent.print_response(
#         "I'm also looking at DigitalOcean. How should I compare it?",
#         user_id=user_id,
#         stream=True,
#     )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        demos = {
            "memory": demo_user_memory,
            # "context": demo_session_context,
            # "learnings": demo_learnings,
        }

        if demo_name == "all":
            demo_user_memory()
            # demo_session_context()
            # demo_learnings()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🧠 Agent with Learning — The Simplest Way")
        print("=" * 60)
        print("\nAvailable demos:")
        print("  memory      - User memory across sessions")
        print("  context     - Session context tracking")
        print("  learnings   - Save and recall insights")
        print("  all         - Run all demos")
        print("\nUsage: python 01_agent_with_learning.py <demo>")
        print("\nRunning 'memory' demo by default...\n")
        demo_user_memory()
