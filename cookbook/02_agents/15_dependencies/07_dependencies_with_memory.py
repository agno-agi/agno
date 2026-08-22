"""
Dependencies With Memory
=============================

Realistic personalisation flow: a dependency fetches user-specific profile
data per-run, and persistent memory accumulates user-specific facts across
runs. Combined, you get an agent that knows who the user is from your
application data AND remembers what they have told it.

This pattern is the foundation for multi-tenant, personalised agents.

Pitfall: dependencies do NOT persist. They resolve per-run from your
application state (DB, cache, request). Memory persists in `db`.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.run import RunContext

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
USER_PROFILES = {
    "user_alice": {
        "name": "Alice",
        "tenant": "acme",
        "preferences": ["concise replies", "code examples"],
    },
    "user_bob": {
        "name": "Bob",
        "tenant": "globex",
        "preferences": ["detailed explanations"],
    },
}


def get_user_profile(run_context: RunContext) -> dict:
    return USER_PROFILES.get(run_context.user_id or "", {"name": "Unknown"})


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = InMemoryDb()

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    enable_user_memories=True,
    add_memories_to_context=True,
    dependencies={"user_profile": get_user_profile},
    instructions=[
        "You are responding to {user_profile}.",
        "Match the user's stated preferences when responding.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Run 1: alice introduces a fact about herself ===")
    agent.print_response(
        "Hi! I'm working on a recommendation engine in Rust this quarter.",
        user_id="user_alice",
        session_id="alice_session_1",
    )

    print("\n=== Run 2: same user, new session — profile dep + memory carry over ===")
    agent.print_response(
        "What was I working on, and what language am I using?",
        user_id="user_alice",
        session_id="alice_session_2",
    )
