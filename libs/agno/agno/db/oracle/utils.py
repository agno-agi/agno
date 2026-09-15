"""Utility functions shared by the Oracle database and vector database adapters.

Four groups, in order: owner-id translation (empty string vs. null), identifier
length handling, unique-violation detection, and upsert via MERGE with retry.
"""

import hashlib
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import Table, bindparam, case, func
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from sqlalchemy.sql.elements import ColumnElement

from agno.utils.log import log_error, log_warning

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


def build_merge_statement(table: Table, key_columns: Sequence[str], value_columns: Sequence[str]):
    """Build a MERGE INTO statement upserting ``table`` on ``key_columns``.

    ``value_columns`` is every bind-parameter column the statement accepts,
    key columns included; columns in ``key_columns`` are matched but never
    reassigned by the UPDATE branch, since a key never changes on upsert (this
    mirrors the Postgres helper excluding ``user_id`` and other key columns
    from ``on_conflict_do_update``'s SET clause).

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
    """
    key_set = set(key_columns)
    update_columns = [c for c in value_columns if c not in key_set]

    on_clause = " AND ".join(f"t.{c} = s.{c}" for c in key_columns)
    using_select = ", ".join(f":{c} AS {c}" for c in value_columns)
    insert_columns = ", ".join(value_columns)
    insert_values = ", ".join(f"s.{c}" for c in value_columns)

    merge_sql = (
        f"MERGE INTO {_qualified_table_name(table)} t USING (SELECT {using_select} FROM dual) s ON ({on_clause})"
    )
    if update_columns:
        update_set = ", ".join(f"t.{c} = s.{c}" for c in update_columns)
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
) -> None:
    """Execute a MERGE-based upsert of ``values`` into ``table``, keyed on
    ``key_columns``, retrying on a concurrent ORA-00001 (see module docstring).

    ``connection`` is anything exposing ``.execute()`` with the same signature
    -- an ORM ``Session`` or a Core ``Connection`` both work. Does not commit;
    the caller controls the transaction.
    """
    stmt = build_merge_statement(table, key_columns, list(values.keys()))
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
) -> None:
    """Batch variant of ``merge_upsert``: one MERGE statement, many parameter sets.

    All records must share the same set of keys. Retries the whole batch on a
    concurrent ORA-00001, same as the single-record case.
    """
    if not records:
        return
    stmt = build_merge_statement(table, key_columns, list(records[0].keys()))
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
