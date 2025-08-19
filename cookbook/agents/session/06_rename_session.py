from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="chat_history",
    instructions="You are a helpful assistant that can answer questions about space and oceans.",
    add_history_to_context=True,
)

agent.print_response("Tell me a new interesting fact about space")
agent.set_session_name(session_name="Interesting Space Facts")

session = agent.get_session(session_id=agent.session_id)
print(session.session_data.get("session_name"))

agent.set_session_name(autogenerate=True)

session = agent.get_session(session_id=agent.session_id)
print(session.session_data.get("session_name"))
