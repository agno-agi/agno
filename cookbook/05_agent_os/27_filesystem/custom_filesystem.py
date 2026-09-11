"""
AgentOS Custom File System
==========================

Supply a configured ``FileSystem`` when the application needs an explicit
namespace or custom limits instead of the managed ``filesystem=True`` defaults.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/custom_filesystem.py
Try: Open http://localhost:7777/filesystem in Agno OS
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem.db",
)
fs = FileSystem(db, namespace="agents/research-agent")
filesystem_agent = Agent(
    id="filesystem-agent",
    name="File System Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=fs,
    instructions="Keep durable working notes in your filesystem.",
    markdown=True,
)

agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with a durable per-agent filesystem.",
    db=db,
    agents=[filesystem_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="custom_filesystem:app", reload=True)
