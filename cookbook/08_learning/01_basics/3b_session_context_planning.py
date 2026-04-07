"""
Session Context: Planning Mode
==============================
Session Context tracks the current conversation's state:
- What's been discussed
- Current goals and their status
- Active plans and progress

Planning mode (enable_planning=True) adds structured goal tracking -
summary plus goal, plan steps, and progress markers.

Compare with: 3a_session_context_summary.py for lightweight tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Planning mode: Tracks goals, plans, and progress in addition to summary.
# Good for task-oriented conversations where you want structured progress.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="Be very concise. Give brief, actionable answers.",
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "planner@example.com"
    session_id = "deploy_app"

    # Turn 1: Set a goal with clear steps
    print("\n" + "=" * 60)
    print("TURN 1: Set goal")
    print("=" * 60 + "\n")

    agent.print_response(
        "Help me deploy a Python app to production. Give me 3 steps.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 2: Complete first step
    print("\n" + "=" * 60)
    print("TURN 2: Complete step 1")
    print("=" * 60 + "\n")

    agent.print_response(
        "Done with step 1. What's the command for step 2?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 3: Complete second step
    print("\n" + "=" * 60)
    print("TURN 3: Complete step 2")
    print("=" * 60 + "\n")

    agent.print_response(
        "Step 2 done. What's left?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)
