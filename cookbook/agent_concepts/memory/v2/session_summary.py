from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

memory = Memory(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_session_summaries=True,
    session_id="session_summary",
)


agent.print_response("Hi my name is John and I live in New York")
agent.print_response("I like to play basketball and hike in the mountains")
