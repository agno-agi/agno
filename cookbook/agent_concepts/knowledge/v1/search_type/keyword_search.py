from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Load knowledge base using keyword search
keyword_db = PgVector(
    table_name="recipes", db_url=db_url, search_type=SearchType.keyword
)
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=keyword_db,
)

# Load data (only required for first time)
knowledge_base.load(recreate=True, upsert=True)

# Run a keyword-based query
results = keyword_db.search("chicken coconut soup", limit=5)
print("Keyword Search Results:", results)
