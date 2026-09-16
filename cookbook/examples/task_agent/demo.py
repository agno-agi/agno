"""Exercise ownership checks with local demo user identities."""

from uuid import uuid4

from task_agent import agent

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = str(uuid4())
    for message in (
        "List my tasks, then mark task-1 complete.",
        "List my tasks again.",
        "Now mark task-2 complete.",
    ):
        agent.print_response(message, user_id="alice", session_id=session_id)
