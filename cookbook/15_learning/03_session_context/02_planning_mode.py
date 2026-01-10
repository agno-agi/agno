"""
Session Context: Planning Mode
==============================
Goal → Plan → Progress tracking for task-oriented sessions.

Planning mode adds structure to session context:
- **Goal**: What the user is trying to achieve
- **Plan**: Steps to reach the goal
- **Progress**: Completed steps
- **Summary**: Overview of the conversation

Use for task-oriented agents where tracking progress matters.

⚠️ Note: Planning mode adds latency (extra LLM call per message).
Only use when goal/plan/progress tracking is valuable.

Run:
    python cookbook/15_learning/session_context/02_planning_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# ============================================================================
# Agent with Planning Mode
# ============================================================================
agent = Agent(
    name="Planning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant that tracks task progress.

When users describe a goal:
1. Help them break it into steps
2. Track which steps are completed
3. Guide them through the remaining steps

Be proactive about updating progress as work is completed.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal, plan, progress
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper: Show full context
# ============================================================================
def show_full_context(session_id: str) -> None:
    """Display goal, plan, progress, and summary."""
    store = agent.learning.session_context_store
    context = store.get(session_id=session_id) if store else None

    print("\n" + "-" * 40)
    print("📋 Full Session Context:")
    print("-" * 40)

    if not context:
        print("  (no context yet)")
        return

    print(f"\n  🎯 Goal: {context.goal or '(not set)'}")

    if context.plan:
        print("\n  📝 Plan:")
        for i, step in enumerate(context.plan, 1):
            print(f"     {i}. {step}")
    else:
        print("\n  📝 Plan: (not set)")

    if context.progress:
        print("\n  ✅ Progress:")
        for item in context.progress:
            print(f"     ✓ {item}")
    else:
        print("\n  ✅ Progress: (none yet)")

    print(f"\n  📄 Summary: {context.summary or '(none)'}")


# ============================================================================
# Demo: Task with Plan
# ============================================================================
def demo_task_with_plan():
    """Show goal, plan, and progress tracking."""
    print("=" * 60)
    print("Demo: Task with Planning")
    print("=" * 60)

    user = "planning_demo@example.com"
    session = "planning_session_001"

    # Step 1: State the goal
    print("\n--- Step 1: State the goal ---\n")
    agent.print_response(
        "I need to deploy a new Python web app to AWS. Help me plan and track this.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)

    # Step 2: Complete first task
    print("\n--- Step 2: First task done ---\n")
    agent.print_response(
        "I've created the Dockerfile and it builds successfully.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)

    # Step 3: Continue progress
    print("\n--- Step 3: More progress ---\n")
    agent.print_response(
        "ECR repository is set up and I've pushed the image.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)

    # Step 4: Ask what's next
    print("\n--- Step 4: What's next? ---\n")
    agent.print_response(
        "What should I do next?",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)


# ============================================================================
# Demo: Complex Multi-Step Task
# ============================================================================
def demo_complex_task():
    """Show planning for a complex, multi-step task."""
    print("\n" + "=" * 60)
    print("Demo: Complex Multi-Step Task")
    print("=" * 60)

    user = "complex_demo@example.com"
    session = "complex_session_001"

    # Define complex goal
    print("\n--- Define complex goal ---\n")
    agent.print_response(
        "I need to migrate our database from MySQL to PostgreSQL. "
        "This includes schema conversion, data migration, "
        "application updates, and testing. Help me plan this.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)

    # Make progress
    print("\n--- Report progress ---\n")
    agent.print_response(
        "I've analyzed the MySQL schema and identified the incompatibilities. "
        "Found 3 tables using MySQL-specific types that need conversion.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)


# ============================================================================
# Demo: Goal Change Mid-Session
# ============================================================================
def demo_goal_change():
    """Show handling a goal change during a session."""
    print("\n" + "=" * 60)
    print("Demo: Goal Change Mid-Session")
    print("=" * 60)

    user = "change_demo@example.com"
    session = "change_session_001"

    # Initial goal
    print("\n--- Initial goal ---\n")
    agent.print_response(
        "Help me set up a CI/CD pipeline for my project.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)

    # Change goal
    print("\n--- Change goal ---\n")
    agent.print_response(
        "Actually, let's switch focus. I need to fix a critical bug first. "
        "Users are seeing 500 errors on the checkout page.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_full_context(session)


# ============================================================================
# When to Use Planning Mode
# ============================================================================
def planning_mode_guide():
    """Print guidance on when to use planning mode."""
    print("\n" + "=" * 60)
    print("When to Use Planning Mode")
    print("=" * 60)
    print("""
✅ USE PLANNING MODE FOR:

- Task management agents
- Project assistants
- Learning/tutorial systems
- Debugging assistants
- Multi-step workflows
- Onboarding processes

❌ DON'T USE PLANNING MODE FOR:

- Simple Q&A
- Chat assistants
- Information lookup
- Single-turn interactions
- Latency-sensitive applications

💡 CONSIDERATIONS:

- Planning mode adds an extra LLM call per message
- Best for sessions that span multiple interactions
- Goal/plan/progress are extracted automatically
- Summary-only mode is faster if you don't need tracking

CONFIGURATION:

    SessionContextConfig(
        enable_planning=True,   # Full tracking
        # vs
        enable_planning=False,  # Summary only (faster)
    )
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_task_with_plan()
    demo_complex_task()
    demo_goal_change()
    planning_mode_guide()

    print("\n" + "=" * 60)
    print("✅ Planning mode tracks:")
    print("   🎯 Goal - What the user wants to achieve")
    print("   📝 Plan - Steps to reach the goal")
    print("   ✅ Progress - Completed steps")
    print("   📄 Summary - Conversation overview")
    print("=" * 60)
