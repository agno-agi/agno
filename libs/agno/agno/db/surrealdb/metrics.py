from datetime import date, datetime, timezone
from textwrap import dedent
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.models import desurrealize_session, surrealize_dates
from agno.db.surrealdb.queries import order_limit_start
from agno.db.utils import (
    COMPONENT_METRICS_KEY_COLUMNS,
    METRICS_BATCH_SIZE,
    METRICS_COMPONENT_TYPES,
    METRICS_COST_FIELDS,
    METRICS_REFRESH_ID,
    METRICS_TOKEN_DETAILS_FIELDS,
    USER_METRICS_KEY_COLUMNS,
    build_user_metrics_row,
)

# The columns of the row of the metrics refreshes table. SurrealDB keeps no field set to NONE
_METRICS_REFRESH_COLUMNS = ("locked_by", "locked_at", "started_at", "finished_at", "status", "error", "fingerprint")

# The keys of a stored run that hold the runs nested inside it
_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# A run nested deeper than this is read whole
_METRICS_NESTED_RUNS_DEPTH = 6

# What component metrics count of a run and of every run nested inside it. Of the messages only each request's
# duration is read, never the content
_METRICS_RUN_DATA_FIELDS = (
    "metrics, model, model_provider, forked_from_message_index, messages.{role, from_history, metrics.{duration}}"
)

# What a legacy run keeps of its own beside run_data: the fields the runs table keeps a column of
_METRICS_LEGACY_RUN_FIELDS = (
    "run_id, agent_id, team_id, workflow_id, parent_run_id, status, created_at, called_from_run_id, "
    "forked_from_session_id"
)


def _stored_day(value: Any) -> Optional[date]:
    """The day a stored metrics row covers, as a plain date.

    SurrealDB hands back a tz-aware datetime for the date column, but the rows are compared
    and totalled by day, so anything that is not already one is normalised here rather than trusted.
    """
    # datetime is a subclass of date, so it has to be narrowed first or a stamp passes through whole
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def desurrealize_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored metric record in the plain shape every other adapter returns.

    SurrealDB hands back a RecordID and its own datetimes, which the response model rejects,
    so the read passes its rows through here.
    """
    row = dict(record)

    if hasattr(row.get("id"), "id"):
        row["id"] = row["id"].id
    elif isinstance(row.get("id"), RecordID):
        row["id"] = str(row["id"].id)

    for field in ("created_at", "updated_at", "date"):
        if isinstance(row.get(field), datetime):
            row[field] = int(row[field].timestamp())

    # Unowned rows are stored with an empty-string user_id
    if row.get("user_id") == "":
        row["user_id"] = None

    return row


# -- Component metrics util methods --
def _metrics_nested_runs_fields(depth: int = _METRICS_NESTED_RUNS_DEPTH) -> str:
    """The fields of the runs nested inside a stored run that component metrics count, down to the given depth."""
    if depth == 0:
        return ", ".join(_METRICS_NESTED_RUN_KEYS)
    nested_fields = _metrics_nested_runs_fields(depth - 1)
    return ", ".join(
        f"{key}.{{run_id, agent_id, team_id, session_id, parent_run_id, {_METRICS_RUN_DATA_FIELDS}, {nested_fields}}}"
        for key in _METRICS_NESTED_RUN_KEYS
    )


def metrics_record_id(table: str, record: Dict[str, Any], key_columns: Sequence[str]) -> RecordID:
    """The id a metrics row is stored under: its key, so a rebuild that writes the same row updates it."""
    key = surrealize_dates({column: record[column] for column in key_columns})
    return RecordID(table, [key[column] for column in key_columns])


def desurrealize_metrics_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored row of the component metrics or user metrics table in the shape the rollup builds, to
    compare and total it.

    Unlike desurrealize_metric, the empty-string user_id is kept as it is built, and the date is a plain date.
    """
    row = dict(record)

    for field in ("created_at", "updated_at"):
        if isinstance(row.get(field), datetime):
            row[field] = int(row[field].timestamp())

    if "date" in row:
        row["date"] = _stored_day(row["date"])

    return row


