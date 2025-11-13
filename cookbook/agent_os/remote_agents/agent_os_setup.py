"""
This acts as the setup for the remote AgentOS instance for testing the remote agents, teams and workflows.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Setup the database
db = PostgresDb(id="basic-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Setup basic agents, teams and workflows
basic_agent = Agent(
    name="Basic Agent",
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)
basic_team = Team(
    id="basic-team",
    name="Basic Team",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[basic_agent],
    add_history_to_context=True,
    num_history_runs=3,
)
basic_workflow = Workflow(
    id="basic-workflow",
    name="Basic Workflow",
    description="Just a simple workflow",
    db=db,
    steps=[
        Step(
            name="step1",
            description="Just a simple step",
            agent=basic_agent,
        )
    ],
    add_workflow_history_to_steps=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for basic agent, team and workflow",
    agents=[basic_agent],
    teams=[basic_team],
    workflows=[basic_workflow],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7778/config

    """
    agent_os.serve(app="agent_os_setup:app", reload=True, access_log=True, port=7778)
