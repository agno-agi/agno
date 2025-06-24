"""Simple example creating a session and using the AgentOS with a SessionConnector to expose it"""

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.connectors import SessionConnector
from agno.db.postgres.postgres import PostgresDb
from agno.memory import Memory
from agno.models.openai import OpenAIChat

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_sessions",
    team_session_table="team_sessions",
    workflow_session_table="workflow_sessions",
)

# Setup the memory
memory = Memory(db=db)

# Setup the agent
basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    markdown=True,
)

# Setup the Agno API App
agent_os = AgentOS(
    name="Example App: Session Agent",
    description="Example app for basic agent with session capabilities",
    os_id="session-demo",
    agents=[basic_agent],
    apps=[SessionConnector(db=db)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    basic_agent.print_response("What is the capital of France?")

    """ Run the Agno API App:
    Now you can interact with your sessions using the API. Examples:
    - http://localhost:8001/session/{id}/sessions
    - http://localhost:8001/session/{id}/sessions/123
    - http://localhost:8001/session/{id}/sessions?agent_id=123
    - http://localhost:8001/session/{id}/sessions?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agent_os.serve(app="session_connector:app", reload=True)
