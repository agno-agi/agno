"""Run `uv pip install ddgs sqlalchemy 'psycopg[binary]' pgvector pypdf openai google.genai` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes",
        db_url=db_url,
        embedder=GeminiEmbedder(),
    ),
)
# Add content to the knowledge; reruns skip re-ingesting via the content hash
knowledge.insert(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    skip_if_exists=True,
)

agent = Agent(
    model=Gemini(id="gemini-3.7-flash"),
    tools=[WebSearchTools()],
    knowledge=knowledge,
    # Store the memories and summary in a database
    db=PostgresDb(db_url=db_url, memory_table="agent_memory"),
    update_memory_on_run=True,
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

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
