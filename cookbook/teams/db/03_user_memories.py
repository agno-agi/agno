from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions", memory_table="user_memories")

agent = Agent(name="test_agent", model=OpenAIChat(id="o3-mini"))

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    session_id="team_user_memories",
    enable_user_memories=True,
)

team.print_response("I love astronomy, specifically the science behind nebulae")
