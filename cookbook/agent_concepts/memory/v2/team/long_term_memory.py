from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(
    db_url=db_url,
    user_memory_table="user_memories",
    team_session_table="team_sessions",
)

memory = Memory(db=db)

agent = Agent(name="test_agent", model=OpenAIChat(id="gpt-4o-mini"))

team = Team(
    members=[agent],
    memory=memory,
    session_id="team_long_term_memory",
    enable_user_memories=True,
)

team.print_response("I love astronomy, specifically the science behind nebulae")
