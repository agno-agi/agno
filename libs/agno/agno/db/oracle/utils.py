"""Utility functions shared by the Oracle database and vector database adapters.

Four groups, in order: owner-id translation (empty string vs. null), identifier
length handling, unique-violation detection, and upsert via MERGE with retry.
"""

import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from sqlalchemy import Table, bindparam, case, func
from sqlalchemy.dialects import oracle as oracle_dialect_module
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from sqlalchemy.sql.elements import ColumnElement

from agno.utils.log import log_error, log_warning

# A dialect instance purely for identifier quoting decisions (reserved-word
# lookup and quote-or-not), never for a live connection. Module-level:
# quoting rules are static, not connection-specific.
_ORACLE_IDENTIFIER_PREPARER = oracle_dialect_module.dialect().identifier_preparer


def quote_column(table: Table, column: str) -> str:
    """The correct SQL reference for ``column`` on ``table`` -- quoted only
    when Oracle requires it (a reserved word, most commonly), matching
    exactly what the table's own DDL compiler already did when the table was
    created.

    Blanket-uppercasing every column reference is not a safe substitute:
    SQLAlchemy's Oracle DDL compiler quotes a reserved-word column name
    automatically, preserving its original (typically lowercase) spelling,
    while every other column is left unquoted and thus folded to uppercase by
    Oracle itself. A column named ``date`` -- the metrics table has one --
    is therefore stored as literally lowercase ``date``, not ``DATE``; a
    reference using either bare case or a forced-uppercase quoted form both
    raise ORA-00904, confirmed against a live server.
    """
    return _ORACLE_IDENTIFIER_PREPARER.format_column(table.c[column])


# -- Owner-id (user_id) translation --
#
# Oracle treats the empty string as NULL. Agno uses three distinct states for
# an owner field: None (every owner, an unfiltered read), "" (the unowned
# bucket -- rows nobody owns but everyone can see), and a name (that owner's
# rows). Stored unmitigated on Oracle, "" would become NULL and collide with
# the "every owner" meaning of a None filter -- a query for "unowned rows"
# would silently also match "no filter at all".
#
# The sentinel below is what "" becomes at rest. It must be applied at every
# adapter boundary that reads or writes an owner field, in both storage and
# the vector database, sync and async: a single path that forgets the
# translation leaks rows across an owner boundary with no exception raised.
# This value must never change once data exists under it without a migration.
UNOWNED_USER_ID = "__agno_unowned__"


def to_db_user_id(user_id: Optional[str]) -> Optional[str]:
    """Translate an agno owner value to what is stored on Oracle.

    None stays None (the "every owner" / unfiltered case). "" becomes the
    sentinel, so it survives Oracle's empty-string-is-null folding and stays
    distinct from None. Any other value is stored unchanged.
    """
    if user_id is None:
        return None
    if user_id == "":
        return UNOWNED_USER_ID
    return user_id


def from_db_user_id(user_id: Optional[str]) -> Optional[str]:
    """Translate a value read from Oracle back to agno owner semantics.

    Inverse of ``to_db_user_id``. A row read outside agno's adapters (a direct
    SQL client, a BI tool) sees the sentinel string rather than an empty
    string -- this is a documented, deliberate consequence of the mitigation.
    """
    if user_id is None:
        return None
    if user_id == UNOWNED_USER_ID:
        return ""
    return user_id


# -- Identifier length handling --
#
# Oracle identifiers (table, column, constraint and index names) are limited
# to 128 bytes since 12.2. Agno's default table names fit comfortably, but
# names this module or the schema layer generates by concatenation --
# {table_name}_{constraint_name}, composite index names built from several
# column names -- can exceed that limit on a long table name or a wide
# composite key.
MAX_IDENTIFIER_LENGTH = 128


