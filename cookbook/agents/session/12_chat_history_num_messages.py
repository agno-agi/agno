from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="chat_history",
    add_history_to_context=True,
    num_history_messages=1,  # Only include the assistant response
)

agent.print_response("Tell me a new interesting fact about space")
agent.print_response("Repeat the last message, but make it much more concise")
