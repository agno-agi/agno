"""Migration v2.3.0: Schema updates for memories and PostgreSQL JSONB

Changes:
- Add created_at column to memories table (all databases)
- Add feedback column to memories table (all databases)
- Change JSON to JSONB for PostgreSQL
"""

import asyncio
import time
from typing import Any, List, Tuple, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.utils.log import log_error, log_info, log_warning
from cookbook.knowledge.vector_db.surrealdb.async_surreal_db import async_demo

try:
    from sqlalchemy import inspect, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> None:
    """
    Apply the following changes to the database:
    - Add created_at, feedback columns to memories table
    - Convert JSON to JSONB for PostgreSQL
    - Change String to Text for long fields (PostgreSQL)
    - Add default values to metrics table (MySQL)
    """
    db_type = type(db).__name__
    log_info(f"Running migration v2.3.0 for {db_type}")

    try:
        if db_type == "PostgresDb":
            _migrate_postgres(db, table_type, table_name)
        elif db_type == "MySQLDb":
            _migrate_mysql(db, table_type, table_name)
        elif db_type == "SqliteDb":
            _migrate_sqlite(db, table_type, table_name)
        elif db_type == "SingleStoreDb":
            _migrate_singlestore(db, table_type, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations (NoSQL/document store)")
    except Exception as e:
        log_error(f"Error running migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise

async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """
    Apply the following changes to the database:
    - Add created_at, feedback columns to memories table
    - Convert JSON to JSONB for PostgreSQL
    - Change String to Text for long fields (PostgreSQL)
    - Add default values to metrics table (MySQL)
    """
    db_type = type(db).__name__
    log_info(f"Running migration v2.3.0 for {db_type}")

    try:
        if db_type == "AsyncPostgresDb":
            await _migrate_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            await _migrate_async_sqlite(db, table_type, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations (NoSQL/document store)")
    except Exception as e:
        log_error(f"Error running migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> None:
    """
    Revert the following changes to the database:
    - Remove created_at, feedback columns from memories table
    - Revert JSONB to JSON for PostgreSQL (if needed)
    """
    db_type = type(db).__name__
    log_info(f"Reverting migration v2.3.0 for {db_type}")

    try:
        if db_type == "PostgresDb":
            _revert_postgres(db, table_type, table_name)
        elif db_type == "MySQLDb":
            _revert_mysql(db, table_type, table_name)
        elif db_type == "SqliteDb":
            _revert_sqlite(db, table_type, table_name)
        elif db_type == "SingleStoreDb":
            _revert_singlestore(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
    except Exception as e:
        log_error(f"Error reverting migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise

async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """
    Revert the following changes to the database:
    - Remove created_at, feedback columns from memories table
    - Revert JSONB to JSON for PostgreSQL (if needed)
    """
    db_type = type(db).__name__
    log_info(f"Reverting migration v2.3.0 for {db_type}")

    try:
        if db_type == "AsyncPostgresDb":
            await _revert_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            await _revert_async_sqlite(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
    except Exception as e:
        log_error(f"Error reverting migration v2.3.0 for {db_type} on table {table_name} asynchronously: {e}")
        raise


def _migrate_postgres(db: BaseDb, table_type: str, table_name: str) -> None:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "public"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            # Check if columns already exist
            check_columns = sess.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name},
            ).fetchall()
            existing_columns = {row[0] for row in check_columns}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ADD COLUMN created_at BIGINT
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {db_schema}.{table_name}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                sess.execute(
                    text(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at
                        ON {db_schema}.{table_name}(created_at)
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"Adding feedback column to {table_name}")
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ADD COLUMN feedback TEXT
                        """
                    )
                )

            json_columns = [
                ("memory", table_name),
                ("topics", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)

        if table_type == "sessions":
            json_columns = [
                ("session_data", table_name),
                ("agent_data", table_name),
                ("team_data", table_name),
                ("workflow_data", table_name),
                ("metadata", table_name),
                ("runs", table_name),
                ("summary", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)
        
        if table_type == "evals":
            json_columns = [
                ("eval_data", table_name),
                ("eval_input", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)
        if table_type == "metrics":
            json_columns = [
                ("token_metrics", table_name),
                ("model_metrics", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)
        if table_type == "knowledge":
            json_columns = [
                ("metadata", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)
        
        if table_type == "culture":
            json_columns = [
                ("metadata", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns)

        sess.commit()
        log_info(f"-- PostgreSQL migration for {table_name} completed successfully")

def _convert_json_to_jsonb(sess: Any, db_schema: str, json_columns: List[Tuple[str, str]]) -> None:
    for column_name, table_name in json_columns:
        table_full_name = f"{db_schema}.{table_name}" if db_schema else table_name
        # Check current type
        col_type = sess.execute(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = :schema
                AND table_name = :table_name
                AND column_name = :column_name
                """
            ),
            {"schema": db_schema, "table_name": table_name, "column_name": column_name},
        ).scalar()

        if col_type == "json":
            log_info(f"-- Converting {table_name}.{column_name} from JSON to JSONB")
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {table_full_name}
                    ALTER COLUMN {column_name} TYPE JSONB USING {column_name}::jsonb
                    """
                )
            )

async def _migrate_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "public"  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        if table_type == "memories":
            # Check if columns already exist
            check_columns = await sess.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name},
            ).fetchall()
            existing_columns = {row[0] for row in check_columns}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ADD COLUMN created_at BIGINT
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {db_schema}.{table_name}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                sess.execute(
                    text(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at
                        ON {db_schema}.{table_name}(created_at)
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"Adding feedback column to {table_name}")
                await sess.execute(
                    text(
                        f"""
                        ALTER TABLE {db_schema}.{table_name}
                        ADD COLUMN feedback TEXT
                        """
                    )
                )

            json_columns = [
                ("memory", table_name),
                ("topics", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)
        if table_type == "sessions":
            json_columns = [
                ("session_data", table_name),
                ("agent_data", table_name),
                ("team_data", table_name),
                ("workflow_data", table_name),
                ("metadata", table_name),
                ("runs", table_name),
                ("summary", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)
        
        if table_type == "evals":
            json_columns = [
                ("eval_data", table_name),
                ("eval_input", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)
        if table_type == "metrics":
            json_columns = [
                ("token_metrics", table_name),
                ("model_metrics", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)
        if table_type == "knowledge":
            json_columns = [
                ("metadata", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)
        
        if table_type == "culture":
            json_columns = [
                ("metadata", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns)


        await sess.commit()
        log_info(f"-- PostgreSQL migration for {table_name} completed successfully")

async def _async_convert_json_to_jsonb(sess: Any, db_schema: str, json_columns: List[Tuple[str, str]]) -> None:
    for column_name, table_name in json_columns:
        table_full_name = f"{db_schema}.{table_name}" if db_schema else table_name
        # Check current type
        col_type = await sess.execute(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = :schema
                AND table_name = :table_name
                AND column_name = :column_name
                """
            ),
            {"schema": db_schema, "table_name": table_name, "column_name": column_name},
        ).scalar()

        if col_type == "json":
            log_info(f"-- Converting {table_name}.{column_name} from JSON to JSONB")
            await sess.execute(
                text(
                    f"""
                    ALTER TABLE {table_full_name}
                    ALTER COLUMN {column_name} TYPE JSONB USING {column_name}::jsonb
                    """
                )
            )

def _migrate_mysql(db: BaseDb, table_type: str, table_name: str) -> None:
    """Migrate MySQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            # Check if columns already exist
            check_columns = sess.execute(
                text(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name},
            ).fetchall()
            existing_columns = {row[0] for row in check_columns}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE `{db_schema}`.`{table_name}`
                        ADD COLUMN `created_at` BIGINT,
                        ADD INDEX `idx_{table_name}_created_at` (`created_at`)
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE `{db_schema}`.`{table_name}`
                        SET `created_at` = COALESCE(`updated_at`, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE `{db_schema}`.`{table_name}`
                        ALTER COLUMN `created_at` SET NOT NULL
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE `{db_schema}`.`{table_name}`
                        ADD COLUMN `feedback` TEXT
                        """
                    )
                )

        sess.commit()
        log_info(f"-- MySQL migration for {table_name} completed successfully")


