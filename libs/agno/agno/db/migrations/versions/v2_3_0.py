"""Migration v2.3.0: Schema updates for memories and PostgreSQL JSONB

Changes:
- Add created_at column to memories table (all databases)
- Add feedback column to memories table (all databases)
- Change JSON to JSONB for PostgreSQL
"""

import time
from typing import Any, List, Tuple

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info, log_warning

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Add created_at, feedback columns to memories table
    - Convert JSON to JSONB for PostgreSQL
    - Change String to Text for long fields (PostgreSQL)
    - Add default values to metrics table (MySQL)

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_type, table_name)
        elif db_type == "MySQLDb":
            return _migrate_mysql(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_type, table_name)
        elif db_type == "SingleStoreDb":
            return _migrate_singlestore(db, table_type, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations (NoSQL/document store)")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Add created_at, feedback columns to memories table
    - Convert JSON to JSONB for PostgreSQL
    - Change String to Text for long fields (PostgreSQL)
    - Add default values to metrics table (MySQL)

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_type, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations (NoSQL/document store)")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Remove created_at, feedback columns from memories table
    - Revert JSONB to JSON for PostgreSQL (if needed)

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "PostgresDb":
            return _revert_postgres(db, table_type, table_name)
        elif db_type == "MySQLDb":
            return _revert_mysql(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_type, table_name)
        elif db_type == "SingleStoreDb":
            return _revert_singlestore(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.3.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Remove created_at, feedback columns from memories table
    - Revert JSONB to JSON for PostgreSQL (if needed)

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.3.0 for {db_type} on table {table_name} asynchronously: {e}")
        raise


def _migrate_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
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
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN created_at BIGINT
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_schema}.{quoted_table}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                sess.execute(
                    text(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at
                        ON {quoted_schema}.{quoted_table}(created_at)
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"Adding feedback column to {table_name}")
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN feedback TEXT
                        """
                    )
                )

            json_columns = [
                ("memory", table_name),
                ("topics", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)

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
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "evals":
            json_columns = [
                ("eval_data", table_name),
                ("eval_input", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "metrics":
            json_columns = [
                ("token_metrics", table_name),
                ("model_metrics", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "knowledge":
            json_columns = [
                ("metadata", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "culture":
            json_columns = [
                ("metadata", table_name),
            ]
            _convert_json_to_jsonb(sess, db_schema, json_columns, db_type)

        sess.commit()
        return True


def _convert_json_to_jsonb(
    sess: Any, db_schema: str, json_columns: List[Tuple[str, str]], db_type: str = "PostgresDb"
) -> None:
    quoted_schema = quote_db_identifier(db_type, db_schema) if db_schema else None
    for column_name, table_name in json_columns:
        quoted_table = quote_db_identifier(db_type, table_name)
        table_full_name = f"{quoted_schema}.{quoted_table}" if quoted_schema else quoted_table
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


async def _migrate_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = await sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        if table_type == "memories":
            # Check if columns already exist
            result = await sess.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name},
            )
            check_columns = result.fetchall()
            existing_columns = {row[0] for row in check_columns}

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column
                await sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN created_at BIGINT
                        """
                    ),
                )
                # Populate created_at
                await sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_schema}.{quoted_table}
                        SET created_at = COALESCE(updated_at, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                await sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ALTER COLUMN created_at SET NOT NULL
                        """
                    ),
                )
                # Add index
                await sess.execute(
                    text(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at
                        ON {quoted_schema}.{quoted_table}(created_at)
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"Adding feedback column to {table_name}")
                await sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN feedback TEXT
                        """
                    )
                )

            json_columns = [
                ("memory", table_name),
                ("topics", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
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
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)

        if table_type == "evals":
            json_columns = [
                ("eval_data", table_name),
                ("eval_input", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "metrics":
            json_columns = [
                ("token_metrics", table_name),
                ("model_metrics", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)
        if table_type == "knowledge":
            json_columns = [
                ("metadata", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)

        if table_type == "culture":
            json_columns = [
                ("metadata", table_name),
            ]
            await _async_convert_json_to_jsonb(sess, db_schema, json_columns, db_type)

        await sess.commit()
        return True


async def _async_convert_json_to_jsonb(
    sess: Any, db_schema: str, json_columns: List[Tuple[str, str]], db_type: str = "AsyncPostgresDb"
) -> None:
    quoted_schema = quote_db_identifier(db_type, db_schema) if db_schema else None
    for column_name, table_name in json_columns:
        quoted_table = quote_db_identifier(db_type, table_name)
        table_full_name = f"{quoted_schema}.{quoted_table}" if quoted_schema else quoted_table
        # Check current type
        result = await sess.execute(
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
        )
        col_type = result.scalar()

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


def _migrate_mysql(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Migrate MySQL database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
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
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN `created_at` BIGINT,
                        ADD INDEX `idx_{table_name}_created_at` (`created_at`)
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_schema}.{quoted_table}
                        SET `created_at` = COALESCE(`updated_at`, :default_time)
                        """
                    ),
                    {"default_time": current_time},
                )
                # Set created_at as non nullable
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        MODIFY COLUMN `created_at` BIGINT NOT NULL
                        """
                    )
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                sess.execute(
                    text(
                        f"""
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN `feedback` TEXT
                        """
                    )
                )

        sess.commit()
        return True


def _migrate_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Migrate SQLite database."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type='table' AND name=:table_name
                """
            ),
            {"table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        if table_type == "memories":
            # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
            # We'll use a simpler approach
            # Check if columns already exist using PRAGMA
            result = sess.execute(text(f"PRAGMA table_info({quoted_table})"))
            columns_info = result.fetchall()
            existing_columns = {row[1] for row in columns_info}  # row[1] contains column name

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column with NOT NULL constraint and default value
                # SQLite doesn't support ALTER COLUMN, so we add NOT NULL directly
                sess.execute(
                    text(f"ALTER TABLE {quoted_table} ADD COLUMN created_at BIGINT NOT NULL DEFAULT {current_time}"),
                )
                # Populate created_at for existing rows
                sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_table}
                        SET created_at = COALESCE(updated_at, :default_time)
                        WHERE created_at = :default_time
                        """
                    ),
                    {"default_time": current_time},
                )
                # Add index
                sess.execute(
                    text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at ON {quoted_table}(created_at)")
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN feedback VARCHAR"))

        sess.commit()
        return True


async def _migrate_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Migrate SQLite database."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = await sess.execute(
            text(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type='table' AND name=:table_name
                """
            ),
            {"table_name": table_name},
        )
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        if table_type == "memories":
            # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
            # We'll use a simpler approach
            # Check if columns already exist using PRAGMA
            result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
            columns_info = result.fetchall()
            existing_columns = {row[1] for row in columns_info}  # row[1] contains column name

            # Add created_at if it doesn't exist
            if "created_at" not in existing_columns:
                log_info(f"-- Adding created_at column to {table_name}")
                current_time = int(time.time())
                # Add created_at column with NOT NULL constraint and default value
                # SQLite doesn't support ALTER COLUMN, so we add NOT NULL directly
                await sess.execute(
                    text(f"ALTER TABLE {quoted_table} ADD COLUMN created_at BIGINT NOT NULL DEFAULT {current_time}"),
                )
                # Populate created_at for existing rows
                await sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_table}
                        SET created_at = COALESCE(updated_at, :default_time)
                        WHERE created_at = :default_time
                        """
                    ),
                    {"default_time": current_time},
                )
                # Add index
                await sess.execute(
                    text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at ON {quoted_table}(created_at)")
                )

            # Add feedback if it doesn't exist
            if "feedback" not in existing_columns:
                log_info(f"-- Adding feedback column to {table_name}")
                await sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN feedback VARCHAR"))

        await sess.commit()
        return True


def _migrate_singlestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Migrate SingleStore database."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
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
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN `created_at` BIGINT,
                        ADD INDEX `idx_{table_name}_created_at` (`created_at`)
                        """
                    ),
                )
                # Populate created_at
                sess.execute(
                    text(
                        f"""
                        UPDATE {quoted_schema}.{quoted_table}
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
                        ALTER TABLE {quoted_schema}.{quoted_table}
                        ADD COLUMN `feedback` TEXT
                        """
                    )
                )

        sess.commit()
        return True


def _revert_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if table_type == "memories":
            # Remove columns (in reverse order)
            sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS feedback"))
            sess.execute(text(f"DROP INDEX IF EXISTS idx_{table_name}_created_at"))
            sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS created_at"))
        sess.commit()
        return True


async def _revert_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = await sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if table_type == "memories":
            # Remove columns (in reverse order)
            await sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS feedback"))
            await sess.execute(text(f"DROP INDEX IF EXISTS idx_{table_name}_created_at"))
            await sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS created_at"))
        await sess.commit()
        return True


def _revert_mysql(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert MySQL migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if table_type == "memories":
            # Get existing columns
            existing_columns = {
                row[0]
                for row in sess.execute(
                    text(
                        """
                        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name
                        """
                    ),
                    {"schema": db_schema, "table_name": table_name},
                )
            }
            # Drop feedback column if it exists
            if "feedback" in existing_columns:
                sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN `feedback`"))
            # Drop created_at index if it exists
            index_exists = sess.execute(
                text(
                    """
                    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                    AND INDEX_NAME = :index_name
                    """
                ),
                {"schema": db_schema, "table_name": table_name, "index_name": f"idx_{table_name}_created_at"},
            ).scalar()
            if index_exists:
                sess.execute(
                    text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP INDEX `idx_{table_name}_created_at`")
                )
            # Drop created_at column if it exists
            if "created_at" in existing_columns:
                sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN `created_at`"))

        sess.commit()
        return True


def _revert_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert SQLite migration."""
    log_warning(f"-- SQLite does not support DROP COLUMN easily. Manual migration may be required for {table_name}.")

    return False


async def _revert_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert SQLite migration."""
    log_warning(f"-- SQLite does not support DROP COLUMN easily. Manual migration may be required for {table_name}.")

    return False


def _revert_singlestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert SingleStore migration."""
    from sqlalchemy import text

    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table_name
                )
                """
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if table_type == "memories":
            sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS `feedback`"))
            sess.execute(
                text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP INDEX IF EXISTS `idx_{table_name}_created_at`")
            )
            sess.execute(text(f"ALTER TABLE {quoted_schema}.{quoted_table} DROP COLUMN IF EXISTS `created_at`"))
        sess.commit()
        return True
