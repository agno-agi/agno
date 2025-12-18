"""Example showing how to use AgentOS with a Postgres database, using our async interface"""

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Setup the Postgres database
db = AsyncPostgresDb(db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai")

# Setup a basic agent, team and workflow
agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
    members=[agent],
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
            agent=agent,
        )
    ],
)

# Setup the AgentOS
agent_os = AgentOS(
    description="Example OS setup",
    agents=[agent],
    teams=[team],
    workflows=[basic_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="async_postgres_demo:app", reload=True)