def _migrate_sqlite(db: BaseDb, table_type: str, table_name: str) -> None:
    """Migrate SQLite database."""

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
            # We'll use a simpler approach
            inspector = inspect(db.db_engine)
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                sess.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN created_at BIGINT"),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {table_name}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {table_name}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at ON {table_name}(created_at)"
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN feedback VARCHAR"))

        sess.commit()
        log_info(f"-- SQLite migration for {table_name} completed successfully")


async def _migrate_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """Migrate SQLite database."""


    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        if table_type == "memories":
            # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
            # We'll use a simpler approach
            inspector = inspect(db.db_engine)  # type: ignore
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                await sess.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN created_at BIGINT"),
                )
                # Populate created_at
                await sess.execute(
                    text(
                        f"""
                        UPDATE {table_name}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                await sess.execute(
                    text(
                        f"""
                        ALTER TABLE {table_name}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                await sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at ON {table_name}(created_at)"
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                await sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN feedback VARCHAR"))

            await sess.commit()
            log_info(f"-- SQLite migration for {table_name} completed successfully")


def _migrate_singlestore(db: BaseDb, table_type: str, table_name: str) -> None:
    """Migrate SingleStore database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            # Check if columns already exist
            check_columns = sess.execute(
                text(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name},
            ).fetchall()
            existing_columns = {row[0] for row in check_columns}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE `{db_schema}`.`{table_name}`
                        ADD COLUMN `created_at` BIGINT,
                        ADD INDEX `idx_{table_name}_created_at` (`created_at`)
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE `{db_schema}`.`{table_name}`
                        SET `created_at` = COALESCE(`updated_at`, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE `{db_schema}`.`{table_name}`
                        ADD COLUMN `feedback` TEXT
                        """
                    )
                )

        sess.commit()
        log_info(f"-- SingleStore migration for {table_name} completed successfully")


