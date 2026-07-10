"""
Managed Vector Databases: Pinecone
====================================
Pinecone is a fully managed, serverless vector database for
production workloads where you want zero infrastructure management.

Features:
- Fully managed, serverless option available
- Automatic scaling and high availability
- Metadata filtering
- Namespaces for multi-tenancy

Requires: pip install pinecone

See also: 01_qdrant.py for recommended default, 04_pgvector.py for PostgreSQL.
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
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if knowledge_pinecone:
        print("\n" + "=" * 60)
        print("Pinecone: managed serverless vector database")
        print("=" * 60 + "\n")

        knowledge_pinecone.insert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_pinecone,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response("What Thai recipes do you know?", stream=True)
    else:
        print("Skipping demo: Pinecone not installed.")
