"""
Local Vector Databases: ChromaDB and LanceDB
==============================================
For local development and prototyping, you can use embedded vector databases
that don't require a server.

ChromaDB:
- In-memory or persistent storage
- Simple setup, good for prototyping
- pip install chromadb

LanceDB:
- File-based storage (no server needed)
- Supports hybrid search
- pip install lancedb tantivy

See also: 01_qdrant.py for production, 03_managed.py for Pinecone, 04_pgvector.py for PostgreSQL.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# ChromaDB Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.chroma import ChromaDb

    knowledge_chroma = Knowledge(
        vector_db=ChromaDb(
            collection="local_demo",
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
except ImportError:
    knowledge_chroma = None
    print("ChromaDB not installed. Run: pip install chromadb")

# ---------------------------------------------------------------------------
# LanceDB Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.lancedb import LanceDb, SearchType

    knowledge_lance = Knowledge(
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="local_demo",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
except ImportError:
    knowledge_lance = None
    print("LanceDB not installed. Run: pip install lancedb tantivy")

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    if knowledge_chroma:
        print("\n" + "=" * 60)
        print("ChromaDB: in-memory vector database")
        print("=" * 60 + "\n")

        knowledge_chroma.insert(url=pdf_url)
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_chroma,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response("What Thai recipes do you know?", stream=True)

    if knowledge_lance:
        print("\n" + "=" * 60)
        print("LanceDB: file-based vector database with hybrid search")
        print("=" * 60 + "\n")

        knowledge_lance.insert(url=pdf_url)
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_lance,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response("What Thai desserts are available?", stream=True)
