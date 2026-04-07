"""
Session Context: Summary Mode (Deep Dive)
=========================================
Running summary of conversation state.

Summary mode maintains a running summary of the conversation that
persists across reconnections. Each turn, the summary is updated
to include the new information.

Compare with: 02_planning_mode.py for goal/plan tracking.
See also: 01_basics/3a_session_context_summary.py for the basics.
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
            enable_planning=False,  # Summary only
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run: Multi-Turn Summary
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "debug@example.com"
    session_id = "debug_session"

    # Turn 1: Initial question
    print("\n" + "=" * 60)
    print("TURN 1: Initial question")
    print("=" * 60 + "\n")

    agent.print_response(
        "I'm debugging a memory leak in my Python FastAPI server. "
        "It processes large JSON payloads.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 2: More context
    print("\n" + "=" * 60)
    print("TURN 2: More context")
    print("=" * 60 + "\n")

    agent.print_response(
        "The memory grows even when there's no traffic. "
        "I've checked for unclosed file handles already.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Turn 3: Follow-up
    print("\n" + "=" * 60)
    print("TURN 3: Follow-up")
    print("=" * 60 + "\n")

    agent.print_response(
        "Could it be related to Pydantic model caching?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id=session_id)

    # Simulate reconnection
    print("\n" + "=" * 60)
    print("TURN 4: Recall after 'reconnection'")
    print("=" * 60 + "\n")

    agent.print_response(
        "What were we debugging?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
