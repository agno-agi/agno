"""
Team Learning: User Memory
==========================
Team learns observations and context about the user across sessions.

User memory captures:
- Observations about the user's situation
- Context from conversations
- Patterns in user behavior
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

analyst = Agent(
    name="Analyst",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Analyze data and provide insights.",
)

advisor = Agent(
    name="Advisor",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Provide strategic recommendations.",
)

team = Team(
    name="Strategy Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[analyst, advisor],
    db=db,
    learning=True,
    markdown=True,
)

if __name__ == "__main__":
    user_id = "memory_test@example.com"

    print("\n" + "=" * 60)
    print("SESSION 1: Share context about current situation")
    print("=" * 60 + "\n")

    team.print_response(
        "We're preparing for a Series A raise. Our MRR is $50K, growing 15% month-over-month. "
        "Main challenge is our CAC is too high relative to LTV.",
        user_id=user_id,
        session_id="memory_session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- Extracted Memories ---")
    lm.user_memory_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("SESSION 2: Follow up (team should remember context)")
    print("=" * 60 + "\n")

    team.print_response(
        "Given what you know about our situation, what metrics should we focus on improving?",
        user_id=user_id,
        session_id="memory_session_2",
        stream=True,
    )
