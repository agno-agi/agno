"""Migration v2.3.0: Schema updates for memories and PostgreSQL JSONB

Changes:
- Add created_at column to memories table (all databases)
- Add feedback column to memories table (all databases)
- Change JSON to JSONB for PostgreSQL
"""

import asyncio
import time
from typing import Any, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.utils.log import log_error, log_info, log_warning

try:
    from sqlalchemy import inspect, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: Union[AsyncBaseDb, BaseDb]) -> None:
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
            _migrate_postgres(db)
        elif db_type == "AsyncPostgresDb":
            asyncio.run(_migrate_async_postgres(db))
        elif db_type == "MySQLDb":
            _migrate_mysql(db)
        elif db_type == "SqliteDb":
            _migrate_sqlite(db)
        elif db_type == "AsyncSqliteDb":
            asyncio.run(_migrate_async_sqlite(db))
        elif db_type == "SingleStoreDb":
            _migrate_singlestore(db)
        else:
            log_info(f"{db_type} does not require schema migrations (NoSQL/document store)")
    except Exception as e:
        log_error(f"Error running migration v2.3.0 for {db_type}: {e}")
        raise


def down(db: BaseDb) -> None:
    """
    Revert the following changes to the database:
    - Remove created_at, feedback columns from memories table
    - Revert JSONB to JSON for PostgreSQL (if needed)
    """
    db_type = type(db).__name__
    log_info(f"Reverting migration v2.3.0 for {db_type}")

    try:
        if db_type == "PostgresDb":
            _revert_postgres(db)
        elif db_type == "AsyncPostgresDb":
            asyncio.run(_revert_async_postgres(db))
        elif db_type == "MySQLDb":
            _revert_mysql(db)
        elif db_type == "SqliteDb":
            _revert_sqlite(db)
        elif db_type == "AsyncSqliteDb":
            asyncio.run(_revert_async_sqlite(db))
        elif db_type == "SingleStoreDb":
            _revert_singlestore(db)
        else:
            log_info(f"Revert not implemented for {db_type}")
    except Exception as e:
        log_error(f"Error reverting migration v2.3.0 for {db_type}: {e}")
        raise


def _migrate_postgres(db: Any) -> None:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "public"

    with db.Session() as sess, sess.begin():
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
            {"schema": db_schema, "table_name": memory_table_name},
        ).fetchall()
        existing_columns = {row[0] for row in check_columns}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ADD COLUMN created_at BIGINT
                    """
                ),
            )
            # Populate created_at
            sess.execute(
                text(
                    f"""
                    UPDATE {db_schema}.{memory_table_name}
                    SET created_at = COALESCE(updated_at, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ALTER COLUMN created_at SET NOT NULL
                    """
                ),
            )
            # Add index
            sess.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{memory_table_name}_created_at
                    ON {db_schema}.{memory_table_name}(created_at)
                    """
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"Adding feedback column to {memory_table_name}")
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ADD COLUMN feedback TEXT
                    """
                )
            )

        # Convert JSON to JSONB for all JSON columns (if not already JSONB)
        json_columns = [
            ("session_data", "agno_sessions"),
            ("agent_data", "agno_sessions"),
            ("team_data", "agno_sessions"),
            ("workflow_data", "agno_sessions"),
            ("metadata", "agno_sessions"),
            ("runs", "agno_sessions"),
            ("summary", "agno_sessions"),
            ("memory", memory_table_name),
            ("topics", memory_table_name),
            ("eval_data", "agno_eval_runs"),
            ("eval_input", "agno_eval_runs"),
            ("token_metrics", "agno_metrics"),
            ("model_metrics", "agno_metrics"),
            ("metadata", "agno_knowledge"),
            ("content", "agno_culture"),
            ("metadata", "agno_culture"),
        ]

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

        sess.commit()
        log_info("-- PostgreSQL migration completed successfully")


async def _migrate_async_postgres(db: AsyncBaseDb) -> None:
    """Migrate PostgreSQL database."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "public"  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
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
            {"schema": db_schema, "table_name": memory_table_name},
        ).fetchall()
        existing_columns = {row[0] for row in check_columns}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ADD COLUMN created_at BIGINT
                    """
                ),
            )
            # Populate created_at
            sess.execute(
                text(
                    f"""
                    UPDATE {db_schema}.{memory_table_name}
                    SET created_at = COALESCE(updated_at, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ALTER COLUMN created_at SET NOT NULL
                    """
                ),
            )
            # Add index
            sess.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{memory_table_name}_created_at
                    ON {db_schema}.{memory_table_name}(created_at)
                    """
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"Adding feedback column to {memory_table_name}")
            await sess.execute(
                text(
                    f"""
                    ALTER TABLE {db_schema}.{memory_table_name}
                    ADD COLUMN feedback TEXT
                    """
                )
            )

        # Convert JSON to JSONB for all JSON columns (if not already JSONB)
        json_columns = [
            ("session_data", "agno_sessions"),
            ("agent_data", "agno_sessions"),
            ("team_data", "agno_sessions"),
            ("workflow_data", "agno_sessions"),
            ("metadata", "agno_sessions"),
            ("runs", "agno_sessions"),
            ("summary", "agno_sessions"),
            ("memory", memory_table_name),
            ("topics", memory_table_name),
            ("eval_data", "agno_eval_runs"),
            ("eval_input", "agno_eval_runs"),
            ("token_metrics", "agno_metrics"),
            ("model_metrics", "agno_metrics"),
            ("metadata", "agno_knowledge"),
            ("content", "agno_culture"),
            ("metadata", "agno_culture"),
        ]

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

        await sess.commit()
        log_info("-- PostgreSQL migration completed successfully")


