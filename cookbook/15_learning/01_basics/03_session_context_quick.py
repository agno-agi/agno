"""
Session Context Quick Start
===========================
Session state tracking in 30 lines.

Session Context captures state for the current conversation:
- Summary of what's happened
- (Optional) Goals, plans, and progress

Run:
    python cookbook/15_learning/basics/03_session_context_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIChat

# Setup
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Agent with session context
agent = Agent(
    name="Session Context Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        session_context=SessionContextConfig(
            enable_planning=False,  # Summary only (faster)
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "session_user@example.com"
    session = "my_session"

    # Multi-turn conversation
    print("\n--- Turn 1 ---\n")
    agent.print_response(
        "I'm building a REST API for a todo app. Help me design it.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Turn 2 ---\n")
    agent.print_response(
        "What endpoints should I create for tasks?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Turn 3: Session summary ---\n")
    agent.print_response(
        "Summarize what we've discussed so far.",
        user_id=user,
        session_id=session,
        stream=True,
    )
