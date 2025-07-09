from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memories",
)

memory = Memory(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    session_id="long_term_memory",
    enable_user_memories=True,
)

agent.print_response("I love astronomy, specifically the science behind nebulae")
