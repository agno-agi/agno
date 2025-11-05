"""
This example shows how to use Redis as a vector database with Agno.

To get started, either set the REDIS_URL environment variable to your Redis connection string,
or start the local Redis docker container using the following command:
./cookbook/scripts/run_redis.sh

"""

import os

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.redis import RedisVectorDb
from agno.vectordb.search import SearchType

# Configure Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INDEX_NAME = os.getenv("REDIS_INDEX", "agno_cookbook_vectors")

# Initialize Redis Vector DB
vector_db = RedisVectorDb(
    index_name=INDEX_NAME,
    redis_url=REDIS_URL,
    search_type=SearchType.vector,  # try SearchType.hybrid for hybrid search
)

# Build a Knowledge base backed by Redis
knowledge = Knowledge(
    name="My Redis Vector Knowledge Base",
    description="This knowledge base uses Redis + RedisVL as the vector store",
    vector_db=vector_db,
)

# Add content (ingestion + chunking + embedding handled by Knowledge)
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
    skip_if_exists=True,
)

# Query with an Agent
agent = Agent(knowledge=knowledge)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# Cleanup examples (uncomment to remove the content)
# vector_db.delete_by_name("Recipes")
# or
# vector_db.delete_by_metadata({"doc_type": "recipe_book"})