def _migrate_mysql(db: Any) -> None:
    """Migrate MySQL database."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
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
            {"schema": db_schema, "table_name": memory_table_name},
        ).fetchall()
        existing_columns = {row[0] for row in check_columns}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    ADD COLUMN `created_at` BIGINT,
                    ADD INDEX `idx_{memory_table_name}_created_at` (`created_at`)
                    """
                ),
            )
            # Populate created_at
            sess.execute(
                text(
                    f"""
                    UPDATE `{db_schema}`.`{memory_table_name}`
                    SET `created_at` = COALESCE(`updated_at`, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    MODIFY COLUMN `created_at` BIGINT NOT NULL
                    """
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"-- Adding feedback column to {memory_table_name}")
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    ADD COLUMN `feedback` TEXT
                    """
                )
            )

        sess.commit()
        log_info("-- MySQL migration completed successfully")


def _migrate_sqlite(db: Any) -> None:
    """Migrate SQLite database."""

    memory_table_name = db.memory_table_name or "agno_memories"

    with db.Session() as sess, sess.begin():
        # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
        # We'll use a simpler approach
        inspector = inspect(db.db_engine)
        existing_columns = {col["name"] for col in inspector.get_columns(memory_table_name)}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            sess.execute(
                text(f"ALTER TABLE {memory_table_name} ADD COLUMN created_at BIGINT"),
            )
            # Populate created_at
            sess.execute(
                text(
                    f"""
                    UPDATE {memory_table_name}
                    SET created_at = COALESCE(updated_at, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            sess.execute(
                text(
                    f"""
                    ALTER TABLE {memory_table_name}
                    MODIFY COLUMN created_at BIGINT NOT NULL
                    """
                ),
            )
            # Add index
            sess.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{memory_table_name}_created_at ON {memory_table_name}(created_at)"
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"-- Adding feedback column to {memory_table_name}")
            sess.execute(text(f"ALTER TABLE {memory_table_name} ADD COLUMN feedback VARCHAR"))

        sess.commit()
        log_info("-- SQLite migration completed successfully")


async def _migrate_async_sqlite(db: AsyncBaseDb) -> None:
    """Migrate SQLite database."""

    memory_table_name = db.memory_table_name or "agno_memories"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints easily
        # We'll use a simpler approach
        inspector = inspect(db.db_engine)  # type: ignore
        existing_columns = {col["name"] for col in inspector.get_columns(memory_table_name)}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            await sess.execute(
                text(f"ALTER TABLE {memory_table_name} ADD COLUMN created_at BIGINT"),
            )
            # Populate created_at
            await sess.execute(
                text(
                    f"""
                    UPDATE {memory_table_name}
                    SET created_at = COALESCE(updated_at, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            await sess.execute(
                text(
                    f"""
                    ALTER TABLE {memory_table_name}
                    MODIFY COLUMN created_at BIGINT NOT NULL
                    """
                ),
            )
            # Add index
            await sess.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{memory_table_name}_created_at ON {memory_table_name}(created_at)"
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"-- Adding feedback column to {memory_table_name}")
            await sess.execute(text(f"ALTER TABLE {memory_table_name} ADD COLUMN feedback VARCHAR"))

        await sess.commit()
        log_info("-- SQLite migration completed successfully")


def _migrate_singlestore(db: Any) -> None:
    """Migrate SingleStore database."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
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
            {"schema": db_schema, "table_name": memory_table_name},
        ).fetchall()
        existing_columns = {row[0] for row in check_columns}

        # Add created_at if it doesn't exist
        if "created_at" not in existing_columns:
            log_info(f"-- Adding created_at column to {memory_table_name}")
            current_time = int(time.time())
            # Add created_at column
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    ADD COLUMN `created_at` BIGINT,
                    ADD INDEX `idx_{memory_table_name}_created_at` (`created_at`)
                    """
                ),
            )
            # Populate created_at
            sess.execute(
                text(
                    f"""
                    UPDATE `{db_schema}`.`{memory_table_name}`
                    SET `created_at` = COALESCE(`updated_at`, :default_time)
                    """
                ),
                {"default_time": current_time},
            )
            # Set created_at as non nullable
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    MODIFY COLUMN `created_at` BIGINT NOT NULL
                    """
                )
            )

        # Add feedback if it doesn't exist
        if "feedback" not in existing_columns:
            log_info(f"-- Adding feedback column to {memory_table_name}")
            sess.execute(
                text(
                    f"""
                    ALTER TABLE `{db_schema}`.`{memory_table_name}`
                    ADD COLUMN `feedback` TEXT
                    """
                )
            )

        sess.commit()
        log_info("-- SingleStore migration completed successfully")


