"""Migration v3.0.0: Normalize session runs into a runs table, add per-user isolation

Changes:
- Create the runs table (one row per run, with the run payload as JSON)
- Copy every run stored in the sessions table `runs` column into the runs table
- Add the user_id column and its index to every table in ``USER_ID_TABLE_TYPES``
- Move the metrics unique key onto (user_id, date, aggregation_period)
- Re-key namespace="user" entity_memory learnings onto their owner's key

This removes the unbounded growth of session rows: each run is now stored once,
in its own row, instead of the whole run list being rewritten on every save.

The legacy `runs` column on `agno_sessions` is intentionally NOT dropped by this
migration — it stays in place as a backup. New writes will null it as sessions
are touched. When you have verified the migration and taken a backup, drop the
column manually by calling ``db.cleanup_legacy_runs_column()``.

Existing rows keep a NULL user_id, so they stay visible to admins and to unscoped
deployments. Document backends pick the field up without a schema change.

metrics is the exception. Its user_id is NOT NULL with an empty-string sentinel for
"unowned", because SQL treats every NULL as distinct and a unique key holding the
column would never match. Its unique key moves too: the pre-v3.0 key on
(date, aggregation_period) rejects the second user's row for a date. SQLite writes
UNIQUE into the CREATE TABLE statement and cannot drop one, so there the table is
rebuilt.
"""

import json
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.utils import CustomJSONEncoder
from agno.utils.log import log_error, log_info, log_warning

try:
    from sqlalchemy import text
    from sqlalchemy.dialects import mysql, postgresql, sqlite
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

BATCH_SIZE = 50


# Table types that get a user_id column and index. Extend this tuple to isolate another
# table, and register it in ``_table_type_to_attr`` in migrations/manager.py or ``up()`` is
# never called for it; a backend whose schema does not declare the column is skipped.
USER_ID_TABLE_TYPES = ("evals", "components", "knowledge", "schedules", "schedule_runs", "metrics")

# Studio 3.0 schedule provenance:
# nullable TEXT columns, so legacy rows need only the ALTERs. managed_by and
# target_id also get lookup indexes.
SCHEDULE_PROVENANCE_COLUMNS = (
    "managed_by",
    "target_type",
    "target_id",
    "created_by_run_id",
    "created_by_session_id",
    "updated_by_run_id",
    "updated_by_session_id",
    "disabled_reason",
)
SCHEDULE_PROVENANCE_INDEXED = ("managed_by", "target_id")

# The pre-v3.0 metrics unique key. It has to go: a per-user bucket needs user_id in the
# key, or the second user's row for a date is rejected.
METRICS_LEGACY_UNIQUE_NAME = "uq_metrics_date_period"
METRICS_LEGACY_UNIQUE_COLUMNS = ("date", "aggregation_period")

# MySQL and SingleStore reject an identifier longer than this with error 1059.
MAX_MYSQL_IDENTIFIER_LENGTH = 64


class ScheduleDuplicateNamesError(RuntimeError):
    """Raised when the per-owner unique schedule-name backstop cannot be built because
    duplicate names already exist. Must propagate so the migration is NOT stamped as
    applied — otherwise the version advances and the index can never be created on a
    later run (a re-run would skip an already-stamped version)."""


# Buckets the operator has to act on, and buckets that only record what the
# re-key did with a row. rekey_user_entity_learnings logs every count already,
# so these lines carry the reason rather than the numbers.
_REKEY_NEEDS_AN_OPERATOR = (
    ("conflicts", "have a row on the target key whose content does not parse"),
    ("failed", "could not be moved"),
    ("malformed", "are missing the entity columns or do not parse"),
)
_REKEY_FOR_THE_RECORD = (
    ("quarantined", "held more than one user's data and moved out of the entity store's reads"),
    ("contaminated_keyed", "record a user other than their owner and were left in place"),
    (
        "unowned",
        "have no owner: no user's erasure reaches them, and a scoped /learnings read returns them to every user",
    ),
)


def _report_rekey(report: Dict[str, Any], table_name: str) -> bool:
    """Say what the entity_memory re-key did with the rows it could not simply move.

    Returns True when the re-key wrote something.
    """
    for buckets, emit in ((_REKEY_NEEDS_AN_OPERATOR, log_warning), (_REKEY_FOR_THE_RECORD, log_info)):
        for bucket, note in buckets:
            count = len(report.get(bucket) or [])
            if count:
                emit(
                    f"{count} entity_memory row(s) on table {table_name} {note}. "
                    "See 'Entity memory: per-user keys' in V3_MIGRATION_GUIDE.md."
                )
    return any(report.get(bucket) for bucket in ("rekeyed", "merged", "quarantined"))


def _rekey_learnings(db: BaseDb, table_name: str) -> bool:
    """Move pre-3.0 namespace="user" entity_memory rows onto their owner's key."""
    from agno.learn.migrations import rekey_user_entity_learnings

    try:
        report = rekey_user_entity_learnings(db, dry_run=False)
    except NotImplementedError:
        log_info(f"{type(db).__name__} does not store learnings; table {table_name} is left unchanged")
        return False
    return _report_rekey(report, table_name)


