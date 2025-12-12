from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

db_data = db.to_dict()

db2 = PostgresDb.from_dict(db_data)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db2,
    tools=[DuckDuckGoTools()],
)

agent.print_response("How many people live in Canada?")
