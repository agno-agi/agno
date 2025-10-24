"""Use this script to migrate your Agno VectorDBs from v1 to v2

This script adds the new columns introduced in v2 to SQL-based vector databases:
- content_hash: String column for content hash tracking
- content_id: String column for content ID tracking

Supported databases:
- PgVector: Adds columns to existing tables (no data movement needed)
- SingleStore: Adds columns to existing tables (no data movement needed)

- Configure your db_url and table details in the script
- Run the script
"""

from agno.utils.log import log_error, log_info, log_warning

# --- Set these variables before running the script ---

## Your database connection details ##
db_url = ""  # For PgVector, SingleStore

## Postgres Sample ##
# db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

## SingleStore Sample ##
# db_url = "mysql+pymysql://user:password@host:port/database"

## Configure which vectordbs to migrate ##
vectordb_configs = {
    # Uncomment and configure the databases you want to migrate
    # SQL DATABASES - True schema migration (no re-indexing needed):
    # "pgvector": {
    #     "schema": "ai",  # Schema name where your vectordb tables are located
    #     "table_names": ["knowledge_base", "documents"],  # List of table names to migrate
    # },
    # "singlestore": {
    #     "schema": "ai",
    #     "table_names": ["knowledge_base", "documents"],
    # },
}

# Migration batch size (adjust based on available memory and table size)
migration_batch_size = 5000

# --- Exit if no configurations are provided ---

if not vectordb_configs:
    log_info(
        "No vectordb configurations provided. Update the vectordb_configs dictionary to include the databases you want to migrate."
    )
    exit()

# --- Run the migration ---


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
            db_url=db_url,
            schema_version=1,  # Use v1 schema for compatibility
        )

        # Check if table exists
        if not pgvector.table_exists():
            log_warning(f"Table {schema}.{table_name} does not exist. Skipping migration.")
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
            db_url=db_url,
        )

        # Check if table exists
        if not singlestore.table_exists():
            log_warning(f"Table {schema}.{table_name} does not exist. Skipping migration.")
            return

        # Check if the new columns already exist
        from sqlalchemy import inspect, text
        from sqlalchemy.exc import SQLAlchemyError

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


# Run migration for all configured vectordbs
for vectordb_type, config in vectordb_configs.items():
    try:
        log_info(f"\n{'=' * 50}")
        log_info(f"Processing {vectordb_type.upper()}")
        log_info(f"{'=' * 50}")

        if vectordb_type == "pgvector":
            if not db_url:
                log_error("db_url is required for PgVector migration")
                continue
            for table_name in config["table_names"]:
                migrate_pgvector_table(table_name, config["schema"])

        elif vectordb_type == "singlestore":
            if not db_url:
                log_error("db_url is required for SingleStore migration")
                continue
            for table_name in config["table_names"]:
                migrate_singlestore_table(table_name, config["schema"])

        else:
            log_warning(f"Unknown vectordb type: {vectordb_type}. Supported types: pgvector, singlestore")

    except Exception as e:
        log_error(f"Error processing {vectordb_type}: {e}")

log_info("\nVectorDB migration completed.")
