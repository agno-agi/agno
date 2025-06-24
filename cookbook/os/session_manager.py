"""Simple example creating a session and using the AgentOS with a SessionConnector to expose it"""

from agno.agent import Agent
from agno.os import AgentOS
from agno.os import Playground
from agno.os.connectors.session.session import SessionConnector
from agno.db.postgres.postgres import PostgresDb
from agno.memory import Memory
from agno.models.openai import OpenAIChat

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
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
agno_client = AgentOS(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[basic_agent],
    interfaces=[Playground()],
    managers=[SessionConnector(db=db)],
)
app = agno_client.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    basic_agent.print_response("What is the capital of France?")

    """ Run the Agno API App:
    Now you can interact with your sessions using the API. Examples:
    - http://localhost:8001/sessions/v1/sessions
    - http://localhost:8001/sessions/v1/sessions/123
    - http://localhost:8001/sessions/v1/sessions?agent_id=123
    - http://localhost:8001/sessions/v1/sessions?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agno_client.serve(app="session_manager:app", reload=True)
