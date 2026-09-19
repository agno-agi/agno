# mypy: disable-error-code=var-annotated
"""Use this script to migrate your Agno VectorDBs from v2 to v3

This script works with PgVector and SingleStore.

v3 adds per-user isolation: each stored chunk carries an owner user_id, and a scoped
search matches `user_id = <caller> OR user_id IS NULL` (NULL = shared). This script adds
that column, which pre-v3 tables don't have, to the provided tables:
- PgVector: user_id VARCHAR column, plus a btree index
- SingleStore: user_id VARCHAR(255) column

No rows are rewritten: existing rows get user_id = NULL and stay shared with everyone.
To give a SingleStore chunk an owner afterwards, delete and re-insert it — the row id
hashes user_id in, so a bare UPDATE duplicates the chunk on the next upsert.

To use the script simply:
- For PgVector, set the `pg_vector_db_url` and `pg_vector_config` variables
- For SingleStore, set the `singlestore_db_url` and `singlestore_config` variables
- Run the script
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


def migrate_pgvector_table(table_name: str, schema: str = "ai") -> None:
    """Migrate a single PgVector table to v3 by adding the user_id column and its index.

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

        # Add the owner column. Nullable, NULL = shared.
        with pgvector.Session() as sess, sess.begin():
            log_info(f"Adding user_id column to {schema}.{table_name}")
            sess.execute(text(f'ALTER TABLE "{schema}"."{table_name}" ADD COLUMN user_id VARCHAR;'))

        # Add an index for the new column
        with pgvector.Session() as sess, sess.begin():
            index_name = f"idx_{table_name}_user_id"
            log_info(f"Creating index {index_name} on user_id column")
            try:
                sess.execute(text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{schema}"."{table_name}" (user_id);'))
            except SQLAlchemyError as e:
                log_warning(f"Could not create index {index_name}: {e}")

        log_info(f"Successfully migrated PgVector table {schema}.{table_name} for user isolation")

    except Exception as e:
        log_error(f"Error migrating PgVector table {schema}.{table_name}: {e}")
        raise


def migrate_singlestore_table(table_name: str, schema: str = "ai") -> None:
    """Migrate a single SingleStore table to v3 by adding the user_id column.

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

        # Add the owner column. Nullable, NULL = shared.
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

    tasks = []
    if pg_vector_config:
        tasks += [
            (f"pgvector:{t}", lambda t=t: migrate_pgvector_table(t, pg_vector_config.get("schema", "ai")))  # type: ignore
            for t in pg_vector_config["table_names"]
        ]
    if singlestore_config:
        tasks += [
            (f"singlestore:{t}", lambda t=t: migrate_singlestore_table(t, singlestore_config.get("schema", "ai")))  # type: ignore
            for t in singlestore_config["table_names"]
        ]

    failures = []
    for label, task in tasks:
        try:
            task()
        except Exception as e:
            log_error(f"Migration failed for {label}: {e}")
            failures.append(label)

    if failures:
        raise RuntimeError(f"SQL schema migration FAILED for: {', '.join(failures)}. Re-run after fixing the cause.")

    log_info("VectorDB user-isolation migration completed.")


if __name__ == "__main__":
    run()