def _revert_postgres(db: Any) -> None:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        # Remove columns (in reverse order)
        sess.execute(text(f"ALTER TABLE {db_schema}.{memory_table_name} DROP COLUMN IF EXISTS feedback"))
        sess.execute(text(f"DROP INDEX IF EXISTS idx_{memory_table_name}_created_at"))
        sess.execute(text(f"ALTER TABLE {db_schema}.{memory_table_name} DROP COLUMN IF EXISTS created_at"))
        sess.commit()
        log_info("-- PostgreSQL migration reverted")


async def _revert_async_postgres(db: AsyncBaseDb) -> None:
    """Revert PostgreSQL migration."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Remove columns (in reverse order)
        await sess.execute(text(f"ALTER TABLE {db_schema}.{memory_table_name} DROP COLUMN IF EXISTS feedback"))
        await sess.execute(text(f"DROP INDEX IF EXISTS idx_{memory_table_name}_created_at"))
        await sess.execute(text(f"ALTER TABLE {db_schema}.{memory_table_name} DROP COLUMN IF EXISTS created_at"))
        await sess.commit()
        log_info("-- PostgreSQL migration reverted")


def _revert_mysql(db: Any) -> None:
    """Revert MySQL migration."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"

    with db.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP COLUMN IF EXISTS `feedback`"))
        sess.execute(
            text(
                f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP INDEX IF EXISTS `idx_{memory_table_name}_created_at`"
            )
        )
        sess.execute(text(f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP COLUMN IF EXISTS `created_at`"))
        sess.commit()
        log_info("-- MySQL migration reverted")


def _revert_sqlite(db: Any) -> None:
    """Revert SQLite migration."""
    log_warning("-- SQLite does not support DROP COLUMN easily. Manual migration may be required.")


async def _revert_async_sqlite(db: AsyncBaseDb) -> None:
    """Revert SQLite migration."""
    log_warning("-- SQLite does not support DROP COLUMN easily. Manual migration may be required.")


def _revert_singlestore(db: Any) -> None:
    """Revert SingleStore migration."""
    from sqlalchemy import text

    memory_table_name = db.memory_table_name or "agno_memories"
    db_schema = db.db_schema or "agno"
    metrics_table_name = db.metrics_table_name or "agno_metrics"

    with db.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP COLUMN IF EXISTS `feedback`"))
        sess.execute(
            text(
                f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP INDEX IF EXISTS `idx_{memory_table_name}_created_at`"
            )
        )
        sess.execute(text(f"ALTER TABLE `{db_schema}`.`{memory_table_name}` DROP COLUMN IF EXISTS `created_at`"))
        sess.execute(
            text(f"ALTER TABLE `{db_schema}`.`{metrics_table_name}` DROP CONSTRAINT IF EXISTS `uq_metrics_date_period`")
        )
        sess.commit()
        log_info("SingleStore migration reverted")
