"""
Session Context: Planning Mode
==============================
Session Context tracks the current conversation's state:
- What's been discussed
- Current goals and their status
- Active plans and progress

Planning mode (enable_planning=True) adds structured goal tracking -
summary plus goal, plan steps, and progress markers.

Compare with: 4_session_context_summary.py for lightweight tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Planning mode: Tracks goals, plans, and progress in addition to summary.
# Good for task-oriented conversations where you want structured progress.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="Help users accomplish their goals. Track progress and next steps.",
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    markdown=True,
)

# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    user_id = "planner@example.com"
    session_id = "migration_project"

    # Turn 1: Define a goal
    print("\n" + "=" * 60)
    print("TURN 1: Define goal")
    print("=" * 60 + "\n")

    agent.print_response(
        "I need to migrate our app from MySQL to PostgreSQL. What are the main steps?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning.session_context_store.print(session_id=session_id)

    # Turn 2: Work on first step
    print("\n" + "=" * 60)
    print("TURN 2: First step detail")
    print("=" * 60 + "\n")

    agent.print_response(
        "Let's start with schema analysis. What should I look for?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning.session_context_store.print(session_id=session_id)

    # Turn 3: Progress update
    print("\n" + "=" * 60)
    print("TURN 3: Mark progress")
    print("=" * 60 + "\n")

    agent.print_response(
        "Done analyzing the schema. What's next?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning.session_context_store.print(session_id=session_id)
