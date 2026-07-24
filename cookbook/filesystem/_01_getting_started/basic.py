"""
FileSystem - Basic
==================
Give your agent a durable, private filesystem. You attach it with one line,
and anything the agent writes stays available in every future run.

Run this file twice. Run 1 writes a note. Run 2 is a new process with no
shared session, and it reads the note back.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
DB_FILE = "tmp/filesystem/getting_started.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions="You are a note-keeping assistant.",
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if fs.read("notes/decisions.md") is None:
        print("run 1 of 2: the store is empty, so ask the agent to record a decision")
        agent.print_response(
            "We just made a decision you will need in future runs: use SQLite for "
            "local development and Postgres in production. Record it in "
            "notes/decisions.md."
        )
        print("Run this file again: a fresh process will read the note back.")
    else:
        print("run 2 of 2: the store is populated, so ask the agent to recall")
        agent.print_response(
            "Which database did we decide to use for local development? "
            "Check your files before answering."
        )
