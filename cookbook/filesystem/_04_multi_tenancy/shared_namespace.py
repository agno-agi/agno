"""
Multi-Tenancy - Shared Namespace
================================

Sharing is explicit, by name: two agents attach the same namespace. The
producer holds the full surface; the consumer gets tools(read_only=True) -
four read tools and the read-only instructions variant - so it can consult
the records but has no tool that could change them.

This example has a recorder agent write decisions and an answering agent look
them up read-only.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem - same backend, same namespace name, two surfaces
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_shared_{uuid4().hex}.db"

db_fs = DbFileSystem(db=SqliteDb(db_file=DB_FILE))
producer_fs = FileSystem(backend=db_fs, namespace="research/decisions")
consumer_fs = FileSystem(backend=db_fs, namespace="research/decisions")

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
recorder = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[producer_fs.tools()],
    instructions="You record engineering decisions.",
)

consumer_toolkit = consumer_fs.tools(read_only=True)
answerer = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[consumer_toolkit],
    instructions="You answer questions about past engineering decisions.",
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("consumer tool surface:", list(consumer_toolkit.functions.keys()))

    recorder.print_response(
        "Append these two decisions to decisions/2026-07.md, one per line: "
        "'vector db: pgvector approved for production' and "
        "'cache: redis approved for session data'."
    )

    print("the read-only consumer looks it up:")
    answerer.print_response("What was decided about the vector database? Look it up.")
