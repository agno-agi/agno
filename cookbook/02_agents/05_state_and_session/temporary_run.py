"""
Temporary Run
=============================

Run an agent without saving the run: pass store_run=False and the agent answers
with the session's history in context, but neither the run nor the session row is
written to the database. Useful for side questions, previews and "what if" prompts
that should not become part of the conversation.

On AgentOS the same option is the store_run form field of the run routes:

    curl -X POST http://localhost:7777/agents/<agent_id>/runs \
        -F message="Summarize this chat so far" -F session_id=<session_id> \
        -F stream=false -F store_run=false

A temporary run cannot be a background run, because background runs are polled
from the stored run row.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/agents.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    add_history_to_context=True,
)

SESSION_ID = "temporary-run-demo"


def stored_runs() -> int:
    session = agent.get_session(session_id=SESSION_ID)
    return len(session.runs or []) if session is not None else 0


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "My favorite color is teal. Remember it.", session_id=SESSION_ID
    )
    print(f"Stored runs after a normal run: {stored_runs()}")

    # The temporary run sees the history (it knows the color) but is not saved.
    agent.print_response(
        "What is my favorite color?", session_id=SESSION_ID, store_run=False
    )
    print(f"Stored runs after a temporary run: {stored_runs()}")

    # The next normal run is saved again, and never saw the temporary one.
    agent.print_response("Now also remember that I like hiking.", session_id=SESSION_ID)
    print(f"Stored runs after another normal run: {stored_runs()}")
