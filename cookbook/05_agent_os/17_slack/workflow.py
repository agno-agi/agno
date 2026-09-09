"""
Serve a Sequential Workflow in Slack
====================================

Run a two-step research-then-writing Workflow in one Slack thread, with
SQLite-backed workflow history available to later runs.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/workflow.py
Try in Slack: Ask "Research passkeys for SaaS apps and write a short adoption brief."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Workflow Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-workflow-db",
    db_file="tmp/slack_workflow.db",
)

researcher = Agent(
    id="slack-workflow-researcher",
    name="Workflow Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    instructions=[
        "Find current, credible sources for the requested topic.",
        "Return concise findings with source links for the next step.",
    ],
)

writer = Agent(
    id="slack-workflow-writer",
    name="Workflow Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Turn the research from the previous step into a concise Slack-ready brief.",
        "Preserve source links and distinguish facts from recommendations.",
    ],
)

content_workflow = Workflow(
    id="slack-content-workflow",
    name="Slack Content Workflow",
    description="Research a topic, then write a concise brief.",
    db=db,
    steps=[
        Step(name="Research", agent=researcher),
        Step(name="Write", agent=writer),
    ],
    add_workflow_history_to_steps=True,
    num_history_runs=3,
)

agent_os = AgentOS(
    id="slack-workflow-os",
    description="AgentOS serving a sequential content Workflow through Slack.",
    workflows=[content_workflow],
    interfaces=[Slack(workflow=content_workflow)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Workflow Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
