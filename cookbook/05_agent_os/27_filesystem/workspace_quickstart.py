"""
AgentOS Shared Workspace
=======================

Two agents share a durable filesystem for project notes and reports.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/workspace_quickstart.py
Try: Connect Agno OS to http://localhost:7777 and open File System
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = SqliteDb(
    id="workspace-db",
    db_file="tmp/workspace.db",
)

fs = FileSystem(db, namespace="project-workspace")

notes_agent = Agent(
    id="notes-agent",
    name="Notes Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=fs,
    instructions=[
        "Save project details and preferences in config/project.json.",
        "Keep feedback and decisions in notes/ as Markdown files.",
        "Read existing files before updating them. Preserve relevant information.",
    ],
    markdown=True,
)

report_agent = Agent(
    id="report-agent",
    name="Report Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=fs,
    instructions=[
        "Read config/project.json and search notes/ for relevant project context.",
        "Write actionable reports to reports/ as Markdown files, citing the source note paths.",
        "Read saved reports when asked about previous recommendations.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="workspace-os",
    description="AgentOS with a shared filesystem for project notes and reports.",
    db=db,
    agents=[notes_agent, report_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="workspace_quickstart:app", reload=True)
