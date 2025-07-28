"""Simple example creating a session and using the AgentOS with a SessionApp to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.os import AgentOS
from agno.team import Team

# Setup the database and memory
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Sessions of this agent will be stored (it has memory)
basic_agent = Agent(
    db=db,
    enable_user_memories=True,
    agent_id="basic",
)
basic_team = Team(
    team_id="basic",
    members=[basic_agent],
    db=db,
    enable_user_memories=True,
)


# Setup the AgentOS
agent_os = AgentOS(agents=[basic_agent])
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
    agent_os.serve(app="session_demo:app", reload=True)
