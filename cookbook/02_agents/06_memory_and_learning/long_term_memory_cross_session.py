"""
Long-Term Memory Across Sessions
================================

Demonstrates how user memories persist across separate sessions.

Key concepts:
- user_id: scopes memories to a person (not a conversation)
- session_id: isolates chat history per conversation
- update_memory_on_run: captures facts after every response

Example prompts to try:
- Session 1: "I am a backend engineer who prefers TypeScript."
- Session 2 (new session_id): "What language do I prefer?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/long_term_memory.db")
user_id = "demo-engineer"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    update_memory_on_run=True,
    instructions=[
        "You are a helpful assistant.",
        "Use stored user memories when answering follow-up questions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Session 1: capture a long-term preference ===")
    agent.print_response(
        "I am a backend engineer who prefers TypeScript over Python.",
        user_id=user_id,
        session_id="onboarding_session",
        stream=True,
    )

    print("\n=== Session 2: new session, same user ===")
    agent.print_response(
        "What programming language do I prefer?",
        user_id=user_id,
        session_id="follow_up_session",
        stream=True,
    )

    print("\n=== Stored memories ===")
    for memory in agent.get_user_memories(user_id=user_id):
        print(f"- {memory.memory}")