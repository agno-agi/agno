from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

# agent = Agent(id="basic_agent", model=OpenAIChat(id="gpt-4o-mini"))

# team = Team(
#     id="basic_team",
#     model=OpenAIChat(id="gpt-4o-mini"),
#     members=[agent],
#     db=db,
#     session_id="team_session_storage",
#     add_history_to_context=True,
# )

# team.print_response("Tell me a new interesting fact about space. Ask your team members to help you.")

# Team member with storage
agent = Agent(
    id="test_agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    add_history_to_context=True,
)

team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[agent],
    db=db,
    session_id="team_session_storage",
)

team.print_response("Tell me a new interesting fact about space")
