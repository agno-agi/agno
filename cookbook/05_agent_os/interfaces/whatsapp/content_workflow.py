"""
Content Workflow
================

A WhatsApp workflow that takes a user's topic, researches it, then writes
a short summary -- delivered back over WhatsApp.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

model = Claude(id="claude-sonnet-4-6")
workflow_db = SqliteDb(db_file="tmp/content_workflow.db")

researcher = Agent(
    name="Researcher",
    role="Search the web and gather key facts",
    model=model,
    tools=[WebSearchTools()],
    instructions=[
        "Search the web for the topic the user asked about.",
        "Return a bullet-point list of the most important facts and sources.",
    ],
    markdown=True,
)

writer = Agent(
    name="Writer",
    role="Write a concise summary from the research",
    model=model,
    instructions=[
        "Using the research provided, write a short, engaging summary.",
        "Keep it under 300 words -- this will be sent over WhatsApp.",
        "End with a one-line takeaway.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------

content_workflow = Workflow(
    name="Content Workflow",
    description="Research a topic and deliver a WhatsApp-friendly summary.",
    db=workflow_db,
    steps=[
        Step(name="Research", agent=researcher),
        Step(name="Write", agent=writer),
    ],
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    workflows=[content_workflow],
    interfaces=[Whatsapp(workflow=content_workflow)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="content_workflow:app", port=8000)
