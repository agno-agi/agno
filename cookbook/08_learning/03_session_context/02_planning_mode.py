"""
Session Context: Planning Mode (Deep Dive)
==========================================
Goal, plan, and progress tracking for task-oriented sessions.

Planning mode adds:
- Goal: What the user is trying to achieve
- Plan: Steps to reach the goal
- Progress: Completed steps

Use for task-oriented agents where tracking progress matters.

Compare with: 01_summary_mode.py for summary-only (faster).
See also: 01_basics/3b_session_context_planning.py for the basics.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal, plan, progress
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run: Task Planning
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "deploy@example.com"
    session_id = "deploy_session"

    # Step 1: State the goal
    print("\n" + "=" * 60)
    print("STEP 1: State the goal")
    print("=" * 60 + "\n")

    agent.print_response(
        "I need to deploy a new Python web app to AWS. Help me plan this.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Step 2: Complete first task
    print("\n" + "=" * 60)
    print("STEP 2: First task done")
    print("=" * 60 + "\n")

    agent.print_response(
        "Done! I've created the Dockerfile and it builds successfully.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Step 3: More progress
    print("\n" + "=" * 60)
    print("STEP 3: More progress")
    print("=" * 60 + "\n")

    agent.print_response(
        "ECR repository is set up and I've pushed the image.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Step 4: What's next?
    print("\n" + "=" * 60)
    print("STEP 4: What's next?")
    print("=" * 60 + "\n")

    agent.print_response(
        "What should I do next?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)
