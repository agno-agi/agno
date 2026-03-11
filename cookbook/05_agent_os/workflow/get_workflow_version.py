"""
Get Workflow Version
====================

Saves two workflow versions to the database and serves them via AgentOS.

Start server:
    python cookbook/05_agent_os/workflow/get_workflow_version.py

Fetch versions:
    curl http://localhost:7777/workflows/research-workflow
    curl "http://localhost:7777/workflows/research-workflow?version=1"
    curl "http://localhost:7777/workflows/research-workflow?version=2"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(session_table="workflow_sessions", db_file="tmp/workflow_versions.db")

# Save version 1
Workflow(
    id="research-workflow",
    name="Research Workflow v1",
    description="Basic single-step research workflow",
    db=db,
    steps=[
        Step(
            name="Research",
            agent=Agent(name="Researcher", model=OpenAIChat(id="gpt-4o")),
        ),
    ],
).save()

# Save version 2 (adds a writing step)
Workflow(
    id="research-workflow",
    name="Research Workflow v2",
    description="Research and writing workflow",
    db=db,
    steps=[
        Step(
            name="Research",
            agent=Agent(name="Researcher", model=OpenAIChat(id="gpt-4o")),
        ),
        Step(
            name="Writing",
            agent=Agent(name="Writer", model=OpenAIChat(id="gpt-4o")),
        ),
    ],
).save()

# Serve from database
agent_os = AgentOS(db=db)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="get_workflow_version:app", reload=True)
