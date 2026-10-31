"""
AgentOS Local File System
=========================

Supply a ``LocalFileSystem`` backend when durable agent files should live under
a real local directory instead of the AgentOS database.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/local_filesystem.py
Try: Open http://localhost:7777/filesystem in Agno OS
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem.db",
)


fs = FileSystem(
    backend=LocalFileSystem(root="./tmp/agent-files"),
    namespace="research",
)
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
    agent_os.serve(app="local_filesystem:app", reload=True)
