"""
Pattern: Research Assistant with Tools + Learning
==================================================
A research assistant that uses web search tools and learns about the user.

This pattern combines:
- User Profile: Researcher's name, field, preferences
- User Memory: Research interests, past queries, patterns
- Tools: DuckDuckGo web search for live research

The assistant becomes more personalized over time while actively
searching the web for information.

This pattern also serves as a regression test for issue #7232:
when tools and learning are both enabled, the learning extraction
model must not see tool scaffolding (system prompts, tool_calls,
tool results) from the parent agent's conversation history.

See also: personal_assistant.py for a tools-free learning pattern.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


def create_research_assistant(user_id: str, session_id: str) -> Agent:
    return Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        db=db,
        instructions=(
            "You are a research assistant. Search the web when asked about "
            "current topics. Keep responses focused and cite sources."
        ),
        tools=[DuckDuckGoTools()],
        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            user_memory=UserMemoryConfig(
                mode=LearningMode.ALWAYS,
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        add_history_to_context=True,
        markdown=True,
    )


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "researcher@example.com"

    # Session 1: Introduce yourself and ask a research question
    print("\n" + "=" * 60)
    print("SESSION 1: Introduction + web search")
    print("=" * 60 + "\n")

    agent = create_research_assistant(user_id, "research_session_1")
    agent.print_response(
        "Hi, I'm Dr. Sarah Kim. I'm a neuroscience researcher at MIT. "
        "Can you search for recent papers on brain-computer interfaces?",
        stream=True,
    )

    lm = agent.learning_machine
    print("\n--- Profile ---")
    lm.user_profile_store.print(user_id=user_id)
    print("\n--- Memories ---")
    lm.user_memory_store.print(user_id=user_id)

    # Session 2: New session — agent should remember the user
    # History from session 1 (including tool calls) should not
    # contaminate the learning extraction model
    print("\n" + "=" * 60)
    print("SESSION 2: Memory recall + another search")
    print("=" * 60 + "\n")

    agent = create_research_assistant(user_id, "research_session_2")
    agent.print_response(
        "What do you know about me? Also, search for the latest on neural implants.",
        stream=True,
    )

    print("\n--- Profile ---")
    lm.user_profile_store.print(user_id=user_id)
    print("\n--- Memories ---")
    lm.user_memory_store.print(user_id=user_id)
