from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, team_session_table="team_sessions")

memory = Memory(db=db)

agent = Agent(name="test_agent", model=OpenAIChat(id="gpt-4o-mini"))

team = Team(
    members=[agent],
    memory=memory,
    session_id="team_short_term_memory",
    add_history_to_messages=True,
)

team.print_response("Tell me a new interesting fact about space")
