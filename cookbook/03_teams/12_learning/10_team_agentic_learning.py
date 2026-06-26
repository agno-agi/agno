"""
Team Learning: Agentic Mode
===========================
Team decides when to update user memory using tools.

In agentic mode:
- Learning is NOT automatic after each response
- Team has tools to explicitly save/update memories
- More control over what gets stored
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn.machine import LearningMachine
from agno.learn.mode import LearningMode
from agno.models.openai import OpenAIResponses
from agno.team import Team

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

planner = Agent(
    name="Planner",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Create project plans and timelines.",
)

executor = Agent(
    name="Executor",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Execute tasks and track progress.",
)

team = Team(
    name="Project Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[planner, executor],
    db=db,
    learning=LearningMachine(
        db=db,
        user_profile=True,
        user_memory=LearningMode.AGENTIC,
    ),
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    user_id = "agentic_test@example.com"

    print("\n" + "=" * 60)
    print("SESSION 1: Team uses tools to save important context")
    print("=" * 60 + "\n")

    team.print_response(
        "I'm launching a new product next month. Key dates: "
        "beta on March 15, marketing push on March 20, GA on April 1. "
        "Please save these important dates.",
        user_id=user_id,
        session_id="agentic_session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- Saved Memories (Agentic) ---")
    lm.user_memory_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("SESSION 2: Recall saved context")
    print("=" * 60 + "\n")

    team.print_response(
        "What are my upcoming launch milestones?",
        user_id=user_id,
        session_id="agentic_session_2",
        stream=True,
    )
