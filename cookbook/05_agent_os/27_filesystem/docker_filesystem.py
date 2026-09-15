"""
AgentOS Docker File System
=========================

Run AgentOS inside Docker and keep agent files in a named volume. Docker mounts
the storage; Agno uses its existing LocalFileSystem backend inside the container.

Run from the repository root:
docker compose -f cookbook/05_agent_os/27_filesystem/docker-compose.yaml up --build

Set OPENAI_API_KEY before starting. Connect Agno OS to http://localhost:7777.
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# The image creates /data and Compose mounts a persistent named volume there.
data_dir = Path("/data")
db = SqliteDb(id="docker-filesystem-db", db_file=str(data_dir / "sessions.db"))
filesystem = FileSystem(
    backend=LocalFileSystem(root=data_dir / "files"),
    namespace="docker-workspace",
)
agent = Agent(
    id="docker-filesystem-agent",
    name="Docker File System Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=filesystem,
    instructions="Save project notes and reports in your filesystem, and read them when asked.",
    markdown=True,
)
agent_os = AgentOS(
    id="docker-filesystem-os",
    description="A local Docker demo with files persisted in a named volume.",
    db=db,
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="0.0.0.0", port=7777, reload=False)
