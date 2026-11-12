"""
AgentOS File System - Shared File System on the OS
==================================================

Pass a ``FileSystem`` to ``AgentOS(filesystems=[...])`` to show it on the File
System page without any agent holding it, the same way
``AgentOS(knowledge=[...])`` shows a knowledge base on the Knowledge page.

Here the application writes the team's shared notes, and AgentOS serves them
read-only. The assistant keeps its own separate files with ``filesystem=True``.
``/config`` lists both namespaces: ``shared-notes`` with no agents, and
``assistant`` with its agent.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/shared_filesystem.py
Try: Connect Agno OS to http://localhost:7777 and open File System, or
     curl http://localhost:7777/config | jq .filesystem
     curl "http://localhost:7777/filesystem/entries?namespace=shared-notes"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create FileSystem - held by the OS, not by an agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem_shared.db",
)

shared_notes = FileSystem(db, namespace="shared-notes")

# ---------------------------------------------------------------------------
# Create Agent - it keeps its own files and does not hold the shared notes
# ---------------------------------------------------------------------------
assistant = Agent(
    id="assistant",
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=True,
    instructions="Keep durable working notes in your filesystem.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with a shared file system that no agent holds.",
    db=db,
    agents=[assistant],
    filesystems=[shared_notes],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The application writes the shared notes; the browser routes only read them.
    if shared_notes.read("handbook/style.md") is None:
        shared_notes.write(
            "handbook/style.md", "Write short sentences. Lead with the answer.\n"
        )

    agent_os.serve(app="shared_filesystem:app", reload=True)
