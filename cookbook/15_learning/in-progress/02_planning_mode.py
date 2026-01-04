"""
Session Context: Planning Mode
==============================
Goal → Plan → Progress tracking.

With `enable_planning=True`, Session Context tracks:
- Summary: What's happened so far
- Goal: What we're trying to achieve
- Plan: Steps to achieve the goal
- Progress: Which steps are complete

This is powerful for task-oriented agents that need to:
- Break down complex tasks
- Track progress across turns
- Resume interrupted work

⚠️ Note: Planning mode adds latency because it extracts more data.
Only use for task-oriented agents where tracking is valuable.

Run:
    python cookbook/15_learning/session_context/02_planning_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Planning Mode
# ============================================================================
agent = Agent(
    name="Planning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant that breaks down complex tasks into steps.

When given a goal:
1. Understand what the user wants to achieve
2. Create a clear, sequential plan
3. Work through steps one at a time
4. Track progress as you go

Be explicit about:
- What the goal is
- What the plan looks like
- Which step you're on
- What's been completed
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
# Demo: Task with Planning
# ============================================================================
def demo_planning():
    """Show goal/plan/progress tracking."""
    print("=" * 60)
    print("Demo: Task with Planning")
    print("=" * 60)

    user = "planning_demo@example.com"
    session = "planning_session_001"

    # Set the goal
    print("\n--- Step 1: Define the goal ---\n")
    agent.print_response(
        "Help me set up a new Python project with proper structure, "
        "tests, linting, and GitHub Actions CI.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Work on first step
    print("\n--- Step 2: First step ---\n")
    agent.print_response(
        "I've created the directory structure. What's next?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Work on second step
    print("\n--- Step 3: Second step ---\n")
    agent.print_response(
        "I've added the pyproject.toml with basic dependencies. "
        "What should I do for testing?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Check progress
    print("\n--- Step 4: Check progress ---\n")
    agent.print_response(
        "Can you summarize our progress? What's left to do?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Resume Interrupted Task
# ============================================================================
def demo_resume_task():
    """Show resuming a task after interruption."""
    print("\n" + "=" * 60)
    print("Demo: Resume Interrupted Task")
    print("=" * 60)

    user = "resume_demo@example.com"
    session = "resume_session_001"

    # Start a task
    print("\n--- Start task ---\n")
    agent.print_response(
        "Help me deploy a FastAPI app to AWS. This is my first time.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Make some progress
    print("\n--- Make progress ---\n")
    agent.print_response(
        "OK, I've created the Dockerfile. What's the next step?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Simulate interruption
    print("\n" + "-" * 40)
    print("User goes away for a while...")
    print("-" * 40)

    # Resume
    print("\n--- Resume later ---\n")
    agent.print_response(
        "Hey, I'm back. Where were we?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Adapting the Plan
# ============================================================================
def demo_plan_adaptation():
    """Show how plans can be modified mid-execution."""
    print("\n" + "=" * 60)
    print("Demo: Plan Adaptation")
    print("=" * 60)

    user = "adapt_demo@example.com"
    session = "adapt_session_001"

    # Initial plan
    print("\n--- Initial plan ---\n")
    agent.print_response(
        "Help me migrate my database from SQLite to PostgreSQL.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Discover complication
    print("\n--- Complication discovered ---\n")
    agent.print_response(
        "Wait, I just realized I also need to handle full-text search. "
        "SQLite uses FTS5, but PostgreSQL has different full-text features. "
        "Can we update the plan?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Continue with adapted plan
    print("\n--- Continue with updated plan ---\n")
    agent.print_response(
        "OK, I've backed up the SQLite database. What's the next step "
        "considering the full-text search requirements?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_planning()
    demo_resume_task()
    demo_plan_adaptation()

    print("\n" + "=" * 60)
    print("✅ Planning mode tracks goal → plan → progress")
    print("   Great for task-oriented agents")
    print("   Plans can adapt as requirements change")
    print("=" * 60)
