"""
Team Learning: Configured Stores
=================================
Configure specific learning stores on a Team using LearningMachine.

This example enables:
- UserProfile (ALWAYS mode): Captures structured user fields
- UserMemory (AGENTIC mode): Team uses tools to save observations
- SessionContext (ALWAYS mode): Tracks session goals and progress

Each store can be independently configured with its own mode.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.team import Team

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

analyst = Agent(
    name="Data Analyst",
    model=OpenAIChat(id="gpt-4o"),
    role="Analyze data and provide insights.",
)

advisor = Agent(
    name="Strategy Advisor",
    model=OpenAIChat(id="gpt-4o"),
    role="Provide strategic recommendations based on analysis.",
)

team = Team(
    name="Advisory Team",
    model=OpenAIChat(id="gpt-4o"),
    members=[analyst, advisor],
    db=db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
        user_memory=UserMemoryConfig(
            mode=LearningMode.AGENTIC,
        ),
        session_context=SessionContextConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    user_id = "bob@example.com"

    # Session 1: Introduction and first task
    print("\n" + "=" * 60)
    print("SESSION 1: Introduction and analysis request")
    print("=" * 60 + "\n")

    team.print_response(
        "I'm Bob, VP of Engineering at a Series B startup. "
        "We have 50 engineers and are scaling to 100. "
        "What should I focus on for our engineering org?",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- User Profile ---")
    lm.user_profile_store.print(user_id=user_id)
    print("\n--- User Memories ---")
    lm.user_memory_store.print(user_id=user_id)
    print("\n--- Session Context ---")
    lm.session_context_store.print(session_id="session_1")

    # Session 2: Follow-up - team knows context
    print("\n" + "=" * 60)
    print("SESSION 2: Follow-up with retained context")
    print("=" * 60 + "\n")

    team.print_response(
        "Given what you know about my situation, "
        "what hiring strategy would you recommend?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
