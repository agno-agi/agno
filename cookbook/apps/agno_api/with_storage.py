from agno.agent import Agent
from agno.app.agno_api import AgnoAPI
from agno.app.agno_api.interfaces.playground import Playground
from agno.app.agno_api.managers.storage.storage import Storage
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"

storage = PostgresDb(db_url=db_url, agent_sessions_table_name="agent_sessions")

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    storage=storage,
    add_datetime_to_instructions=True,
    markdown=True,
)

agno_client = AgnoAPI(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[basic_agent],
    interfaces=[Playground()],
    managers=[Storage(storage=storage)],
)
app = agno_client.get_app()

if __name__ == "__main__":
    agno_client.serve(app="with_storage:app", reload=True)
