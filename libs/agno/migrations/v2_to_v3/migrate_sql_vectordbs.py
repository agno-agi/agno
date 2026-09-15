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

`table_names` is optional. Leave it out and the script discovers every Agno vector table
in the schema, which is what you want when the table names come from application config
rather than being known up front. Discovery matches Agno's own vector-table shape (an
`embedding` column plus `content_hash` and `content_id`), so a vector table created by
something other than Agno in the same schema is left alone. Set `table_names` explicitly
to migrate an exact list and skip discovery entirely.
"""

from typing import List

from agno.utils.log import log_error, log_info, log_warning

# ------------ Setup for PgVector ------------

## Your database connection string
pg_vector_db_url = ""  # Example: "postgresql+psycopg://ai:ai@localhost:5532/ai"

## Configuration of the schema and tables to migrate
pg_vector_config = {
    # "schema": "ai",  # Schema where your tables are located
    # "table_names": ["documents"],  # Omit to discover every Agno vector table in the schema
}
# -----------------------------------------

# ------------ Setup for SingleStore ------------

# Your database connection string
singlestore_db_url = ""  # Example: "mysql+pymysql://user:password@host:port/database"

# Exact configuration of the tables to migrate
singlestore_config = {
    # "schema": "ai",  # Schema where your tables are located
    # "table_names": ["documents"],  # Omit to discover every Agno vector table in the schema
}
# -----------------------------------------

# Columns that together identify a table as an Agno vector store. `embedding` alone would
# also match vector tables written by other tools sharing the schema; the content columns
# are what make the match Agno-specific.
_AGNO_VECTOR_COLUMNS = {"embedding", "content_hash", "content_id"}


def discover_pgvector_tables(schema: str = "ai") -> List[str]:
    """Find every Agno vector table in a PgVector schema.

    Args:
        schema: Database schema to scan.

    Returns:
        Sorted table names carrying Agno's vector-table column signature.
    """
    from sqlalchemy import create_engine, inspect

    engine = create_engine(pg_vector_db_url)
    try:
        inspector = inspect(engine)
        return sorted(
            table_name
            for table_name in inspector.get_table_names(schema=schema)
            if _AGNO_VECTOR_COLUMNS.issubset({col["name"] for col in inspector.get_columns(table_name, schema=schema)})
        )
    finally:
        engine.dispose()


def discover_singlestore_tables(schema: str = "ai") -> List[str]:
    """Find every Agno vector table in a SingleStore schema.

    Args:
        schema: Database schema to scan.

    Returns:
        Sorted table names carrying Agno's vector-table column signature.
    """
    from sqlalchemy import create_engine, inspect

    engine = create_engine(singlestore_db_url)
    try:
        inspector = inspect(engine)
        return sorted(
            table_name
            for table_name in inspector.get_table_names(schema=schema)
            if _AGNO_VECTOR_COLUMNS.issubset({col["name"] for col in inspector.get_columns(table_name, schema=schema)})
        )
    finally:
        engine.dispose()


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
    """Run the configured SQL vector-DB schema migrations.

    Each backend migrates the tables named in its config, or -- when `table_names` is
    omitted -- every Agno vector table discovered in its schema.
    """
    if not pg_vector_db_url and not singlestore_db_url:
        log_error("To run the migration, set `pg_vector_db_url` for PgVector, or `singlestore_db_url` for SingleStore.")
        return

    tasks = []
    if pg_vector_db_url:
        pg_schema = pg_vector_config.get("schema", "ai")
        pg_tables = pg_vector_config.get("table_names")
        if pg_tables is None:
            log_info(f"No `table_names` set for PgVector: discovering Agno vector tables in schema '{pg_schema}'")
            pg_tables = discover_pgvector_tables(pg_schema)  # type: ignore[arg-type]
            log_info(f"Discovered {len(pg_tables)} PgVector table(s): {', '.join(pg_tables) or 'none'}")
        tasks += [
            (f"pgvector:{t}", lambda t=t: migrate_pgvector_table(t, pg_schema))  # type: ignore
            for t in pg_tables
        ]
    if singlestore_db_url:
        s2_schema = singlestore_config.get("schema", "ai")
        s2_tables = singlestore_config.get("table_names")
        if s2_tables is None:
            log_info(f"No `table_names` set for SingleStore: discovering Agno vector tables in schema '{s2_schema}'")
            s2_tables = discover_singlestore_tables(s2_schema)  # type: ignore[arg-type]
            log_info(f"Discovered {len(s2_tables)} SingleStore table(s): {', '.join(s2_tables) or 'none'}")
        tasks += [
            (f"singlestore:{t}", lambda t=t: migrate_singlestore_table(t, s2_schema))  # type: ignore
            for t in s2_tables
        ]

    if not tasks:
        log_warning("No tables to migrate. Nothing was changed.")
        return

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
