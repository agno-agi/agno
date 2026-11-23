"""
AgentOS File System - OS-Level Stores
=====================================

Filesystems declared on the AgentOS itself with ``AgentOS(filesystem=...)``.
They are listed in ``/config`` and browsable through the ``/filesystem`` routes
whether or not an agent holds them, the way ``AgentOS(knowledge=[...])`` exposes
knowledge bases.

An OS-level store is not handed to agents automatically. An agent that should
read or write those files attaches the same store itself.

This example declares one OS-level store and four agents:

- ``handbook``: declared on the AgentOS only. No agent holds it, so ``/config``
  lists it with ``agents: []``.
- ``shared``: held by two agents. The writer has full access; the editor holds
  it read-only, so ``/config`` lists it once with both agents linked.
- The editor holds two namespaces, ``drafts`` and ``shared``, by passing a list
  to ``filesystem``. It appears under both in ``/config``.
- The notes agent uses ``filesystem=True`` and keeps its own ``{agent_id}``
  namespace. The plain agent attaches nothing and gets no file tools.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/os_level_filesystem.py
Try: Connect Agno OS to http://localhost:7777 and open File System, or
     curl http://localhost:7777/config | jq .filesystem
     curl "http://localhost:7777/filesystem/entries?namespace=handbook"
     curl "http://localhost:7777/filesystem/content?namespace=handbook&path=onboarding/welcome.md"
     curl "http://localhost:7777/filesystem/files"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create FileSystems
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem_os_level.db",
)

# Declared on the AgentOS only: browsable, held by no agent.
handbook = FileSystem(db, namespace="handbook")
# Held by the writer with full access.
shared = FileSystem(db, namespace="shared")
# The same store, read-only: same backend and namespace, so the same files.
shared_read_only = FileSystem(db, namespace="shared", read_only=True)
# The editor's own working store.
drafts = FileSystem(db, namespace="drafts")

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Holds one namespace with full access.
writer = Agent(
    id="writer",
    name="Shared Writer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=shared,
    instructions="You keep team notes as markdown files, one topic per file.",
    markdown=True,
)

# Holds two namespaces: a list gives the agent one set of file tools per store,
# each with its own permissions. Here it writes drafts and only reads shared.
editor = Agent(
    id="editor",
    name="Editor",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=[drafts, shared_read_only],
    instructions="You write drafts in your own files and consult the shared team notes.",
    markdown=True,
)

# Keeps its own namespace, named after the agent id.
notes_agent = Agent(
    id="notes-agent",
    name="Notes Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=True,
    instructions="You keep your own working notes in files.",
    markdown=True,
)

# Attaches no filesystem: the OS-level stores add no tools to it.
plain_agent = Agent(
    id="plain-agent",
    name="Plain Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="You answer questions directly.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with filesystems declared on the OS itself.",
    db=db,
    agents=[writer, editor, notes_agent, plain_agent],
    filesystem=[handbook],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Seed the stores so the browser has something to show before any run.
    if handbook.read("onboarding/welcome.md") is None:
        handbook.write(
            "onboarding/welcome.md",
            "# Welcome\n\nThis handbook is declared on the AgentOS. No agent holds it.\n",
        )
    if shared.read("notes/standup.md") is None:
        shared.write("notes/standup.md", "- filesystem moved to the AgentOS level\n")

    if drafts.read("posts/launch.md") is None:
        drafts.write("posts/launch.md", "# Launch post\n\nFirst draft.\n")

    agent_os.serve(app="os_level_filesystem:app", reload=True)
