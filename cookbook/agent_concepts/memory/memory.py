from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, agent_session_table="Friday_13")

memory = Memory(db=db)

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), memory=memory)

agent.print_response("Tell me an interesting fact about the moon")
