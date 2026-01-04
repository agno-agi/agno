"""
Combined: User Profile + Session Context
========================================
Long-term memory + current session state.

This is the most common combination:
- **User Profile**: Who is this person? What do they like?
- **Session Context**: What are we working on right now?

Together they provide:
- Personalized responses based on user history
- Continuity within the current task
- Context that persists even with message truncation

Run:
    python cookbook/15_learning/combined/01_user_plus_session.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with User Profile + Session Context
# ============================================================================
agent = Agent(
    name="Personal Assistant",
    model=model,
    db=db,
    instructions="""\
You are a personal assistant that remembers users and tracks tasks.

You combine two types of context:
1. User Profile: Long-term knowledge about the user
2. Session Context: Current task state and progress

Use user knowledge to personalize your responses.
Use session context to maintain task continuity.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: New User, First Session
# ============================================================================
def demo_new_user():
    """Show first interaction with a new user."""
    print("=" * 60)
    print("Demo: New User, First Session")
    print("=" * 60)

    user = "new_user@example.com"
    session = "intro_session"

    print("\n--- Introduction ---\n")
    agent.print_response(
        "Hi! I'm Jordan, a frontend developer at a startup. "
        "I mainly work with React and TypeScript. "
        "I prefer detailed explanations with code examples.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Start a task ---\n")
    agent.print_response(
        "Help me optimize the performance of my React app. "
        "Users are complaining about slow load times.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Same User, New Session
# ============================================================================
def demo_returning_user():
    """Show how user knowledge persists across sessions."""
    print("\n" + "=" * 60)
    print("Demo: Returning User, New Session")
    print("=" * 60)

    user = "new_user@example.com"  # Same user
    session = "new_task_session"  # New session

    print("\n--- New session (user should be recognized) ---\n")
    agent.print_response(
        "Hey, I have a different question today. "
        "What's the best state management approach for large apps?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n💡 Notice: Agent remembers user's tech stack (React/TypeScript)")
    print("   and preferences (detailed explanations with code)")


# ============================================================================
# Demo: Long Task with Session Context
# ============================================================================
def demo_long_task():
    """Show session context tracking a multi-step task."""
    print("\n" + "=" * 60)
    print("Demo: Long Task with Session Context")
    print("=" * 60)

    user = "task_user@example.com"
    session = "long_task_session"

    # User profile
    print("\n--- Quick intro ---\n")
    agent.print_response(
        "I'm Alex, a DevOps engineer. I like concise answers.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Start multi-step task
    print("\n--- Start task ---\n")
    agent.print_response(
        "Help me set up monitoring for our Kubernetes cluster. "
        "I need metrics, logs, and alerts.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Progress
    print("\n--- Progress update ---\n")
    agent.print_response(
        "I've set up Prometheus for metrics. What's next?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # More progress
    print("\n--- More progress ---\n")
    agent.print_response(
        "Grafana dashboards are done. Now I need logging.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Check progress
    print("\n--- Check overall progress ---\n")
    agent.print_response(
        "What have we completed and what's left?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: User Context Informs Session
# ============================================================================
def demo_context_interaction():
    """Show how user profile informs session interactions."""
    print("\n" + "=" * 60)
    print("Demo: User Context Informs Session")
    print("=" * 60)

    user = "senior_dev@example.com"
    session = "informed_session"

    # Establish user context
    print("\n--- Establish expertise level ---\n")
    agent.print_response(
        "I'm a senior engineer with 15 years of experience. "
        "I've built distributed systems at Google and Meta. "
        "Skip the basics, I want deep technical discussions.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Technical question - should get expert-level response
    print("\n--- Technical question ---\n")
    agent.print_response(
        "I'm designing a consensus algorithm for our distributed cache. "
        "Compare Raft vs Paxos for my use case: 3-5 nodes, strong consistency, "
        "high read throughput.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n💡 Response should be expert-level because user profile")
    print("   indicates senior engineer with distributed systems experience")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_new_user()
    demo_returning_user()
    demo_long_task()
    demo_context_interaction()

    print("\n" + "=" * 60)
    print("✅ User Profile + Session Context")
    print("   User Profile = who they are, persists forever")
    print("   Session Context = what we're doing now")
    print("=" * 60)