def truncate_identifier(name: str, max_length: int = MAX_IDENTIFIER_LENGTH) -> str:
    """Keep a generated Oracle identifier within ``max_length`` bytes.

    Returns ``name`` unchanged when it already fits. Otherwise truncates it
    and appends a short deterministic hash of the full original name, so that
    two different long names sharing a common prefix cannot collide after
    truncation the way a bare truncation would.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_length:
        return name

    digest = hashlib.sha1(encoded).hexdigest()[:8]
    budget = max_length - len(digest) - 1  # -1 for the separator
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    return f"{truncated}_{digest}"


def apply_sorting(stmt: Any, table: Table, sort_by: Optional[str] = None, sort_order: Optional[str] = None) -> Any:
    """Apply ORDER BY to a SELECT statement. Identical to the Postgres helper
    of the same name -- nothing here is dialect-specific.

    For ``updated_at``, falls back to ``created_at`` via COALESCE so pre-3.0
    records with a null ``updated_at`` still sort by their creation time.
    """
    if sort_by is None:
        return stmt
    if not hasattr(table.c, sort_by):
        return stmt

    if sort_by == "updated_at" and hasattr(table.c, "created_at"):
        sort_column = func.coalesce(table.c.updated_at, table.c.created_at)
    else:
        sort_column = getattr(table.c, sort_by)

    if sort_order == "asc":
        return stmt.order_by(sort_column.asc())
    return stmt.order_by(sort_column.desc())


# -- Table existence and validity --
#
# Both queries stay within the connecting user's default privileges: USER_TABLES
# (no db_schema given -- the connecting user's own schema, per ADR: db_schema
# defaults to None on Oracle, meaning "my schema") requires no grant at all,
# and ALL_TABLES (an explicit db_schema) shows every table the connecting user
# has been granted visibility into, again without an elevated privilege. Both
# are cheap dictionary views, unlike the V$ performance views used for version
# detection.
def is_table_available(session: Session, table_name: str, db_schema: Optional[str] = None) -> bool:
    """Whether a table named ``table_name`` exists in ``db_schema`` (the
    connecting user's own schema when ``db_schema`` is None).

    Table names are compared case-insensitively via UPPER(): Oracle folds an
    unquoted identifier to uppercase at creation, and agno always creates
    tables unquoted, so this matches what is actually stored regardless of
    the case the caller wrote the Python-side name in.
    """
    try:
        if db_schema is None:
            query = text("SELECT 1 FROM user_tables WHERE table_name = UPPER(:table_name)")
            params: Dict[str, Any] = {"table_name": table_name}
        else:
            query = text("SELECT 1 FROM all_tables WHERE owner = UPPER(:db_schema) AND table_name = UPPER(:table_name)")
            params = {"db_schema": db_schema, "table_name": table_name}
        return session.execute(query, params).first() is not None
    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


def is_valid_table(
    db_engine: Engine,
    table_name: str,
    expected_columns: Any,
    db_schema: Optional[str] = None,
) -> bool:
    """Whether an existing table has (at least) the expected column names.

    ``expected_columns`` is an iterable of column names -- callers pass the
    keys of a schema definition dict, filtered of the leading-underscore
    special keys. Only names are compared, never types: the schema variant
    (JSON storage, boolean representation) legitimately differs between a
    table created on an older server and one created on a newer one, and
    that divergence is exactly what reflection-wins-over-version-detection
    (see ``_version.py``) is for, not something this check should flag.

    Raises whatever the inspection itself raises, so a failed inspection is
    never read as "the table doesn't match" -- a database outage during
    validation must surface as an outage, not as a stale-schema false
    positive.
    """
    try:
        expected = {name for name in expected_columns if not str(name).startswith("_")}
        inspector = inspect(db_engine)
        existing_columns_info = inspector.get_columns(table_name, schema=db_schema)
        existing = {col["name"] for col in existing_columns_info}

        missing = expected - existing
        if missing:
            log_warning(
                f"Missing columns {missing} in table {db_schema}.{table_name}"
                if db_schema
                else f"Missing columns {missing} in table {table_name}"
            )
            return False
        return True
    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {str(e)}")
        raise


# -- Partial uniqueness via function-based indexes --
#
# Oracle has no partial (predicate-qualified) index. The standard idiom is a
# unique index over a CASE expression that folds every non-matching row to
# NULL in every indexed column: Oracle's B-tree index does not store an entry
# whose indexed columns are ALL null, so those rows are invisible to the
# unique check -- exactly the effect a partial index's WHERE clause has on
# Postgres. This has no precedent elsewhere in the repository.
#
# ``where_sql`` is the same predicate text a Postgres partial index already
# carries in each table's ``_partial_unique_indexes`` entry (plain IS NULL /
# IS NOT NULL / AND expressions -- no Postgres-specific syntax), reused
# as-is: it becomes the CASE WHEN condition for every column in the index.
def partial_unique_index_elements(table: Table, columns: Sequence[str], where_sql: str) -> List[ColumnElement]:
    """Build the CASE-wrapped column expressions for a function-based unique
    index emulating a partial unique index with predicate ``where_sql``.

    Every returned expression evaluates to NULL together on a row that does
    not satisfy ``where_sql``, so such rows are fully-null in the index and
    excluded from the uniqueness check; a row that does satisfy it indexes
    its real column values, and duplicates among those are rejected exactly
    as they would be by a Postgres partial unique index with the same WHERE.
    """
    condition = text(where_sql)
    return [case((condition, table.c[column]), else_=None) for column in columns]


# -- Unique-violation detection --
#
# ORA-00001: unique constraint violated. Detected by Oracle error code, never
# by message text: the message is rendered in the database's NLS_LANGUAGE and
# a text match silently stops working the moment a deployment's language
# setting differs from whatever language the code was written against.
ORA_UNIQUE_CONSTRAINT_VIOLATED = 1


def is_unique_violation(error: BaseException) -> bool:
    """Whether ``error`` is (or wraps) an ORA-00001 unique-constraint violation.

    SQLAlchemy wraps the driver exception in its own error type; the
    driver-level python-oracledb error, exposing ``.code``, lives on
    ``error.args[0]`` for the immediate driver error and on ``error.orig`` for
    a SQLAlchemy-wrapped one. Both are checked, recursively, so this works
    whether ``error`` is the raw driver exception or the wrapped one.
    """
    for arg in getattr(error, "args", ()):
        if getattr(arg, "code", None) == ORA_UNIQUE_CONSTRAINT_VIOLATED:
            return True
    orig = getattr(error, "orig", None)
    if orig is not None and orig is not error:
        return is_unique_violation(orig)
    return False


# ORA-00955: name is already used by an existing object. Raised when two
# concurrent CREATE TABLE (or CREATE INDEX) statements race for the same
# name; the loser sees this rather than a unique-constraint violation, since
# the collision is on the data dictionary, not a table's own constraint.
ORA_NAME_ALREADY_USED = 955


def is_duplicate_object(error: BaseException) -> bool:
    """Whether ``error`` is (or wraps) an ORA-00955 duplicate-name error.

    Mirrors ``is_unique_violation``'s traversal; see its docstring.
    """
    for arg in getattr(error, "args", ()):
        if getattr(arg, "code", None) == ORA_NAME_ALREADY_USED:
            return True
    orig = getattr(error, "orig", None)
    if orig is not None and orig is not error:
        return is_duplicate_object(orig)
    return False


# -- Upsert via MERGE, with retry on ORA-00001 --
#
# Oracle has no INSERT ... ON CONFLICT clause. The idiom is a MERGE statement:
# match on the key columns, UPDATE the rest when matched, INSERT the full row
# when not. SQLAlchemy Core has no fluent construction for Oracle MERGE (only
# Postgres/SQLite/MySQL expose an on-conflict insert), so the statement is
# built as text and executed with bound parameters -- values are always
# passed as bind parameters, never interpolated into the SQL string, so this
# carries no more injection risk than any other parameterized statement.
#
# MERGE is not immune to a concurrent race: two sessions MERGE-ing the same
# not-yet-existing key can both evaluate NOT MATCHED and both attempt the
# INSERT, and the loser sees ORA-00001 even though it went through MERGE, not
# a bare INSERT. The retry below re-issues the same MERGE; on retry the
# winner's row is now visible, so the statement takes the UPDATE branch.
DEFAULT_MERGE_RETRY_ATTEMPTS = 3


def _qualified_table_name(table: Table) -> str:
    return table.fullname if table.schema else table.name


def build_merge_statement(
    table: Table,
    key_columns: Sequence[str],
    value_columns: Sequence[str],
    preserve_on_conflict: Sequence[str] = (),
):
    """Build a MERGE INTO statement upserting ``table`` on ``key_columns``.

    ``value_columns`` is every bind-parameter column the statement accepts,
    key columns included; columns in ``key_columns`` are matched but never
    reassigned by the UPDATE branch, since a key never changes on upsert (this
    mirrors the Postgres helper excluding ``user_id`` and other key columns
    from ``on_conflict_do_update``'s SET clause).

    ``preserve_on_conflict`` names columns that are written on a fresh INSERT
    but left untouched on an UPDATE -- for example ``created_at``, which a
    second upsert of the same row must not overwrite. Equivalent to a Postgres
    ``on_conflict_do_update`` simply omitting that column from ``set_=``.

    Returns a SQLAlchemy ``TextClause`` with named bind parameters matching
    ``value_columns``, each explicitly typed via ``bindparams(type_=...)``
    from the corresponding column on ``table``. This is not optional: a bare
    ``text()`` bind parameter carries no type, so a column's own
    ``process_bind_param`` -- which is where ``OracleNativeJSON`` and
    ``OracleClobJSON`` serialize a Python dict to text -- never runs, and the
    raw dict reaches the driver, which cannot bind it
    (``DPY-3002: Python value of type "dict" is not supported``), confirmed
    against a live server. Execute the returned statement with a dict of
    ``value_columns`` names to values.

    Every column *reference* (not the bind parameter names, which follow
    their own, separate naming rules) goes through ``quote_column``, which
    defers to SQLAlchemy's own Oracle identifier preparer rather than
    guessing. This matters because a blanket transform is not safe: the
    metrics table's ``date`` column collides with the DATE type name, and
    SQLAlchemy's DDL compiler already quotes such reserved-word columns at
    creation time, preserving their original (lowercase) spelling, while
    every other column is left unquoted and folded to uppercase by Oracle
    itself. An unquoted reference to ``date`` here raises ORA-00923 ("FROM
    keyword not found"); a forced-uppercase quoted one raises ORA-00904
    ("invalid identifier", since the stored name really is lowercase) --
    both confirmed against a live server. ``quote_column`` produces whatever
    the table's own DDL already committed to, for every column.
    """
    key_set = set(key_columns)
    preserve_set = set(preserve_on_conflict)
    update_columns = [c for c in value_columns if c not in key_set and c not in preserve_set]

    def q(col: str) -> str:
        return quote_column(table, col)

    on_clause = " AND ".join(f"t.{q(c)} = s.{q(c)}" for c in key_columns)
    using_select = ", ".join(f":{c} AS {q(c)}" for c in value_columns)
    insert_columns = ", ".join(q(c) for c in value_columns)
    insert_values = ", ".join(f"s.{q(c)}" for c in value_columns)

    merge_sql = (
        f"MERGE INTO {_qualified_table_name(table)} t USING (SELECT {using_select} FROM dual) s ON ({on_clause})"
    )
    if update_columns:
        update_set = ", ".join(f"t.{q(c)} = s.{q(c)}" for c in update_columns)
        merge_sql += f" WHEN MATCHED THEN UPDATE SET {update_set}"
    merge_sql += f" WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})"

    typed_params = [bindparam(c, type_=table.c[c].type) for c in value_columns]
    return text(merge_sql).bindparams(*typed_params)


def merge_upsert(
    connection: "Session | Connection",
    table: Table,
    key_columns: Sequence[str],
    values: Dict[str, Any],
    max_attempts: int = DEFAULT_MERGE_RETRY_ATTEMPTS,
    preserve_on_conflict: Sequence[str] = (),
) -> None:
    """Execute a MERGE-based upsert of ``values`` into ``table``, keyed on
    ``key_columns``, retrying on a concurrent ORA-00001 (see module docstring).

    ``connection`` is anything exposing ``.execute()`` with the same signature
    -- an ORM ``Session`` or a Core ``Connection`` both work. Does not commit;
    the caller controls the transaction.
    """
    stmt = build_merge_statement(table, key_columns, list(values.keys()), preserve_on_conflict=preserve_on_conflict)
    attempt = 0
    while True:
        attempt += 1
        try:
            connection.execute(stmt, values)
            return
        except Exception as e:
            if is_unique_violation(e) and attempt < max_attempts:
                continue
            raise


def merge_upsert_many(
    connection: "Session | Connection",
    table: Table,
    key_columns: Sequence[str],
    records: Sequence[Dict[str, Any]],
    max_attempts: int = DEFAULT_MERGE_RETRY_ATTEMPTS,
    preserve_on_conflict: Sequence[str] = (),
) -> None:
    """Batch variant of ``merge_upsert``: one MERGE statement, many parameter sets.

    All records must share the same set of keys. Retries the whole batch on a
    concurrent ORA-00001, same as the single-record case.
    """
    if not records:
        return
    stmt = build_merge_statement(table, key_columns, list(records[0].keys()), preserve_on_conflict=preserve_on_conflict)
    attempt = 0
    while True:
        attempt += 1
        try:
            connection.execute(stmt, records)
            return
        except Exception as e:
            if is_unique_violation(e) and attempt < max_attempts:
                continue
            raise


# -- Metrics calculation --
#
# Not shared cross-backend code despite being identical logic everywhere:
# every SQL and NoSQL adapter in the repository (Postgres, MySQL, SQLite,
# Mongo, Redis, Valkey, Firestore, DynamoDB, ...) keeps its own copy of these
# three functions in its own utils.py, rather than one shared implementation
# -- an established repository convention, not an Oracle-specific choice.
# Copied verbatim from postgres/utils.py: pure Python over already-decoded
# session/run dicts, nothing dialect-specific.
def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[Dict[str, Any]]:
    """Calculate metrics for the given single date, bucketed per user.

    Args:
        date_to_process: The date to calculate metrics for.
        sessions_data: The sessions data to calculate metrics for.

    Returns:
        One record per user. Sessions without a ``user_id`` are bucketed
        under ``""``.
    """

    def _empty_metric_record() -> Dict[str, Any]:
        return {
            "users_count": 0,
            "agent_sessions_count": 0,
            "team_sessions_count": 0,
            "workflow_sessions_count": 0,
            "agent_runs_count": 0,
            "team_runs_count": 0,
            "workflow_runs_count": 0,
            "token_metrics": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "audio_total_tokens": 0,
                "audio_input_tokens": 0,
                "audio_output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
            },
            "model_counts": {},
        }

    session_types = [
        ("agent", "agent_sessions_count", "agent_runs_count"),
        ("team", "team_sessions_count", "team_runs_count"),
        ("workflow", "workflow_sessions_count", "workflow_runs_count"),
    ]

    per_user: Dict[str, Dict[str, Any]] = {}

    for session_type, sessions_count_key, runs_count_key in session_types:
        sessions = sessions_data.get(session_type, []) or []

        for session in sessions:
            bucket_key = session.get("user_id") or ""
            bucket = per_user.setdefault(bucket_key, _empty_metric_record())
            bucket[sessions_count_key] += 1

            runs = session.get("runs", []) or []
            bucket[runs_count_key] += len(runs)
            for run in runs:
                if model_id := run.get("model"):
                    model_provider = run.get("model_provider", "")
                    key = f"{model_id}:{model_provider}"
                    bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            session_data = session.get("session_data", {}) or {}
            session_metrics = session_data.get("session_metrics", {}) or {}
            for field in bucket["token_metrics"]:
                bucket["token_metrics"][field] += session_metrics.get(field, 0)

    current_time = int(time.time())
    completed = date_to_process < datetime.now(timezone.utc).date()

    records: List[Dict[str, Any]] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        # One distinct user per bucket, and none for the unowned one, so summed counts stay correct.
        users_count = 0 if user_id == "" else 1

        records.append(
            {
                "id": str(uuid4()),
                "date": date_to_process,
                "completed": completed,
                "token_metrics": bucket["token_metrics"],
                "model_metrics": model_metrics,
                "created_at": current_time,
                "updated_at": current_time,
                "aggregation_period": "daily",
                "user_id": user_id,
                "users_count": users_count,
                "agent_sessions_count": bucket["agent_sessions_count"],
                "team_sessions_count": bucket["team_sessions_count"],
                "workflow_sessions_count": bucket["workflow_sessions_count"],
                "agent_runs_count": bucket["agent_runs_count"],
                "team_runs_count": bucket["team_runs_count"],
                "workflow_runs_count": bucket["workflow_runs_count"],
            }
        )

    return records


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: List[date], start_timestamp: int
) -> Optional[Dict[str, Any]]:
    """Return all session data for the given dates, for all session types.

    Returns a dict keyed by ISO date, each value ``{"agent": [...], "team":
    [...], "workflow": [...]}``.
    """
    if not dates_to_process:
        return None

    all_sessions_data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        date_to_process.isoformat(): {"agent": [], "team": [], "workflow": []} for date_to_process in dates_to_process
    }

    for session in sessions:
        session_date = (
            datetime.fromtimestamp(session.get("created_at", start_timestamp), tz=timezone.utc).date().isoformat()
        )
        if session_date in all_sessions_data:
            all_sessions_data[session_date][session["session_type"]].append(session)

    return all_sessions_data


def get_dates_to_calculate_metrics_for(starting_date: date) -> List[date]:
    """The list of dates to calculate metrics for, from ``starting_date`` through today."""
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]
