"""Simple example creating a session and using the AgentOS with a MetricsApp to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Setup the agent
basic_agent = Agent(
    name="Basic Agent",
    model=Claude(id="claude-3-5-sonnet-20240620"),
    db=db,
    enable_user_memories=True,
    markdown=True,
)

# Setup the Agno API App
agent_os = AgentOS(
    description="Example app showcasing the MetricsApp",
    os_id="metrics-demo",
    agents=[basic_agent],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    basic_agent.print_response("What is the capital of France?")

    """ Run the Agno API App:
    Now you can interact with your metrics using the API. Examples:
    - http://localhost:8001/metrics
    """
    agent_os.serve(app="metrics_demo:app", reload=True)
