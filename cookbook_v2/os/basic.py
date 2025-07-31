from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.team import Team
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(db_url=db_url)


basic_agent = Agent(
    name="Basic Agent",
    agent_id="basic-agent",
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_messages=True,
    num_history_runs=3,
    add_datetime_to_instructions=True,
    markdown=True,
)
basic_team = Team(
    team_id="basic-team",
    name="Basic Team",
    db=db,
    description="Just a simple team",
    members=[basic_agent],
)
basic_workflow = Workflow(
    workflow_id="basic-workflow",
    name="Basic Workflow",
    description="Just a simple workflow",
    steps=[
        Step(
            name="step1",
            description="Just a simple step",
            agent=basic_agent,
        )
    ],
)

agent_os = AgentOS(
    description="Example app for basic agent with playground capabilities",
    os_id="basic-app",
    agents=[basic_agent],
    teams=[basic_team],
    workflows=[basic_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
