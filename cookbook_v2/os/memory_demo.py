from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(db_url=db_url)

# Setup the agent
agent = Agent(
    name="Memory Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
    markdown=True,
)

# Setup the Agno API App
agno_client = AgentOS(
    description="Example app for basic agent with memory capabilities",
    os_id="memory-demo",
    agents=[agent],
)
app = agno_client.get_app()


if __name__ == "__main__":
    # Generate a memory
    agent.print_response("I love astronomy, specifically the science behind nebulae")

    """ Run your AgentOS:
    Now you can interact with your memory using the API. Examples:
    - http://localhost:8001/memory/{id}/memories
    - http://localhost:8001/memory/{id}/memories/123
    - http://localhost:8001/memory/{id}/memories?agent_id=123
    - http://localhost:8001/memory/{id}/memories?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agno_client.serve(app="memory_demo:app", reload=True)
