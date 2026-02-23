"""
Managed Vector Databases: Pinecone and Qdrant
===============================================
For cloud-hosted, fully managed vector search at scale.

Pinecone:
- Fully managed, serverless option available
- Automatic scaling and high availability
- pip install pinecone

Qdrant:
- Cloud or self-hosted options
- Rich filtering capabilities
- pip install qdrant-client

See also: 01_pgvector.py for production self-hosted, 02_local.py for local dev.
"""

from os import getenv

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Pinecone Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.pineconedb import PineconeDb

    knowledge_pinecone = Knowledge(
        vector_db=PineconeDb(
            name="knowledge-demo",
            api_key=getenv("PINECONE_API_KEY"),
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
except ImportError:
    knowledge_pinecone = None
    print("Pinecone not installed. Run: pip install pinecone")

# ---------------------------------------------------------------------------
# Qdrant Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.qdrant import Qdrant

    knowledge_qdrant = Knowledge(
        vector_db=Qdrant(
            collection="knowledge-demo",
            url=getenv("QDRANT_URL", "http://localhost:6333"),
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
except ImportError:
    knowledge_qdrant = None
    print("Qdrant not installed. Run: pip install qdrant-client")

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    if knowledge_pinecone:
        print("\n" + "=" * 60)
        print("Pinecone: managed serverless vector database")
        print("=" * 60 + "\n")

        knowledge_pinecone.insert(url=pdf_url)
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_pinecone,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response("What Thai recipes do you know?", stream=True)

    if knowledge_qdrant:
        print("\n" + "=" * 60)
        print("Qdrant: managed or self-hosted vector database")
        print("=" * 60 + "\n")

        knowledge_qdrant.insert(url=pdf_url)
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_qdrant,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response("What Thai desserts are available?", stream=True)
