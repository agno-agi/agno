"""
Learning Machines: Agentic Mode
===============================
In AGENTIC mode, the agent receives tools to explicitly manage learning.
It decides when to save profiles and memories based on conversation context.

Compare with learning=True (ALWAYS mode) where extraction happens automatically.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agents.db")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "alice2@example.com"

    # Session 1: Agent decides what to save via tool calls
    print("\n--- Session 1: Agent uses tools to save profile and memories ---\n")
    agent.print_response(
        "Hi! I'm Alice. I work at Anthropic as a research scientist. "
        "I prefer concise responses without too much explanation.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    lm = agent.learning_machine
    lm.user_profile_store.print(user_id=user_id)
    lm.user_memory_store.print(user_id=user_id)

    # Session 2: New session - agent remembers
    print("\n--- Session 2: Agent remembers across sessions ---\n")
    agent.print_response(
        "What do you know about me?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
