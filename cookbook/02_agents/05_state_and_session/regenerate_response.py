"""
Regenerate Response
===================
Regenerate the last agent response in a session.

The agent replays prior context (minus the final assistant output)
and produces a fresh answer. By default the old run is replaced;
set ``preserve_original=True`` to keep it with a ``regenerated`` status.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agents.db")

agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "regenerate-demo"
    user_id = "demo-user"

    # 1. Initial conversation
    print("\n--- Original response ---\n")
    agent.print_response(
        "Give me 3 fun facts about octopuses",
        session_id=session_id,
        user_id=user_id,
        stream=True,
    )

    # 2. Regenerate -- replaces the original run by default
    print("\n--- Regenerated response (replaces original) ---\n")
    response = agent.regenerate(
        session_id=session_id,
        user_id=user_id,
        stream=False,
    )
    print(response.content)

    # 3. Regenerate with additional instructions to steer the output
    print("\n--- Regenerated with additional instructions ---\n")
    response = agent.regenerate(
        additional_instructions="Make the facts more surprising and include a source for each.",
        session_id=session_id,
        user_id=user_id,
        stream=False,
    )
    print(response.content)

    # 4. Regenerate but keep the original run (preserve_original=True)
    print("\n--- Regenerated with preserve_original=True ---\n")
    response = agent.regenerate(
        preserve_original=True,
        session_id=session_id,
        user_id=user_id,
        stream=False,
    )
    print(response.content)
    print(f"\nTotal runs in session: {len(agent.agent_session.runs)}")
