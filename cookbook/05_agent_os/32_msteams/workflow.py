"""
Serve a Sequential Workflow on Microsoft Teams
==============================================

Research a topic, then write a concise brief using the research output.
Prerequisites: OPENAI_API_KEY and the MICROSOFT_APP_* credentials in README.md
Run: python cookbook/05_agent_os/32_msteams/workflow.py
Try: Ask for a short adoption brief about passkeys.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.msteams import MSTeams
from agno.tools.websearch import WebSearchTools
from agno.workflow import Step, Workflow

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    instructions="Find credible sources for the requested topic and return concise findings with links.",
)
writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Turn the previous step's findings into a short Teams-ready brief. Preserve source links.",
)
content_workflow = Workflow(
    id="msteams-content-workflow",
    name="Teams Content Workflow",
    db=SqliteDb(id="msteams-workflow-db", db_file="tmp/msteams_workflow.db"),
    steps=[Step(name="Research", agent=researcher), Step(name="Write", agent=writer)],
    add_workflow_history_to_steps=True,
    num_history_runs=3,
)
agent_os = AgentOS(
    id="msteams-workflow-os",
    workflows=[content_workflow],
    interfaces=[MSTeams(workflow=content_workflow)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)
