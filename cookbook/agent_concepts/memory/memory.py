from agno.db.postgres import PostgresDb
from agno.agent.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, agent_sessions="agent_sessions_2")

memory = Memory(db=db)

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), memory=memory, session_id="test_session_1")

agent.print_response("How is it going?")