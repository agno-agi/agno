from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

# Create Knowledge Instance with LanceDB
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with LanceDB",
    vector_store=LanceDb(
        table_name="vectors",
        uri="tmp/lancedb",
    ),
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes from website"},
)

# Create and use the agent
agent = Agent(knowledge=knowledge)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"user_tag": "Recipes from website"})
