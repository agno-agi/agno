"""
Team Learning: User Profile
===========================
Team learns and recalls user profile across sessions.

This demonstrates that Team.add_learnings_to_context works correctly:
- Session 1: Team extracts user profile from conversation
- Session 2: Team recalls profile in new session (different session_id)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research and provide detailed information.",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Write clear, concise content.",
)

team = Team(
    name="Content Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer],
    db=db,
    learning=True,
    markdown=True,
)

if __name__ == "__main__":
    user_id = "profile_test@example.com"

    print("\n" + "=" * 60)
    print("SESSION 1: Share profile information")
    print("=" * 60 + "\n")

    team.print_response(
        "Hi, I'm Marcus. I'm a DevOps engineer at a fintech startup. "
        "I prefer practical examples over theory, and I work primarily with Kubernetes.",
        user_id=user_id,
        session_id="profile_session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- Extracted Profile ---")
    lm.user_profile_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("SESSION 2: Team should recall profile (NEW SESSION)")
    print("=" * 60 + "\n")

    team.print_response(
        "What do you know about me? Keep it brief.",
        user_id=user_id,
        session_id="profile_session_2",
        stream=True,
    )
