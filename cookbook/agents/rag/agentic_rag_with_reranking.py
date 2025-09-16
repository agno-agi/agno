"""
1. Run: `pip install openai agno cohere lancedb tantivy sqlalchemy` to install the dependencies
2. Export your OPENAI_API_KEY and CO_API_KEY
3. Run: `python cookbook/agent_concepts/rag/agentic_rag_with_reranking.py` to run the agent
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIChat
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
        reranker=CohereReranker(
            model="rerank-multilingual-v3.0"
        ),  # Use Cohere for reranking
    ),
)

knowledge.add_content(name="Agno Docs", url="https://docs.agno.com/introduction.md")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge,
    markdown=True,
)

if __name__ == "__main__":
    # Load the knowledge base, comment after first run
    agent.print_response("What are Agno's key features?")