def desurrealize_metrics_refresh(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return the stored row of the metrics refreshes table with every column, None for one it does not keep."""
    return {"id": METRICS_REFRESH_ID, **{column: record.get(column) for column in _METRICS_REFRESH_COLUMNS}}


def get_all_sessions_for_component_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """Get the sessions created in the given time range, with only what component metrics count.

    Args:
        table (str): The sessions table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[Dict[str, Any]]: The sessions: their id, type, owner, agent, team or workflow, metadata and compaction
            metrics.
    """
    query = dedent(f"""
        SELECT id, user_id, agent, team, workflow, metadata, session_data.compaction_metrics AS compaction_metrics
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
    """)
    results = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)

    sessions = [desurrealize_session(x) for x in results]
    for session in sessions:
        # Rows are kept under the type's value
        if isinstance(session.get("session_type"), SessionType):
            session["session_type"] = session["session_type"].value
    return sessions


def get_all_sessions_with_legacy_runs_for_component_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
    page: int,
) -> List[Dict[str, Any]]:
    """Get a page of the sessions that can hold legacy runs created in the given time range: those with a legacy
    runs field, created before its end and last written after its start.

    Args:
        table (str): The sessions table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.
        page (int): The page to read, from 1, of METRICS_BATCH_SIZE sessions.

    Returns:
        List[Dict[str, Any]]: The sessions: their id, owner, creation time and legacy runs, with only what component
            metrics count of each.
    """
    # Paged by offset over a filtered scan of the sessions table
    query = dedent(f"""
        SELECT id, user_id, created_at,
            runs.{{{_METRICS_LEGACY_RUN_FIELDS}, {_METRICS_RUN_DATA_FIELDS}, {_metrics_nested_runs_fields()}}} AS runs
        FROM {table}
        WHERE runs != NONE AND created_at < $end AND (updated_at ?? created_at) >= $start
        {order_limit_start("id", "ASC", METRICS_BATCH_SIZE, page)}
    """)
    results = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    return [desurrealize_session(x) for x in results]


def get_all_runs_for_component_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
    session_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Get the runs created in the given time range, with only what component metrics count.

    Args:
        table (str): The runs table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.
        session_ids (Optional[Sequence[str]]): Only the runs of these sessions, when given.

    Returns:
        List[Dict[str, Any]]: The runs, with the run_data calculate_date_component_metrics reads. Of the messages it
            reads only each request's duration, and of the runs nested inside a run the same.
    """
    # A run started inside a tool call names the run that called the tool as its parent. A run copied into a forked
    # session repeats a run counted in the session it was made in
    query = dedent(f"""
        SELECT
            run_id, session_id, run_type, agent_id, team_id, workflow_id, user_id,
            parent_run_id ?? run_data.called_from_run_id AS parent_run_id, status,
            run_data.{{{_METRICS_RUN_DATA_FIELDS}, {_metrics_nested_runs_fields()}}} AS run_data
        FROM {table}
        WHERE created_at >= $start AND created_at < $end AND !run_data.forked_from_session_id
        {"AND session_id IN $session_ids" if session_ids is not None else ""}
    """)
    variables: Dict[str, Any] = {"start": start_timestamp, "end": end_timestamp, "session_ids": session_ids}
    return list(utils.query(client, query, variables, dict))


def bulk_upsert_metrics_rows(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    heartbeat: Tuple[str, Dict[str, Any]],
    user_metrics_table: str,
    table: Optional[str] = None,
    component_metrics_records: Sequence[Dict[str, Any]] = (),
    stale_ids: Sequence[RecordID] = (),
    user_metrics_rows: Sequence[Dict[str, Any]] = (),
    stale_user_metrics_ids: Sequence[RecordID] = (),
    everyone_row: Optional[Dict[str, Any]] = None,
    read_version: Optional[int] = None,
    reopen_month_start: Optional[date] = None,
) -> bool:
    """Write a period's rows of the component metrics and user metrics tables in one transaction, only while this
    worker still holds the metrics refresh, and delete the given rows first.

    Args:
        heartbeat (Tuple[str, Dict[str, Any]]): The statement that refreshes locked_at of the metrics refresh,
            returning its row only while this worker holds it, and its variables.
        user_metrics_table (str): The user metrics table.
        table (Optional[str]): The component metrics table. None writes no component metrics row.
        component_metrics_records (Sequence[Dict[str, Any]]): The component metrics rows to upsert.
        stale_ids (Sequence[RecordID]): The ids of the stored component metrics rows to delete.
        user_metrics_rows (Sequence[Dict[str, Any]]): The user rows of the user metrics table to upsert. A user row is
            written with its period's everyone row, so its completed and version are never compared.
        stale_user_metrics_ids (Sequence[RecordID]): The ids of the stored user rows of the user metrics table to delete.
        everyone_row (Optional[Dict[str, Any]]): The everyone row to upsert, from build_user_metrics_rows. None
            writes none.
        read_version (Optional[int]): The version of the stored everyone row read before its period's rows were
            rebuilt. None when there was no stored row.
        reopen_month_start (Optional[date]): The first day of the month whose everyone row to reopen with the rows.
            None reopens none.

    Returns:
        bool: False when another process took the refresh over, and nothing was written.
    """
    heartbeat_statement, variables = heartbeat
    variables = dict(variables)
    statements = []

    if stale_ids:
        variables["stale_ids"] = list(stale_ids)
        statements.append("DELETE $stale_ids;")

    if table is not None and component_metrics_records:
        variables["records"] = [
            {**surrealize_dates(record), "id": metrics_record_id(table, record, COMPONENT_METRICS_KEY_COLUMNS)}
            for record in component_metrics_records
        ]
        # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
        update_columns = [
            f"{column} = $input.{column}"
            for column in component_metrics_records[0]
            if column not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
        ]
        statements.append(
            f"INSERT INTO {table} $records ON DUPLICATE KEY UPDATE {', '.join(update_columns)} RETURN NONE;"
        )

    if stale_user_metrics_ids:
        variables["stale_user_metrics_ids"] = list(stale_user_metrics_ids)
        statements.append("DELETE $stale_user_metrics_ids;")

    for name, rows in [
        ("user_metrics_rows", list(user_metrics_rows)),
        ("everyone_row", [everyone_row] if everyone_row else []),
    ]:
        if not rows:
            continue
        # A new row starts at version 1, and every write of a stored one moves its version by one in the same
        # statement, so two writers never give it the same version
        variables[name] = [
            {
                **surrealize_dates(row),
                "id": metrics_record_id(user_metrics_table, row, USER_METRICS_KEY_COLUMNS),
                "version": 1,
            }
            for row in rows
        ]
        # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
        update_columns = [
            f"{column} = $input.{column}"
            for column in rows[0]
            if column not in [*USER_METRICS_KEY_COLUMNS, "created_at", "version", "completed"]
        ]
        if name == "everyone_row":
            # Compared in the statement, before the version moves, so a reopen written since the version was read
            # keeps the period open
            variables["read_version"] = read_version
            update_columns.append(
                "completed = IF $read_version != NONE AND version = $read_version THEN $input.completed ELSE false END"
            )
        else:
            update_columns.append("completed = $input.completed")
        update_columns.append("version += 1")
        statements.append(
            f"INSERT INTO {user_metrics_table} ${name} ON DUPLICATE KEY UPDATE {', '.join(update_columns)} RETURN NONE;"
        )

    if reopen_month_start is not None:
        variables["reopen_month_row"] = _reopen_metrics_row(user_metrics_table, reopen_month_start, "monthly")
        statements.append(
            f"INSERT INTO {user_metrics_table} [$reopen_month_row] ON DUPLICATE KEY UPDATE completed = false, "
            "version += 1 RETURN NONE;"
        )

    # One block is one transaction: the rows are written only while the refresh is still held, and a read never sees
    # half of them. The everyone row is written last, so its version never moves without the rows it tells of.
    # Queried directly, as utils.query_one returns a failed statement as None instead of raising it
    held = client.query(
        dedent(f"""
            {{
                LET $held = ({heartbeat_statement});
                IF $held {{
                    {" ".join(statements)}
                }};
                RETURN $held != [];
            }}
        """),
        variables,
    )
    # SDK 1.x returns a failed statement as its error message instead of raising it
    if isinstance(held, str):
        raise RuntimeError(held)
    return bool(held)


def heartbeat_metrics_refresh(table: str, worker_id: str) -> Tuple[str, Dict[str, Any]]:
    """Build the refresh of locked_at for this worker's metrics refresh, and its variables. It returns the row's id
    only while this worker still holds it.

    Args:
        table (str): The metrics refreshes table.
        worker_id (str): The id of the calculation that claimed it.

    Returns:
        Tuple[str, Dict[str, Any]]: The statement and its variables.
    """
    statement = "UPDATE $refresh SET locked_at = time::unix(time::now()) WHERE locked_by = $worker_id RETURN id"
    return statement, {"refresh": RecordID(table, METRICS_REFRESH_ID), "worker_id": worker_id}


def _reopen_metrics_row(table: str, row_date: date, aggregation_period: str) -> Dict[str, Any]:
    """Build the empty open everyone row of a day or a month of the user metrics table, which a reopen inserts when
    the period has none."""
    return {
        **surrealize_dates(build_user_metrics_row([], aggregation_period, row_date, completed=False)),
        "id": metrics_record_id(
            table,
            {"aggregation_period": aggregation_period, "date": row_date, "user_id": ""},
            USER_METRICS_KEY_COLUMNS,
        ),
        "version": 1,
    }


def reopen_metrics_day(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, day: date
) -> None:
    """Reopen a day's everyone row of the user metrics table, inserting an empty open row when it has none, so the
    next refresh rebuilds the day.

    Args:
        table (str): The user metrics table.
        day (date): The day, from metrics_day_to_reopen.
    """
    utils.query(
        client,
        f"INSERT INTO {table} [$row] ON DUPLICATE KEY UPDATE completed = false, version += 1 RETURN NONE",
        {"row": _reopen_metrics_row(table, day, "daily")},
        dict,
    )


def reopen_metrics_days_from(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, starting_date: date
) -> None:
    """Reopen every day's everyone row of the user metrics table from the given date on, as a write reopens a day,
    so the next calculation rebuilds them.

    Args:
        table (str): The user metrics table.
        starting_date (date): The first day to reopen.
    """
    utils.query(
        client,
        f'UPDATE {table} SET completed = false, version += 1 WHERE aggregation_period = "daily" AND user_id = "" '
        "AND date >= $start RETURN NONE",
        {"start": datetime.combine(starting_date, datetime.min.time()).replace(tzinfo=timezone.utc)},
        dict,
    )


def build_metrics_rows_fields(fields: Sequence[str], table_type: str) -> str:
    """Build the fields of a stored metrics row with only what totalling the given fields reads.

    Args:
        fields (Sequence[str]): The columns to total.
        table_type (str): "component_metrics" or "user_metrics", whose row is read.

    Returns:
        str: The fields, for a SELECT.
    """
    selected = ["aggregation_period", "date", "updated_at"]
    for field in fields:
        if field in [*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens", *METRICS_COST_FIELDS]:
            selected.append("token_details")
        # The user metrics table keeps the sessions of each type, and the component metrics table the runs of each
        # component, with the run that started them
        elif field == "sessions_count" and table_type == "user_metrics":
            selected.extend(f"{component_type}_sessions_count" for component_type in METRICS_COMPONENT_TYPES)
        elif field == "root_runs_count" and table_type == "component_metrics":
            selected.extend(["runs_count", "parent_component_id"])
        else:
            selected.append(field)
    return ", ".join(dict.fromkeys(selected))
