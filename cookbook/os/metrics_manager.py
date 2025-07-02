"""Simple example creating a session and using the AgentOS with a MetricsManager to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.memory import Memory
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.managers import MetricsManager, SessionManager

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_sessions",
    team_session_table="team_sessions",
    workflow_session_table="workflow_sessions",
    metrics_table="metrics",
)

# Setup the memory
memory = Memory(db=db)

# Setup the agent
basic_agent = Agent(
    name="Basic Agent",
    model=Claude(id="claude-3-5-sonnet-20240620"),
    session_id="123",
    memory=memory,
    enable_user_memories=True,
    markdown=True,
)

# Setup the Agno API App
agent_os = AgentOS(
    name="Example App: Metrics",
    description="Example app showcasing the MetricsManager",
    os_id="metrics-demo",
    agents=[basic_agent],
    apps=[SessionManager(db=db), MetricsManager(db=db)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    basic_agent.print_response("What is the capital of France?")

    """ Run the Agno API App:
    Now you can interact with your metrics using the API. Examples:
    - http://localhost:8001/metrics
    """
    agent_os.serve(app="metrics_manager:app", reload=True)
