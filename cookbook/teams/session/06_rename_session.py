from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
)

team.print_response("Tell me a new interesting fact about space")
team.set_session_name(session_name="Interesting Space Facts")
print(team.get_session_name())

# Autogenerate session name
team.set_session_name(autogenerate=True)
print(team.get_session_name())
