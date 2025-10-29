from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Load knowledge base using hybrid search
hybrid_db = PgVector(table_name="recipes", db_url=db_url, search_type=SearchType.hybrid)
knowledge = Knowledge(
    name="Hybrid Search Knowledge Base",
    vector_db=hybrid_db,
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)

# Run a hybrid search query
results = hybrid_db.search("chicken coconut soup", limit=5)
print("Hybrid Search Results:", results)