async def _arekey_learnings(db: AsyncBaseDb, table_name: str) -> bool:
    """Async version of _rekey_learnings."""
    from agno.learn.migrations import arekey_user_entity_learnings

    try:
        report = await arekey_user_entity_learnings(db, dry_run=False)
    except NotImplementedError:
        log_info(f"{type(db).__name__} does not store learnings; table {table_name} is left unchanged")
        return False
    return _report_rekey(report, table_name)


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Move session runs out of the sessions `runs` column into the runs table
    - Add a user_id column and index to the tables listed in USER_ID_TABLE_TYPES
    - Move the metrics unique key onto (user_id, date, aggregation_period)
    - Re-key namespace="user" entity_memory learnings onto their owner's key

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        # The learnings re-key is a content move, identical on every backend that
        # stores learnings, so it does not go through the per-backend schema work.
        if table_type == "learnings":
            return _rekey_learnings(db, table_name)

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_type, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _migrate_mysql_like(db, table_type, table_name)
        elif db_type == "MongoDb":
            return _migrate_mongo(db, table_type, table_name)
        elif db_type == "FirestoreDb":
            return _migrate_firestore(db, table_type, table_name)
        elif db_type == "RedisDb":
            return _migrate_redis(db, table_type, table_name)
        elif db_type == "ValkeyDb":
            return _migrate_valkey(db, table_type, table_name)
        elif db_type == "JsonDb":
            return _migrate_jsondb(db, table_type, table_name)
        elif db_type == "GcsJsonDb":
            return _migrate_gcsjsondb(db, table_type, table_name)
        elif db_type == "InMemoryDb":
            return _migrate_inmemorydb(db, table_type, table_name)
        elif db_type == "DynamoDb":
            return _migrate_dynamodb(db, table_type, table_name)
        elif db_type == "SurrealDb":
            return _migrate_surrealdb(db, table_type, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Move session runs out of the sessions `runs` column into the runs table
    - Add a user_id column and index to the tables listed in USER_ID_TABLE_TYPES
    - Move the metrics unique key onto (user_id, date, aggregation_period)
    - Re-key namespace="user" entity_memory learnings onto their owner's key

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        # See the sync twin: the learnings re-key is a content move.
        if table_type == "learnings":
            return await _arekey_learnings(db, table_name)

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_type, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_type, table_name)
        elif db_type == "AsyncMongoDb":
            return await _migrate_async_mongo(db, table_type, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Move runs back into the sessions `runs` column and drop the runs table
    - Drop the user_id column and index from the tables listed in USER_ID_TABLE_TYPES
    - Move the metrics unique key back onto (date, aggregation_period)
    - The entity_memory re-key is not reverted

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    # The pre-3.0 entity_memory key under namespace="user" is shared across
    # users, so moving these rows back onto it would collide them again.
    if table_type == "learnings":
        log_warning(
            f"The entity_memory re-key on table {table_name} cannot be reverted: the pre-3.0 key is shared across users"
        )
        return False

    db_type = type(db).__name__

    try:
        if db_type == "PostgresDb":
            return _revert_postgres(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_type, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _revert_mysql_like(db, table_type, table_name)
        elif db_type == "MongoDb":
            return _revert_mongo(db, table_type, table_name)
        elif db_type == "FirestoreDb":
            return _revert_firestore(db, table_type, table_name)
        elif db_type == "RedisDb":
            return _revert_redis(db, table_type, table_name)
        elif db_type == "ValkeyDb":
            return _revert_valkey(db, table_type, table_name)
        elif db_type == "JsonDb":
            return _revert_jsondb(db, table_type, table_name)
        elif db_type == "GcsJsonDb":
            return _revert_gcsjsondb(db, table_type, table_name)
        elif db_type == "InMemoryDb":
            return _revert_inmemorydb(db, table_type, table_name)
        elif db_type == "DynamoDb":
            return _revert_dynamodb(db, table_type, table_name)
        elif db_type == "SurrealDb":
            return _revert_surrealdb(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Move runs back into the sessions `runs` column and drop the runs table
    - Drop the user_id column and index from the tables listed in USER_ID_TABLE_TYPES
    - Move the metrics unique key back onto (date, aggregation_period)
    - The entity_memory re-key is not reverted

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    # The pre-3.0 entity_memory key under namespace="user" is shared across
    # users, so moving these rows back onto it would collide them again.
    if table_type == "learnings":
        log_warning(
            f"The entity_memory re-key on table {table_name} cannot be reverted: the pre-3.0 key is shared across users"
        )
        return False

    db_type = type(db).__name__

    try:
        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_type, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _revert_async_mysql(db, table_type, table_name)
        elif db_type == "AsyncMongoDb":
            return await _revert_async_mongo(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Per-backend dispatch
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on PostgreSQL."""
    if table_type == "sessions":
        return _migrate_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_postgres_user_id(db, table_type, table_name)
    return False


async def _migrate_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async PostgreSQL."""
    if table_type == "sessions":
        return await _migrate_async_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_postgres_user_id(db, table_type, table_name)
    return False


def _migrate_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on SQLite."""
    if table_type == "sessions":
        return _migrate_sqlite_sessions(db, table_name)
    if table_type == "metrics":
        # SQLite can only move the unique key by rebuilding the table, and the rebuild
        # brings the column and its index with it, so the plain add has nothing left to do
        return _migrate_sqlite_metrics_table(db, table_type, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_sqlite_user_id(db, table_type, table_name)
    return False


async def _migrate_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async SQLite."""
    if table_type == "sessions":
        return await _migrate_async_sqlite_sessions(db, table_name)
    if table_type == "metrics":
        # See _migrate_sqlite: on SQLite the rebuild is the whole metrics migration
        return await _migrate_async_sqlite_metrics_table(db, table_type, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_sqlite_user_id(db, table_type, table_name)
    return False


def _migrate_mysql_like(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on MySQL or SingleStore."""
    if table_type == "sessions":
        return _migrate_mysql_like_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_mysql_like_user_id(db, table_type, table_name)
    return False


async def _migrate_async_mysql(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async MySQL."""
    if table_type == "sessions":
        return await _migrate_async_mysql_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_mysql_user_id(db, table_type, table_name)
    return False


def _revert_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on PostgreSQL."""
    if table_type == "sessions":
        return _revert_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_postgres_user_id(db, table_type, table_name)
    return False


async def _revert_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async PostgreSQL."""
    if table_type == "sessions":
        return await _revert_async_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_postgres_user_id(db, table_type, table_name)
    return False


def _revert_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on SQLite."""
    if table_type == "sessions":
        return _revert_sqlite_sessions(db, table_name)
    if table_type == "metrics":
        # SQLite cannot drop a column its unique constraint covers, so metrics goes back
        # the same way it came: by rebuilding the table
        return _revert_sqlite_metrics_table(db, table_type, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_sqlite_user_id(db, table_type, table_name)
    return False


async def _revert_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async SQLite."""
    if table_type == "sessions":
        return await _revert_async_sqlite_sessions(db, table_name)
    if table_type == "metrics":
        # See _revert_sqlite: metrics goes back through a rebuild
        return await _revert_async_sqlite_metrics_table(db, table_type, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_sqlite_user_id(db, table_type, table_name)
    return False


def _revert_mysql_like(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on MySQL or SingleStore."""
    if table_type == "sessions":
        return _revert_mysql_like_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_mysql_like_user_id(db, table_type, table_name)
    return False


async def _revert_async_mysql(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async MySQL."""
    if table_type == "sessions":
        return await _revert_async_mysql_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_mysql_user_id(db, table_type, table_name)
    return False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_run_rows(
    runs: Optional[List[Dict[str, Any]]],
    session_id: str,
    user_id: Optional[str],
    run_data_as_string: bool,
) -> List[Dict[str, Any]]:
    """Build runs-table rows from the runs found in a sessions table `runs` column."""
    runs = _decode_run_data(runs)
    if not runs:
        return []

    current_time = int(time.time())
    rows = []
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("run_id") is None:
            continue

        if run.get("agent_id"):
            run_type = "agent"
        elif run.get("team_id"):
            run_type = "team"
        else:
            run_type = "workflow"

        rows.append(
            {
                "run_id": run.get("run_id"),
                "session_id": session_id,
                "run_type": run_type,
                "agent_id": run.get("agent_id"),
                "team_id": run.get("team_id"),
                "workflow_id": run.get("workflow_id"),
                "user_id": user_id,
                "parent_run_id": run.get("parent_run_id"),
                "status": run.get("status"),
                "run_index": run_index,
                "run_data": json.dumps(run, cls=CustomJSONEncoder) if run_data_as_string else run,
                "created_at": run.get("created_at") or current_time,
                "updated_at": current_time,
            }
        )
    return rows


def _forget_table(db, table_name: Optional[str], attribute: str) -> None:
    """Drop a table from the adapter's SQLAlchemy state after it goes away.

    ``DROP TABLE`` and ``RENAME TO`` leave the Table object registered on
    ``db.metadata``, so a later up() in the same process fails with
    "Table is already defined".
    """
    invalidate = getattr(db, "_invalidate_table_cache", None)
    if invalidate is not None and table_name is not None:
        invalidate(table_name)
    else:
        # Third-party adapter without the cache helper: best-effort metadata cleanup
        metadata = getattr(db, "metadata", None)
        if metadata is not None and table_name is not None:
            for table in list(metadata.tables.values()):
                if table.name == table_name:
                    metadata.remove(table)
    if hasattr(db, attribute):
        setattr(db, attribute, None)


def _forget_runs_table(db) -> None:
    """Forget the runs table, after a revert has dropped it."""
    _forget_table(db, getattr(db, "runs_table_name", None), "runs_table")


def _forget_metrics_table(db, table_name: str) -> None:
    """Forget the metrics table, after a rebuild has replaced it."""
    _forget_table(db, table_name, "metrics_table")


def _decode_run_data(value: Any) -> Any:
    """Decode a run_data or legacy runs payload read back through a raw SQL SELECT.

    A raw select skips the column's JSON deserializer, so SQLite hands back both layers.
    """
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, str):
        value = json.loads(value)
    return value


def _column_exists(sess, db_schema: str, table_name: str, column_name: str, db_type: str) -> bool:
    """Check if a column exists in a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = :column"
        )
    result = sess.execute(query, {"schema": db_schema, "table": table_name, "column": column_name})
    return result.scalar() is not None


async def _async_column_exists(sess, db_schema: str, table_name: str, column_name: str, db_type: str) -> bool:
    """Async version: check if a column exists in a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = :column"
        )
    result = await sess.execute(query, {"schema": db_schema, "table": table_name, "column": column_name})
    return result.scalar() is not None


def _index_columns_query(db_type: str) -> Any:
    """The statement listing the columns an index covers, for this backend."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        return text(
            "SELECT a.attname FROM pg_class t "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_index ix ON ix.indrelid = t.oid "
            "JOIN pg_class i ON i.oid = ix.indexrelid "
            "JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
            "WHERE n.nspname = :schema AND t.relname = :table AND i.relname = :index "
            "ORDER BY k.ord"
        )
    # MySQL / SingleStore
    return text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND INDEX_NAME = :index "
        "ORDER BY SEQ_IN_INDEX"
    )


def _bound_index_name(db_type: str, index_name: str) -> str:
    """The index name as the server stores it, safe to bind in the existence check.

    Postgres folds identifiers longer than 63 bytes down to 63, so a constructed key name
    past the limit is stored truncated. psycopg truncates the over-long parameter the same
    way on the cast to ``name``, but asyncpg's binary protocol refuses it outright.
    """
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        return index_name[:63]
    return index_name


def _index_exists(
    sess, db_schema: str, table_name: str, index_name: str, db_type: str, columns: Optional[List[str]] = None
) -> bool:
    """Check if an index exists on a table.

    ``columns`` narrows the check to an index that really covers them: one of that
    name on other columns would make the migration skip the index it needs.
    """
    result = sess.execute(
        _index_columns_query(db_type),
        {"schema": db_schema, "table": table_name, "index": _bound_index_name(db_type, index_name)},
    )
    found = [row[0] for row in result.fetchall()]
    if not found:
        return False
    return columns is None or sorted(found) == sorted(columns)


async def _async_index_exists(
    sess, db_schema: str, table_name: str, index_name: str, db_type: str, columns: Optional[List[str]] = None
) -> bool:
    """Async version: check if an index exists on a table."""
    result = await sess.execute(
        _index_columns_query(db_type),
        {"schema": db_schema, "table": table_name, "index": _bound_index_name(db_type, index_name)},
    )
    found = [row[0] for row in result.fetchall()]
    if not found:
        return False
    return columns is None or sorted(found) == sorted(columns)


def _unique_indexes_query(db_type: str) -> Any:
    """The statement listing every unique index on a table with its columns."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        return text(
            "SELECT i.relname, a.attname FROM pg_class t "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_index ix ON ix.indrelid = t.oid "
            "JOIN pg_class i ON i.oid = ix.indexrelid "
            "JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
            "WHERE n.nspname = :schema AND t.relname = :table AND ix.indisunique"
        )
    # MySQL / SingleStore
    return text(
        "SELECT INDEX_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND NON_UNIQUE = 0"
    )


def _legacy_metrics_key_names(rows: List[tuple]) -> List[str]:
    """The unique keys among ``(name, column)`` rows that cover exactly the pre-v3.0 pair.

    Found by column set, not by name: RENAME TABLE keeps index names, so a renamed
    table carries the legacy key under its old table's name — which a name lookup
    misses, leaving a key that quietly merges owners again.
    """
    by_name: Dict[str, List[str]] = {}
    for name, column in rows:
        by_name.setdefault(name, []).append(column)
    wanted = sorted(METRICS_LEGACY_UNIQUE_COLUMNS)
    return sorted(name for name, cols in by_name.items() if sorted(cols) == wanted)


def _metrics_legacy_unique_names(sess, db_schema: str, table_name: str, db_type: str) -> List[str]:
    """Names of every unique key still covering exactly (date, aggregation_period)."""
    result = sess.execute(_unique_indexes_query(db_type), {"schema": db_schema, "table": table_name})
    return _legacy_metrics_key_names(result.fetchall())


async def _async_metrics_legacy_unique_names(sess, db_schema: str, table_name: str, db_type: str) -> List[str]:
    """Async variant of :func:`_metrics_legacy_unique_names`."""
    result = await sess.execute(_unique_indexes_query(db_type), {"schema": db_schema, "table": table_name})
    return _legacy_metrics_key_names(result.fetchall())


def _sqlite_table_exists(sess, table_name: str) -> bool:
    """Whether a table of this name exists in the SQLite database."""
    return (
        sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        is not None
    )


async def _async_sqlite_table_exists(sess, table_name: str) -> bool:
    """Async variant of :func:`_sqlite_table_exists`."""
    result = await sess.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    )
    return result.scalar() is not None


def _sqlite_index_columns(sess, index_name: str) -> List[str]:
    """The columns a SQLite index covers."""
    info = sess.execute(text(f"PRAGMA index_info({quote_db_identifier('SqliteDb', index_name)})")).fetchall()
    return [row[2] for row in info]


async def _async_sqlite_index_columns(sess, index_name: str) -> List[str]:
    """Async variant of :func:`_sqlite_index_columns`."""
    result = await sess.execute(text(f"PRAGMA index_info({quote_db_identifier('SqliteDb', index_name)})"))
    return [row[2] for row in result.fetchall()]


def _sqlite_has_unique_on(sess, quoted_table: str, columns: List[str]) -> bool:
    """Whether the table already carries a UNIQUE index over exactly these columns.

    Read from PRAGMA rather than the CREATE TABLE text: an equivalent key can be
    present under a different name, and a name can appear without being a constraint.
    """
    wanted = sorted(columns)
    for index in sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall():
        if index[2] and sorted(_sqlite_index_columns(sess, index[1])) == wanted:
            return True
    return False


async def _async_sqlite_has_unique_on(sess, quoted_table: str, columns: List[str]) -> bool:
    """Async variant of :func:`_sqlite_has_unique_on`."""
    wanted = sorted(columns)
    result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
    for index in result.fetchall():
        if index[2] and sorted(await _async_sqlite_index_columns(sess, index[1])) == wanted:
            return True
    return False


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        if not _column_exists(sess, db_schema, table_name, "runs", db_type):
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = sess.execute(text(f"SELECT session_id, user_id, runs FROM {full_table} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = postgresql.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_postgres_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for async PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    # Ensure the runs table exists
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_schema = :schema AND table_name = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        column_exists = await _async_column_exists(sess, db_schema, table_name, "runs", db_type)
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = await sess.execute(text(f"SELECT session_id, user_id, runs FROM {full_table} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = postgresql.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                await sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for SQLite."""
    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        columns_info = sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = sess.execute(text(f"SELECT session_id, user_id, runs FROM {table_name} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = sqlite.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_sqlite_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for async SQLite."""
    # Ensure the runs table exists
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        table_exists = (
            await sess.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        columns_info = (await sess.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = await sess.execute(text(f"SELECT session_id, user_id, runs FROM {table_name} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = sqlite.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                await sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


# ---------------------------------------------------------------------------
# Revert functions
# ---------------------------------------------------------------------------


def _revert_postgres_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    runs_table_name = db.runs_table_name
    quoted_runs_table = f"{quoted_schema}.{quote_db_identifier(db_type, runs_table_name)}"

    with db.Session() as sess, sess.begin():  # type: ignore
        runs_table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        if not _column_exists(sess, db_schema, table_name, "runs", db_type):
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN runs JSONB"))

        # Rebuild the runs blobs from the runs table
        result = sess.execute(
            text(
                f"SELECT session_id, json_agg(run_data ORDER BY run_index, created_at) "
                f"FROM {quoted_runs_table} GROUP BY session_id"
            )
        )
        for session_id, runs in result.fetchall():
            sess.execute(
                text(f"UPDATE {full_table} SET runs = CAST(:runs AS JSONB) WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE {quoted_runs_table}"))
        _forget_runs_table(db)

        return True


async def _revert_async_postgres_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for async PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    runs_table_name = db.runs_table_name
    quoted_runs_table = f"{quoted_schema}.{quote_db_identifier(db_type, runs_table_name)}"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        runs_table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_schema = :schema AND table_name = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        column_exists = await _async_column_exists(sess, db_schema, table_name, "runs", db_type)
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN runs JSONB"))

        # Rebuild the runs blobs from the runs table
        result = await sess.execute(
            text(
                f"SELECT session_id, json_agg(run_data ORDER BY run_index, created_at) "
                f"FROM {quoted_runs_table} GROUP BY session_id"
            )
        )
        for session_id, runs in result.fetchall():
            await sess.execute(
                text(f"UPDATE {full_table} SET runs = CAST(:runs AS JSONB) WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE {quoted_runs_table}"))
        _forget_runs_table(db)

        return True


def _revert_sqlite_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for SQLite."""
    runs_table_name = db.runs_table_name

    with db.Session() as sess, sess.begin():  # type: ignore
        runs_table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        columns_info = sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN runs JSON"))

        # Rebuild the runs blobs from the runs table
        result = sess.execute(text(f"SELECT DISTINCT session_id FROM {runs_table_name} ORDER BY session_id")).fetchall()
        for (session_id,) in result:
            run_rows = sess.execute(
                text(
                    f"SELECT run_data FROM {runs_table_name} "
                    f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                ),
                {"session_id": session_id},
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE {runs_table_name}"))
        _forget_runs_table(db)

        return True


async def _revert_async_sqlite_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for async SQLite."""
    runs_table_name = db.runs_table_name

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        runs_table_exists = (
            await sess.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        columns_info = (await sess.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN runs JSON"))

        # Rebuild the runs blobs from the runs table
        result = (
            await sess.execute(text(f"SELECT DISTINCT session_id FROM {runs_table_name} ORDER BY session_id"))
        ).fetchall()
        for (session_id,) in result:
            run_rows = (
                await sess.execute(
                    text(
                        f"SELECT run_data FROM {runs_table_name} "
                        f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                    ),
                    {"session_id": session_id},
                )
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            await sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE {runs_table_name}"))
        _forget_runs_table(db)

        return True


# ---------------------------------------------------------------------------
# MySQL / SingleStore (sync). SingleStore is MySQL-protocol-compatible so it
# uses the same code path. AsyncMySQLDb has its own coroutine variants below.
# ---------------------------------------------------------------------------


def _migrate_mysql_like_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table for MySQL or SingleStore.

    Non-destructive: the legacy `runs` column is left in place. Call
    ``db.cleanup_legacy_runs_column()`` to drop it once you have verified
    the migration and taken a backup.
    """
    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore

        # Does the sessions table exist?
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        # Does the legacy `runs` column exist?
        column_exists = (
            sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            ).scalar()
            is not None
        )
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Copy every legacy run into the runs table
        result = sess.execute(
            text(f"SELECT session_id, user_id, runs FROM `{db_schema}`.`{table_name}` WHERE runs IS NOT NULL")
        )
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                # MySQL JSON columns come back as either dict/list (asyncmy)
                # or str (pymysql), depending on driver — _build_run_rows handles both.
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = mysql.insert(runs_table).values(rows)
                # ON DUPLICATE KEY UPDATE that effectively does nothing: keeps idempotency
                # without raising on previously-migrated runs.
                insert_stmt = insert_stmt.on_duplicate_key_update(run_id=insert_stmt.inserted.run_id)
                sess.execute(insert_stmt)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_mysql_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_migrate_mysql_like_sessions`."""
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        result = await sess.execute(
            text(f"SELECT session_id, user_id, runs FROM `{db_schema}`.`{table_name}` WHERE runs IS NOT NULL")
        )
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = mysql.insert(runs_table).values(rows)
                insert_stmt = insert_stmt.on_duplicate_key_update(run_id=insert_stmt.inserted.run_id)
                await sess.execute(insert_stmt)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


def _revert_mysql_like_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild blobs in `sessions.runs` from the runs table; drop the runs table."""
    runs_table_name = db.runs_table_name  # type: ignore

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore

        runs_table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        column_exists = (
            sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            ).scalar()
            is not None
        )
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` ADD COLUMN `runs` JSON"))

        # Rebuild blobs
        session_ids = sess.execute(
            text(f"SELECT DISTINCT session_id FROM `{db_schema}`.`{runs_table_name}` ORDER BY session_id")
        ).fetchall()
        for (session_id,) in session_ids:
            run_rows = sess.execute(
                text(
                    f"SELECT run_data FROM `{db_schema}`.`{runs_table_name}` "
                    f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                ),
                {"session_id": session_id},
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))
        _forget_runs_table(db)

        return True


async def _revert_async_mysql_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_revert_mysql_like_sessions`."""
    runs_table_name = db.runs_table_name  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore

        runs_table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` ADD COLUMN `runs` JSON"))

        result = await sess.execute(
            text(f"SELECT DISTINCT session_id FROM `{db_schema}`.`{runs_table_name}` ORDER BY session_id")
        )
        session_ids = result.fetchall()
        for (session_id,) in session_ids:
            run_rows = (
                await sess.execute(
                    text(
                        f"SELECT run_data FROM `{db_schema}`.`{runs_table_name}` "
                        f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                    ),
                    {"session_id": session_id},
                )
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            await sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))
        _forget_runs_table(db)

        return True


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------


def _index_keys(index_info: Dict[str, Any]) -> List[Any]:
    """Normalize an ``index_information()`` entry's key spec to a list of tuples."""
    return [tuple(pair) for pair in index_info.get("key", [])]


def _migrate_mongo_schedules(db: BaseDb, table_name: str) -> bool:
    """Drop the legacy global-unique ``name`` index and build the v3 index set.

    Pre-3.0.0 declared schedule names unique across all owners. v3 names are
    unique per owner, so on a legacy collection the surviving unique index both
    rejects cross-user name reuse (raw DuplicateKeyError instead of the
    router's 409) and conflicts with the runtime index bootstrap.
    """
    from agno.db.mongo.utils import create_collection_indexes

    database = db.database  # type: ignore[attr-defined]
    if table_name not in database.list_collection_names():
        log_info(f"Schedules collection {table_name} does not exist, skipping migration")
        return False

    collection = database[table_name]
    for index_name, info in collection.index_information().items():
        if _index_keys(info) == [("name", 1)] and info.get("unique"):
            log_info(
                f"-- Dropping legacy unique index '{index_name}' on {table_name}.name "
                "(v3 schedule names are unique per owner)"
            )
            collection.drop_index(index_name)

    # Build the v3 index set (non-unique name, user_id, compound claim/list, and the
    # unique (user_id, name) backstop). create_collection_indexes tolerates a per-index
    # failure (needed for the legacy name conflict), so confirm the backstop landed —
    # if duplicate names blocked it, fail the migration so it is not stamped as done and
    # a re-run can finish once the duplicates are resolved.
    create_collection_indexes(collection, "schedules")
    if "uq_user_name" not in collection.index_information():
        raise ScheduleDuplicateNamesError(
            f"Cannot create the unique (user_id, name) backstop on {table_name}: duplicate schedule "
            "names exist within one owner bucket. Resolve the duplicates, then re-run the migration."
        )
    log_info(f"-- Ensured v3 indexes on schedules collection {table_name}")
    return True


def _revert_mongo_schedules(db: BaseDb, table_name: str) -> bool:
    """Restore the v2 global-unique ``name`` index on the schedules collection."""
    database = db.database  # type: ignore[attr-defined]
    if table_name not in database.list_collection_names():
        return False

    collection = database[table_name]
    for index_name, info in collection.index_information().items():
        if _index_keys(info) == [("name", 1)] and not info.get("unique"):
            collection.drop_index(index_name)
    try:
        collection.create_index([("name", 1)], unique=True)
        log_info(f"-- Restored v2 unique index on {table_name}.name")
    except Exception as e:
        log_warning(
            f"Could not restore the v2 unique name index on {table_name} - per-owner duplicate "
            f"schedule names likely exist. Resolve the duplicates, then create it manually: {e}"
        )
    return True


def _migrate_mongo(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once you have verified
    the migration and taken a backup.

    For the schedules collection, repairs the legacy index layout instead
    (see :func:`_migrate_mongo_schedules`).
    """
    if table_type == "schedules":
        return _migrate_mongo_schedules(db, table_name)
    if table_type != "sessions":
        return False

    sessions_collection = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_collection is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    # Ensure the runs collection exists (creates indexes too)
    runs_collection = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_collection is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    cursor = sessions_collection.find(
        {"runs": {"$exists": True, "$ne": None, "$not": {"$size": 0}}},
        {"session_id": 1, "user_id": 1, "runs": 1},
    ).batch_size(BATCH_SIZE)

    for doc in cursor:
        rows = _build_run_rows(doc.get("runs"), doc.get("session_id"), doc.get("user_id"), run_data_as_string=False)
        for row in rows:
            runs_collection.replace_one({"run_id": row["run_id"]}, row, upsert=True)
            migrated_runs += 1

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )

    return True


def _revert_mongo(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is dropped at the end.
    """
    if table_type == "schedules":
        return _revert_mongo_schedules(db, table_name)
    if table_type != "sessions":
        return False

    sessions_collection = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_collection_name = db.runs_table_name  # type: ignore
    runs_collection = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore

    if sessions_collection is None or runs_collection is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    # Group runs by session_id, ordered
    pipeline = [
        {"$sort": {"session_id": 1, "run_index": 1, "created_at": 1}},
        {"$group": {"_id": "$session_id", "runs": {"$push": "$run_data"}}},
    ]
    for group in runs_collection.aggregate(pipeline):
        session_id = group["_id"]
        runs = group["runs"]
        sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {"runs": runs}},
        )

    log_info(f"-- Dropping runs collection {runs_collection_name}")
    runs_collection.drop()

    return True


async def _migrate_async_mongo_schedules(db: AsyncBaseDb, table_name: str) -> bool:
    """Async variant of :func:`_migrate_mongo_schedules`."""
    from agno.db.mongo.utils import create_collection_indexes_async

    database = db.database  # type: ignore[attr-defined]
    if table_name not in await database.list_collection_names():
        log_info(f"Schedules collection {table_name} does not exist, skipping migration")
        return False

    collection = database[table_name]
    index_info = await collection.index_information()
    for index_name, info in index_info.items():
        if _index_keys(info) == [("name", 1)] and info.get("unique"):
            log_info(
                f"-- Dropping legacy unique index '{index_name}' on {table_name}.name "
                "(v3 schedule names are unique per owner)"
            )
            await collection.drop_index(index_name)

    await create_collection_indexes_async(collection, "schedules")
    if "uq_user_name" not in await collection.index_information():
        raise ScheduleDuplicateNamesError(
            f"Cannot create the unique (user_id, name) backstop on {table_name}: duplicate schedule "
            "names exist within one owner bucket. Resolve the duplicates, then re-run the migration."
        )
    log_info(f"-- Ensured v3 indexes on schedules collection {table_name}")
    return True


async def _revert_async_mongo_schedules(db: AsyncBaseDb, table_name: str) -> bool:
    """Async variant of :func:`_revert_mongo_schedules`."""
    database = db.database  # type: ignore[attr-defined]
    if table_name not in await database.list_collection_names():
        return False

    collection = database[table_name]
    index_info = await collection.index_information()
    for index_name, info in index_info.items():
        if _index_keys(info) == [("name", 1)] and not info.get("unique"):
            await collection.drop_index(index_name)
    try:
        await collection.create_index([("name", 1)], unique=True)
        log_info(f"-- Restored v2 unique index on {table_name}.name")
    except Exception as e:
        log_warning(
            f"Could not restore the v2 unique name index on {table_name} - per-owner duplicate "
            f"schedule names likely exist. Resolve the duplicates, then create it manually: {e}"
        )
    return True


async def _migrate_async_mongo(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async variant of :func:`_migrate_mongo`."""
    if table_type == "schedules":
        return await _migrate_async_mongo_schedules(db, table_name)
    if table_type != "sessions":
        return False

    sessions_collection = await db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_collection is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    runs_collection = await db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_collection is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    cursor = sessions_collection.find(
        {"runs": {"$exists": True, "$ne": None, "$not": {"$size": 0}}},
        {"session_id": 1, "user_id": 1, "runs": 1},
    ).batch_size(BATCH_SIZE)

    async for doc in cursor:
        rows = _build_run_rows(doc.get("runs"), doc.get("session_id"), doc.get("user_id"), run_data_as_string=False)
        for row in rows:
            await runs_collection.replace_one({"run_id": row["run_id"]}, row, upsert=True)
            migrated_runs += 1

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


async def _revert_async_mongo(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async variant of :func:`_revert_mongo`."""
    if table_type == "schedules":
        return await _revert_async_mongo_schedules(db, table_name)
    if table_type != "sessions":
        return False

    sessions_collection = await db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_collection_name = db.runs_table_name  # type: ignore
    runs_collection = await db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore

    if sessions_collection is None or runs_collection is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    pipeline = [
        {"$sort": {"session_id": 1, "run_index": 1, "created_at": 1}},
        {"$group": {"_id": "$session_id", "runs": {"$push": "$run_data"}}},
    ]
    # PyMongo's async client returns a coroutine from aggregate(), Motor a cursor.
    for group in await db._aggregate_to_list(runs_collection, pipeline):  # type: ignore
        session_id = group["_id"]
        runs = group["runs"]
        await sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {"runs": runs}},
        )

    log_info(f"-- Dropping runs collection {runs_collection_name}")
    await runs_collection.drop()
    return True


# ---------------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------------


def _migrate_firestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once verified.
    """
    if table_type != "sessions":
        return False

    sessions_ref = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_ref is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    runs_ref = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_ref is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    batch = db.db_client.batch()  # type: ignore
    pending_in_batch = 0
    BATCH_LIMIT = 400  # Firestore batches max out at 500 writes; stay below the cap

    for doc in sessions_ref.stream():
        data = doc.to_dict() or {}
        legacy_runs = data.get("runs")
        if not legacy_runs:
            continue
        session_id = data.get("session_id")
        if not session_id:
            continue
        rows = _build_run_rows(legacy_runs, session_id, data.get("user_id"), run_data_as_string=False)
        for row in rows:
            run_doc_ref = runs_ref.document(row["run_id"])
            batch.set(run_doc_ref, row)
            pending_in_batch += 1
            migrated_runs += 1
            if pending_in_batch >= BATCH_LIMIT:
                batch.commit()
                batch = db.db_client.batch()  # type: ignore
                pending_in_batch = 0

    if pending_in_batch:
        batch.commit()

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_firestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is deleted at the end.
    """
    if table_type != "sessions":
        return False

    from google.cloud.firestore import FieldFilter  # type: ignore[import-untyped]

    sessions_ref = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_ref = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if sessions_ref is None or runs_ref is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    runs_by_session: Dict[str, List[Any]] = {}
    for doc in runs_ref.stream():
        d = doc.to_dict() or {}
        sid = d.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (d.get("run_index") or 0, d.get("created_at") or 0, d.get("run_data"))
        )

    # Rebuild the inline blob on each session doc
    batch = db.db_client.batch()  # type: ignore
    pending = 0
    for sid, items in runs_by_session.items():
        items.sort(key=lambda t: (t[0], t[1]))
        runs = [t[2] for t in items]
        q = sessions_ref.where(filter=FieldFilter("session_id", "==", sid))
        for sd in q.stream():
            batch.update(sd.reference, {"runs": runs})
            pending += 1
            if pending >= 400:
                batch.commit()
                batch = db.db_client.batch()  # type: ignore
                pending = 0
    if pending:
        batch.commit()

    # Wipe the runs collection
    log_info("-- Deleting all documents in the runs collection")
    batch = db.db_client.batch()  # type: ignore
    pending = 0
    for doc in runs_ref.stream():
        batch.delete(doc.reference)
        pending += 1
        if pending >= 400:
            batch.commit()
            batch = db.db_client.batch()  # type: ignore
            pending = 0
    if pending:
        batch.commit()

    return True


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def _migrate_redis(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session records into per-run keys.

    Non-destructive: the legacy `runs` field is left in place on the session
    record. Call ``db.cleanup_legacy_runs_field()`` once you have verified the
    migration to free the storage.
    """
    if table_type != "sessions":
        return False

    sessions = db._get_all_records("sessions")  # type: ignore
    migrated_runs = 0
    for session in sessions:
        legacy_runs = session.get("runs")
        if not legacy_runs:
            continue
        rows = _build_run_rows(legacy_runs, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        if not rows:
            continue
        # Write each run key directly + populate the sorted-set index.
        index_key = db._runs_by_session_index_key(session["session_id"])  # type: ignore
        from agno.db.redis.utils import generate_redis_key, serialize_data  # type: ignore

        pipe = db.redis_client.pipeline()  # type: ignore
        for row in rows:
            key = generate_redis_key(prefix=db.db_prefix, table_type="runs", key_id=row["run_id"])  # type: ignore
            pipe.set(key, serialize_data(row), ex=db.expire)  # type: ignore
            pipe.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
        pipe.execute()
        migrated_runs += len(rows)

    log_info(f"-- Copied {migrated_runs} runs into per-run Redis keys")
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_redis(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session records, then delete run keys."""
    if table_type != "sessions":
        return False

    from agno.db.redis.utils import generate_redis_key  # type: ignore

    # Collect runs per session
    runs_keys = db._get_all_records("runs")  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in runs_keys:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions = db._get_all_records("sessions")  # type: ignore
    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]
        db._store_record(table_type="sessions", record_id=sid, data=session)  # type: ignore

    # Delete per-run keys + per-session indexes
    for r in runs_keys:
        rid = r.get("run_id")
        if not rid:
            continue
        try:
            db.redis_client.delete(generate_redis_key(prefix=db.db_prefix, table_type="runs", key_id=rid))  # type: ignore
        except Exception:
            pass
    for sid in list(runs_by_session.keys()):
        try:
            db.redis_client.delete(db._runs_by_session_index_key(sid))  # type: ignore
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# Valkey
# ---------------------------------------------------------------------------


def _migrate_valkey(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session records into per-run keys.

    Non-destructive: the legacy `runs` field is left in place on the session
    record. Call ``db.cleanup_legacy_runs_field()`` once you have verified the
    migration to free the storage.
    """
    if table_type != "sessions":
        return False

    from glide_sync import ExpirySet, ExpiryType

    from agno.db.valkey.utils import generate_valkey_key, serialize_data  # type: ignore

    sessions = db._get_all_records("sessions")  # type: ignore
    migrated_runs = 0
    for session in sessions:
        legacy_runs = session.get("runs")
        if not legacy_runs:
            continue
        rows = _build_run_rows(legacy_runs, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        if not rows:
            continue
        # Write each run key directly + populate the sorted-set index.
        index_key = db._runs_by_session_index_key(session["session_id"])  # type: ignore
        pipeline = db._create_pipeline()  # type: ignore
        expiry = ExpirySet(ExpiryType.SEC, db.expire) if db.expire is not None else None  # type: ignore
        for row in rows:
            key = generate_valkey_key(prefix=db.db_prefix, table_type="runs", key_id=row["run_id"])  # type: ignore
            pipeline.set(key, serialize_data(row), expiry=expiry)
            pipeline.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
        if db.expire is not None:  # type: ignore
            pipeline.expire(index_key, db.expire)  # type: ignore
        db._exec_pipeline(pipeline)  # type: ignore
        migrated_runs += len(rows)

    log_info(f"-- Copied {migrated_runs} runs into per-run Valkey keys")
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_valkey(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session records, then delete run keys."""
    if table_type != "sessions":
        return False

    from agno.db.valkey.utils import generate_valkey_key  # type: ignore

    # Collect runs per session
    runs_keys = db._get_all_records("runs")  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in runs_keys:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions = db._get_all_records("sessions")  # type: ignore
    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]
        db._store_record(table_type="sessions", record_id=sid, data=session)  # type: ignore

    # Delete per-run keys + per-session indexes
    for r in runs_keys:
        rid = r.get("run_id")
        if not rid:
            continue
        try:
            db.valkey_client.delete([generate_valkey_key(prefix=db.db_prefix, table_type="runs", key_id=rid)])  # type: ignore
        except Exception:
            pass
    for sid in list(runs_by_session.keys()):
        try:
            db.valkey_client.delete([db._runs_by_session_index_key(sid)])  # type: ignore
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# JsonDb / GcsJsonDb / InMemoryDb
# These adapters store sessions as a single list (file/object/in-memory dict).
# Each one exposes the same `_store_session_runs`-style helper added in v3,
# plus a way to walk the legacy `runs` field on each session record.
# ---------------------------------------------------------------------------


def _migrate_jsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on each session record into the runs file.

    Idempotent: reruns don't clobber fresh post-migration writes. Any run_id
    already present in the runs table wins — the legacy blob is only used
    to backfill run_ids that aren't there yet.
    """
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    if not sessions:
        log_info(f"Sessions file {table_name}.json is empty or missing, skipping migration")
        return False

    existing_runs = db._read_runs_file(create_table_if_not_found=True)  # type: ignore
    by_id = {r["run_id"]: r for r in existing_runs if "run_id" in r}

    migrated = 0
    for session in sessions:
        legacy = session.get("runs")
        if not legacy:
            continue
        rows = _build_run_rows(legacy, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        for row in rows:
            # Runs table wins on conflict: never overwrite a post-migration
            # update with the stale blob copy on a rerun.
            if row["run_id"] in by_id:
                continue
            by_id[row["run_id"]] = row
            migrated += 1

    if migrated:
        db._write_runs_file(list(by_id.values()))  # type: ignore
    log_info(f"-- Copied {migrated} runs into {db.runs_table_name}.json")  # type: ignore
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_jsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on each session record from the runs file."""
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    all_runs = db._read_runs_file(create_table_if_not_found=False)  # type: ignore

    runs_by_session: Dict[str, List[Any]] = {}
    for r in all_runs:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]

    db._write_json_file(db.session_table_name, sessions)  # type: ignore
    db._write_runs_file([])  # type: ignore
    return True


def _migrate_gcsjsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Same shape as :func:`_migrate_jsondb` — both store sessions as a JSON list (file vs object).

    Idempotent: reruns don't clobber fresh post-migration writes. Any run_id
    already present in the runs table wins.
    """
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    if not sessions:
        log_info(f"Sessions object {table_name}.json is empty or missing, skipping migration")
        return False

    existing_runs = db._read_json_file(db.runs_table_name, create_table_if_not_found=True)  # type: ignore
    by_id = {r["run_id"]: r for r in existing_runs if "run_id" in r}

    migrated = 0
    for session in sessions:
        legacy = session.get("runs")
        if not legacy:
            continue
        rows = _build_run_rows(legacy, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        for row in rows:
            if row["run_id"] in by_id:
                continue
            by_id[row["run_id"]] = row
            migrated += 1

    if migrated:
        db._write_json_file(db.runs_table_name, list(by_id.values()))  # type: ignore
    log_info(f"-- Copied {migrated} runs into {db.runs_table_name}.json (GCS)")  # type: ignore
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_gcsjsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    all_runs = db._read_json_file(db.runs_table_name, create_table_if_not_found=False)  # type: ignore

    runs_by_session: Dict[str, List[Any]] = {}
    for r in all_runs:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]

    db._write_json_file(db.session_table_name, sessions)  # type: ignore
    db._write_json_file(db.runs_table_name, [])  # type: ignore
    return True


def _migrate_inmemorydb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """InMemoryDb is not normalized in v3.0; runs stay inline."""
    if table_type != "sessions":
        return False

    log_info("-- InMemoryDb does not split runs into a separate table; skipping migration.")
    return False


def _revert_inmemorydb(db: BaseDb, table_type: str, table_name: str) -> bool:
    if table_type != "sessions":
        return False

    return False


# ---------------------------------------------------------------------------
# DynamoDb
# ---------------------------------------------------------------------------


# DynamoDB error codes that indicate a transient, retryable failure.
_DYNAMO_THROTTLE_CODES = {
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
    "InternalServerError",
}


def _dynamo_put_run_with_retry(
    client,
    table_name: str,
    item: Dict[str, Any],
    max_retries: int = 5,
    initial_backoff_seconds: float = 0.1,
) -> bool:
    """Conditionally put a run item, retrying transient throttling failures.

    The write is guarded by ``attribute_not_exists(run_id)`` so a run that was
    already copied (e.g. by a partial/lazy self-migration) is left untouched --
    keeping the migration idempotent and preserving the "store wins" invariant.

    On throttling, retries with exponential backoff. Any non-throttling error,
    or throttling that survives ``max_retries``, is propagated so a partial
    migration fails loudly instead of silently dropping runs (the legacy blob is
    lazily nulled on the next session write, so a silent skip means data loss).

    Returns:
        True if the item was written, False if it already existed.
    """
    backoff = initial_backoff_seconds
    for attempt in range(max_retries + 1):
        try:
            client.put_item(
                TableName=table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(run_id)",
            )
            return True
        except client.exceptions.ConditionalCheckFailedException:
            return False
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code")
            if code in _DYNAMO_THROTTLE_CODES and attempt < max_retries:
                log_warning(
                    f"Dynamo put_item throttled ({code}) migrating run "
                    f"{item.get('run_id', {}).get('S')}; retry {attempt + 1}/{max_retries} "
                    f"after {backoff:.2f}s"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
                continue
            raise
    # Unreachable: the final attempt above always returns or raises.
    raise RuntimeError(f"Failed to migrate run into {table_name} after {max_retries} retries")


def _migrate_dynamodb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session item into the agno_runs table."""
    if table_type != "sessions":
        return False

    import json as _json

    client = db.client  # type: ignore
    runs_table = db.runs_table_name  # type: ignore

    # Ensure runs table exists
    db._get_table("runs", create_table_if_not_found=True)  # type: ignore

    # Scan all sessions
    items: List[Dict[str, Any]] = []
    try:
        response = client.scan(TableName=table_name)
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except Exception as e:
        log_error(f"Failed to scan {table_name} during v3 migration: {str(e)}")
        return False

    migrated = 0
    for item in items:
        runs_attr = item.get("runs")
        if runs_attr is None:
            continue

        legacy: Any = None
        if "S" in runs_attr:
            try:
                legacy = _json.loads(runs_attr["S"])
            except (_json.JSONDecodeError, TypeError):
                legacy = None
        elif "L" in runs_attr:
            legacy = runs_attr["L"]

        if not legacy:
            continue

        session_id = item.get("session_id", {}).get("S")
        user_id = item.get("user_id", {}).get("S")
        if not session_id:
            continue

        rows = _build_run_rows(legacy, session_id, user_id, run_data_as_string=False)
        for row in rows:
            payload = {k: v for k, v in row.items() if v is not None}
            if "run_data" in payload and isinstance(payload["run_data"], (dict, list)):
                payload["run_data"] = _json.dumps(payload["run_data"])
            dynamo_item = _serialize_to_dynamo_item_minimal(payload)
            # Propagates on non-transient failure so a partial migration aborts
            # loudly rather than silently dropping runs. Safe to re-run (the
            # conditional write skips already-migrated runs).
            if _dynamo_put_run_with_retry(client, runs_table, dynamo_item):
                migrated += 1

    log_info(
        f"-- Copied {migrated} runs into {runs_table}. The legacy 'runs' attribute on each session item "
        "was preserved as a backup. Once verified, drop it via db.cleanup_legacy_runs_field()."
    )
    return migrated > 0


def _revert_dynamodb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Walk runs and re-attach to session items, then truncate the runs table."""
    if table_type != "sessions":
        return False

    import json as _json

    client = db.client  # type: ignore
    runs_table = db.runs_table_name  # type: ignore

    items: List[Dict[str, Any]] = []
    try:
        response = client.scan(TableName=runs_table)
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = client.scan(TableName=runs_table, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except Exception as e:
        log_error(f"Failed to scan runs table {runs_table}: {str(e)}")
        return False

    runs_by_session: Dict[str, List[Any]] = {}
    for it in items:
        sid = it.get("session_id", {}).get("S")
        if not sid:
            continue
        run_index = int(it.get("run_index", {}).get("N", "0"))
        created_at = int(it.get("created_at", {}).get("N", "0"))
        run_data_raw = it.get("run_data", {}).get("S")
        if not run_data_raw:
            continue
        try:
            payload = _json.loads(run_data_raw)
        except (_json.JSONDecodeError, TypeError):
            continue
        runs_by_session.setdefault(sid, []).append((run_index, created_at, payload))

    failed_sids: set = set()
    for sid, items_for_session in runs_by_session.items():
        items_for_session.sort(key=lambda t: (t[0], t[1]))
        legacy_runs = [t[2] for t in items_for_session]
        try:
            client.update_item(
                TableName=table_name,
                Key={"session_id": {"S": sid}},
                UpdateExpression="SET #runs = :runs",
                ExpressionAttributeNames={"#runs": "runs"},
                ExpressionAttributeValues={":runs": {"S": _json.dumps(legacy_runs)}},
            )
        except Exception as e:
            log_error(f"Failed to revert runs onto session {sid}: {str(e)}")
            failed_sids.add(sid)

    # Truncate the runs table, but preserve runs for any session whose blob
    # rebuild failed -- deleting them would lose the only remaining copy.
    preserved = 0
    for it in items:
        run_id = it.get("run_id", {}).get("S")
        if not run_id:
            continue
        if it.get("session_id", {}).get("S") in failed_sids:
            preserved += 1
            continue
        try:
            client.delete_item(TableName=runs_table, Key={"run_id": {"S": run_id}})
        except Exception:
            pass

    if failed_sids:
        log_warning(
            f"Preserved {preserved} run(s) in {runs_table} for {len(failed_sids)} session(s) whose "
            "blob rebuild failed; re-run down() after resolving the error."
        )

    return True


def _serialize_to_dynamo_item_minimal(data: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal DynamoDB item serializer used by the v3 migration."""
    item: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            item[key] = {"BOOL": value}
        elif isinstance(value, (int, float)):
            item[key] = {"N": str(value)}
        elif isinstance(value, str):
            item[key] = {"S": value}
        elif isinstance(value, (dict, list)):
            import json as _json

            item[key] = {"S": _json.dumps(value)}
        else:
            item[key] = {"S": str(value)}
    return item


# ---------------------------------------------------------------------------
# SurrealDb
# ---------------------------------------------------------------------------


def _migrate_surrealdb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session record into the runs table."""
    if table_type != "sessions":
        return False

    from surrealdb import RecordID  # type: ignore

    from agno.db.surrealdb.models import serialize_run_row  # local import to avoid hard dep

    runs_table = db.runs_table_name  # type: ignore

    # Make sure the runs table exists
    db._get_table("runs", create_table_if_not_found=True)  # type: ignore

    sessions_raw = db._query(f"SELECT * FROM {table_name}", {}, dict)  # type: ignore
    migrated = 0
    for s in sessions_raw:
        legacy = s.get("runs")
        if not legacy:
            continue

        session_id = s.get("id")
        if isinstance(session_id, RecordID):
            session_id = session_id.id
        user_id = s.get("user_id")
        if not session_id:
            continue

        rows = _build_run_rows(legacy, session_id, user_id, run_data_as_string=False)
        for row in rows:
            content = serialize_run_row(row, runs_table)
            try:
                db._query_one(  # type: ignore
                    "UPSERT ONLY $record CONTENT $content",
                    {"record": RecordID(runs_table, row["run_id"]), "content": content},
                    dict,
                )
                migrated += 1
            except Exception as e:
                log_error(f"Failed to migrate run {row.get('run_id')}: {str(e)}")

    log_info(
        f"-- Copied {migrated} runs into {runs_table}. The legacy 'runs' field on each session record "
        "was preserved as a backup. Once verified, drop it via db.cleanup_legacy_runs_field()."
    )
    return migrated > 0


def _revert_surrealdb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Walk runs and rebuild the legacy `runs` blob on each session row."""
    if table_type != "sessions":
        return False

    from surrealdb import RecordID  # type: ignore

    runs_table = db.runs_table_name  # type: ignore

    rows_raw = db._query(f"SELECT * FROM {runs_table}", {}, dict)  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in rows_raw:
        sid = r.get("session_id")
        if isinstance(sid, RecordID):
            sid = sid.id
        if not sid:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions_table = table_name
    failed_sids: set = set()
    for sid, items in runs_by_session.items():
        items.sort(key=lambda t: (t[0], t[1]))
        legacy_runs = [t[2] for t in items if t[2] is not None]
        try:
            db.client.query(  # type: ignore
                "UPDATE $record SET runs = $runs",
                {"record": RecordID(sessions_table, sid), "runs": legacy_runs},
            )
        except Exception as e:
            log_error(f"Failed to revert runs onto session {sid}: {str(e)}")
            failed_sids.add(sid)

    if not failed_sids:
        # No failures: truncate the whole runs table.
        try:
            db.client.delete(runs_table)  # type: ignore
        except Exception:
            pass
    else:
        # Preserve runs for sessions whose blob rebuild failed -- deleting them
        # would lose the only remaining copy. Delete the rest by record id.
        preserved = 0
        for r in rows_raw:
            sid = r.get("session_id")
            if isinstance(sid, RecordID):
                sid = sid.id
            if sid in failed_sids:
                preserved += 1
                continue
            rid = r.get("id")
            if rid is None:
                continue
            try:
                db.client.delete(rid)  # type: ignore
            except Exception:
                pass
        log_warning(
            f"Preserved {preserved} run(s) in {runs_table} for {len(failed_sids)} session(s) whose "
            "blob rebuild failed; re-run down() after resolving the error."
        )
    return True


# ---------------------------------------------------------------------------
# user_id column
# ---------------------------------------------------------------------------


def _table_schema(db, table_type: str) -> Optional[Dict[str, Any]]:
    """The adapter's own schema definition for this table type, or None if it has none."""
    db_type = type(db).__name__

    schemas: Any
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        from agno.db.postgres import schemas
    elif db_type in ("MySQLDb", "AsyncMySQLDb"):
        from agno.db.mysql import schemas
    elif db_type == "SingleStoreDb":
        from agno.db.singlestore import schemas
    else:
        from agno.db.sqlite import schemas

    try:
        return schemas.get_table_schema_definition(table_type)
    except (ValueError, KeyError):
        return None


def _user_id_column_ddl(db, table_type: str) -> Optional[str]:
    """Compile the user_id column definition from the adapter's own schema for this table.

    A NOT NULL column carries its default too: ``ADD COLUMN ... NOT NULL`` is rejected
    on a populated table without one. Returns None when this adapter's schema has no
    such table or no user_id column.
    """
    table_schema = _table_schema(db, table_type)
    if table_schema is None or "user_id" not in table_schema:
        return None
    column = table_schema["user_id"]

    column_ddl = column["type"]().compile(dialect=db.db_engine.dialect)
    default = column.get("default")
    if column.get("nullable") is False and isinstance(default, str):
        escaped_default = default.replace("'", "''")
        column_ddl = f"{column_ddl} NOT NULL DEFAULT '{escaped_default}'"
    return column_ddl


def _user_id_composite_indexes(db, table_type: str, table_name: str) -> List[tuple]:
    """Schema-declared composite indexes that include user_id, as (name, columns).

    Names follow the adapters' composite-index convention:
    ``idx_{table}_{columns joined with _}``.
    """
    table_schema = _table_schema(db, table_type)
    if table_schema is None:
        return []
    composites = table_schema.get("__composite_indexes__", [])
    return [
        (f"idx_{table_name}_{'_'.join(idx['columns'])}", list(idx["columns"]))
        for idx in composites
        if "user_id" in idx["columns"]
    ]


def _metrics_unique_constraint(db, table_name: str) -> Optional[tuple]:
    """The metrics unique constraint the adapter declares, as (name, columns).

    SingleStore declares none: it rejects a second multi-column UNIQUE alongside the
    id primary key (error 1706), so it gets the column and nothing else.
    """
    table_schema = _table_schema(db, "metrics")
    if table_schema is None:
        return None
    for constraint in table_schema.get("_unique_constraints", []):
        if "user_id" in constraint["columns"]:
            # The adapters prefix the declared name with the table name
            return f"{table_name}_{constraint['name']}", list(constraint["columns"])
    return None


def _metrics_key_name_fits(db, table_name: str) -> bool:
    """Whether the v3.0 unique key name fits MySQL's identifier limit.

    Checked before the migration touches the table: the new key goes on before the old one
    comes off, so overflowing mid-way would leave the legacy key still merging owners. The
    table is named in the log and left at its pre-v3.0 shape, rather than raised on, so one
    over-long metrics table does not stop the tables migrated after it. PostgreSQL truncates
    to 63 bytes rather than refuse, and truncates the name ``_index_exists`` looks it up by
    to the same bytes, so it needs no check.

    The manager stamps a skipped table as migrated, but the version row is keyed by table
    name, so the rename the log asks for leaves an unstamped table that migrates cleanly.
    """
    declared = _metrics_unique_constraint(db, table_name)
    if declared is None:
        return True
    unique_name = declared[0]
    if len(unique_name) <= MAX_MYSQL_IDENTIFIER_LENGTH:
        return True
    longest_table = len(table_name) + MAX_MYSQL_IDENTIFIER_LENGTH - len(unique_name)
    log_warning(
        f"Skipping migration of {table_name}: its v3.0 unique key would be named {unique_name}, which is "
        f"{len(unique_name)} characters against this database's limit of {MAX_MYSQL_IDENTIFIER_LENGTH}. "
        f"Rename the metrics table to at most {longest_table} characters and migrate again."
    )
    return False


def _sqlite_metrics_ddl(db, table_name: str, with_user_id: bool) -> Optional[tuple]:
    """The CREATE statements for a metrics table, as (table, indexes).

    Built from the adapter's own schema, so a rebuilt table matches a fresh install.
    ``with_user_id`` False gives the pre-v3.0 shape.
    """
    from sqlalchemy import Column, Index, MetaData, Table, UniqueConstraint
    from sqlalchemy.schema import CreateIndex, CreateTable

    table_schema = _table_schema(db, "metrics")
    if table_schema is None:
        return None

    if with_user_id:
        declared = _metrics_unique_constraint(db, table_name)
        if declared is None:
            return None
        unique_name, unique_columns = declared
    else:
        unique_name = f"{table_name}_{METRICS_LEGACY_UNIQUE_NAME}"
        unique_columns = list(METRICS_LEGACY_UNIQUE_COLUMNS)

    columns, indexed = [], []
    for name, spec in table_schema.items():
        if name.startswith("_") or (name == "user_id" and not with_user_id):
            continue
        columns.append(
            Column(
                name,
                spec["type"](),
                primary_key=spec.get("primary_key", False),
                nullable=spec.get("nullable", True),
            )
        )
        if spec.get("index"):
            indexed.append(name)

    table = Table(table_name, MetaData(), *columns, UniqueConstraint(*unique_columns, name=unique_name))
    dialect = db.db_engine.dialect
    return (
        str(CreateTable(table).compile(dialect=dialect)),
        [
            str(CreateIndex(Index(f"idx_{table_name}_{name}", table.c[name])).compile(dialect=dialect))
            for name in indexed
        ],
    )


def _is_metrics_shaped(db, columns: List[str]) -> bool:
    """Whether a table is exactly the metrics table, so the rebuild may replace it.

    The rebuild drops and recreates the table from the adapter's schema, so a mismatched
    (table_type, table_name) pair has to be refused rather than acted on, and so does a
    column the schema does not declare: it would go with the table it was added to.
    """
    table_schema = _table_schema(db, "metrics")
    if table_schema is None:
        return False
    expected = {name for name in table_schema if not name.startswith("_") and name != "user_id"}
    if not expected.issubset(columns):
        return False
    undeclared = sorted(set(columns) - expected - {"user_id"})
    if undeclared:
        log_warning(f"Refusing to rebuild metrics: the table carries columns the schema does not declare: {undeclared}")
        return False
    return True


def _drop_incomplete_metrics_rows(sess, table_name: str, full_table: str) -> None:
    """Remove the newest unfinished metrics day, as ownership lands.

    Stamped unowned, such a row becomes a bucket the per-user recalculation never
    rewrites, and the day is counted twice for good. Only the newest day goes, and only
    when it sits past every completed one: that is the day the recalculation resumes at,
    so the only one certain to be rebuilt from sessions. Unowned rows only, so a second
    replica cannot delete real per-user buckets.
    """
    # Separate SELECTs because MySQL cannot subquery the table a DELETE targets
    last_completed = sess.execute(text(f"SELECT MAX(date) FROM {full_table} WHERE completed = true")).scalar()
    newest = sess.execute(text(f"SELECT MAX(date) FROM {full_table}")).scalar()
    if newest is None or (last_completed is not None and newest <= last_completed):
        return
    result = sess.execute(
        text(
            f"DELETE FROM {full_table} WHERE completed = false AND (user_id = '' OR user_id IS NULL) AND date = :newest"
        ),
        {"newest": newest},
    )
    if result.rowcount:
        log_info(f"-- Cleared the unfinished newest metric day from {table_name} so it recalculates per user")


async def _async_drop_incomplete_metrics_rows(sess, table_name: str, full_table: str) -> None:
    """Async variant of :func:`_drop_incomplete_metrics_rows`."""
    # Separate SELECTs because MySQL cannot subquery the table a DELETE targets
    result = await sess.execute(text(f"SELECT MAX(date) FROM {full_table} WHERE completed = true"))
    last_completed = result.scalar()
    result = await sess.execute(text(f"SELECT MAX(date) FROM {full_table}"))
    newest = result.scalar()
    if newest is None or (last_completed is not None and newest <= last_completed):
        return
    result = await sess.execute(
        text(
            f"DELETE FROM {full_table} WHERE completed = false AND (user_id = '' OR user_id IS NULL) AND date = :newest"
        ),
        {"newest": newest},
    )
    if result.rowcount:
        log_info(f"-- Cleared the unfinished newest metric day from {table_name} so it recalculates per user")


@contextmanager
def _sqlite_ddl_transaction(db) -> Generator[Any, None, None]:
    """A connection on which DDL really does roll back.

    pysqlite commits DDL as it goes, so an interrupted rebuild would strand the rows in
    the renamed-aside table; an explicit BEGIN keeps it one unit.
    """
    with db.db_engine.connect() as conn:
        conn.exec_driver_sql("BEGIN")
        try:
            yield conn
        except Exception:
            conn.exec_driver_sql("ROLLBACK")
            raise
        conn.exec_driver_sql("COMMIT")


@asynccontextmanager
async def _async_sqlite_ddl_transaction(db) -> AsyncGenerator[Any, None]:
    """Async variant of :func:`_sqlite_ddl_transaction`."""
    async with db.db_engine.connect() as conn:
        await conn.exec_driver_sql("BEGIN")
        try:
            yield conn
        except Exception:
            await conn.exec_driver_sql("ROLLBACK")
            raise
        await conn.exec_driver_sql("COMMIT")


def _swap_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Move the metrics unique key onto (user_id, date, aggregation_period) for PostgreSQL.

    The new key goes on first, so the table is never briefly without one. The old one is
    then dropped both ways: Postgres refuses DROP INDEX on an index a constraint owns,
    and DROP CONSTRAINT does not see a hand-created index of that name.
    """
    db_type = type(db).__name__
    applied = False
    declared = _metrics_unique_constraint(db, table_name)
    if declared is not None:
        name, columns = declared
        if not _index_exists(sess, db_schema, table_name, name, db_type, columns):
            log_info(f"-- Adding unique constraint {name} on {table_name}")
            # No ADD CONSTRAINT IF NOT EXISTS, and a failure poisons the transaction:
            # the savepoint absorbs a key another process added first
            try:
                with sess.begin_nested():
                    sess.execute(
                        text(
                            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, name)} "
                            f"UNIQUE ({', '.join(columns)})"
                        )
                    )
            except Exception:
                if not _index_exists(sess, db_schema, table_name, name, db_type, columns):
                    raise
            applied = True

    # By column set, not name: a renamed table carries the legacy key under its old name
    for legacy_name in _metrics_legacy_unique_names(sess, db_schema, table_name, db_type):
        log_info(f"-- Dropping legacy unique constraint {legacy_name} from {table_name}")
        quoted_legacy = quote_db_identifier(db_type, legacy_name)
        sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT IF EXISTS {quoted_legacy}"))
        sess.execute(text(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, db_schema)}.{quoted_legacy}"))
        applied = True

    return applied


async def _swap_async_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async PostgreSQL variant of :func:`_swap_postgres_metrics_unique`."""
    db_type = type(db).__name__
    applied = False
    declared = _metrics_unique_constraint(db, table_name)
    if declared is not None:
        name, columns = declared
        if not await _async_index_exists(sess, db_schema, table_name, name, db_type, columns):
            log_info(f"-- Adding unique constraint {name} on {table_name}")
            # See _swap_postgres_metrics_unique: the savepoint keeps a key another
            # process added first from poisoning this transaction
            try:
                async with sess.begin_nested():
                    await sess.execute(
                        text(
                            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, name)} "
                            f"UNIQUE ({', '.join(columns)})"
                        )
                    )
            except Exception:
                if not await _async_index_exists(sess, db_schema, table_name, name, db_type, columns):
                    raise
            applied = True

    # See _swap_postgres_metrics_unique: found by column set, not name
    for legacy_name in await _async_metrics_legacy_unique_names(sess, db_schema, table_name, db_type):
        log_info(f"-- Dropping legacy unique constraint {legacy_name} from {table_name}")
        quoted_legacy = quote_db_identifier(db_type, legacy_name)
        await sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT IF EXISTS {quoted_legacy}"))
        await sess.execute(text(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, db_schema)}.{quoted_legacy}"))
        applied = True

    return applied


def _swap_mysql_like_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """MySQL / SingleStore variant of :func:`_swap_postgres_metrics_unique`.

    MySQL implements a unique constraint as an index, so the legacy key goes with DROP
    INDEX. SingleStore declares none and never carried the legacy one either, so there is
    nothing to drop and nothing to add. The new key goes on before the old one comes off:
    MySQL commits each ALTER on its own, so dropping first would leave no key at all if
    the add then failed.
    """
    db_type = type(db).__name__
    applied = False
    declared = _metrics_unique_constraint(db, table_name)
    if declared is not None:
        name, columns = declared
        if not _index_exists(sess, db_schema, table_name, name, db_type, columns):
            log_info(f"-- Adding unique constraint {name} on {table_name}")
            quoted_columns = ", ".join(quote_db_identifier(db_type, column) for column in columns)
            # No ADD CONSTRAINT IF NOT EXISTS, so on failure the check is made again:
            # a key another process added first is there either way
            try:
                sess.execute(
                    text(
                        f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, name)} "
                        f"UNIQUE ({quoted_columns})"
                    )
                )
            except Exception:
                if not _index_exists(sess, db_schema, table_name, name, db_type, columns):
                    raise
            applied = True

    # By column set, not name: a renamed table carries the legacy key under its old name
    for legacy_name in _metrics_legacy_unique_names(sess, db_schema, table_name, db_type):
        log_info(f"-- Dropping legacy unique constraint {legacy_name} from {table_name}")
        # No DROP INDEX IF EXISTS, so on failure the check is made again: a key another
        # process dropped first is gone either way
        try:
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, legacy_name)} ON {full_table}"))
        except Exception:
            if _index_exists(sess, db_schema, table_name, legacy_name, db_type):
                raise
        applied = True

    return applied


async def _swap_async_mysql_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async MySQL variant of :func:`_swap_mysql_like_metrics_unique`."""
    db_type = type(db).__name__
    applied = False
    declared = _metrics_unique_constraint(db, table_name)
    if declared is not None:
        name, columns = declared
        if not await _async_index_exists(sess, db_schema, table_name, name, db_type, columns):
            log_info(f"-- Adding unique constraint {name} on {table_name}")
            quoted_columns = ", ".join(quote_db_identifier(db_type, column) for column in columns)
            # See _swap_mysql_like_metrics_unique: a key another process added
            # first is not a reason to fail the migration
            try:
                await sess.execute(
                    text(
                        f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, name)} "
                        f"UNIQUE ({quoted_columns})"
                    )
                )
            except Exception:
                if not await _async_index_exists(sess, db_schema, table_name, name, db_type, columns):
                    raise
            applied = True

    # See _swap_mysql_like_metrics_unique: found by column set, not name
    for legacy_name in await _async_metrics_legacy_unique_names(sess, db_schema, table_name, db_type):
        log_info(f"-- Dropping legacy unique constraint {legacy_name} from {table_name}")
        # No DROP INDEX IF EXISTS, so on failure the check is made again: a key another
        # process dropped first is gone either way
        try:
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, legacy_name)} ON {full_table}"))
        except Exception:
            if await _async_index_exists(sess, db_schema, table_name, legacy_name, db_type):
                raise
        applied = True

    return applied


def _schedule_unique_backstop_ddls(db_type: str, full_table: str, table_name: str) -> List[tuple]:
    """(index_name, DDL) pairs backing per-owner schedule-name uniqueness.

    Index names match what the adapters' table builders create on fresh tables,
    so the existence checks are shared. Unique INDEXes rather than constraints
    because SQLite cannot ``ALTER TABLE ADD CONSTRAINT``; enforcement is
    identical. NULLs are distinct in unique indexes, so the unowned bucket
    gets its own partial index.
    """
    uq_user = f"{table_name}_uq_user_name"
    uq_unowned = f"{table_name}_uq_unowned_name"
    return [
        (
            uq_user,
            f"CREATE UNIQUE INDEX {quote_db_identifier(db_type, uq_user)} "
            f"ON {full_table} (user_id, name) WHERE user_id IS NOT NULL",
        ),
        (
            uq_unowned,
            f"CREATE UNIQUE INDEX {quote_db_identifier(db_type, uq_unowned)} "
            f"ON {full_table} (name) WHERE user_id IS NULL",
        ),
    ]


def _is_duplicate_key_error(exc: Exception) -> bool:
    """Whether a CREATE UNIQUE INDEX failed because duplicate rows already exist
    (vs a transient/connection error). Checked by SQLSTATE/type, not message text."""
    try:
        from sqlalchemy.exc import IntegrityError

        if isinstance(exc, IntegrityError):
            return True
    except ImportError:
        pass
    # SQLite surfaces this as OperationalError; Postgres as a wrapped UniqueViolation.
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "23505":  # unique_violation
        return True
    return "unique" in str(getattr(exc, "orig", exc)).lower()


def _raise_or_return_dup(idx_name: str, table_name: str, exc: Exception) -> None:
    """Turn a duplicate-key failure into an actionable, MIGRATION-FAILING error; re-raise
    anything else. Never swallow: a stamped-but-unindexed table can never self-heal."""
    if _is_duplicate_key_error(exc):
        raise ScheduleDuplicateNamesError(
            f"Cannot create unique index {idx_name} on {table_name}: duplicate schedule names exist "
            "within one owner bucket. Resolve the duplicates (the router enforces per-owner uniqueness "
            "on create, so these predate it), then re-run the migration."
        ) from exc
    raise exc


def _postgres_schedule_unique_backstop(db: Any, db_schema: str, table_name: str, full_table: str, db_type: str) -> bool:
    """Each index runs in its own transaction. A duplicate-name failure raises
    (failing the migration, unstamped) so a later re-run can finish the job."""
    applied = False
    for idx_name, ddl in _schedule_unique_backstop_ddls(db_type, full_table, table_name):
        try:
            with db.Session() as sess, sess.begin():
                if _index_exists(sess, db_schema, table_name, idx_name, db_type):
                    continue
                log_info(f"-- Adding unique index {idx_name} on {table_name} (schedule names are unique per owner)")
                sess.execute(text(ddl))
                applied = True
        except Exception as e:
            _raise_or_return_dup(idx_name, table_name, e)
    return applied


async def _async_postgres_schedule_unique_backstop(
    db: Any, db_schema: str, table_name: str, full_table: str, db_type: str
) -> bool:
    """Async variant of :func:`_postgres_schedule_unique_backstop`."""
    applied = False
    for idx_name, ddl in _schedule_unique_backstop_ddls(db_type, full_table, table_name):
        try:
            async with db.async_session_factory() as sess, sess.begin():
                if await _async_index_exists(sess, db_schema, table_name, idx_name, db_type):
                    continue
                log_info(f"-- Adding unique index {idx_name} on {table_name} (schedule names are unique per owner)")
                await sess.execute(text(ddl))
                applied = True
        except Exception as e:
            _raise_or_return_dup(idx_name, table_name, e)
    return applied


def _sqlite_schedule_unique_backstop(db: Any, table_name: str, quoted_table: str, db_type: str) -> bool:
    """SQLite variant of :func:`_postgres_schedule_unique_backstop`."""
    applied = False
    for idx_name, ddl in _schedule_unique_backstop_ddls(db_type, quoted_table, table_name):
        try:
            with db.Session() as sess, sess.begin():
                existing = {idx[1] for idx in sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()}
                if idx_name in existing:
                    continue
                log_info(f"-- Adding unique index {idx_name} on {table_name} (schedule names are unique per owner)")
                sess.execute(text(ddl))
                applied = True
        except Exception as e:
            _raise_or_return_dup(idx_name, table_name, e)
    return applied


async def _async_sqlite_schedule_unique_backstop(db: Any, table_name: str, quoted_table: str, db_type: str) -> bool:
    """Async SQLite variant of :func:`_postgres_schedule_unique_backstop`."""
    applied = False
    for idx_name, ddl in _schedule_unique_backstop_ddls(db_type, quoted_table, table_name):
        try:
            async with db.async_session_factory() as sess, sess.begin():
                result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
                if idx_name in {idx[1] for idx in result.fetchall()}:
                    continue
                log_info(f"-- Adding unique index {idx_name} on {table_name} (schedule names are unique per owner)")
                await sess.execute(text(ddl))
                applied = True
        except Exception as e:
            _raise_or_return_dup(idx_name, table_name, e)
    return applied


def _migrate_postgres_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False
        column_added = False

        if not _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            # IF NOT EXISTS: a replica booting alongside another should not die over a
            # column the other added between the check above and this statement
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS user_id {column_ddl}"))
            column_added = True
            applied = True

        if table_type == "metrics":
            # Strongest lock first: the key swap takes ACCESS EXCLUSIVE while CREATE INDEX
            # takes SHARE, and two replicas that both took SHARE deadlock on the upgrade
            key_swapped = _swap_postgres_metrics_unique(sess, db, db_schema, table_name, full_table)
            if key_swapped:
                applied = True
            # A hand-added column skips the branch above, so the delete keys off the key
            # swap too. Neither fires on a no-op re-run, sparing a current-day bucket.
            if column_added or key_swapped:
                _drop_incomplete_metrics_rows(sess, table_name, full_table)

            # Not tied to the transition above: a column an earlier run left defaulted still
            # needs the default dropped on a pass that changes nothing else
            if _metrics_user_id_has_default(sess, db_schema, table_name):
                log_info(f"-- Dropping the transitional default from user_id on {table_name}")
                sess.execute(text(f"ALTER TABLE {full_table} ALTER COLUMN user_id DROP DEFAULT"))
                applied = True

        if not _index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(
                text(f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index_name)} ON {full_table} (user_id)")
            )
            applied = True

        for comp_name, comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            # A composite can reference v3-only columns (e.g. linked_to) a legacy table lacks.
            if not all(c == "user_id" or _column_exists(sess, db_schema, table_name, c, db_type) for c in comp_cols):
                continue
            if not _index_exists(sess, db_schema, table_name, comp_name, db_type):
                log_info(f"-- Adding index {comp_name} on {table_name}")
                sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, comp_name)} "
                        f"ON {full_table} ({', '.join(comp_cols)})"
                    )
                )
                applied = True

    if table_type == "schedules":
        with db.Session() as sess, sess.begin():  # type: ignore
            for column in SCHEDULE_PROVENANCE_COLUMNS:
                log_info(f"-- Ensuring {column} column on {table_name}")
                sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {column} VARCHAR"))
            for column in SCHEDULE_PROVENANCE_INDEXED:
                index = f"idx_{table_name}_{column}"
                sess.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index)} ON {full_table} ({column})")
                )
        applied = True

    # Outside the main transaction: a duplicate-name failure only skips the backstop.
    if table_type == "schedules":
        applied = _postgres_schedule_unique_backstop(db, db_schema, table_name, full_table, db_type) or applied
    return applied


async def _migrate_async_postgres_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async PostgreSQL variant of :func:`_migrate_postgres_user_id`."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False
        column_added = False

        if not await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            # See _migrate_postgres_user_id: IF NOT EXISTS lets two replicas
            # migrate the same table at once
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS user_id {column_ddl}"))
            column_added = True
            applied = True

        if table_type == "metrics":
            # See _migrate_postgres_user_id: the key swap's ACCESS EXCLUSIVE
            # comes before CREATE INDEX's SHARE, or two replicas deadlock
            key_swapped = await _swap_async_postgres_metrics_unique(sess, db, db_schema, table_name, full_table)
            if key_swapped:
                applied = True
            # See _migrate_postgres_user_id: a hand-added column skips the
            # branch above, so the delete keys off the key swap too
            if column_added or key_swapped:
                await _async_drop_incomplete_metrics_rows(sess, table_name, full_table)

            # See _migrate_postgres_user_id: a column an earlier run left defaulted
            # still needs the default dropped
            if await _async_metrics_user_id_has_default(sess, db_schema, table_name):
                log_info(f"-- Dropping the transitional default from user_id on {table_name}")
                await sess.execute(text(f"ALTER TABLE {full_table} ALTER COLUMN user_id DROP DEFAULT"))
                applied = True

        if not await _async_index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index_name)} ON {full_table} (user_id)")
            )
            applied = True

        for comp_name, comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            # A composite can reference v3-only columns (e.g. linked_to) a legacy table lacks.
            cols_present = True
            for c in comp_cols:
                if c != "user_id" and not await _async_column_exists(sess, db_schema, table_name, c, db_type):
                    cols_present = False
                    break
            if not cols_present:
                continue
            if not await _async_index_exists(sess, db_schema, table_name, comp_name, db_type):
                log_info(f"-- Adding index {comp_name} on {table_name}")
                await sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, comp_name)} "
                        f"ON {full_table} ({', '.join(comp_cols)})"
                    )
                )
                applied = True

    if table_type == "schedules":
        async with db.async_session_factory() as sess, sess.begin():  # type: ignore
            for column in SCHEDULE_PROVENANCE_COLUMNS:
                log_info(f"-- Ensuring {column} column on {table_name}")
                await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {column} VARCHAR"))
            for column in SCHEDULE_PROVENANCE_INDEXED:
                index = f"idx_{table_name}_{column}"
                await sess.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index)} ON {full_table} ({column})")
                )
        applied = True

    # Outside the main transaction: a duplicate-name failure only skips the backstop.
    if table_type == "schedules":
        applied = (
            await _async_postgres_schedule_unique_backstop(db, db_schema, table_name, full_table, db_type) or applied
        )
    return applied


def _metrics_user_id_has_default(sess, db_schema: str, table_name: str) -> bool:
    """True while metrics user_id still carries the server default the column was added with.

    ``ADD COLUMN ... NOT NULL`` needs one on a populated table, but it must not outlive the
    migration: an insert that omits the owner would land whole-deployment counts in the
    unowned bucket rather than fail, which is not what a table created by the schema does.
    """
    return (
        sess.execute(
            text(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_schema = :schema AND table_name = :table_name AND column_name = 'user_id'"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        is not None
    )


async def _async_metrics_user_id_has_default(sess, db_schema: str, table_name: str) -> bool:
    """Async variant of :func:`_metrics_user_id_has_default`."""
    result = await sess.execute(
        text(
            "SELECT column_default FROM information_schema.columns"
            " WHERE table_schema = :schema AND table_name = :table_name AND column_name = 'user_id'"
        ),
        {"schema": db_schema, "table_name": table_name},
    )
    return result.scalar() is not None


def _metrics_user_id_needs_modify(sess, db_schema: str, table_name: str) -> bool:
    """True while metrics user_id still carries a default."""
    row = sess.execute(
        text(
            "SELECT COLUMN_DEFAULT FROM INFORMATION_SCHEMA.COLUMNS"
            " WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name AND COLUMN_NAME = 'user_id'"
        ),
        {"schema": db_schema, "table_name": table_name},
    ).fetchone()
    if row is None:
        return False
    return row[0] is not None


async def _async_metrics_user_id_needs_modify(sess, db_schema: str, table_name: str) -> bool:
    """Async variant of :func:`_metrics_user_id_needs_modify`."""
    result = await sess.execute(
        text(
            "SELECT COLUMN_DEFAULT FROM INFORMATION_SCHEMA.COLUMNS"
            " WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name AND COLUMN_NAME = 'user_id'"
        ),
        {"schema": db_schema, "table_name": table_name},
    )
    row = result.fetchone()
    if row is None:
        return False
    return row[0] is not None


def _metrics_user_id_modify_ddl(db) -> Optional[str]:
    """The metrics user_id column as MODIFY COLUMN wants it: typed, NOT NULL, no default.

    ON DUPLICATE KEY UPDATE names no constraint, so a pre-v3.0 writer's insert still lands
    here; without the default it fails rather than filing whole-deployment counts under the
    unowned bucket.
    """
    table_schema = _table_schema(db, "metrics")
    if table_schema is None or "user_id" not in table_schema:
        return None
    return f"{table_schema['user_id']['type']().compile(dialect=db.db_engine.dialect)} NOT NULL"


def _migrate_mysql_like_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for MySQL or SingleStore."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False
    if table_type == "metrics" and not _metrics_key_name_fits(db, table_name):
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False
        column_added = False

        if not _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            # No ADD COLUMN IF NOT EXISTS, so on failure the check is made again: a
            # column another process added first is there either way
            try:
                sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `user_id` {column_ddl}"))
            except Exception:
                if not _column_exists(sess, db_schema, table_name, "user_id", db_type):
                    raise
            column_added = True
            applied = True

        if not _index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
            log_info(f"-- Adding index {index_name} on {table_name}")
            # See the column above: another process may have created it first
            try:
                sess.execute(
                    text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                )
            except Exception:
                if not _index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
                    raise
            applied = True

        if table_type == "metrics":
            key_swapped = _swap_mysql_like_metrics_unique(sess, db, db_schema, table_name, full_table)
            if key_swapped:
                applied = True
            # See _migrate_postgres_user_id: a hand-added column skips the
            # branch above, so the delete keys off the key swap too
            if column_added or key_swapped:
                _drop_incomplete_metrics_rows(sess, table_name, full_table)

            # Not tied to the transition above: a column an earlier run left case-insensitive
            # or defaulted still needs rewriting on a pass that changes nothing else
            modify_ddl = _metrics_user_id_modify_ddl(db)
            if modify_ddl is not None and _metrics_user_id_needs_modify(sess, db_schema, table_name):
                log_info(f"-- Rewriting user_id on {table_name} without a default")
                sess.execute(text(f"ALTER TABLE {full_table} MODIFY COLUMN `user_id` {modify_ddl}"))
                applied = True

        return applied


async def _migrate_async_mysql_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async MySQL variant of :func:`_migrate_mysql_like_user_id`."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False
    if table_type == "metrics" and not _metrics_key_name_fits(db, table_name):
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False
        column_added = False

        if not await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            # See _migrate_mysql_like_user_id: a column another process added
            # first is not a reason to fail the migration
            try:
                await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `user_id` {column_ddl}"))
            except Exception:
                if not await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
                    raise
            column_added = True
            applied = True

        if not await _async_index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
            log_info(f"-- Adding index {index_name} on {table_name}")
            # See the column above: another process may have created it first
            try:
                await sess.execute(
                    text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                )
            except Exception:
                if not await _async_index_exists(sess, db_schema, table_name, index_name, db_type, ["user_id"]):
                    raise
            applied = True

        if table_type == "metrics":
            key_swapped = await _swap_async_mysql_metrics_unique(sess, db, db_schema, table_name, full_table)
            if key_swapped:
                applied = True
            # See _migrate_postgres_user_id: a hand-added column skips the
            # branch above, so the delete keys off the key swap too
            if column_added or key_swapped:
                await _async_drop_incomplete_metrics_rows(sess, table_name, full_table)

            # Not tied to the transition above: a column an earlier run left case-insensitive
            # or defaulted still needs rewriting on a pass that changes nothing else
            modify_ddl = _metrics_user_id_modify_ddl(db)
            if modify_ddl is not None and await _async_metrics_user_id_needs_modify(sess, db_schema, table_name):
                log_info(f"-- Rewriting user_id on {table_name} without a default")
                await sess.execute(text(f"ALTER TABLE {full_table} MODIFY COLUMN `user_id` {modify_ddl}"))
                applied = True

        return applied


def _sqlite_metrics_rebuild_plan(db, table_name: str, table_info: List[tuple], index_rows: List[tuple]) -> tuple:
    """Work out what a rebuild has to carry over, as (carried, extra_indexes).

    ``carried`` are the schema's own columns the live table has, ``extra_indexes`` the
    index statements the schema will not recreate; the rebuild would otherwise drop them.
    """
    table_schema = _table_schema(db, "metrics") or {}
    schema_columns = {name for name in table_schema if not name.startswith("_")}
    indexed = {f"idx_{table_name}_{name}" for name in schema_columns if table_schema[name].get("index")}

    carried = [col[1] for col in table_info if col[1] in schema_columns and col[1] != "user_id"]
    extra_indexes = [row[1] for row in index_rows if row[0] not in indexed]
    return carried, extra_indexes


def _migrate_sqlite_metrics_table(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Rebuild the metrics table so its unique key includes user_id, for SQLite.

    SQLite writes UNIQUE into the CREATE TABLE statement and has no
    ``ALTER TABLE ... DROP CONSTRAINT``, so the legacy key can only go by rebuilding the
    table. One transaction: it lands, or the original table is left exactly as it was.
    """
    if table_type != "metrics":
        return False

    declared = _metrics_unique_constraint(db, table_name)
    ddl = _sqlite_metrics_ddl(db, table_name, with_user_id=True)
    if declared is None or ddl is None:
        return False
    unique_columns = declared[1]
    create_sql, index_sqls = ddl

    db_type = type(db).__name__
    backup_name = f"{table_name}_pre_v3_0_0"
    quoted_table = quote_db_identifier(db_type, table_name)
    quoted_backup = quote_db_identifier(db_type, backup_name)

    with db.Session() as sess:  # type: ignore
        if not _sqlite_table_exists(sess, table_name):
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        if _sqlite_has_unique_on(sess, quoted_table, unique_columns):
            return False

        table_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        # The rebuild replaces the table, so refuse a mismatched (table_type, table_name)
        if not _is_metrics_shaped(db, [col[1] for col in table_info]):
            log_warning(
                f"Table {table_name} is not shaped like a metrics table, so it keeps its pre-v3.0 shape "
                "and metrics writes against it will fail. Point metrics_table at the right table, or move "
                "the undeclared columns onto one of your own."
            )
            return False
        index_rows = sess.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"),
            {"t": table_name},
        ).fetchall()
        # A hand-made UNIQUE index without user_id would reject the second owner's row, so it is not replayed
        unique_names = {idx[1] for idx in sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall() if idx[2]}
        kept_indexes = [
            row for row in index_rows if row[0] not in unique_names or "user_id" in _sqlite_index_columns(sess, row[0])
        ]

    carried, extra_indexes = _sqlite_metrics_rebuild_plan(db, table_name, table_info, kept_indexes)
    copied_sql = ", ".join(quote_db_identifier(db_type, col) for col in carried)
    # Rows written before ownership existed belong to the unowned bucket
    owner_sql = "COALESCE(user_id, '')" if "user_id" in [col[1] for col in table_info] else "''"

    log_info(f"-- Rebuilding {table_name} to move its unique key onto user_id")
    with _sqlite_ddl_transaction(db) as conn:
        conn.exec_driver_sql(f"ALTER TABLE {quoted_table} RENAME TO {quoted_backup}")
        # Index names are unique across the database, so the old ones go first
        for index_row in index_rows:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, index_row[0])}")

        conn.exec_driver_sql(create_sql)
        for statement in index_sqls + extra_indexes:
            conn.exec_driver_sql(statement)

        conn.exec_driver_sql(
            f"INSERT INTO {quoted_table} ({copied_sql}, user_id) SELECT {copied_sql}, {owner_sql} FROM {quoted_backup}"
        )
        # See _drop_incomplete_metrics_rows: stamped unowned, an in-progress day would
        # leave a bucket the per-user recalculation never targets, counting it twice
        conn.exec_driver_sql(
            f"DELETE FROM {quoted_table} WHERE completed = 0 AND user_id = '' "
            f"AND date = (SELECT MAX(date) FROM {quoted_table}) "
            f"AND date > COALESCE((SELECT MAX(date) FROM {quoted_table} WHERE completed = 1), '')"
        )
        conn.exec_driver_sql(f"DROP TABLE {quoted_backup}")

    _forget_metrics_table(db, table_name)
    return True


async def _migrate_async_sqlite_metrics_table(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_migrate_sqlite_metrics_table`."""
    if table_type != "metrics":
        return False

    declared = _metrics_unique_constraint(db, table_name)
    ddl = _sqlite_metrics_ddl(db, table_name, with_user_id=True)
    if declared is None or ddl is None:
        return False
    unique_columns = declared[1]
    create_sql, index_sqls = ddl

    db_type = type(db).__name__
    backup_name = f"{table_name}_pre_v3_0_0"
    quoted_table = quote_db_identifier(db_type, table_name)
    quoted_backup = quote_db_identifier(db_type, backup_name)

    async with db.async_session_factory() as sess:  # type: ignore
        if not await _async_sqlite_table_exists(sess, table_name):
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        if await _async_sqlite_has_unique_on(sess, quoted_table, unique_columns):
            return False

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        table_info = result.fetchall()
        # The rebuild replaces the table, so refuse a mismatched (table_type, table_name)
        if not _is_metrics_shaped(db, [col[1] for col in table_info]):
            log_warning(
                f"Table {table_name} is not shaped like a metrics table, so it keeps its pre-v3.0 shape "
                "and metrics writes against it will fail. Point metrics_table at the right table, or move "
                "the undeclared columns onto one of your own."
            )
            return False
        result = await sess.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"),
            {"t": table_name},
        )
        index_rows = result.fetchall()
        # See _migrate_sqlite_metrics_table: a hand-made UNIQUE index without user_id is not replayed
        result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
        unique_names = {idx[1] for idx in result.fetchall() if idx[2]}
        kept_indexes = [
            row
            for row in index_rows
            if row[0] not in unique_names or "user_id" in await _async_sqlite_index_columns(sess, row[0])
        ]

    carried, extra_indexes = _sqlite_metrics_rebuild_plan(db, table_name, table_info, kept_indexes)
    copied_sql = ", ".join(quote_db_identifier(db_type, col) for col in carried)
    # Rows written before ownership existed belong to the unowned bucket
    owner_sql = "COALESCE(user_id, '')" if "user_id" in [col[1] for col in table_info] else "''"

    log_info(f"-- Rebuilding {table_name} to move its unique key onto user_id")
    async with _async_sqlite_ddl_transaction(db) as conn:
        statements = [f"ALTER TABLE {quoted_table} RENAME TO {quoted_backup}"]
        # Index names are unique across the database, so the old ones go first
        statements += [f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, row[0])}" for row in index_rows]
        statements.append(create_sql)
        statements += index_sqls + extra_indexes
        for statement in statements:
            await conn.exec_driver_sql(statement)

        await conn.exec_driver_sql(
            f"INSERT INTO {quoted_table} ({copied_sql}, user_id) SELECT {copied_sql}, {owner_sql} FROM {quoted_backup}"
        )
        # See _migrate_sqlite_metrics_table: only the newest unfinished day goes,
        # and the per-user recalculation rebuilds it from sessions
        await conn.exec_driver_sql(
            f"DELETE FROM {quoted_table} WHERE completed = 0 AND user_id = '' "
            f"AND date = (SELECT MAX(date) FROM {quoted_table}) "
            f"AND date > COALESCE((SELECT MAX(date) FROM {quoted_table} WHERE completed = 1), '')"
        )
        await conn.exec_driver_sql(f"DROP TABLE {quoted_backup}")

    _forget_metrics_table(db, table_name)
    return True


def _migrate_sqlite_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for SQLite."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        if "user_id" not in {col[1] for col in columns_info}:
            log_info(f"-- Adding user_id column to {table_name}")
            sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
        existing_indexes = {idx[1] for idx in indexes}
        if index_name not in existing_indexes:
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)"))
            applied = True

        table_columns = {col[1] for col in columns_info} | {"user_id"}
        for comp_name, comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            # A composite can reference v3-only columns (e.g. linked_to) a legacy table lacks.
            if not all(c in table_columns for c in comp_cols):
                continue
            if comp_name not in existing_indexes:
                log_info(f"-- Adding index {comp_name} on {table_name}")
                sess.execute(
                    text(
                        f"CREATE INDEX {quote_db_identifier(db_type, comp_name)} ON {quoted_table} ({', '.join(comp_cols)})"
                    )
                )
                applied = True

    if table_type == "schedules":
        with db.Session() as sess, sess.begin():  # type: ignore
            columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
            existing_columns = {col[1] for col in columns_info}
            indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
            existing_indexes = {idx[1] for idx in indexes}
            for column in SCHEDULE_PROVENANCE_COLUMNS:
                if column not in existing_columns:
                    log_info(f"-- Adding {column} column to {table_name}")
                    sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {column} TEXT"))
                    applied = True
            for column in SCHEDULE_PROVENANCE_INDEXED:
                index = f"idx_{table_name}_{column}"
                if index not in existing_indexes:
                    log_info(f"-- Adding index {index} on {table_name}")
                    sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index)} ON {quoted_table} ({column})")
                    )
                    applied = True

    # Outside the main transaction: a duplicate-name failure only skips the backstop.
    if table_type == "schedules":
        applied = _sqlite_schedule_unique_backstop(db, table_name, quoted_table, db_type) or applied
    return applied


async def _migrate_async_sqlite_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_migrate_sqlite_user_id`."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        if "user_id" not in {col[1] for col in result.fetchall()}:
            log_info(f"-- Adding user_id column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
        existing_indexes = {idx[1] for idx in result.fetchall()}
        if index_name not in existing_indexes:
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
            )
            applied = True

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        table_columns = {col[1] for col in result.fetchall()} | {"user_id"}
        for comp_name, comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            # A composite can reference v3-only columns (e.g. linked_to) a legacy table lacks.
            if not all(c in table_columns for c in comp_cols):
                continue
            if comp_name not in existing_indexes:
                log_info(f"-- Adding index {comp_name} on {table_name}")
                await sess.execute(
                    text(
                        f"CREATE INDEX {quote_db_identifier(db_type, comp_name)} ON {quoted_table} ({', '.join(comp_cols)})"
                    )
                )
                applied = True

    if table_type == "schedules":
        async with db.async_session_factory() as sess, sess.begin():  # type: ignore
            columns_info = (await sess.execute(text(f"PRAGMA table_info({quoted_table})"))).fetchall()
            existing_columns = {col[1] for col in columns_info}
            indexes = (await sess.execute(text(f"PRAGMA index_list({quoted_table})"))).fetchall()
            existing_indexes = {idx[1] for idx in indexes}
            for column in SCHEDULE_PROVENANCE_COLUMNS:
                if column not in existing_columns:
                    log_info(f"-- Adding {column} column to {table_name}")
                    await sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {column} TEXT"))
                    applied = True
            for column in SCHEDULE_PROVENANCE_INDEXED:
                index = f"idx_{table_name}_{column}"
                if index not in existing_indexes:
                    log_info(f"-- Adding index {index} on {table_name}")
                    await sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index)} ON {quoted_table} ({column})")
                    )
                    applied = True

    # Outside the main transaction: a duplicate-name failure only skips the backstop.
    if table_type == "schedules":
        applied = await _async_sqlite_schedule_unique_backstop(db, table_name, quoted_table, db_type) or applied
    return applied


def _metrics_revert_is_blocked(sess, table_name: str, full_table: str) -> bool:
    """True when metrics holds owned rows, which makes dropping user_id lossy.

    Two owners' buckets for a date collapse into duplicate (date, aggregation_period)
    rows the moment the column goes, and the legacy unique key can no longer be put back.
    A NULL counts as owned: the column is NOT NULL, so one means the table was hand-patched.
    """
    owned = sess.execute(text(f"SELECT 1 FROM {full_table} WHERE user_id <> '' OR user_id IS NULL LIMIT 1")).scalar()
    if owned is None:
        return False
    log_warning(
        f"Skipping revert of {table_name}: it holds per-user metric rows, and dropping user_id would "
        "merge them into duplicates for the same date. Consolidate or delete the owned rows first."
    )
    return True


async def _async_metrics_revert_is_blocked(sess, table_name: str, full_table: str) -> bool:
    """Async variant of :func:`_metrics_revert_is_blocked`."""
    result = await sess.execute(text(f"SELECT 1 FROM {full_table} WHERE user_id <> '' OR user_id IS NULL LIMIT 1"))
    if result.scalar() is None:
        return False
    log_warning(
        f"Skipping revert of {table_name}: it holds per-user metric rows, and dropping user_id would "
        "merge them into duplicates for the same date. Consolidate or delete the owned rows first."
    )
    return True


def _drop_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Drop the v3.0 metrics unique key for PostgreSQL.

    The key covers user_id, so it has to go before the column can be dropped; the
    legacy key goes back afterwards (:func:`_restore_postgres_metrics_unique`).
    """
    db_type = type(db).__name__
    declared = _metrics_unique_constraint(db, table_name)
    if declared is None:
        return False

    unique_name = declared[0]
    if not _index_exists(sess, db_schema, table_name, unique_name, db_type):
        return False
    log_info(f"-- Dropping unique constraint {unique_name} from {table_name}")
    # Both ways round, as in the up path: DROP CONSTRAINT does not see a hand-created
    # index of that name, and DROP INDEX is refused on one a constraint owns
    quoted_unique = quote_db_identifier(db_type, unique_name)
    sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT IF EXISTS {quoted_unique}"))
    sess.execute(text(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, db_schema)}.{quoted_unique}"))
    return True


async def _drop_async_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async PostgreSQL variant of :func:`_drop_postgres_metrics_unique`."""
    db_type = type(db).__name__
    declared = _metrics_unique_constraint(db, table_name)
    if declared is None:
        return False

    unique_name = declared[0]
    if not await _async_index_exists(sess, db_schema, table_name, unique_name, db_type):
        return False
    log_info(f"-- Dropping unique constraint {unique_name} from {table_name}")
    # See _drop_postgres_metrics_unique: the name can be either a constraint or a
    # hand-created index, and each is dropped by the statement the other refuses.
    quoted_unique = quote_db_identifier(db_type, unique_name)
    await sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT IF EXISTS {quoted_unique}"))
    await sess.execute(text(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, db_schema)}.{quoted_unique}"))
    return True


def _restore_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Put the metrics unique key back on (date, aggregation_period) for PostgreSQL.

    A table with no unique key at all would break the v2 upsert's ON CONFLICT.
    Safe only because the revert refuses while any row is owned.
    """
    db_type = type(db).__name__
    if _metrics_unique_constraint(db, table_name) is None:
        return False

    legacy_name = f"{table_name}_{METRICS_LEGACY_UNIQUE_NAME}"
    if _index_exists(sess, db_schema, table_name, legacy_name, db_type):
        return False
    log_info(f"-- Restoring legacy unique constraint {legacy_name} on {table_name}")
    sess.execute(
        text(
            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, legacy_name)} "
            f"UNIQUE ({', '.join(METRICS_LEGACY_UNIQUE_COLUMNS)})"
        )
    )
    return True


async def _restore_async_postgres_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async PostgreSQL variant of :func:`_restore_postgres_metrics_unique`."""
    db_type = type(db).__name__
    if _metrics_unique_constraint(db, table_name) is None:
        return False

    legacy_name = f"{table_name}_{METRICS_LEGACY_UNIQUE_NAME}"
    if await _async_index_exists(sess, db_schema, table_name, legacy_name, db_type):
        return False
    log_info(f"-- Restoring legacy unique constraint {legacy_name} on {table_name}")
    await sess.execute(
        text(
            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, legacy_name)} "
            f"UNIQUE ({', '.join(METRICS_LEGACY_UNIQUE_COLUMNS)})"
        )
    )
    return True


def _drop_mysql_like_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """MySQL / SingleStore variant of :func:`_drop_postgres_metrics_unique`."""
    db_type = type(db).__name__
    declared = _metrics_unique_constraint(db, table_name)
    if declared is None:
        return False

    unique_name = declared[0]
    if not _index_exists(sess, db_schema, table_name, unique_name, db_type):
        return False
    log_info(f"-- Dropping unique constraint {unique_name} from {table_name}")
    sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, unique_name)} ON {full_table}"))
    return True


async def _drop_async_mysql_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async MySQL variant of :func:`_drop_mysql_like_metrics_unique`."""
    db_type = type(db).__name__
    declared = _metrics_unique_constraint(db, table_name)
    if declared is None:
        return False

    unique_name = declared[0]
    if not await _async_index_exists(sess, db_schema, table_name, unique_name, db_type):
        return False
    log_info(f"-- Dropping unique constraint {unique_name} from {table_name}")
    await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, unique_name)} ON {full_table}"))
    return True


def _restore_mysql_like_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """MySQL / SingleStore variant of :func:`_restore_postgres_metrics_unique`.

    Restored last, after the column is gone: MySQL commits each ALTER on its own, so a
    failed DROP COLUMN leaves no key rather than one that merges owners.
    """
    db_type = type(db).__name__
    if _metrics_unique_constraint(db, table_name) is None:
        return False

    legacy_name = f"{table_name}_{METRICS_LEGACY_UNIQUE_NAME}"
    if _index_exists(sess, db_schema, table_name, legacy_name, db_type):
        return False
    log_info(f"-- Restoring legacy unique constraint {legacy_name} on {table_name}")
    quoted_columns = ", ".join(quote_db_identifier(db_type, column) for column in METRICS_LEGACY_UNIQUE_COLUMNS)
    sess.execute(
        text(
            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, legacy_name)} "
            f"UNIQUE ({quoted_columns})"
        )
    )
    return True


async def _restore_async_mysql_metrics_unique(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async MySQL variant of :func:`_restore_mysql_like_metrics_unique`."""
    db_type = type(db).__name__
    if _metrics_unique_constraint(db, table_name) is None:
        return False

    legacy_name = f"{table_name}_{METRICS_LEGACY_UNIQUE_NAME}"
    if await _async_index_exists(sess, db_schema, table_name, legacy_name, db_type):
        return False
    log_info(f"-- Restoring legacy unique constraint {legacy_name} on {table_name}")
    quoted_columns = ", ".join(quote_db_identifier(db_type, column) for column in METRICS_LEGACY_UNIQUE_COLUMNS)
    await sess.execute(
        text(
            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, legacy_name)} "
            f"UNIQUE ({quoted_columns})"
        )
    )
    return True


def _drop_postgres_schedule_provenance(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Drop the schedule provenance columns and their lookup indexes for PostgreSQL.

    Each drop is guarded on its own: the forward migration adds a column only when
    the table lacks it, so a table an older build migrated can carry some of them
    and not others. The indexes are dropped by name rather than left to the
    column drop's cascade, so the revert names exactly what the forward
    migration created.
    """
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    applied = False

    for column in SCHEDULE_PROVENANCE_INDEXED:
        index = f"idx_{table_name}_{column}"
        if _index_exists(sess, db_schema, table_name, index, db_type):
            log_info(f"-- Dropping index {index} from {table_name}")
            sess.execute(text(f"DROP INDEX IF EXISTS {quoted_schema}.{quote_db_identifier(db_type, index)}"))
            applied = True

    for column in SCHEDULE_PROVENANCE_COLUMNS:
        if _column_exists(sess, db_schema, table_name, column, db_type):
            log_info(f"-- Dropping {column} column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {column}"))
            applied = True

    return applied


async def _drop_async_postgres_schedule_provenance(sess, db, db_schema: str, table_name: str, full_table: str) -> bool:
    """Async PostgreSQL variant of :func:`_drop_postgres_schedule_provenance`."""
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    applied = False

    for column in SCHEDULE_PROVENANCE_INDEXED:
        index = f"idx_{table_name}_{column}"
        if await _async_index_exists(sess, db_schema, table_name, index, db_type):
            log_info(f"-- Dropping index {index} from {table_name}")
            await sess.execute(text(f"DROP INDEX IF EXISTS {quoted_schema}.{quote_db_identifier(db_type, index)}"))
            applied = True

    for column in SCHEDULE_PROVENANCE_COLUMNS:
        if await _async_column_exists(sess, db_schema, table_name, column, db_type):
            log_info(f"-- Dropping {column} column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {column}"))
            applied = True

    return applied


def _revert_postgres_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        is_metrics = table_type == "metrics"
        column_exists = _column_exists(sess, db_schema, table_name, "user_id", db_type)
        if is_metrics and column_exists and _metrics_revert_is_blocked(sess, table_name, full_table):
            return False

        applied = False

        if is_metrics and _drop_postgres_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        if _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        if column_exists:
            log_info(f"-- Dropping user_id column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN user_id"))
            applied = True

        if table_type == "schedules" and _drop_postgres_schedule_provenance(
            sess, db, db_schema, table_name, full_table
        ):
            applied = True

        if is_metrics and _restore_postgres_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        return applied


async def _revert_async_postgres_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async PostgreSQL variant of :func:`_revert_postgres_user_id`."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        is_metrics = table_type == "metrics"
        column_exists = await _async_column_exists(sess, db_schema, table_name, "user_id", db_type)
        if is_metrics and column_exists and await _async_metrics_revert_is_blocked(sess, table_name, full_table):
            return False

        applied = False

        if is_metrics and await _drop_async_postgres_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        if await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        if column_exists:
            log_info(f"-- Dropping user_id column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN user_id"))
            applied = True

        if table_type == "schedules" and await _drop_async_postgres_schedule_provenance(
            sess, db, db_schema, table_name, full_table
        ):
            applied = True

        if is_metrics and await _restore_async_postgres_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        return applied


def _revert_mysql_like_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for MySQL or SingleStore."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        is_metrics = table_type == "metrics"
        column_exists = _column_exists(sess, db_schema, table_name, "user_id", db_type)
        if is_metrics and column_exists and _metrics_revert_is_blocked(sess, table_name, full_table):
            return False

        applied = False

        dropped_unique = is_metrics and _drop_mysql_like_metrics_unique(sess, db, db_schema, table_name, full_table)
        if dropped_unique:
            applied = True

        dropped_index = False
        if _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            dropped_index = True
            applied = True

        if column_exists:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `user_id`"))
            except Exception:
                # MySQL and SingleStore commit DDL immediately, so the drops above stuck.
                # Put them back rather than leave two owners' buckets with nothing apart.
                if dropped_index:
                    sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                    )
                if dropped_unique:
                    _swap_mysql_like_metrics_unique(sess, db, db_schema, table_name, full_table)
                raise
            applied = True

        # The legacy key only goes back once user_id is gone: it cannot hold while two
        # owners still have a row for the same date
        if is_metrics and _restore_mysql_like_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        return applied


async def _revert_async_mysql_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async MySQL variant of :func:`_revert_mysql_like_user_id`."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        is_metrics = table_type == "metrics"
        column_exists = await _async_column_exists(sess, db_schema, table_name, "user_id", db_type)
        if is_metrics and column_exists and await _async_metrics_revert_is_blocked(sess, table_name, full_table):
            return False

        applied = False

        dropped_unique = is_metrics and await _drop_async_mysql_metrics_unique(
            sess, db, db_schema, table_name, full_table
        )
        if dropped_unique:
            applied = True

        dropped_index = False
        if await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            dropped_index = True
            applied = True

        if column_exists:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `user_id`"))
            except Exception:
                # MySQL commits DDL immediately, so the drops above already stuck.
                # Put them back rather than leave two owners' buckets with nothing apart.
                if dropped_index:
                    await sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                    )
                if dropped_unique:
                    await _swap_async_mysql_metrics_unique(sess, db, db_schema, table_name, full_table)
                raise
            applied = True

        # See _revert_mysql_like_user_id: the legacy key only goes back once
        # user_id is gone
        if is_metrics and await _restore_async_mysql_metrics_unique(sess, db, db_schema, table_name, full_table):
            applied = True

        return applied


def _revert_sqlite_metrics_table(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Rebuild the metrics table back to its pre-v3.0 shape, for SQLite.

    SQLite cannot drop the v3.0 key or a column it covers, so the only way back is
    another rebuild. Indexes covering user_id are not replayed.
    """
    if table_type != "metrics":
        return False

    declared = _metrics_unique_constraint(db, table_name)
    ddl = _sqlite_metrics_ddl(db, table_name, with_user_id=False)
    if declared is None or ddl is None:
        return False
    unique_columns = declared[1]
    legacy_ddl, legacy_index_sqls = ddl

    db_type = type(db).__name__
    backup_name = f"{table_name}_pre_v3_0_0"
    quoted_table = quote_db_identifier(db_type, table_name)
    quoted_backup = quote_db_identifier(db_type, backup_name)

    with db.Session() as sess:  # type: ignore
        if not _sqlite_table_exists(sess, table_name):
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if not _sqlite_has_unique_on(sess, quoted_table, unique_columns):
            return False
        if _metrics_revert_is_blocked(sess, table_name, quoted_table):
            return False

        table_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        # See _migrate_sqlite_metrics_table: the rebuild recreates the table from the schema,
        # so a column the schema does not declare would go with the one being replaced
        if not _is_metrics_shaped(db, [col[1] for col in table_info]):
            log_warning(f"Table {table_name} keeps its v3.0 shape until those columns are moved off it")
            return False
        index_rows = sess.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"),
            {"t": table_name},
        ).fetchall()
        kept_indexes = [row for row in index_rows if "user_id" not in _sqlite_index_columns(sess, row[0])]

    _, extra_indexes = _sqlite_metrics_rebuild_plan(db, table_name, table_info, kept_indexes)
    carried = [col[1] for col in table_info if col[1] != "user_id"]
    carried_sql = ", ".join(quote_db_identifier(db_type, col) for col in carried)

    log_info(f"-- Rebuilding {table_name} back to its pre-v3.0.0 unique key")
    with _sqlite_ddl_transaction(db) as conn:
        conn.exec_driver_sql(f"ALTER TABLE {quoted_table} RENAME TO {quoted_backup}")
        for index_row in index_rows:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, index_row[0])}")

        conn.exec_driver_sql(legacy_ddl)
        for statement in legacy_index_sqls + extra_indexes:
            conn.exec_driver_sql(statement)

        conn.exec_driver_sql(f"INSERT INTO {quoted_table} ({carried_sql}) SELECT {carried_sql} FROM {quoted_backup}")
        conn.exec_driver_sql(f"DROP TABLE {quoted_backup}")

    _forget_metrics_table(db, table_name)
    return True


async def _revert_async_sqlite_metrics_table(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_revert_sqlite_metrics_table`."""
    if table_type != "metrics":
        return False

    declared = _metrics_unique_constraint(db, table_name)
    ddl = _sqlite_metrics_ddl(db, table_name, with_user_id=False)
    if declared is None or ddl is None:
        return False
    unique_columns = declared[1]
    legacy_ddl, legacy_index_sqls = ddl

    db_type = type(db).__name__
    backup_name = f"{table_name}_pre_v3_0_0"
    quoted_table = quote_db_identifier(db_type, table_name)
    quoted_backup = quote_db_identifier(db_type, backup_name)

    async with db.async_session_factory() as sess:  # type: ignore
        if not await _async_sqlite_table_exists(sess, table_name):
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False
        if not await _async_sqlite_has_unique_on(sess, quoted_table, unique_columns):
            return False
        if await _async_metrics_revert_is_blocked(sess, table_name, quoted_table):
            return False

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        table_info = result.fetchall()
        # See _migrate_sqlite_metrics_table: the rebuild recreates the table from the schema,
        # so a column the schema does not declare would go with the one being replaced
        if not _is_metrics_shaped(db, [col[1] for col in table_info]):
            log_warning(f"Table {table_name} keeps its v3.0 shape until those columns are moved off it")
            return False
        result = await sess.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"),
            {"t": table_name},
        )
        index_rows = result.fetchall()
        kept_indexes = [row for row in index_rows if "user_id" not in await _async_sqlite_index_columns(sess, row[0])]

    _, extra_indexes = _sqlite_metrics_rebuild_plan(db, table_name, table_info, kept_indexes)
    carried = [col[1] for col in table_info if col[1] != "user_id"]
    carried_sql = ", ".join(quote_db_identifier(db_type, col) for col in carried)

    log_info(f"-- Rebuilding {table_name} back to its pre-v3.0.0 unique key")
    async with _async_sqlite_ddl_transaction(db) as conn:
        statements = [f"ALTER TABLE {quoted_table} RENAME TO {quoted_backup}"]
        statements += [f"DROP INDEX IF EXISTS {quote_db_identifier(db_type, row[0])}" for row in index_rows]
        statements.append(legacy_ddl)
        statements += legacy_index_sqls + extra_indexes
        statements.append(f"INSERT INTO {quoted_table} ({carried_sql}) SELECT {carried_sql} FROM {quoted_backup}")
        statements.append(f"DROP TABLE {quoted_backup}")
        for statement in statements:
            await conn.exec_driver_sql(statement)

    _forget_metrics_table(db, table_name)
    return True


def _drop_sqlite_schedule_provenance(sess, table_name: str, quoted_table: str, db_type: str) -> bool:
    """Drop the schedule provenance columns and their lookup indexes for SQLite.

    The indexes go first: SQLite refuses DROP COLUMN while an index still covers
    the column. Each drop is guarded on its own, because the forward migration
    adds a column only when the table lacks it, so a table an older build
    migrated can carry some of them and not others.
    """
    applied = False

    indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
    existing_indexes = {idx[1] for idx in indexes}
    for column in SCHEDULE_PROVENANCE_INDEXED:
        index = f"idx_{table_name}_{column}"
        if index in existing_indexes:
            log_info(f"-- Dropping index {index} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index)}"))
            applied = True

    columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
    existing_columns = {col[1] for col in columns_info}
    for column in SCHEDULE_PROVENANCE_COLUMNS:
        if column in existing_columns:
            log_info(f"-- Dropping {column} column from {table_name}")
            sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN {column}"))
            applied = True

    return applied


async def _drop_async_sqlite_schedule_provenance(sess, table_name: str, quoted_table: str, db_type: str) -> bool:
    """Async SQLite variant of :func:`_drop_sqlite_schedule_provenance`."""
    applied = False

    result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
    existing_indexes = {idx[1] for idx in result.fetchall()}
    for column in SCHEDULE_PROVENANCE_INDEXED:
        index = f"idx_{table_name}_{column}"
        if index in existing_indexes:
            log_info(f"-- Dropping index {index} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index)}"))
            applied = True

    result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
    existing_columns = {col[1] for col in result.fetchall()}
    for column in SCHEDULE_PROVENANCE_COLUMNS:
        if column in existing_columns:
            log_info(f"-- Dropping {column} column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN {column}"))
            applied = True

    return applied


def _revert_sqlite_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for SQLite."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        import sqlite3

        # DROP COLUMN needs SQLite 3.35.0. Skip early, or the index drop lands and the column drop fails.
        if sqlite3.sqlite_version_info < (3, 35, 0):
            log_info(f"SQLite revert for {table_name}: DROP COLUMN needs SQLite >= 3.35.0, skipping")
            return False

        applied = False

        dropped_index = False
        indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
        existing_indexes = {idx[1] for idx in indexes}
        # Composite indexes must go first: SQLite won't drop a column an index still covers.
        for comp_name, _comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            if comp_name in existing_indexes:
                log_info(f"-- Dropping index {comp_name} from {table_name}")
                sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, comp_name)}"))
                applied = True
        # The unique name backstops also cover user_id (v3-only; v2 had no DB-level uniqueness).
        if table_type == "schedules":
            for uq_name in (f"{table_name}_uq_user_name", f"{table_name}_uq_unowned_name"):
                if uq_name in existing_indexes:
                    log_info(f"-- Dropping unique index {uq_name} from {table_name}")
                    sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, uq_name)}"))
                    applied = True
        if index_name in existing_indexes:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)}"))
            dropped_index = True
            applied = True

        columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        if "user_id" in {col[1] for col in columns_info}:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN user_id"))
            except Exception:
                # SQLite commits DDL outside the session, so the index drop above stuck.
                if dropped_index:
                    sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
                    )
                raise
            applied = True

        if table_type == "schedules" and _drop_sqlite_schedule_provenance(sess, table_name, quoted_table, db_type):
            applied = True

        return applied


