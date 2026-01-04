"""
Session Context Quick Start
===========================
Session state tracking in 30 lines.

Session Context captures what's happening in the current session:
- Summary of the conversation so far
- Goal (if planning enabled)
- Plan steps (if planning enabled)
- Progress (if planning enabled)

Key behavior: Context builds on itself. Even if message history is
truncated, the context persists and provides continuity.

Run:
    python cookbook/15_learning/basics/03_session_context_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIResponses(id="gpt-5.2")

# Agent with session context
agent = Agent(
    name="Session Context Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,  # Disable user profile for this demo
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal, plan, progress
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    session = "planning_session_001"

    # Start a multi-step task
    agent.print_response(
        "Help me set up a new Python project with tests and CI/CD.",
        user_id="demo@example.com",
        session_id=session,
        stream=True,
    )

    print("\n---\n")

    # Continue the conversation
    agent.print_response(
        "I've created the directory structure. What's next?",
        user_id="demo@example.com",
        session_id=session,
        stream=True,
    )

    print("\n---\n")

    # Session context tracks progress even across message truncation
    agent.print_response(
        "Summarize what we've accomplished so far.",
        user_id="demo@example.com",
        session_id=session,
        stream=True,
    )
