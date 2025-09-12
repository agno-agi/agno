"""Migration utility to add content_hash column and index to Knowledge tables"""

from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text

from agno.db.mysql.mysql import MySQLDb
from agno.db.postgres.postgres import PostgresDb
from agno.db.sqlite.sqlite import SqliteDb
from agno.utils.log import log_error, log_info, log_warning


def migrate(
    db: Union[PostgresDb, MySQLDb, SqliteDb],
    knowledge_table_name: Optional[str] = None,
    dry_run: bool = False,
):
    """
    Add content_hash column and index to Knowledge table.

    This migration adds:
    1. A content_hash VARCHAR(255) column
    2. An index on the content_hash column for improved query performance

    Note: Existing records will have NULL content_hash until they are
    accessed/updated by the application, which will populate the hash.

    Args:
        db: The database to migrate
        knowledge_table_name: The name of the knowledge table. If not provided, uses default 'knowledge'
        dry_run: If True, only show what would be done without making changes
    """
    table_name = knowledge_table_name or "knowledge"

    log_info(f"Starting Knowledge content_hash migration for table: {table_name}")

    if dry_run:
        log_info("DRY RUN MODE - No changes will be made")

    try:
        # Step 1: Check if content_hash column and index already exist
        column_exists = _column_exists(db, table_name, "content_hash")
        index_name = f"idx_{table_name}_content_hash"
        index_exists = _index_exists(db, table_name, index_name)

        if column_exists and index_exists:
            log_info(f"content_hash column and index already exist in {table_name}, skipping migration")
            return
        elif column_exists:
            log_info(f"content_hash column already exists in {table_name}, will add index only")
        elif index_exists:
            log_warning(f"content_hash index exists but column doesn't in {table_name} - this shouldn't happen!")

        # Step 2: Add content_hash column if it doesn't exist
        if not column_exists:
            if not dry_run:
                _add_content_hash_column(db, table_name)
                log_info(f"Added content_hash column to {table_name}")
            else:
                log_info(f"Would add content_hash column to {table_name}")

        # Step 3: Add index on content_hash column if it doesn't exist
        if not index_exists:
            if not dry_run:
                _add_content_hash_index(db, table_name)
                log_info(f"Added index on content_hash column in {table_name}")
            else:
                log_info(f"Would add index on content_hash column in {table_name}")

        # Step 4: Check existing records
        existing_records = _get_all_knowledge_records(db, table_name)
        log_info(f"Found {len(existing_records)} existing records")
        log_info(
            "Note: Existing records will have NULL content_hash until they are accessed/updated by the application"
        )

        log_info(f"Migration completed successfully. Added content_hash column and index to {table_name}.")

    except Exception as e:
        log_error(f"Error during Knowledge content_hash migration: {e}")
        raise


def _column_exists(db: Union[PostgresDb, MySQLDb, SqliteDb], table_name: str, column_name: str) -> bool:
    """Check if a column exists in the table"""
    try:
        with db.Session() as sess:
            if isinstance(db, PostgresDb):
                query = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name AND column_name = :column_name
                """)
            elif isinstance(db, MySQLDb):
                query = text("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = :table_name AND COLUMN_NAME = :column_name
                """)
            else:  # SQLite
                query = text(f"PRAGMA table_info({table_name})")
                result = sess.execute(query)
                columns = [row[1] for row in result]  # Column name is at index 1
                return column_name in columns

            result = sess.execute(query, {"table_name": table_name, "column_name": column_name})
            return result.fetchone() is not None

    except Exception as e:
        log_warning(f"Could not check if column exists: {e}")
        return False


def _add_content_hash_column(db: Union[PostgresDb, MySQLDb, SqliteDb], table_name: str):
    """Add content_hash column to the table"""
    try:
        with db.Session() as sess:
            # Add VARCHAR column for content_hash
            alter_query = text(f"ALTER TABLE {table_name} ADD COLUMN content_hash VARCHAR(255)")
            sess.execute(alter_query)
            sess.commit()

    except Exception as e:
        log_error(f"Error adding content_hash column: {e}")
        raise


