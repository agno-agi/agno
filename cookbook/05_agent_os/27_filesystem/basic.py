"""
AgentOS File System
===================

Enable a private durable filesystem with ``filesystem=True``. By default files
are scoped to the agent. AgentOS adds user scope only when user isolation is on.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/basic.py
Try: Open http://localhost:7777/filesystem in Agno OS
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(
    id="filesystem-db",
    db_file="tmp/filesystem.db",
)

filesystem_agent = Agent(
    id="filesystem-agent",
    name="File System Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    filesystem=True,
    instructions="Keep durable working notes in your filesystem.",
    markdown=True
)

agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with a durable per-agent filesystem.",
    db=db,
    agents=[filesystem_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
