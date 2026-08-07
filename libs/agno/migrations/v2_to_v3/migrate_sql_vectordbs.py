# mypy: disable-error-code=var-annotated
"""Migrate SQL-based Agno VectorDBs for per-user isolation (v2 -> v3).

v3 adds per-user RAG isolation: each stored chunk carries an owner ``user_id``
column, and scoped searches return ``WHERE user_id = <caller> OR user_id IS NULL``
(``NULL`` = shared / org-wide, visible to everyone).

Existing (pre-v3) tables have no ``user_id`` column. The adapter only creates
the schema when the table does NOT already exist, so an existing table is left
untouched and the new code fails with ``column "user_id" does not exist`` on the
first insert/search. This script adds the column (and its index) to existing
tables.

Data safety: no rows are moved or rewritten. After the column is added, every
existing row has ``user_id = NULL`` and is therefore treated as SHARED — it stays
visible to all callers. So this is a pure, non-destructive schema migration.

Backends:
- PgVector    -> ALTER TABLE ADD COLUMN user_id VARCHAR + btree index
- SingleStore -> ALTER TABLE ADD COLUMN user_id VARCHAR(255)

Optional ownership backfill (NOT done here): if you want to *assign* existing
shared chunks to a specific owner instead of leaving them shared, you can
``UPDATE <table> SET user_id = '<owner>' WHERE ...``.
  * PgVector: safe in place — the row id does not depend on user_id.
  * SingleStore: the row id folds user_id in (``md5(base_id_content_hash_user_id)``),
    so a bare UPDATE leaves the id inconsistent with what a later scoped upsert
    computes, creating a duplicate on the next re-upsert. To reassign an owner on
    SingleStore, delete + re-insert the chunk under the target user instead.

Usage:
- Set ``pg_vector_db_url`` + ``pg_vector_config`` for PgVector, and/or
  ``singlestore_db_url`` + ``singlestore_config`` for SingleStore.
- Run the script.
"""

from agno.utils.log import log_error, log_info, log_warning

# ------------ Setup for PgVector ------------

## Your database connection string
pg_vector_db_url = ""  # Example: "postgresql+psycopg://ai:ai@localhost:5532/ai"

## Configuration of the schema and tables to migrate
pg_vector_config = {
    # "schema": "ai",  # Schema where your tables are located
    # "table_names": ["documents"],  # Tables to migrate
}
# -----------------------------------------

# ------------ Setup for SingleStore ------------

# Your database connection string
singlestore_db_url = ""  # Example: "mysql+pymysql://user:password@host:port/database"

# Exact configuration of the tables to migrate
singlestore_config = {
    # "schema": "ai",  # Schema where your tables are located
    # "table_names": ["documents"],  # Tables to migrate
}
# -----------------------------------------

#  Exit if no configurations are provided
def migrate_pgvector_table(table_name: str, schema: str = "ai") -> None:
    """Add the ``user_id`` column (and its index) to a PgVector table.

    Idempotent: skips the table if the column already exists.

    Args:
        table_name: Name of the table to migrate.
        schema: Database schema name.
    """
    try:
        log_info(f"Starting user_id migration for PgVector table: {schema}.{table_name}")

        from agno.vectordb.pgvector.pgvector import PgVector

        pgvector = PgVector(table_name=table_name, schema=schema, db_url=pg_vector_db_url)

        if not pgvector.table_exists():
            log_warning(f"Table {schema}.{table_name} not found. Skipping migration.")
            return

        from sqlalchemy import inspect, text
        from sqlalchemy.exc import SQLAlchemyError

        inspector = inspect(pgvector.db_engine)
        column_names = [col["name"] for col in inspector.get_columns(table_name, schema=schema)]

        if "user_id" in column_names:
            log_info(f"Table {schema}.{table_name} already has the user_id column. No migration needed.")
            return

        # Add the owner column. Nullable, defaulting to NULL = shared.
        with pgvector.Session() as sess, sess.begin():
            log_info(f"Adding user_id column to {schema}.{table_name}")
            sess.execute(text(f'ALTER TABLE "{schema}"."{table_name}" ADD COLUMN user_id VARCHAR;'))

        # Index it for fast scope filtering (mirrors idx_{table}_user_id in the adapter).
        with pgvector.Session() as sess, sess.begin():
            index_name = f"idx_{table_name}_user_id"
            log_info(f"Creating index {index_name} on user_id column")
            try:
                sess.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{schema}"."{table_name}" (user_id);')
                )
            except SQLAlchemyError as e:
                log_warning(f"Could not create index {index_name}: {e}")

        log_info(f"Successfully migrated PgVector table {schema}.{table_name} for user isolation")

    except Exception as e:
        log_error(f"Error migrating PgVector table {schema}.{table_name}: {e}")
        raise


def migrate_singlestore_table(table_name: str, schema: str = "ai") -> None:
    """Add the ``user_id`` column to a SingleStore table.

    Idempotent: skips the table if the column already exists.

    Args:
        table_name: Name of the table to migrate.
        schema: Database schema name.
    """
    try:
        log_info(f"Starting user_id migration for SingleStore table: {schema}.{table_name}")

        from agno.vectordb.singlestore.singlestore import SingleStore

        singlestore = SingleStore(collection=table_name, schema=schema, db_url=singlestore_db_url)

        if not singlestore.table_exists():
            log_warning(f"Table {schema}.{table_name} not found. Skipping migration.")
            return

        from sqlalchemy import inspect, text

        inspector = inspect(singlestore.db_engine)
        column_names = [col["name"] for col in inspector.get_columns(table_name, schema=schema)]

        if "user_id" in column_names:
            log_info(f"Table {schema}.{table_name} already has the user_id column. No migration needed.")
            return

        # Add the owner column. Matches the adapter's VARCHAR(255), nullable = NULL = shared.
        with singlestore.Session() as sess, sess.begin():
            log_info(f"Adding user_id column to {schema}.{table_name}")
            sess.execute(text(f"ALTER TABLE `{schema}`.`{table_name}` ADD COLUMN user_id VARCHAR(255);"))

        log_info(f"Successfully migrated SingleStore table {schema}.{table_name} for user isolation")

    except Exception as e:
        log_error(f"Error migrating SingleStore table {schema}.{table_name}: {e}")
        raise


def run() -> None:
    """Run the configured SQL vector-DB schema migrations."""
    if not (pg_vector_db_url and pg_vector_config) and not (singlestore_db_url and singlestore_config):
        log_error(
            "To run the migration, set `pg_vector_db_url` + `pg_vector_config` for PgVector, "
            "or `singlestore_db_url` + `singlestore_config` for SingleStore."
        )
        return

    try:
        if pg_vector_config:
            for table_name in pg_vector_config["table_names"]:
                migrate_pgvector_table(table_name, pg_vector_config["schema"])  # type: ignore

        if singlestore_config:
            for table_name in singlestore_config["table_names"]:
                migrate_singlestore_table(table_name, singlestore_config["schema"])  # type: ignore

    except Exception as e:
        log_error(f"Error during migration: {e}")

    log_info("VectorDB user-isolation migration completed.")


if __name__ == "__main__":
    run()