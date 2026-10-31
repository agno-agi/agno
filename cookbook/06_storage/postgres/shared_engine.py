"""Share a configured PostgreSQL pool without copying Agno's engine defaults."""

from os import getenv

from agno.db.postgres import PostgresDb, create_postgres_engine
from agno.fs.db import DbFileSystem

# ---------------------------------------------------------------------------
# Create the shared engine and database
# ---------------------------------------------------------------------------
engine = create_postgres_engine(
    getenv("DATABASE_URL", "postgresql://ai:ai@localhost:5532/ai"),
    pool_size=5,
    max_overflow=5,
    connect_args={"connect_timeout": 5},
)
db = PostgresDb(id="shared-postgres", db_engine=engine)
files = DbFileSystem(db=db, table_name="agent_files", db_schema="ai")
# PgVector(db=db, table_name="knowledge", ...) can borrow this same pool.

# ---------------------------------------------------------------------------
# Inspect configuration without connecting to the database
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("PostgreSQL engine configured; no database connection opened.")
    print("Filesystem shares the database engine:", files.db_engine is db.db_engine)
