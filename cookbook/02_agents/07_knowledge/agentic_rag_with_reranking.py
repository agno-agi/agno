"""
Agentic Rag With Reranking
=============================

1. Run: `uv pip install openai agno cohere lancedb sqlalchemy` to install the dependencies.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    # Use LanceDB as the vector database and store embeddings in the `agno_docs` table
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(
            id="text-embedding-3-small"
        ),  # Use OpenAI for embeddings
    ),
    # Reranking belongs on Knowledge: it applies to every vector db and can
    # widen the candidate pool for rerankers that need one.
    # Use Cohere for reranking.
    reranker=CohereReranker(model="rerank-multilingual-v3.0"),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    knowledge.insert(name="Agno Docs", url="https://docs.agno.com/introduction")
    agent.print_response("What are Agno's key features?")
