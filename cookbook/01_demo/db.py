# ============================================================================
# Configure database for storing sessions, memories, metrics, evals and knowledge
# ============================================================================
from agno.db.postgres import PostgresDb

# Used for Knowledge VectorDB
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
demo_db = PostgresDb(id="agno-demo-db", db_url=db_url)
