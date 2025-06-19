"""Simple example creating a session and using the AgnoAPI with a SessionManager to expose it"""

from agno.agent import Agent
from agno.app.agno_api import AgnoAPI
from agno.app.agno_api.interfaces.playground import Playground
from agno.app.agno_api.managers.session.session import SessionManager
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
agno_client = AgnoAPI(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[basic_agent],
    interfaces=[Playground()],
    managers=[SessionManager(db=db)],
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
    - http://localhost:8001/sessions/v1/sessions?limit=10&offset=0&sort_by=created_at&sort_order=desc
    """
    agno_client.serve(app="session_manager:app", reload=True)
