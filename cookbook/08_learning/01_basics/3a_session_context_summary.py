"""
Session Context: Summary Mode
=============================
Session Context tracks the current conversation's state:
- What's been discussed
- Key decisions made
- Important context

Summary mode provides lightweight tracking - a running summary without goal/plan structure.

Compare with: 3b_session_context_planning.py for goal-oriented tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Summary mode: Just tracks what's been discussed, no planning overhead.
# Good for general conversations where you want continuity without structure.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="Be very concise. Give brief answers in 1-2 sentences.",
    learning=LearningMachine(session_context=True),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "session@example.com"
    session_id = "api_design"

    # Turn 1: Start discussion
    print("\n" + "=" * 60)
    print("TURN 1: Start discussion")
    print("=" * 60 + "\n")

    agent.print_response(
        "I'm designing a REST API for a todo app. PUT or PATCH for updates?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 2: Follow-up
    print("\n" + "=" * 60)
    print("TURN 2: Follow-up question")
    print("=" * 60 + "\n")

    agent.print_response(
        "What URL structure for that endpoint?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 3: Test recall
    print("\n" + "=" * 60)
    print("TURN 3: Test context recall")
    print("=" * 60 + "\n")

    agent.print_response(
        "What did we decide?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)
