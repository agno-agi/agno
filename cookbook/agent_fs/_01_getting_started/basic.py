"""
AgentFS - Basic
===============

A durable, private filesystem for your agent: attach it with one line, and
anything the agent writes is available in every future run.

This example proves durability across processes, not just sessions: run it
twice. Run 1 writes a note; run 2 is a fresh process that reads it back.
"""

import os
from pathlib import Path

from agno.agent import Agent
from agno.fs import AgentFS
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create AgentFS
# ---------------------------------------------------------------------------
# One SQLite file reused across invocations on purpose: this example exists to
# show the store surviving the process. Delete the db file to start over.
Path("tmp").mkdir(exist_ok=True)
DB_FILE = os.environ.get("AGNO_FS_DB") or "tmp/agent_fs_getting_started.db"

fs = AgentFS(
    fs=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="getting-started"
)

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
        print("run 1 of 2: store is empty - asking the agent to record a decision")
        agent.print_response(
            "We just made a decision you will need in future runs: use SQLite for "
            "local development and Postgres in production. Record it in "
            "notes/decisions.md."
        )
        print("Run this file again: a fresh process will read the note back.")
    else:
        print("run 2 of 2: store already populated - asking the agent to recall")
        agent.print_response(
            "Which database did we decide to use for local development? "
            "Check your files before answering."
        )
