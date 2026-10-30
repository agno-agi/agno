import time
from datetime import date, datetime, timezone
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Sequence, Union
from uuid import uuid4

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.models import desurrealize_dates, desurrealize_session, surrealize_dates
from agno.db.surrealdb.queries import WhereClause, order_limit_start
from agno.db.utils import (
    OS_METRICS_KEY_COLUMNS,
    OS_METRICS_TOTALS_KEY_COLUMNS,
    metrics_starting_date_from_days,
)
from agno.utils.log import log_error

# A process that stopped mid-rebuild holds the OS metrics lock this many seconds at most
OS_METRICS_LOCK_SECONDS = 300

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000

# The keys of a stored run that hold the runs nested inside it
_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# A run nested deeper than this is read whole
_OS_METRICS_NESTED_RUNS_DEPTH = 6


def get_all_sessions_for_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: Optional[datetime] = None,
    end_timestamp: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Get all sessions of all types (agent, team, workflow) as raw dictionaries.

    Args:
        start_timestamp (Optional[int]): The start timestamp to filter by. Defaults to None.
        end_timestamp (Optional[int]): The end timestamp to filter by. Defaults to None.

    Returns:
        List[Dict[str, Any]]: List of session dictionaries with session_type field.

    Raises:
        Exception: If an error occurs during retrieval.
    """
    where = WhereClause()

    # starting_date
    if start_timestamp is not None:
        where = where.and_("created_at", start_timestamp, ">=")

    # ending_date
    if end_timestamp is not None:
        where = where.and_("created_at", end_timestamp, "<=")

    where_clause, where_vars = where.build()

    # Query
    query = dedent(f"""
        SELECT *
        FROM {table}
        {where_clause}
    """)

    results = utils.query(client, query, where_vars, dict)
    return [desurrealize_session(x) for x in results]


def _stored_day(value: Any) -> Optional[date]:
    """The day a stored metrics row covers, as a plain date.

    SurrealDB hands back a tz-aware datetime for the date column, but the shared decision
    compares days, so anything that is not already one is normalised here rather than trusted.
    """
    # datetime is a subclass of date, so it has to be narrowed first or a stamp passes through whole
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def get_metrics_calculation_starting_date(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, get_sessions: Callable
) -> Optional[date]:
    """Get the first date for which metrics calculation is needed:

    1. If there are metrics records, return the date of the first day without a complete metrics record.
    2. If there are no metrics records, return the date of the first recorded session.
    3. If there are no metrics records and no sessions records, return None.

    Args:
        table (Table): The table to get the starting date for.

    Returns:
        Optional[date]: The starting date for which metrics calculation is needed.
    """
    # 1. resume at the earliest incomplete day after the latest completed one, otherwise the
    # day after that one: the date column is a datetime stamped at midnight, so the strict
    # comparison below excludes the completed day itself
    completed_record = utils.query_one(
        client,
        dedent(f"""
            SELECT * FROM ONLY {table}
            WHERE completed = true
            ORDER BY date DESC
            LIMIT 1
        """),
        {},
        dict,
    )
    stored_completed_day = completed_record["date"] if completed_record else None

    incomplete_where = (
        "WHERE completed = false" if stored_completed_day is None else "WHERE completed = false AND date > $last"
    )
    incomplete_vars: Dict[str, Any] = {} if stored_completed_day is None else {"last": stored_completed_day}
    incomplete_record = utils.query_one(
        client,
        dedent(f"""
            SELECT * FROM ONLY {table}
            {incomplete_where}
            ORDER BY date ASC
            LIMIT 1
        """),
        incomplete_vars,
        dict,
    )

    latest_completed = _stored_day(stored_completed_day)
    earliest_incomplete = _stored_day(incomplete_record["date"]) if incomplete_record else None

    starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
    if starting_date is not None:
        return starting_date

    # 2. No metrics records. Return the date of the first recorded session
    first_session, _ = get_sessions(
        session_type=SessionType.AGENT,  # this is ignored because of component_id=None and deserialize=False
        sort_by="created_at",
        sort_order="asc",
        limit=1,
        component_id=None,
        deserialize=False,
    )
    assert isinstance(first_session, list)

    first_session_date = first_session[0]["created_at"] if first_session else None

    # 3. No metrics records and no sessions records. Return None
    if first_session_date is None:
        return None

    # Handle different types for created_at
    if isinstance(first_session_date, datetime):
        return first_session_date.date()
    elif isinstance(first_session_date, int):
        # Assume it's a Unix timestamp
        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()
    elif isinstance(first_session_date, str):
        # Try parsing as ISO format
        return datetime.fromisoformat(first_session_date.replace("Z", "+00:00")).date()
    else:
        # If it's already a date object
        if isinstance(first_session_date, date):
            return first_session_date
        raise ValueError(f"Unexpected type for created_at: {type(first_session_date)}")


def desurrealize_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored metric record in the plain shape every other adapter returns.

    SurrealDB hands back a RecordID and its own datetimes, which the response model rejects,
    so both the read and the recalculation pass their rows through here.
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


def bulk_upsert_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    metrics_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (List[Dict[str, Any]]): The list of metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    metrics_records = [surrealize_dates(x) for x in metrics_records]

    results = []
    from agno.utils.log import log_debug

    for metric in metrics_records:
        log_debug(f"Upserting metric: {metric}")
        # Per-record: a mid-run failure must not discard the records that already landed
        try:
            result = utils.query_one(
                client,
                "UPSERT $record CONTENT $content",
                {"record": RecordID(table, metric["id"]), "content": metric},
                dict,
            )
        except Exception as e:
            log_error(f"Error upserting metrics record: {str(e)}")
            continue

        if result:
            results.append(result)

    return results


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types.

    Args:
        sessions (List[Dict[str, Any]]): The sessions to process.
        dates_to_process (list[date]): The dates to fetch session data for.
        start_timestamp (int): The start timestamp (fallback if created_at is missing).

    Returns:
        dict: A dictionary with dates as keys and session data as values, for all session types.

    Example:
    {
        "2000-01-01": {
            "agent": [<session1>, <session2>, ...],
            "team": [...],
            "workflow": [...],
        }
    }
    """
    if not dates_to_process:
        return None

    all_sessions_data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        date_to_process.isoformat(): {"agent": [], "team": [], "workflow": []} for date_to_process in dates_to_process
    }

    for session in sessions:
        created_at = session.get("created_at", start_timestamp)

        # Handle different types for created_at
        if isinstance(created_at, datetime):
            session_date = created_at.date().isoformat()
        elif isinstance(created_at, int):
            session_date = datetime.fromtimestamp(created_at, tz=timezone.utc).date().isoformat()
        elif isinstance(created_at, date):
            session_date = created_at.isoformat()
        else:
            # Fallback to start_timestamp if type is unexpected
            session_date = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).date().isoformat()

        if session_date in all_sessions_data:
            session_type = session.get("session_type", "agent")  # Default to agent if missing
            all_sessions_data[session_date][session_type].append(session)

    return all_sessions_data


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per user_id.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        List[dict]: One metrics record per user. Sessions with no user_id bucket under "".
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
        sessions = sessions_data.get(session_type, [])

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

            session_metrics = (session.get("session_data") or {}).get("session_metrics", {}) or {}
            for field in bucket["token_metrics"]:
                bucket["token_metrics"][field] += session_metrics.get(field, 0)

    current_time = datetime.now(timezone.utc)
    completed = date_to_process < current_time.date()
    # Stamp the day being aggregated, not today, so backfilled days stay in get_metrics range queries
    date_at_midnight = datetime.combine(date_to_process, datetime.min.time(), tzinfo=timezone.utc)

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        users_count = 0 if user_id == "" else 1
        # Deterministic per-(date, user) ID, so re-calculating the same window upserts the same record
        record_id = f"{date_to_process.isoformat()}|{user_id}"

        records.append(
            {
                "id": record_id,
                "date": date_at_midnight,
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


def _os_metrics_nested_runs_fields(depth: int = _OS_METRICS_NESTED_RUNS_DEPTH) -> str:
    """The fields of the runs nested inside a stored run that OS metrics count, down to the given depth."""
    if depth == 0:
        return ", ".join(_OS_METRICS_NESTED_RUN_KEYS)
    fields = (
        "run_id, agent_id, team_id, metrics, model, model_provider, forked_from_message_index, "
        "messages.{role, from_history, metrics}"
    )
    nested_fields = _os_metrics_nested_runs_fields(depth - 1)
    return ", ".join(f"{key}.{{{fields}, {nested_fields}}}" for key in _OS_METRICS_NESTED_RUN_KEYS)


def os_metrics_record_id(table: str, record: Dict[str, Any], key_columns: Sequence[str]) -> RecordID:
    """The id an OS metrics row is stored under: its key, so a rebuild that writes the same row updates it."""
    key = surrealize_dates({column: record[column] for column in key_columns})
    return RecordID(table, [key[column] for column in key_columns])


def desurrealize_os_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored OS metrics row in the shape calculate_date_os_metrics builds, to compare and total it.

    Unlike desurrealize_metric, the empty-string user_id is kept as it is built, and the date is a plain date.
    """
    row = dict(record)

    for field in ("created_at", "updated_at"):
        if isinstance(row.get(field), datetime):
            row[field] = int(row[field].timestamp())

    if "date" in row:
        row["date"] = _stored_day(row["date"])

    return row


def get_os_metrics_calculation_starting_date(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], totals_table: str, sessions_table: str
) -> Optional[date]:
    """Get the first date for which OS metrics calculation is needed:

    1. If there are total rows of days, return the earliest day not completed after the latest completed one,
       otherwise the day after that one.
    2. If there are none, return the date of the first recorded session.
    3. If there are no total rows and no sessions records, return None.

    Args:
        totals_table (str): The OS metrics totals table.
        sessions_table (str): The sessions table.

    Returns:
        Optional[date]: The starting date for which OS metrics calculation is needed.
    """
    # 1. resume at the earliest incomplete day after the latest completed one, otherwise the
    # day after that one: the date column is a datetime stamped at midnight, so the strict
    # comparison below excludes the completed day itself
    completed_record = utils.query_one(
        client,
        dedent(f"""
            SELECT date FROM ONLY {totals_table}
            WHERE aggregation_period = "daily" AND completed = true
            ORDER BY date DESC
            LIMIT 1
        """),
        {},
        dict,
    )
    stored_completed_day = completed_record["date"] if completed_record else None

    incomplete_where = (
        'WHERE aggregation_period = "daily" AND completed = false'
        if stored_completed_day is None
        else 'WHERE aggregation_period = "daily" AND completed = false AND date > $last'
    )
    incomplete_vars: Dict[str, Any] = {} if stored_completed_day is None else {"last": stored_completed_day}
    incomplete_record = utils.query_one(
        client,
        dedent(f"""
            SELECT date FROM ONLY {totals_table}
            {incomplete_where}
            ORDER BY date ASC
            LIMIT 1
        """),
        incomplete_vars,
        dict,
    )

    latest_completed = _stored_day(stored_completed_day)
    earliest_incomplete = _stored_day(incomplete_record["date"]) if incomplete_record else None

    starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
    if starting_date is not None:
        return starting_date

    # 2. No total rows. Return the date of the first recorded session.
    # Queried directly rather than through get_sessions, which also counts the sessions
    first_session = utils.query_one(
        client,
        dedent(f"""
            SELECT created_at FROM ONLY {sessions_table}
            ORDER BY created_at ASC
            LIMIT 1
        """),
        {},
        dict,
    )

    # 3. No total rows and no sessions records. Return None.
    if first_session is None:
        return None

    return _stored_day(first_session["created_at"])


def get_all_sessions_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """Get the sessions created in the given time range, with only what OS metrics count.

    Args:
        table (str): The sessions table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[Dict[str, Any]]: The sessions: their id, type, owner and agent, team or workflow.
    """
    query = dedent(f"""
        SELECT id, user_id, agent, team, workflow
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


def get_all_sessions_with_legacy_runs_for_os_metrics_calculation(
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
        page (int): The page to read, from 1, of OS_METRICS_BATCH_SIZE sessions.

    Returns:
        List[Dict[str, Any]]: The sessions: their owner, creation time and legacy runs.
    """
    query = dedent(f"""
        SELECT id, user_id, created_at, runs
        FROM {table}
        WHERE runs != NONE AND created_at < $end AND (updated_at ?? created_at) >= $start
        {order_limit_start("id", "ASC", OS_METRICS_BATCH_SIZE, page)}
    """)
    results = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    return [desurrealize_dates(x) for x in results]


def get_all_runs_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """Get the runs created in the given time range, with only what OS metrics count.

    Args:
        table (str): The runs table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[Dict[str, Any]]: The runs, with the run_data calculate_date_os_metrics reads. Of the messages it
            reads only the role, from_history and metrics, and of the runs nested inside a run the same.
    """
    query = dedent(f"""
        SELECT
            run_id, run_type, agent_id, team_id, workflow_id, user_id, parent_run_id, status,
            run_data.{{
                metrics, model, model_provider, forked_from_message_index, forked_from_session_id,
                messages.{{role, from_history, metrics}},
                {_os_metrics_nested_runs_fields()}
            }} AS run_data
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
    """)
    return list(utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict))


def lock_os_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, wait_for_rebuild: bool
) -> Optional[str]:
    """Take the OS metrics lock of the given table, so one process rebuilds its OS metrics at a time.

    The lock is a record that expires after OS_METRICS_LOCK_SECONDS, so a process that stopped mid-rebuild never
    holds it for good.

    Args:
        table (str): The OS metrics table.
        wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, skip instead.

    Returns:
        Optional[str]: The token the lock is held with. None when another process holds it.
    """
    token = str(uuid4())
    while True:
        try:
            # One block is one transaction: an expired lock is removed and the new one created together
            response = client.query(
                dedent(f"""
                    {{
                        DELETE $lock WHERE expires_at < time::now();
                        CREATE $lock SET token = $lock_token, expires_at = time::now() + {OS_METRICS_LOCK_SECONDS}s;
                    }}
                """),
                {"lock": RecordID(table, "lock"), "lock_token": token},
            )
            # SDK 1.x returns a failed statement's error message instead of raising it
            if isinstance(response, str):
                raise RuntimeError(response)
            return token
        except Exception as e:
            # Another process holds the lock, or took it at the same moment
            if "already exists" not in str(e) and "can be retried" not in str(e):
                raise
        if not wait_for_rebuild:
            return None
        time.sleep(0.1)


def unlock_os_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, token: str
) -> None:
    """Release the OS metrics lock of the given table, unless it expired and another process holds it.

    Args:
        table (str): The OS metrics table.
        token (str): The token the lock is held with.
    """
    utils.query(
        client, "DELETE $lock WHERE token = $lock_token", {"lock": RecordID(table, "lock"), "lock_token": token}, dict
    )


def bulk_upsert_os_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    os_metrics_records: List[Dict[str, Any]],
    totals_table: str,
    totals_row: Optional[Dict[str, Any]],
    stale_ids: Optional[List[RecordID]] = None,
) -> None:
    """Bulk upsert OS metrics and the totals row of their period into the database in one transaction, and delete
    the given records first.

    Args:
        table (str): The OS metrics table.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
        totals_table (str): The OS metrics totals table.
        totals_row (Optional[Dict[str, Any]]): The totals row to upsert, from build_os_metrics_totals_row. A new
            row starts at version 1, and every write of a stored one moves its version by one in the same
            statement, so two writers never give it the same version. None writes no totals row.
        stale_ids (Optional[List[RecordID]]): The ids of the stored OS metrics records to delete.
    """
    statements = []
    variables: Dict[str, Any] = {}

    if stale_ids:
        variables["stale_ids"] = stale_ids
        statements.append("DELETE $stale_ids;")

    if os_metrics_records:
        variables["records"] = [
            {**surrealize_dates(record), "id": os_metrics_record_id(table, record, OS_METRICS_KEY_COLUMNS)}
            for record in os_metrics_records
        ]
        # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
        update_columns = [
            f"{column} = $input.{column}"
            for column in os_metrics_records[0]
            if column
            not in [
                "aggregation_period",
                "date",
                "user_id",
                "component_type",
                "component_id",
                "parent_component_id",
                "created_at",
            ]
        ]
        statements.append(
            f"INSERT INTO {table} $records ON DUPLICATE KEY UPDATE {', '.join(update_columns)} RETURN NONE;"
        )

    if totals_row is not None:
        variables["totals_row"] = {
            **surrealize_dates(totals_row),
            "id": os_metrics_record_id(totals_table, totals_row, OS_METRICS_TOTALS_KEY_COLUMNS),
            "version": 1,
        }
        # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
        update_columns = [
            f"{column} = $input.{column}"
            for column in totals_row
            if column not in ["aggregation_period", "date", "created_at", "version"]
        ]
        update_columns.append("version += 1")
        # Written last, so its version never moves without the rows it tells of
        statements.append(
            f"INSERT INTO {totals_table} $totals_row ON DUPLICATE KEY UPDATE {', '.join(update_columns)} RETURN NONE;"
        )

    if not statements:
        return

    # One block is one transaction, so a read never sees half of it
    utils.query(client, f"{{ {' '.join(statements)} }}", variables, dict)
