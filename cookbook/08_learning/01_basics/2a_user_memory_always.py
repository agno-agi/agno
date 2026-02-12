"""
User Memory: Always Mode
========================
User Memory captures unstructured observations about users:
- Work context and role
- Communication style preferences
- Patterns and interests
- Any memorable facts

ALWAYS mode extracts memories automatically in parallel
while the agent responds - no explicit tool calls needed.

Compare with: 2b_user_memory_agentic.py for explicit tool-based updates.
See also: 1a_user_profile_always.py for structured profile fields.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ALWAYS mode: Extraction happens automatically after each response.
# The agent doesn't see or call any memory tools - it's invisible.
# Memories stores unstructured observations that don't fit profile fields.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        user_memory=UserMemoryConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "alice@example.com"

    # Session 1: Share information naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (extraction happens automatically)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Hi! I work at Anthropic as a research scientist. "
        "I prefer concise responses without too much explanation. "
        "I'm currently working on a paper about transformer architectures.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    agent.learning_machine.user_memory_store.print(user_id=user_id)

    # Session 2: New session - memories are recalled automatically
    print("\n" + "=" * 60)
    print("SESSION 2: Memories recalled in new session")
    print("=" * 60 + "\n")

    agent.print_response(
        "What's a good Python library for async HTTP requests?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    agent.learning_machine.user_memory_store.print(user_id=user_id)