def _revert_postgres(db: BaseDb, table_type: str, table_name: str) -> None:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            # Remove columns (in reverse order)
            sess.execute(text(f"ALTER TABLE {db_schema}.{table_name} DROP COLUMN IF EXISTS feedback"))
            sess.execute(text(f"DROP INDEX IF EXISTS idx_{table_name}_created_at"))
            sess.execute(text(f"ALTER TABLE {db_schema}.{table_name} DROP COLUMN IF EXISTS created_at"))
            sess.commit()
            log_info("-- PostgreSQL migration reverted")


async def _revert_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        if table_type == "memories":
            # Remove columns (in reverse order)
            await sess.execute(text(f"ALTER TABLE {db_schema}.{table_name} DROP COLUMN IF EXISTS feedback"))
            await sess.execute(text(f"DROP INDEX IF EXISTS idx_{table_name}_created_at"))
            await sess.execute(text(f"ALTER TABLE {db_schema}.{table_name} DROP COLUMN IF EXISTS created_at"))
        await sess.commit()
        log_info(f"-- PostgreSQL migration for {table_name} reverted")


def _revert_mysql(db: BaseDb, table_type: str, table_name: str) -> None:
    """Revert MySQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` DROP COLUMN IF EXISTS `feedback`"))
            sess.execute(
                text(
                    f"ALTER TABLE `{db_schema}`.`{table_name}` DROP INDEX IF EXISTS `idx_{table_name}_created_at`"
                )
            )
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` DROP COLUMN IF EXISTS `created_at`"))
        sess.commit()
        log_info(f"-- MySQL migration for {table_name} reverted")


def _revert_sqlite(db: BaseDb, table_type: str, table_name: str) -> None:
    """Revert SQLite migration."""
    log_warning(f"-- SQLite does not support DROP COLUMN easily. Manual migration may be required for {table_name}.")


async def _revert_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> None:
    """Revert SQLite migration."""
    log_warning(f"-- SQLite does not support DROP COLUMN easily. Manual migration may be required for {table_name}.")


def _revert_singlestore(db: BaseDb, table_type: str, table_name: str) -> None:
    """Revert SingleStore migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        if table_type == "memories":
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` DROP COLUMN IF EXISTS `feedback`"))
            sess.execute(
                text(
                    f"ALTER TABLE `{db_schema}`.`{table_name}` DROP INDEX IF EXISTS `idx_{table_name}_created_at`"
                )
            )
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` DROP COLUMN IF EXISTS `created_at`"))
        sess.commit()
        log_info(f"-- SingleStore migration for {table_name} reverted")
