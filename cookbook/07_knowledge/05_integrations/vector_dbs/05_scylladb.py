"""
ScyllaDB: high-performance, real-time database for AI
===============================================
ScyllaDB is a high-performance, real-time, distributed database
that provides low latency reads/writes and supports vector similarity search.

You can use ScyllaDB with Agno by reusing the existing Cassandra integration.

Key features:
- High-availability and fault tolerance
- Globally distributed, multi-region support
- Vector ANN search
- High throughput and low latency at scale
- Self-hosted or cloud (ScyllaDB Cloud)

Setup (self-hosted ScyllaDB):
    docker run -d --name scylla \
        -p 9042:9042 \
        scylladb/scylla:latest \
        --developer-mode=1 \
        --enable-cassio-compatibility=1

    Note: --enable-cassio-compatibility is required to ensure ScyllaDB can
    leverage the existing Cassandra integration.

Requires: pip install scylla-driver cassio

See also: 01_qdrant.py for Qdrant production, 02_local.py for local dev, 03_managed.py for Pinecone, 04_pgvector.py for PostgreSQL.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.cassandra import Cassandra
from cassandra.cluster import Cluster

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

SCYLLA_HOST = "127.0.0.1"
SCYLLA_PORT = 9042
KEYSPACE = "agno_knowledge"

# Connect and ensure the keyspace exists.
# For this example, we use a single-node ScyllaDB cluster running locally
# In production, you'd need at least three nodes.
cluster = Cluster([SCYLLA_HOST], port=SCYLLA_PORT)
session = cluster.connect()
session.execute(
    f"""
    CREATE KEYSPACE IF NOT EXISTS {KEYSPACE};
    """
)

# The vector store takes its dimension from the embedder, so the value set here
# determines the column size. text-embedding-3-small supports adjustable output
# dimensions via the API.
embedder = OpenAIEmbedder(id="text-embedding-3-small", dimensions=1024)

# --- Basic ScyllaDB setup ---
knowledge = Knowledge(
    vector_db=Cassandra(
        table_name="thai_recipes",
        keyspace=KEYSPACE,
        session=session,
        embedder=embedder,
    ),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    print("\n" + "=" * 60)
    print("ScyllaDB: Loading documents into vector store")
    print("=" * 60 + "\n")
    knowledge.insert(url=pdf_url)

    print("\n" + "=" * 60)
    print("ScyllaDB: Vector search")
    print("=" * 60 + "\n")
    agent.print_response("What Thai recipes do you know?", stream=True)

    print("\n" + "=" * 60)
    print("ScyllaDB: Second query")
    print("=" * 60 + "\n")
    agent.print_response(
        "What are the health benefits of Khao Niew Dam Piek Maphrao Awn?",
        stream=True,
    )
