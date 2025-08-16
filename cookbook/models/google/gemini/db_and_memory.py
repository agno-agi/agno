"""Run `pip install duckduckgo-search pgvector google.genai` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(db_url=db_url)

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
# Add content to the knowledge
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-001"),
    tools=[DuckDuckGoTools()],
    knowledge=knowledge,
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    # This setting adds a tool to search the knowledge for information
    search_knowledge=True,
    # This setting adds a tool to get chat history
    read_chat_history=True,
    # Add the previous chat history to the context sent to the Model.
    add_history_to_context=True,
    # This setting adds 6 previous messages from chat history to the messages sent to the LLM
    markdown=True,
    debug_mode=True,
    num_history_runs=6,
)
agent.print_response("Whats is the latest AI news?")
