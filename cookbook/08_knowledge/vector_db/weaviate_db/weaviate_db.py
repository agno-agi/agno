from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Weaviate
from agno.vectordb.weaviate.index import Distance, VectorIndex

vector_db = Weaviate(
    collection="vectors",
    search_type=SearchType.vector,
    vector_index=VectorIndex.HNSW,
    distance=Distance.COSINE,
    local=False,  # Set to True if using Weaviate locally
)

# Create Knowledge Instance with Weaviate
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with Weaviate",
    vector_db=vector_db,
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
    skip_if_exists=True,
)

# Create and use the agent
agent = Agent(knowledge=knowledge)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# Delete operations
vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
