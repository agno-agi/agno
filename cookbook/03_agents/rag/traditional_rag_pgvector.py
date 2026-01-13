"""
1. Run: `./cookbook/run_pgvector.sh` to start a postgres container with pgvector
2. Run: `pip install openai sqlalchemy 'psycopg[binary]' pgvector agno` to install the dependencies
3. Run: `python cookbook/rag/01_traditional_rag_pgvector.py` to run the agent
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    # Use PgVector as the vector database and store embeddings in the `ai.recipes` table
    vector_db=PgVector(
        table_name="recipes",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    # Enable RAG by adding context from the `knowledge` to the user prompt.
    add_knowledge_to_context=True,
    # Set as False because Agents default to `search_knowledge=True`
    search_knowledge=False,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
