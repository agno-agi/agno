from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Load knowledge base using vector search
vector_db = PgVector(table_name="recipes", db_url=db_url, search_type=SearchType.vector)
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

# Load data (only required for first time)
knowledge_base.load(recreate=True, upsert=True)

# Run a vector-based query
results = vector_db.search("chicken coconut soup", limit=5)
print("Vector Search Results:", results)
