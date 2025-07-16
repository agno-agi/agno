from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = Knowledge(
    name="My PG Vector Knowledge Base",
    description="This is a knowledge base that uses a PG Vector DB",
    vector_store=PgVector(table_name="vectors", db_url=db_url),
)
knowledge_base.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes from website"},
)

# knowledge_base.remove_vector_by_name("Recipes")

# knowledge_base.remove_vector_by_metadata({"user_tag": "Recipes from website"})
