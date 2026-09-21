"""
AgentOS File System - Read-Only Consumer
========================================

Two agents share one namespace with different permissions. The recorder owns
the records and gets the full tool surface. The answerer receives
``fs.tools(read_only=True)`` through the same ``filesystem`` setting, so it holds
three read tools and nothing that could change the records.

AgentOS lists both agents on the shared filesystem and reports the answerer in
``read_only_agents``.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/read_only_consumer.py
Try: Connect Agno OS to http://localhost:7777 and open File System, or
     curl http://localhost:7777/config | jq .filesystem
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create FileSystem - one namespace, shared by name
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem_read_only.db",
)

decisions = FileSystem(db, namespace="research/decisions")

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# A FileSystem gives the agent the default read-write tools and instructions.
recorder = Agent(
    id="recorder",
    name="Decision Recorder",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=decisions,
    instructions="You record engineering decisions, one per line, in decisions/<year>-<month>.md.",
    markdown=True,
)

# A toolkit carries its own permissions. add_instructions=True puts the
# matching read-only instructions in the system prompt.
answerer = Agent(
    id="answerer",
    name="Decision Answerer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=decisions.tools(read_only=True, add_instructions=True),
    instructions="You answer questions about past engineering decisions. Look them up before answering.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with a writer and a read-only consumer on one filesystem.",
    db=db,
    agents=[recorder, answerer],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Seed one record so the browser has something to show before any run.
    if decisions.read("decisions/2026-09.md") is None:
        decisions.write(
            "decisions/2026-09.md", "vector db: pgvector approved for production\n"
        )

    print("answerer tools:", sorted(answerer.filesystem.functions))  # type: ignore[union-attr]
    agent_os.serve(app="read_only_consumer:app", reload=True)
