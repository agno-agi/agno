"""
Knowledge Learning — Add a Knowledge Base
==========================================
Building on user profile learning, add a knowledge base to capture
reusable insights that persist and can be searched semantically.

What you get with LearningMachine(knowledge=kb):
- ✅ User Profile: Remembers facts about users (default)
- ✅ Learnings: Saves and recalls reusable insights via semantic search

The agent gets TWO tools for learnings:
- save_learning: Save insights worth remembering
- search_learnings: Find relevant past learnings

Note: Learnings are shared across users — they're general knowledge,
not personal info. Great for capturing best practices, patterns, etc.

Run this example:
    python cookbook/learning/03_knowledge_learning.py
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

# Database for user profiles and session context
db = PostgresDb(db_url=db_url)

# Knowledge base for storing learnings (enables semantic search)
learnings_kb = Knowledge(
    name="Agent Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Model for the agent
model = OpenAIChat(id="gpt-4o")

# =============================================================================
# Create the Agent — Add knowledge to enable Learnings!
# =============================================================================

agent = Agent(
    name="Learning Assistant",
    model=model,
    db=db,
    # Just add knowledge and learnings are auto-enabled!
    learning=LearningMachine(knowledge=learnings_kb),
    # Standard agent settings
    add_datetime_to_context=True,
    markdown=True,
)


# =============================================================================
# Demo: Capturing and Recalling Learnings
# =============================================================================


def demo_save_learning():
    """Show the agent saving a reusable learning."""
    print("=" * 60)
    print("Demo: Agent Saves a Learning")
    print("=" * 60)

    user_id = "dev@example.com"
    session_id = "learning_session"

    print("\n📝 User asks a question that generates insight")
    print("-" * 40)

    agent.print_response(
        "What's the best way to handle API rate limits in production? "
        "I keep getting 429 errors from external services.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n💡 The agent may have saved a learning about rate limiting.")
    print("   Let's test if it can recall it later...")


def demo_recall_learning():
    """Show the agent recalling a previously saved learning."""
    print("\n" + "=" * 60)
    print("Demo: Agent Recalls a Learning")
    print("=" * 60)

    # Different user, different session — but learnings are shared!
    user_id = "another_dev@example.com"
    session_id = "new_session"

    print("\n📝 Different user asks a related question")
    print("-" * 40)

    agent.print_response(
        "My app crashes when third-party APIs are slow. How should I handle this?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n💡 The agent should use search_learnings to find relevant insights")
    print("   from previous conversations (even with different users).")


def demo_explicit_save():
    """Show explicitly asking the agent to save something."""
    print("\n" + "=" * 60)
    print("Demo: Explicitly Save a Learning")
    print("=" * 60)

    user_id = "senior_dev@example.com"
    session_id = "explicit_save_session"

    print("\n📝 User explicitly asks agent to remember something")
    print("-" * 40)

    agent.print_response(
        "Here's something important we learned on our team: "
        "Always use database transactions when updating multiple tables, "
        "even if you think the operations are independent. We lost data "
        "twice before learning this. Please save this as a learning.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )


def demo_search_learnings():
    """Show searching for learnings directly."""
    print("\n" + "=" * 60)
    print("Demo: Search for Learnings")
    print("=" * 60)

    user_id = "curious_dev@example.com"
    session_id = "search_session"

    print("\n📝 User asks agent to search for learnings")
    print("-" * 40)

    agent.print_response(
        "Search your learnings for anything related to database best practices.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )


def demo_combined_memory():
    """Show user profile + learnings working together."""
    print("\n" + "=" * 60)
    print("Demo: User Profile + Learnings Together")
    print("=" * 60)

    user_id = "fullstack@example.com"

    # Session 1: Establish user context
    print("\n📝 Session 1: User introduces themselves")
    print("-" * 40)

    agent.print_response(
        "Hi! I'm a fullstack developer working mostly with React and Node.js. "
        "I'm pretty senior but always looking to learn best practices.",
        user_id=user_id,
        session_id="intro_session",
        stream=True,
    )

    # Session 2: Ask question that combines profile + learnings
    print("\n\n📝 Session 2: Question that uses both profile and learnings")
    print("-" * 40)

    agent.print_response(
        "What database patterns should I be aware of for my stack?",
        user_id=user_id,
        session_id="combined_session",
        stream=True,
    )

    print("\n\n💡 The agent should:")
    print("   1. Remember the user is a fullstack React/Node developer (user profile)")
    print("   2. Search for relevant learnings about databases")
    print("   3. Tailor the response to their experience level")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    demos = {
        "save": demo_save_learning,
        "recall": demo_recall_learning,
        "explicit": demo_explicit_save,
        "search": demo_search_learnings,
        "combined": demo_combined_memory,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]

        if demo_name == "all":
            demo_save_learning()
            demo_recall_learning()
            demo_explicit_save()
            demo_search_learnings()
            demo_combined_memory()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🧠 Knowledge Learning — Add a Knowledge Base")
        print("=" * 60)
        print("\nThis cookbook shows LearningMachine(knowledge=kb) in action.")
        print("\nAvailable demos:")
        print("  save      - Agent saves a learning from conversation")
        print("  recall    - Agent recalls learning for a related question")
        print("  explicit  - User explicitly asks agent to save something")
        print("  search    - Agent searches learnings on demand")
        print("  combined  - User profile + learnings working together")
        print("  all       - Run all demos")
        print("\nUsage: python 03_knowledge_learning.py <demo>")
        print("\nRunning 'save' demo by default...\n")
        demo_save_learning()
