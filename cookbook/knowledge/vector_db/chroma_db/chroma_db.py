import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb

# Create Knowledge Instance with ChromaDB
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with ChromaDB",
    vector_db=ChromaDb(
        collection="vectors", path="tmp/chromadb", persistent_client=True
    ),
)

asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book"},
    )
)

# Create and use the agent
agent = Agent(knowledge=knowledge)


agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# Delete operations examples
vector_db = knowledge.vector_db
vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"user_tag": "Recipes from website"})