async def _revert_async_sqlite_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_revert_sqlite_user_id`."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        import sqlite3

        # DROP COLUMN needs SQLite 3.35.0. Skip early, or the index drop lands and the column drop fails.
        if sqlite3.sqlite_version_info < (3, 35, 0):
            log_info(f"SQLite revert for {table_name}: DROP COLUMN needs SQLite >= 3.35.0, skipping")
            return False

        applied = False

        result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
        existing_indexes = {idx[1] for idx in result.fetchall()}
        dropped_index = False
        # Composite indexes must go first: SQLite won't drop a column an index still covers.
        for comp_name, _comp_cols in _user_id_composite_indexes(db, table_type, table_name):
            if comp_name in existing_indexes:
                log_info(f"-- Dropping index {comp_name} from {table_name}")
                await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, comp_name)}"))
                applied = True
        # The unique name backstops also cover user_id (v3-only; v2 had no DB-level uniqueness).
        if table_type == "schedules":
            for uq_name in (f"{table_name}_uq_user_name", f"{table_name}_uq_unowned_name"):
                if uq_name in existing_indexes:
                    log_info(f"-- Dropping unique index {uq_name} from {table_name}")
                    await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, uq_name)}"))
                    applied = True
        if index_name in existing_indexes:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)}"))
            dropped_index = True
            applied = True

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        if "user_id" in {col[1] for col in result.fetchall()}:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                await sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN user_id"))
            except Exception:
                # SQLite commits DDL outside the session, so the index drop above stuck.
                if dropped_index:
                    await sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
                    )
                raise
            applied = True

        if table_type == "schedules" and await _drop_async_sqlite_schedule_provenance(
            sess, table_name, quoted_table, db_type
        ):
            applied = True

        return applied
