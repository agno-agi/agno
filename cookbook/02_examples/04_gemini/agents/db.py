# ============================================================================
# Configure database for storing agent sessions, memories, metrics, evals and knowledge
# ============================================================================
from agno.db.postgres import PostgresDb

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
gemini_agents_db = PostgresDb(id="gemini-agents-db", db_url=db_url)
