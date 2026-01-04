"""
User Profile Quick Start
========================
User memory in 30 lines.

User Profile captures long-term information about users:
- Name and preferences
- Work context
- Communication style
- Any memorable facts

Run:
    python cookbook/15_learning/basics/02_user_profile_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.models.openai import OpenAIResponses

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIResponses(id="gpt-5.2")

# Agent with user profile learning
agent = Agent(
    name="User Profile Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract from conversations
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "quick_user@example.com"

    # Share some info
    agent.print_response(
        "I'm Bob, a backend engineer who loves Rust and hates meetings.",
        user_id=user,
        session_id="s1",
        stream=True,
    )

    print("\n---\n")

    # Recall it later
    agent.print_response(
        "What programming language should you recommend to me?",
        user_id=user,
        session_id="s2",
        stream=True,
    )
