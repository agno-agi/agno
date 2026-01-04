"""
Advanced: Curator Maintenance
=============================
Keeping memories healthy with pruning and deduplication.

Over time, memory stores can accumulate:
- Stale data that's no longer relevant
- Duplicate entries saying the same thing
- Low-quality observations

The Curator provides maintenance operations:
- prune(): Remove old memories by age or count
- deduplicate(): Remove duplicate entries

Currently supports: UserProfile memories
Future: Entity memory, learned knowledge

Run:
    python cookbook/15_learning/advanced/02_curator_maintenance.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Learning
# ============================================================================
agent = Agent(
    name="Curator Demo Agent",
    model=model,
    db=db,
    instructions="You are a helpful assistant that remembers things about users.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Create Memories for Pruning
# ============================================================================
def demo_setup_memories():
    """Create some memories to demonstrate pruning."""
    print("=" * 60)
    print("Setup: Creating memories for demonstration")
    print("=" * 60)

    user = "curator_demo@example.com"

    memories = [
        "My favorite color is blue.",
        "I work at TechCorp.",
        "I like Python programming.",
        "I prefer dark mode.",
        "My favorite color is blue.",  # Duplicate
        "I'm working on a machine learning project.",
        "I like Python programming.",  # Duplicate
        "I drink coffee every morning.",
        "My favorite color is BLUE!",  # Near-duplicate (different case)
    ]

    for memory in memories:
        agent.print_response(
            f"Remember this: {memory}",
            user_id=user,
            session_id="setup_session",
            stream=True,
        )

    print("\n✅ Memories created\n")
    return user


# ============================================================================
# Demo: View Current Memories
# ============================================================================
def demo_view_memories(user_id: str):
    """Show current state of memories."""
    print("=" * 60)
    print("Current Memories (Before Maintenance)")
    print("=" * 60)

    agent.print_response(
        "List everything you remember about me.",
        user_id=user_id,
        session_id="view_session",
        stream=True,
    )


# ============================================================================
# Demo: Deduplicate Memories
# ============================================================================
def demo_deduplicate(user_id: str):
    """Remove duplicate memories."""
    print("\n" + "=" * 60)
    print("Demo: Deduplication")
    print("=" * 60)

    # Access curator through the learning machine
    learning = agent.learning
    
    print("\nRunning deduplication...")
    try:
        removed = learning.curator.deduplicate(user_id=user_id)
        print(f"✅ Removed {removed} duplicate memories")
    except Exception as e:
        print(f"Note: Curator operation: {e}")
        print("(Curator is available when database tables are properly set up)")


# ============================================================================
# Demo: Prune by Count
# ============================================================================
def demo_prune_by_count(user_id: str):
    """Keep only N most recent memories."""
    print("\n" + "=" * 60)
    print("Demo: Prune by Count (Keep 5 Most Recent)")
    print("=" * 60)

    learning = agent.learning
    
    print("\nRunning prune(max_count=5)...")
    try:
        removed = learning.curator.prune(user_id=user_id, max_count=5)
        print(f"✅ Removed {removed} old memories")
    except Exception as e:
        print(f"Note: Curator operation: {e}")


# ============================================================================
# Demo: Prune by Age
# ============================================================================
def demo_prune_by_age(user_id: str):
    """Remove memories older than N days."""
    print("\n" + "=" * 60)
    print("Demo: Prune by Age (Remove > 90 days old)")
    print("=" * 60)

    learning = agent.learning
    
    print("\nRunning prune(max_age_days=90)...")
    try:
        removed = learning.curator.prune(user_id=user_id, max_age_days=90)
        print(f"✅ Removed {removed} old memories")
    except Exception as e:
        print(f"Note: Curator operation: {e}")


# ============================================================================
# Curator Usage Guide
# ============================================================================
def usage_guide():
    """Print curator usage examples."""
    print("\n" + "=" * 60)
    print("Curator Usage Guide")
    print("=" * 60)
    print("""
# Access curator through the learning machine
learning = agent.learning

# Remove exact duplicate memories
removed = learning.curator.deduplicate(user_id="alice")

# Keep only 100 most recent memories
removed = learning.curator.prune(user_id="alice", max_count=100)

# Remove memories older than 90 days
removed = learning.curator.prune(user_id="alice", max_age_days=90)

# Combine: Remove old AND keep max count
removed = learning.curator.prune(
    user_id="alice",
    max_age_days=90,
    max_count=100,
)

# Production pattern: Run maintenance periodically
import schedule

def daily_maintenance():
    for user_id in get_active_users():
        learning.curator.deduplicate(user_id=user_id)
        learning.curator.prune(user_id=user_id, max_age_days=180, max_count=500)

schedule.every().day.at("03:00").do(daily_maintenance)
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    user_id = demo_setup_memories()
    demo_view_memories(user_id)
    demo_deduplicate(user_id)
    demo_prune_by_count(user_id)
    demo_prune_by_age(user_id)
    usage_guide()

    print("\n" + "=" * 60)
    print("✅ Curator keeps memories healthy")
    print("   deduplicate() removes duplicates")
    print("   prune() removes old/excess memories")
    print("=" * 60)
