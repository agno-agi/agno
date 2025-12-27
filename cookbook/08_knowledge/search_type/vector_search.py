from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Load knowledge base using vector search
vector_db = PgVector(table_name="recipes", db_url=db_url, search_type=SearchType.vector)
knowledge = Knowledge(
    name="Vector Search Knowledge Base",
    vector_db=vector_db,
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)

# Run a vector-based query
results = vector_db.search("chicken coconut soup", limit=5)
print("Vector Search Results:", results)
