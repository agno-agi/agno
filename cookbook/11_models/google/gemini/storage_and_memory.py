"""Run `pip install ddgs pgvector google.genai` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge import PDFUrlKnowledgeBase
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
knowledge_base.load(recreate=True)  # Comment out after first run

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-001"),
    tools=[DuckDuckGoTools()],
    knowledge=knowledge_base,
    # Store the memories and summary in a database
    db=PostgresDb(db_url=db_url, memory_table="agent_memory"),
    enable_user_memories=True,
    enable_session_summaries=True,
    # This setting adds a tool to search the knowledge base for information
    search_knowledge=True,
    # This setting adds a tool to get chat history
    read_chat_history=True,
    # Add the previous chat history to the messages sent to the Model.
    add_history_to_context=True,
    # This setting adds 6 previous messages from chat history to the messages sent to the LLM
    num_history_runs=6,
    markdown=True,
)
agent.print_response("Whats is the latest AI news?")
