"""
Second Brain - Memory You Own, Behind Your Own MCP Server
=========================================================
A private agent that remembers what you are building: durable notes in its own
filesystem, plus a learned profile of how you work. It is also an MCP server, so
Claude Desktop, Cursor and your own apps all read and write the same brain.

Running this file captures a decision in one session, then recalls it in a fresh
session with no chat history. Run it twice: the second run answers from the notes
and the profile the first run left behind. To start the MCP server, run the
folder instead: python cookbook/examples/second_brain
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Storage: one database holds the sessions, the learning stores and the notes
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/second_brain.db")

# The namespace is resolved per run from the caller's user_id, so every person
# gets their own notes. A run with no user_id fails closed.
notebook = FileSystem(db, namespace="brain/{user_id}")

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
second_brain = Agent(
    id="second-brain",
    name="Second Brain",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(user_profile=True, user_memory=True, entity_memory=True),
    tools=[notebook.tools()],
    instructions=[
        "You remember what this person is building, so they never re-explain it.",
        "Keep one note per project in notes/<project>.md. Append decisions as they are made.",
        "Answer for their stack and their taste, never in general.",
        "Three sentences unless they ask for more.",
    ],
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create the AgentOS - REST on /, MCP on /mcp
# ---------------------------------------------------------------------------
agent_os = AgentOS(agents=[second_brain], mcp_server=True)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "ashpreet"

    second_brain.print_response(
        "I am building Harbor, a Postgres-backed job queue in Rust. I picked advisory "
        "locks over SELECT FOR UPDATE SKIP LOCKED because our workers are long-lived. "
        "I want terse answers, no bullet lists.",
        user_id=user_id,
        session_id=f"capture-{uuid4().hex[:8]}",
    )

    # A brand new session: nothing carries over except the notes and the profile.
    second_brain.print_response(
        "What did I decide about locking in Harbor, and why?",
        user_id=user_id,
        session_id=f"recall-{uuid4().hex[:8]}",
    )

    print("Files in this user's brain:")
    for meta in notebook.resolve(user_id=user_id).list():
        print(f"  {meta.path}  ({meta.size_bytes} bytes)")
