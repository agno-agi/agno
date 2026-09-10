"""AgentOS with files on disk and sessions in SQLite.

Set OPENAI_API_KEY, then run this file. FILESYSTEM_ROOT optionally selects a
dedicated storage directory, including a mounted Docker volume.
Ask: Save a project outline to notes/project.md.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(id="local-files-db", db_file="tmp/local_files_sessions.db")
filesystem = FileSystem(
    backend=LocalFileSystem(root=getenv("FILESYSTEM_ROOT", "tmp/agent_files")),
    namespace="local-assistant",
)

agent = Agent(
    id="local-files-agent",
    name="Local Files Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=filesystem,
    instructions="Keep durable working notes in your filesystem. Save notes only when asked.",
    markdown=True,
)

agent_os = AgentOS(
    id="local-files-os",
    db=db,
    agents=[agent],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
