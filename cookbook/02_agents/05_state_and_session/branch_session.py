"""
Branch Session
===============
Branch an agent session to create a new independent conversation.

This is useful when you want to explore a different direction without
losing the original conversation, or let multiple users continue from
the same checkpoint.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agents.db")

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    original_session = "branch-demo-original"
    user_id = "demo-user"

    # 1. Build up a conversation
    print("\n--- Building original conversation ---\n")
    agent.print_response(
        "I'm planning a trip to Japan. What are the top 3 cities to visit?",
        session_id=original_session,
        user_id=user_id,
        stream=True,
    )
    agent.print_response(
        "Tell me more about Kyoto. What should I see there?",
        session_id=original_session,
        user_id=user_id,
        stream=True,
    )

    # 2. Branch the session
    new_session_id = agent.branch_session(
        source_session_id=original_session,
        user_id=user_id,
    )
    print(f"\nBranched session: {original_session} -> {new_session_id}\n")

    # 3. Continue the branched session in a different direction
    print("\n--- Continuing branched session (different direction) ---\n")
    agent.print_response(
        "Actually, I changed my mind. Tell me about Osaka's street food scene instead.",
        session_id=new_session_id,
        user_id=user_id,
        stream=True,
    )

    # 4. Original session is untouched -- continue it separately
    print("\n--- Continuing original session (unaffected) ---\n")
    agent.print_response(
        "What about the temples in Kyoto? Which ones are must-see?",
        session_id=original_session,
        user_id=user_id,
        stream=True,
    )
