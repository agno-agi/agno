# mypy: disable-error-code=var-annotated
"""Use this script to migrate your Agno VectorDBs from v1 to v2

This script works with PgVector and SingleStore.

This script will update the provided tables to add the two new columns introduced in v2:
- content_hash: String column for content hash tracking
- content_id: String column for content ID tracking

To use the script simply:
- For PGVector, set the `pg_vector_db_url` and `pg_vector_config` variables
- For SingleStore, set the `singlestore_db_url` and `singlestore_config` variables
- Run the script
"""

from agno.utils.log import log_error, log_info, log_warning

# ------------ Setup for PGVector ------------

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

# Migration batch size (adjust based on available memory and table size)
migration_batch_size = 5000

#  Exit if no configurations are provided
if not (pg_vector_db_url and pg_vector_config) and not (singlestore_db_url and singlestore_config):
    log_error(
        "To run the migration, you need to set the `pg_vector_db_url` and `pg_vector_config` variables for PGVector, or `singlestore_db_url` and `singlestore_config` for SingleStore."
    )
    exit()


def migrate_pgvector_table(table_name: str, schema: str = "ai") -> None:
    """
    Migrate a single PgVector table to v2 by adding content_hash and content_id columns.

    Args:
        table_name: Name of the table to migrate
        schema: Database schema name
    """
    try:
        log_info(f"Starting migration for PgVector table: {schema}.{table_name}")

        # Create PgVector instance to get database connection
        from agno.vectordb.pgvector.pgvector import PgVector

        pgvector = PgVector(
            table_name=table_name,
            schema=schema,
            db_url=pg_vector_db_url,
            schema_version=1,  # Use v1 schema for compatibility
        )

        # Check if table exists
        if not pgvector.table_exists():
            log_warning(f"Table {schema}.{table_name} not found. Skipping migration.")
            return

        # Check if the new columns already exist
        from sqlalchemy import inspect, text
        from sqlalchemy.exc import SQLAlchemyError

        inspector = inspect(pgvector.db_engine)
        columns = inspector.get_columns(table_name, schema=schema)
        column_names = [col["name"] for col in columns]

        content_hash_exists = "content_hash" in column_names
        content_id_exists = "content_id" in column_names

        if content_hash_exists and content_id_exists:
            log_info(f"Table {schema}.{table_name} already has the v2 columns. No migration needed.")
            return

        # Add missing columns
        with pgvector.Session() as sess, sess.begin():
            if not content_hash_exists:
                log_info(f"Adding content_hash column to {schema}.{table_name}")
                sess.execute(text(f'ALTER TABLE "{schema}"."{table_name}" ADD COLUMN content_hash VARCHAR;'))

            if not content_id_exists:
                log_info(f"Adding content_id column to {schema}.{table_name}")
                sess.execute(text(f'ALTER TABLE "{schema}"."{table_name}" ADD COLUMN content_id VARCHAR;'))

        # Add indexes for the new columns
        with pgvector.Session() as sess, sess.begin():
            if not content_hash_exists:
                index_name = f"idx_{table_name}_content_hash"
                log_info(f"Creating index {index_name} on content_hash column")
                try:
                    sess.execute(
                        text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{schema}"."{table_name}" (content_hash);')
                    )
                except SQLAlchemyError as e:
                    log_warning(f"Could not create index {index_name}: {e}")

            if not content_id_exists:
                index_name = f"idx_{table_name}_content_id"
                log_info(f"Creating index {index_name} on content_id column")
                try:
                    sess.execute(
                        text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{schema}"."{table_name}" (content_id);')
                    )
                except SQLAlchemyError as e:
                    log_warning(f"Could not create index {index_name}: {e}")

        log_info(f"Successfully migrated PgVector table {schema}.{table_name} to v2")

    except Exception as e:
        log_error(f"Error migrating PgVector table {schema}.{table_name}: {e}")
        raise


def migrate_singlestore_table(table_name: str, schema: str = "ai") -> None:
    """
    Migrate a single SingleStore table to v2 by adding content_hash and content_id columns.

    Args:
        table_name: Name of the table to migrate
        schema: Database schema name
    """
    try:
        log_info(f"Starting migration for SingleStore table: {schema}.{table_name}")

        from agno.vectordb.singlestore.singlestore import SingleStore

        singlestore = SingleStore(
            collection=table_name,
            schema=schema,
            db_url=singlestore_db_url,
        )

        # Check if table exists
        if not singlestore.table_exists():
            log_warning(f"Table {schema}.{table_name} not found. Skipping migration.")
            return

        # Check if the new columns already exist
        from sqlalchemy import inspect, text

        inspector = inspect(singlestore.db_engine)
        columns = inspector.get_columns(table_name, schema=schema)
        column_names = [col["name"] for col in columns]

        content_hash_exists = "content_hash" in column_names
        content_id_exists = "content_id" in column_names

        if content_hash_exists and content_id_exists:
            log_info(f"Table {schema}.{table_name} already has the v2 columns. No migration needed.")
            return

        # Add missing columns
        with singlestore.Session() as sess, sess.begin():
            if not content_hash_exists:
                log_info(f"Adding content_hash column to {schema}.{table_name}")
                sess.execute(text(f"ALTER TABLE `{schema}`.`{table_name}` ADD COLUMN content_hash TEXT;"))

            if not content_id_exists:
                log_info(f"Adding content_id column to {schema}.{table_name}")
                sess.execute(text(f"ALTER TABLE `{schema}`.`{table_name}` ADD COLUMN content_id TEXT;"))

        log_info(f"Successfully migrated SingleStore table {schema}.{table_name} to v2")

    except Exception as e:
        log_error(f"Error migrating SingleStore table {schema}.{table_name}: {e}")
        raise


# Run the migrations
try:
    # PGVector migration
    if pg_vector_config:
        for table_name in pg_vector_config["table_names"]:
            migrate_pgvector_table(table_name, pg_vector_config["schema"])  # type: ignore

    # SingleStore migration
    if singlestore_config:
        for table_name in singlestore_config["table_names"]:
            migrate_singlestore_table(table_name, singlestore_config["schema"])  # type: ignore

except Exception as e:
    log_error(f"Error during migration: {e}")

log_info("VectorDB migration completed.")
