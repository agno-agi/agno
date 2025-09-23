from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url,
)
# *******************************


memory_agent = Agent(
    name="Memory Agent",
    id="memory-agent",
    model=OpenAIChat(id="gpt-4.1"),
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
    # Set a database
    db=db,
    # Enable memory
    enable_user_memories=True,
    # Add a tool to search the web
    tools=[DuckDuckGoTools()],
)
