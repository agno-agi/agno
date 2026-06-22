"""
Regenerate and Branch
======================
Combine regenerate and branch to explore alternative responses
in a branched conversation.

Workflow:
1. Run a conversation
2. Branch the session at a checkpoint
3. Regenerate the last response in the branched session
4. Continue each branch independently
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
    session_id = "regen-branch-demo"
    user_id = "demo-user"

    # 1. Build a conversation
    print("\n--- Original conversation ---\n")
    agent.print_response(
        "Recommend a programming language for building web APIs",
        session_id=session_id,
        user_id=user_id,
        stream=True,
    )

    # 2. Branch the session before regenerating
    branched_session = agent.branch_session(
        source_session_id=session_id,
        user_id=user_id,
    )
    print(f"\nBranched to: {branched_session}")

    # 3. Regenerate in the branched session with different instructions
    print("\n--- Regenerated response in branched session ---\n")
    response = agent.regenerate(
        additional_instructions="Focus on Go and Rust instead. Compare their ecosystems.",
        session_id=branched_session,
        user_id=user_id,
        stream=False,
    )
    print(response.content)

    # 4. Continue the original session (unchanged)
    print("\n--- Continue original session ---\n")
    agent.print_response(
        "How do I get started with your recommendation?",
        session_id=session_id,
        user_id=user_id,
        stream=True,
    )

    # 5. Continue the branched session (different direction)
    print("\n--- Continue branched session ---\n")
    agent.print_response(
        "Which one has better async support?",
        session_id=branched_session,
        user_id=user_id,
        stream=True,
    )
