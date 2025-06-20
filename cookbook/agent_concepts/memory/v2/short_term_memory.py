from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, agent_session_table="test_agent_session_0619")

memory = Memory(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    session_id="test_session_0619_11",
    add_history_to_messages=True,
)

agent.print_response("Tell me a new interesting fact about space")
