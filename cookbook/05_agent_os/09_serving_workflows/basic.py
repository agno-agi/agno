"""
Serve a Workflow with AgentOS
=============================

Serve one two-step workflow as an HTTP resource. AgentOS adds discovery,
execution, streaming, persisted-run, and WebSocket routes around the workflow.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/basic.py
Try: Run run_over_api.py or ws_stream.py from this folder in another terminal
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Create Served Workflow
# ---------------------------------------------------------------------------

WORKFLOW_ID = "release-notes-workflow"

db = SqliteDb(
    id="serving-workflows-db",
    db_file="tmp/serving_workflows.db",
)

draft_agent = Agent(
    id="release-notes-drafter",
    name="Release Notes Drafter",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=(
        "Turn the request into a concise release-note draft with a heading and "
        "three short bullets."
    ),
)

editor_agent = Agent(
    id="release-notes-editor",
    name="Release Notes Editor",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=(
        "Edit the preceding draft for clarity. Return only the final heading "
        "and three short bullets."
    ),
)

release_notes_workflow = Workflow(
    id=WORKFLOW_ID,
    name="Release Notes Workflow",
    description="Draft and edit concise release notes in two steps.",
    db=db,
    steps=[
        Step(name="Draft Release Notes", agent=draft_agent),
        Step(name="Edit Release Notes", agent=editor_agent),
    ],
)

agent_os = AgentOS(
    id="serving-workflows-os",
    description="AgentOS serving a two-step workflow.",
    db=db,
    workflows=[release_notes_workflow],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Workflow Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
