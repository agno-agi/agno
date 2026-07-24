"""
Multi-Tenancy - Basic
=====================

One static agent, one file store per end-user: namespace="assistant/{user_id}"
resolves per tool call from the run's user_id - never from anything the model
says - and an anonymous run fails closed instead of sharing files.

This example serves two users with isolated files, then shows the fail-closed
anonymous run.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_tenants_{uuid4().hex}.db"

db_fs = DbFileSystem(db_url=f"sqlite:///{DB_FILE}")
fs = FileSystem(backend=db_fs, namespace="assistant/{user_id}")

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
    # Each run records what the AGENT did for that tenant - its own work log, not a
    # profile of the user (that would be memory). The namespace keeps the logs apart.
    agent.print_response(
        "Append to work-log.md: 'Resolved a duplicate-charge refund on the checkout service.'",
        user_id="alice",
    )
    agent.print_response(
        "Append to work-log.md: 'Investigated a failed invoice on the billing service.'",
        user_id="bob",
    )

    print("alice asks - and gets only her own work log:")
    agent.print_response(
        "What have you logged for me so far? Check your files.", user_id="alice"
    )

    print("anonymous run - fails closed, no shared fallback namespace:")
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
