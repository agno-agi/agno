"""
Cosmos MongoDB vCore
====================

Demonstrates Cosmos DB (MongoDB vCore compatibility) as a vector DB backend.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.mongodb import MongoVectorDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
mdb_connection_string = "mongodb+srv://<username>:<encoded_password>@cluster0.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge_base = Knowledge(
    vector_db=MongoVectorDb(
        collection_name="recipes",
        db_url=mdb_connection_string,
        search_index_name="recipes",
        cosmos_compatibility=True,
    ),
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(knowledge=knowledge_base)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    knowledge_base.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    agent.print_response("How to make Thai curry?", markdown=True)


if __name__ == "__main__":
    main()
