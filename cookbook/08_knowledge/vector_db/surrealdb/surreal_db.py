# Run SurrealDB in a container before running this script
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.surrealdb import SurrealDb
from surrealdb import Surreal

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"

# Create a client
client = Surreal(url=SURREALDB_URL)
client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)

surrealdb = SurrealDb(
    client=client,
    collection="recipes",  # Collection name for storing documents
    efc=150,  # HNSW construction time/accuracy trade-off
    m=12,  # HNSW max number of connections per element
    search_ef=40,  # HNSW search time/accuracy trade-off
    embedder=OpenAIEmbedder(),
)


def sync_demo():
    """Demonstrate synchronous usage of SurrealDb"""
    knowledge = Knowledge(
        vector_db=surrealdb,
    )

    # Load data synchronously
    knowledge.add_content(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    )

    # Create agent and query synchronously
    agent = Agent(knowledge=knowledge)
    agent.print_response(
        "What are the 3 categories of Thai SELECT is given to restaurants overseas?",
        markdown=True,
    )


if __name__ == "__main__":
    # Run synchronous demo
    print("Running synchronous demo...")
    sync_demo()
