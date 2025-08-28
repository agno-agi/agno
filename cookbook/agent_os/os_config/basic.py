from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import (
    AgentOSConfig,
    ChatConfig,
    DatabaseConfig,
    MemoryConfig,
    MemoryDomainConfig,
)
from agno.os.interfaces.slack import Slack
from agno.os.interfaces.whatsapp import Whatsapp
from agno.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", id="db-0001")
db2 = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai2", id="db-0002")

# Setup basic agents, teams and workflows
basic_agent = Agent(
    id="basic-agent",
    name="Basic Agent",
    db=db,
    enable_session_summaries=True,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
basic_team = Team(
    id="basic-team",
    name="Basic Team",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[basic_agent],
    enable_user_memories=True,
)
basic_workflow = Workflow(
    id="basic-workflow",
    name="Basic Workflow",
    description="Just a simple workflow",
    db=db2,
    steps=[
        Step(
            name="step1",
            description="Just a simple step",
            agent=basic_agent,
        )
    ],
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example AgentOS",
    os_id="basic-os",
    agents=[basic_agent],
    teams=[basic_team],
    workflows=[basic_workflow],
    interfaces=[Whatsapp(agent=basic_agent), Slack(agent=basic_agent)],
    # Configuration for the AgentOS
    config=AgentOSConfig(
        chat=ChatConfig(
            quick_prompts={
                "basic-agent": [
                    "What can you do?",
                    "What tools do you have?",
                    "Tell me about AgentOS",
                ],
                "basic-team": ["Which members are in the team?"],
                "basic-workflow": ["What are the steps in the workflow?"],
            },
        ),
        memory=MemoryConfig(
            display_name="Default Memory Page Name",
            dbs=[
                DatabaseConfig(
                    db_id=db.id,
                    domain_config=MemoryDomainConfig(
                        display_name="Postgres Memory",
                    ),
                )
            ],
        ),
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available endpoints at:
    http://localhost:7777/config
    """
    agent_os.serve(app="basic:app", reload=True)
