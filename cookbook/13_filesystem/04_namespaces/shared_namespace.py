"""
Namespaces - Sharing One Store
==============================
Two agents share files by attaching the same namespace by name. The producer
gets the full tool surface. The consumer gets tools(read_only=True), which is
four read tools plus the read-only instructions, so it can consult the
records but holds no tool that could change them.

This example has a recorder agent write decisions and an answering agent look
them up read-only.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem - same backend, same namespace name, two surfaces
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_shared_{uuid4().hex}.db"

db = SqliteDb(db_file=DB_FILE)
producer_fs = FileSystem(db, namespace="research/decisions")
consumer_fs = FileSystem(db, namespace="research/decisions")

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