def _add_content_hash_index(db: Union[PostgresDb, MySQLDb, SqliteDb], table_name: str):
    """Add index on content_hash column"""
    try:
        with db.Session() as sess:
            # Create index on content_hash column
            index_name = f"idx_{table_name}_content_hash"
            create_index_query = text(f"CREATE INDEX {index_name} ON {table_name} (content_hash)")
            sess.execute(create_index_query)
            sess.commit()

    except Exception as e:
        log_error(f"Error adding content_hash index: {e}")
        raise


def _index_exists(db: Union[PostgresDb, MySQLDb, SqliteDb], table_name: str, index_name: str) -> bool:
    """Check if an index exists on the table"""
    try:
        with db.Session() as sess:
            if isinstance(db, PostgresDb):
                query = text("""
                    SELECT indexname 
                    FROM pg_indexes 
                    WHERE tablename = :table_name AND indexname = :index_name
                """)
                result = sess.execute(query, {"table_name": table_name, "index_name": index_name})
                return result.fetchone() is not None
            elif isinstance(db, MySQLDb):
                query = text("""
                    SELECT INDEX_NAME 
                    FROM INFORMATION_SCHEMA.STATISTICS 
                    WHERE TABLE_NAME = :table_name AND INDEX_NAME = :index_name
                """)
                result = sess.execute(query, {"table_name": table_name, "index_name": index_name})
                return result.fetchone() is not None
            else:  # SQLite
                query = text(f"PRAGMA index_list({table_name})")
                result = sess.execute(query)
                indexes = [row[1] for row in result]  # Index name is at index 1
                return index_name in indexes

    except Exception as e:
        log_warning(f"Could not check if index exists: {e}")
        return False


def _get_all_knowledge_records(db: Union[PostgresDb, MySQLDb, SqliteDb], table_name: str) -> List[Dict[str, Any]]:
    """Get all records from the knowledge table"""
    try:
        with db.Session() as sess:
            result = sess.execute(text(f"SELECT * FROM {table_name}"))
            return [row._asdict() for row in result]

    except Exception as e:
        log_error(f"Error getting records from {table_name}: {e}")
        return []


def validate_migration(
    db: Union[PostgresDb, MySQLDb, SqliteDb],
    knowledge_table_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate that the migration was successful.

    Returns:
        Dict with validation results
    """
    table_name = knowledge_table_name or "knowledge"

    try:
        with db.Session() as sess:
            # Check if column exists
            column_exists = _column_exists(db, table_name, "content_hash")

            # Check if index exists
            index_name = f"idx_{table_name}_content_hash"
            index_exists = _index_exists(db, table_name, index_name)

            # Count total records
            total_count_result = sess.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            total_count = total_count_result.scalar()

            # Count records with content_hash
            hash_count_result = sess.execute(text(f"SELECT COUNT(*) FROM {table_name} WHERE content_hash IS NOT NULL"))
            hash_count = hash_count_result.scalar()

            # Count records without content_hash
            no_hash_count = total_count - hash_count

            return {
                "column_exists": column_exists,
                "index_exists": index_exists,
                "total_records": total_count,
                "records_with_hash": hash_count,
                "records_without_hash": no_hash_count,
                "migration_complete": column_exists
                and index_exists,  # Migration is complete if both column and index exist
                "notes": "Existing records will have NULL content_hash until accessed/updated by the application",
            }

    except Exception as e:
        log_error(f"Error validating migration: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    # Example usage:
    from agno.db.migrations.knowledge_content_hash import migrate, validate_migration
    from agno.db.postgres.postgres import PostgresDb

    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

    # Initialize your database
    db = PostgresDb(
        db_url=db_url,
    )

    # Run migration (dry run first to see what will happen)
    migrate(db, knowledge_table_name="knowledge_contents", dry_run=True)

    # Run actual migration (adds both column and index)
    migrate(db, knowledge_table_name="knowledge_contents", dry_run=False)

    # Validate migration (check that column and index were added)
    results = validate_migration(db, knowledge_table_name="knowledge_contents")
    print(f"Migration validation: {results}")
    print("Note: Existing records will have NULL content_hash until accessed by the application")

    pass
