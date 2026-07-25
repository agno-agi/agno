"""
Namespaces - Per-User Stores
============================
One agent instance, one file store per end-user. The namespace
"assistant/{user_id}" is resolved on every tool call from the run's user_id,
which your code sets and the model cannot influence. A run without a user_id
fails closed rather than falling back to a shared store.

This example serves two users with isolated files, then shows the anonymous
run failing.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_tenants_{uuid4().hex}.db"

db = SqliteDb(db_file=DB_FILE)
fs = FileSystem(db, namespace="assistant/{user_id}")

# ---------------------------------------------------------------------------
# Create Agent - one instance serves every user
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions="You are a project assistant. Keep your working notes in your files.",
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Each run records what the agent did for that tenant, and the namespace keeps
    # the two work logs apart.
    agent.print_response(
        "Append to work-log.md: 'Resolved a duplicate-charge refund on the checkout service.'",
        user_id="alice",
    )
    agent.print_response(
        "Append to work-log.md: 'Investigated a failed invoice on the billing service.'",
        user_id="bob",
    )

    print("alice asks, and gets only her own work log:")
    agent.print_response(
        "What have you logged for me so far? Check your files.", user_id="alice"
    )

    print("anonymous run fails closed, with no shared fallback namespace:")
    agent.print_response("What have you logged for me? Check your files.")

    print("proof of isolation, straight from the backend:")
    print(
        "assistant/alice ->",
        repr(fs.resolve(user_id="alice").read("work-log.md")),
    )
    print(
        "assistant/bob   ->",
        repr(fs.resolve(user_id="bob").read("work-log.md")),
    )
