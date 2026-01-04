"""
Database Configuration
======================
Shared database setup for all Learning Machine cookbooks.

Uses PostgreSQL with PgVector for:
- Agent sessions and state
- User profiles and memories
- Session contexts
- Entity memory
- Learned knowledge (vector embeddings)
"""

from agno.db.postgres import PostgresDb

# ============================================================================
# Database URL
# ============================================================================
# Default: Local PostgreSQL with pgvector extension
# To use a different database, set the AGNO_DB_URL environment variable
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# ============================================================================
# Shared Database Instance
# ============================================================================
# Used by all agents in this cookbook
db = PostgresDb(id="learning-cookbook-db", db_url=db_url)
