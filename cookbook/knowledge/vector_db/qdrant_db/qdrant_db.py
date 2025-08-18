from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "thai-recipes"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

knowledge = Knowledge(
    name="My Qdrant Vector Knowledge Base",
    description="This is a knowledge base that uses a Qdrant Vector DB",
    vector_db=vector_db,
    contents_db=contents_db,
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

# Create and use the agent
agent = Agent(knowledge=knowledge)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)


vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
