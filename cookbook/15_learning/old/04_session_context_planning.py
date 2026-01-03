"""
Session Context with Planning Mode
===========================================
Enable `enable_planning=True` to track more than just summaries:

- Goal: What the user is trying to accomplish
- Plan: Steps to achieve the goal
- Progress: Which steps have been completed

Perfect for:
- Project planning sessions
- Multi-step tutorials
- Task breakdowns
- Workflow tracking
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Create Learning Agent with Planning Mode
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=True,
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal/plan/progress
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show session context with planning
# =============================================================================
def show_context(session_id: str):
    """Display the stored session context with planning details."""
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    if context:
        print("\n📋 Session Context:")
        if context.summary:
            print(f"   Summary: {context.summary[:100]}...")
        if context.goal:
            print(f"   🎯 Goal: {context.goal}")
        if context.plan:
            print(f"   📝 Plan:")
            for i, step in enumerate(context.plan, 1):
                print(f"      {i}. {step}")
        if context.progress:
            print(f"   ✅ Progress:")
            for item in context.progress:
                print(f"      ✓ {item}")
    else:
        print("\n📋 No session context yet.")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "dave@example.com"
    session_id = "project_planning"

    # --- Turn 1: Define the goal ---
    print("=" * 60)
    print("Turn 1: Define the goal")
    print("=" * 60)
    agent.print_response(
        "I want to build a REST API for my startup's inventory management system. "
        "It needs to handle products, orders, and customers. Can you help me plan this?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 2: Create the plan ---
    print("=" * 60)
    print("Turn 2: Create a plan")
    print("=" * 60)
    agent.print_response(
        "That sounds good. Let's break it down into steps. I'm using FastAPI and PostgreSQL.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 3: Complete step 1 ---
    print("=" * 60)
    print("Turn 3: Work on first step")
    print("=" * 60)
    agent.print_response(
        "I've set up the project structure and installed FastAPI. Show me the database models.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 4: Complete step 2 ---
    print("=" * 60)
    print("Turn 4: Complete another step")
    print("=" * 60)
    agent.print_response(
        "Done! The database models are created. Now let's build the API endpoints for products.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 5: Check progress ---
    print("=" * 60)
    print("Turn 5: Review progress")
    print("=" * 60)
    agent.print_response(
        "Where are we in the plan? What's left to do?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)
