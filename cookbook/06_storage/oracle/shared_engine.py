"""Share a configured Oracle connection pool without copying Agno's engine defaults."""

from os import getenv

from agno.db.oracle import OracleDb
from agno.db.oracle.engine import create_oracle_engine
from agno.fs.db import DbFileSystem

# ---------------------------------------------------------------------------
# Create the shared engine and database
# ---------------------------------------------------------------------------
engine = create_oracle_engine(
    getenv(
        "DATABASE_URL", "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1"
    ),
    pool_size=5,
    max_overflow=5,
)
db = OracleDb(id="shared-oracle", db_engine=engine)
files = DbFileSystem(db=db, table_name="agent_files")
# OracleVector(db=db, table_name="knowledge", ...) can borrow this same pool.

# ---------------------------------------------------------------------------
# Run: inspect configuration without connecting to the database
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Oracle engine configured; no database connection opened.")
    print("Filesystem shares the database engine:", files.db_engine is db.db_engine)
