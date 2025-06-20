from agno.agent import Agent
from agno.app.agno_api import AgnoAPI
from agno.app.agno_api.interfaces.playground import Playground
from agno.app.agno_api.managers.memory.memory import MemoryManager
from agno.db.postgres.postgres import PostgresDb
from agno.memory import Memory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_session",
    user_memory_table="user_memory",
)

# Setup the memory
memory = Memory(db=db)

# Setup the agent
agent = Agent(
    name="Memory Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    markdown=True,
)

# Setup the Agno API App
agno_client = AgnoAPI(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[agent],
    interfaces=[Playground()],
    managers=[MemoryManager(memory=memory)],
)
app = agno_client.get_app()


if __name__ == "__main__":
    # Generate a memory
    agent.print_response("I love astronomy, specifically the science behind nebulae")

    # Run the Agno API App
    agno_client.serve(app="with_memory:app", reload=True)
