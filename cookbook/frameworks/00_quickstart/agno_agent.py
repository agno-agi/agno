"""
Agno Agent on AgentOS
=====================
A native Agno agent with the Workspace tool, served through AgentOS.

The Workspace tool gives the agent read/write/search access to a local
directory. Destructive ops (write/edit/delete/shell) require human
confirmation by default — AgentOS renders these as approval prompts
in the run timeline.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/00_quickstart/agno_agent.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

agent = Agent(
    name="Agno Agent",
    model="openai:gpt-5.4",
    tools=[
        Workspace(
            root=".",
            allowed=["read", "list", "search"],
            confirm=["write", "edit", "delete", "shell"],
        )
    ],
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agno_agent:app", reload=True)
