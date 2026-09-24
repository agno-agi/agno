"""
AgentOS File System - Several Stores On One Agent
=================================================

One agent works with two namespaces: its own drafts, which it may change, and a
team handbook it can only read. The ``filesystem`` setting holds one store, so
both are attached as toolkits through ``tools``.

Every FileSystemTools registers the same tool names, and an agent keeps the first
registration per name. ``include_tools`` splits the surface so the names do not
collide: the drafts toolkit contributes the write tools, the handbook toolkit
the read tools.

AgentOS discovers filesystems attached through ``tools`` as well as the setting.
The browser routes address a store by ``namespace``.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/multiple_stores_per_agent.py
Try: curl "http://localhost:7777/filesystem/entries?namespace=analyst/drafts"
     curl "http://localhost:7777/filesystem/entries?namespace=team/handbook"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create FileSystems - two namespaces on one database
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem_multiple_stores.db",
)

drafts = FileSystem(db, namespace="analyst/drafts")
handbook = FileSystem(db, namespace="team/handbook")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
analyst = Agent(
    id="analyst",
    name="Analyst",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[
        drafts.tools(
            name="drafts", include_tools=["write_file", "append_file", "replace_lines"]
        ),
        handbook.tools(name="handbook", read_only=True),
    ],
    instructions=[
        "You write analysis drafts that follow the team handbook.",
        "read_file, list_files and search_content read the team handbook. You cannot change it.",
        "write_file, append_file and replace_lines write your own drafts.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with one agent holding a writable and a read-only filesystem.",
    db=db,
    agents=[analyst],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Seed both stores so the browser has something to show before any run.
    if handbook.read("style.md") is None:
        handbook.write("style.md", "Lead with the conclusion. Cite every number.\n")
    if drafts.read("q3-review.md") is None:
        drafts.write("q3-review.md", "# Q3 review\n\nDraft in progress.\n")

    for filesystem, read_only in analyst.filesystems:
        print(filesystem.namespace, "read-only" if read_only else "read-write")
    agent_os.serve(app="multiple_stores_per_agent:app", reload=True)
