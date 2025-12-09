# ============================================================================
# Database Session
# ============================================================================
from agno.db.postgres import PostgresDb

from db.url import db_url

docs_db = PostgresDb(id="docs-assistant-db", db_url=db_url)
