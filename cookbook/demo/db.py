from agno.db.postgres import PostgresDb

# ============================================================================
# Configure database for storing session, memory and knowledge
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url, session_table="agno_knowledge_agent")
