"""Two AgentOS agents sharing one durable filesystem.

Set OPENAI_API_KEY, then run this file.
Ask Researcher: Save a launch brief to briefs/launch.md.
Then ask Editor: Read briefs/launch.md and save an edited copy to drafts/launch.md.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(id="shared-files-db", db_file="tmp/shared_files.db")
shared_files = FileSystem(db=db, namespace="shared/editorial")

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=shared_files,
    instructions="Draft research briefs in briefs/. Save files only when asked.",
    markdown=True,
)
editor = Agent(
    id="editor",
    name="Editor",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=shared_files,
    instructions="Read shared briefs and save edited drafts in drafts/ when asked. Preserve the original briefs.",
    markdown=True,
)

agent_os = AgentOS(
    id="shared-files-os",
    db=db,
    agents=[researcher, editor],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
