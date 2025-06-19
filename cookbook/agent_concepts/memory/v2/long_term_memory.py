from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(
    db_url=db_url,
    agent_session_table="test_agent_session_0618",
    user_memory_table="test_user_memories_0618",
)

memory = Memory(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    session_id="test_session",
    enable_user_memories=True,
)

agent.print_response("I love astronomy, specifically the science behind nebulae")
