"""Utility functions for the Redis database class."""

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from agno.db.utils import (
    METRICS_REFRESH_ID,
    METRICS_TOKEN_FIELDS,
    build_user_metrics_row,
    get_metrics_legacy_runs,
    get_sort_value,
    metrics_parent_run_id,
    user_metrics_row_to_store,
)
from agno.utils.log import log_warning

try:
    from redis import Redis, RedisCluster
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")


# Keys each SCAN call walks, as the Valkey adapter scans. SCAN walks every key of the database, not only the matching
# ones, and the Redis default of 10 takes a round trip per 10 keys
METRICS_SCAN_COUNT = 1000

# The keys of a stored run that hold the runs nested inside it, in the order the rollup walks them
_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")


# -- Serialization and deserialization --


class CustomEncoder(json.JSONEncoder):
    """Custom encoder to handle non JSON serializable types."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()

        return super().default(obj)


def serialize_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, cls=CustomEncoder)


def deserialize_data(data: str) -> dict:
    return json.loads(data)


# -- Redis utils --


def generate_redis_key(prefix: str, table_type: str, key_id: str) -> str:
    """Generate Redis key with proper namespacing."""
    return f"{prefix}:{table_type}:{key_id}"


def generate_index_key(prefix: str, table_type: str, index_field: str, index_value: str) -> str:
    """Generate Redis key for index entries."""
    return f"{prefix}:{table_type}:index:{index_field}:{index_value}"


def get_all_keys_for_table(
    redis_client: Union[Redis, RedisCluster], prefix: str, table_type: str, count: Optional[int] = None
) -> List[str]:
    """Get all relevant keys for the given table type.

    Args:
        redis_client (Redis): The Redis client.
        prefix (str): The prefix for the keys.
        table_type (str): The table type.
        count (Optional[int]): How many keys each SCAN call walks. ``None`` uses the Redis default.

    Returns:
        List[str]: A list of all relevant keys for the given table type.
    """
    pattern = f"{prefix}:{table_type}:*"
    all_keys = redis_client.scan_iter(match=pattern, count=count)
    relevant_keys = []

    # Helper namespaces, matched by prefix so a record id that merely contains one
    # of these markers is not dropped from the results
    index_prefix = f"{prefix}:{table_type}:index:"
    runs_by_session_prefix = f"{prefix}:runs:by_session:"

    for key in all_keys:
        # Coerce bytes -> str for substring checks (decode_responses may not be set)
        key_str = key.decode() if isinstance(key, (bytes, bytearray)) else key
        if key_str.startswith(index_prefix):  # Skip index keys
            continue
        # Skip helper indexes maintained by the v3+ runs collection
        # (e.g. `<prefix>:runs:by_session:<session_id>` sorted-set indexes)
        if key_str.startswith(runs_by_session_prefix):
            continue
        relevant_keys.append(key)

    return relevant_keys


# -- DB util methods --


def apply_sorting(
    records: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to the given records list.

    Args:
        records: The list of dictionaries to sort
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The sorted list

    Note:
        If sorting by "updated_at", will fallback to "created_at" in case of None.
    """
    if sort_by is None or not records:
        return records

    try:
        is_descending = sort_order == "desc"

        # Sort using the helper function that handles updated_at -> created_at fallback
        sorted_records = sorted(
            records,
            key=lambda x: (get_sort_value(x, sort_by) is None, get_sort_value(x, sort_by)),
            reverse=is_descending,
        )

        return sorted_records

    except Exception as e:
        log_warning(f"Error sorting Redis records: {str(e)}")
        return records


def apply_pagination(
    records: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination.

    Raises ``ValueError`` when ``page`` is provided without ``limit`` — see
    ``agno.db.utils.validate_pagination``.
    """
    from agno.db.utils import validate_pagination

    validate_pagination(limit, page)
    if limit is None:
        return records

    if page is not None and page > 0:
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        return records[start_idx:end_idx]

    return records[:limit]


def apply_filters(records: List[Dict[str, Any]], conditions: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not conditions:
        return records

    filtered_records = []
    for record in records:
        match = True
        for key, value in conditions.items():
            if key not in record or record[key] != value:
                match = False
                break
        if match:
            filtered_records.append(record)

    return filtered_records


def create_index_entries(
    redis_client: Union[Redis, RedisCluster],
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            redis_client.sadd(index_key, record_id)


def remove_index_entries(
    redis_client: Union[Redis, RedisCluster],
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            redis_client.srem(index_key, record_id)


# -- Metrics utils --


def generate_created_at_index_key(prefix: str, table_type: str) -> str:
    """Generate the key of the sorted set that lists the records of a table by created_at, so the records of a day are
    read without scanning the table."""
    return f"{prefix}:{table_type}:index:created_at"


def generate_metrics_prefix(prefix: str) -> str:
    """Generate the prefix of every key of the metrics tables. The braces make it the keys' hash tag, so they share one
    cluster slot and a transaction can write the rows of a day together with the metrics refresh."""
    return f"{{{prefix}}}"


def component_metrics_record_id(record: Dict[str, Any]) -> str:
    """The id of the key a row of the component metrics table is stored under, one per period, day, owner and
    component.

    The id starts with the day and ends with the period, so both are read off an index entry without reading the row.
    """
    key = json.dumps(
        [
            record["user_id"],
            record["component_type"],
            record["component_id"],
            record["parent_component_id"],
            record["root_component_id"],
        ]
    )
    key_segment = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{record['date'].isoformat()}_{key_segment}_{record['aggregation_period']}"


def user_metrics_record_id(aggregation_period: str, row_date: date, user_id: str) -> str:
    """The id of the key a row of the user metrics table is stored under, one per period, day and user."""
    user_segment = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"{row_date.isoformat()}_{user_segment}_{aggregation_period}"


def metrics_record_key(record_id: Any) -> Tuple[date, str]:
    """Read the day and the period off the id of a component metrics or user metrics row."""
    # Coerce bytes -> str (decode_responses may not be set)
    record_id = record_id.decode() if isinstance(record_id, (bytes, bytearray)) else str(record_id)
    return date.fromisoformat(record_id[:10]), record_id.rsplit("_", 1)[1]


def metrics_day_start(day: date) -> int:
    """The timestamp of the start of the given UTC day."""
    return int(datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())


def deserialize_component_metrics_record(data: Any) -> Dict[str, Any]:
    """Deserialize a stored component metrics row, with its day read back as a date."""
    record = deserialize_data(data)
    record["date"] = date.fromisoformat(record["date"])
    return record


def serialize_user_metrics_record(record: Dict[str, Any]) -> Dict[str, str]:
    """Serialize each column of a user metrics row to a field of the hash it is stored in."""
    return {column: json.dumps(value, ensure_ascii=False, cls=CustomEncoder) for column, value in record.items()}


def deserialize_user_metrics_record(fields: Dict[Any, Any]) -> Dict[str, Any]:
    """Deserialize the fields of a stored user metrics row, with its day read back as a date."""
    record = {
        (column.decode() if isinstance(column, bytes) else column): json.loads(value)
        for column, value in fields.items()
        if value is not None
    }
    if "date" in record:
        record["date"] = date.fromisoformat(record["date"])
    return record


def bulk_upsert_component_metrics(
    pipe: Any, prefix: str, component_metrics_records: List[Dict[str, Any]], expire: Optional[int] = None
) -> None:
    """Upsert component metrics into the database, in the given pipeline.

    Args:
        pipe (Any): The pipeline to upsert in.
        prefix (str): The prefix of the metrics keys.
        component_metrics_records (List[Dict[str, Any]]): The component metrics records to upsert, each with the
            created_at of its stored row.
        expire (Optional[int]): The TTL of the keys in seconds.
    """
    for record in component_metrics_records:
        record_id = component_metrics_record_id(record)
        pipe.set(
            generate_redis_key(prefix=prefix, table_type="component_metrics", key_id=record_id),
            serialize_data(record),
            ex=expire,
        )
        create_index_entries(
            redis_client=pipe,
            prefix=prefix,
            table_type="component_metrics",
            record_id=record_id,
            record_data=record,
            index_fields=["date", "user_id"],
        )


def delete_component_metrics(pipe: Any, prefix: str, component_metrics_records: List[Dict[str, Any]]) -> None:
    """Delete the given stored component metrics rows, in the given pipeline.

    Args:
        pipe (Any): The pipeline to delete in.
        prefix (str): The prefix of the metrics keys.
        component_metrics_records (List[Dict[str, Any]]): The stored rows to delete.
    """
    for record in component_metrics_records:
        record_id = component_metrics_record_id(record)
        remove_index_entries(
            redis_client=pipe,
            prefix=prefix,
            table_type="component_metrics",
            record_id=record_id,
            record_data=record,
            index_fields=["date", "user_id"],
        )
        pipe.delete(generate_redis_key(prefix=prefix, table_type="component_metrics", key_id=record_id))


def upsert_user_metrics_row(
    redis_client: Union[Redis, RedisCluster],
    prefix: str,
    user_metrics_row: Dict[str, Any],
    read_version: Optional[int],
    worker_id: str,
    expire: Optional[int] = None,
) -> bool:
    """Upsert a user metrics row into the database, only while the given worker still holds the metrics refresh.

    The stored version is compared and the row written in one transaction that watches the row and the metrics
    refresh, so a write that reopens the period, or a process that takes the refresh over, fails it. The row is then
    read and written again, or not at all.

    Args:
        redis_client (Union[Redis, RedisCluster]): The Redis client.
        prefix (str): The prefix of the metrics keys.
        user_metrics_row (Dict[str, Any]): The row, from build_user_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
        worker_id (str): The id of the calculation that holds the metrics refresh.
        expire (Optional[int]): The TTL of the key in seconds.

    Returns:
        bool: False when another process took the metrics refresh over, and nothing was written.
    """
    from redis.exceptions import WatchError

    record_id = user_metrics_record_id(
        user_metrics_row["aggregation_period"], user_metrics_row["date"], user_metrics_row["user_id"]
    )
    key = generate_redis_key(prefix=prefix, table_type="user_metrics", key_id=record_id)
    refresh_key = generate_redis_key(prefix=prefix, table_type="metrics_refreshes", key_id=METRICS_REFRESH_ID)
    for _ in range(10):
        try:
            with redis_client.pipeline(transaction=True) as pipe:
                pipe.watch(key, refresh_key)
                raw = pipe.get(refresh_key)
                refresh_row = json.loads(raw if isinstance(raw, str) else raw.decode()) if raw is not None else {}
                if refresh_row.get("locked_by") != worker_id:
                    pipe.unwatch()
                    return False
                fields = pipe.hgetall(key)
                stored_row = deserialize_user_metrics_record(fields) if fields else None  # type: ignore[arg-type]
                row = user_metrics_row_to_store(user_metrics_row, stored_row, read_version)
                pipe.multi()
                pipe.hset(key, mapping=serialize_user_metrics_record(row))  # type: ignore[arg-type]
                if expire is not None:
                    pipe.expire(key, expire)
                create_index_entries(
                    redis_client=pipe,
                    prefix=prefix,
                    table_type="user_metrics",
                    record_id=record_id,
                    record_data=row,
                    index_fields=["date", "user_id"],
                )
                pipe.execute()
                return True
        except WatchError:
            continue
    return False


def bulk_upsert_user_metrics_rows(
    pipe: Any, prefix: str, user_metrics_rows: List[Dict[str, Any]], expire: Optional[int] = None
) -> None:
    """Upsert the user rows of a period into the user metrics table, in the given pipeline.

    A user row is written with its period's everyone row, so its completed is never compared. Every write moves its
    version by one in the same pipeline, so two writers never give it the same version, and created_at is never
    overwritten.

    Args:
        pipe (Any): The pipeline to upsert in.
        prefix (str): The prefix of the metrics keys.
        user_metrics_rows (List[Dict[str, Any]]): The user rows, from build_user_metrics_rows.
        expire (Optional[int]): The TTL of the keys in seconds.
    """
    for user_metrics_row in user_metrics_rows:
        record_id = user_metrics_record_id(
            user_metrics_row["aggregation_period"], user_metrics_row["date"], user_metrics_row["user_id"]
        )
        key = generate_redis_key(prefix=prefix, table_type="user_metrics", key_id=record_id)
        fields = serialize_user_metrics_record(user_metrics_row)
        created_at = fields.pop("created_at")
        pipe.hset(key, mapping=fields)
        pipe.hsetnx(key, "created_at", created_at)
        pipe.hincrby(key, "version", 1)
        if expire is not None:
            pipe.expire(key, expire)
        create_index_entries(
            redis_client=pipe,
            prefix=prefix,
            table_type="user_metrics",
            record_id=record_id,
            record_data=user_metrics_row,
            index_fields=["date", "user_id"],
        )


def delete_user_metrics_rows(pipe: Any, prefix: str, user_metrics_rows: List[Dict[str, Any]]) -> None:
    """Delete the given stored user rows of the user metrics table, in the given pipeline.

    Args:
        pipe (Any): The pipeline to delete in.
        prefix (str): The prefix of the metrics keys.
        user_metrics_rows (List[Dict[str, Any]]): The stored rows to delete.
    """
    for user_metrics_row in user_metrics_rows:
        record_id = user_metrics_record_id(
            user_metrics_row["aggregation_period"], user_metrics_row["date"], user_metrics_row["user_id"]
        )
        remove_index_entries(
            redis_client=pipe,
            prefix=prefix,
            table_type="user_metrics",
            record_id=record_id,
            record_data=user_metrics_row,
            index_fields=["date", "user_id"],
        )
        pipe.delete(generate_redis_key(prefix=prefix, table_type="user_metrics", key_id=record_id))


def _reopen_metrics_row(pipe: Any, prefix: str, row_date: date, aggregation_period: str, expire: Optional[int]) -> None:
    """Add the reopen of a day's or a month's everyone row of the user metrics table to the given pipeline.

    Every field of an empty open row is set only where the row has none, then the row is opened and its version moved
    by one, so the reopen never reads the row: a period with no row gets an empty open row at version 1.
    """
    record_id = user_metrics_record_id(aggregation_period, row_date, "")
    key = generate_redis_key(prefix=prefix, table_type="user_metrics", key_id=record_id)
    empty_row = {**build_user_metrics_row([], aggregation_period, row_date, completed=False), "version": 0}
    for column, value in serialize_user_metrics_record(empty_row).items():
        pipe.hsetnx(key, column, value)
    pipe.hset(key, "completed", json.dumps(False))
    pipe.hincrby(key, "version", 1)
    if expire is not None:
        pipe.expire(key, expire)
    create_index_entries(
        redis_client=pipe,
        prefix=prefix,
        table_type="user_metrics",
        record_id=record_id,
        record_data=empty_row,
        index_fields=["date", "user_id"],
    )


def reopen_metrics_day(pipe: Any, prefix: str, day: date, expire: Optional[int] = None) -> None:
    """Reopen a day's user metrics row, in the given pipeline, so the next refresh rebuilds the day.

    Args:
        pipe (Any): The pipeline of the write that changed the day.
        prefix (str): The prefix of the metrics keys.
        day (date): The day, from metrics_day_to_reopen.
        expire (Optional[int]): The TTL of the key in seconds.
    """
    _reopen_metrics_row(pipe, prefix, day, "daily", expire)


def reopen_metrics_month(pipe: Any, prefix: str, month_start: date, expire: Optional[int] = None) -> None:
    """Reopen a month's user metrics row, in the given pipeline, so the next refresh rebuilds the month.

    Args:
        pipe (Any): The pipeline of the day rebuilt in the month.
        prefix (str): The prefix of the metrics keys.
        month_start (date): The first day of the month.
        expire (Optional[int]): The TTL of the key in seconds.
    """
    _reopen_metrics_row(pipe, prefix, month_start, "monthly", expire)


def reopen_metrics_days_from(
    pipe: Any, prefix: str, everyone_record_ids: List[str], starting_date: date, expire: Optional[int] = None
) -> None:
    """Reopen every day's everyone row of the user metrics table from the given date on, as a write reopens a day,
    in the given pipeline, so the next calculation rebuilds them.

    Args:
        pipe (Any): The pipeline to reopen in.
        prefix (str): The prefix of the metrics keys.
        everyone_record_ids (List[str]): The ids of the everyone rows.
        starting_date (date): The first day to reopen.
        expire (Optional[int]): The TTL of the keys in seconds.
    """
    for day, aggregation_period in map(metrics_record_key, everyone_record_ids):
        if aggregation_period == "daily" and day >= starting_date:
            reopen_metrics_day(pipe, prefix, day, expire)


def _build_component_metrics_run_data(run_data: Dict[str, Any]) -> Dict[str, Any]:
    """The run_data of a stored run, or of a run nested inside it, with only what component metrics count."""
    metrics = run_data.get("metrics") or {}
    trimmed_metrics = {
        key: metrics[key]
        for key in list(METRICS_TOKEN_FIELDS) + ["cost", "additional_metrics", "duration", "time_to_first_token"]
        if metrics.get(key) is not None
    }
    # Of the details, only the id, provider and cost of each model the call used
    details = metrics.get("details")
    trimmed_metrics["details"] = (
        {
            model_type: [
                {
                    "id": model_metrics.get("id"),
                    "provider": model_metrics.get("provider"),
                    "cost": model_metrics.get("cost"),
                }
                for model_metrics in model_type_metrics
                if isinstance(model_metrics, dict)
            ]
            if isinstance(model_type_metrics, list)
            else []
            for model_type, model_type_metrics in details.items()
        }
        if isinstance(details, dict)
        else bool(details)
    )
    trimmed: Dict[str, Any] = {
        "run_id": run_data.get("run_id"),
        "agent_id": run_data.get("agent_id"),
        "team_id": run_data.get("team_id"),
        "session_id": run_data.get("session_id"),
        "parent_run_id": run_data.get("parent_run_id"),
        "metrics": trimmed_metrics,
        "model": run_data.get("model"),
        "model_provider": run_data.get("model_provider"),
        "forked_from_session_id": run_data.get("forked_from_session_id"),
        # Only each request's duration, skipping messages carried over from an earlier run: those from history,
        # and those a forked run copied from the run it was forked from
        "messages": [
            {"role": "assistant", "metrics": {"duration": message["metrics"]["duration"]}}
            for message in (run_data.get("messages") or [])[run_data.get("forked_from_message_index") or 0 :]
            if isinstance(message, dict)
            and message.get("role") == "assistant"
            and not message.get("from_history")
            and (message.get("metrics") or {}).get("duration") is not None
        ],
    }
    for key in _METRICS_NESTED_RUN_KEYS:
        nested = run_data.get(key)
        # A workflow agent's run is stored as the run itself, the other nested runs in lists
        if isinstance(nested, dict):
            trimmed[key] = _build_component_metrics_run_data(nested)
        elif isinstance(nested, list) and nested:
            trimmed[key] = [
                _build_component_metrics_run_data(nested_run) for nested_run in nested if isinstance(nested_run, dict)
            ]
    return trimmed


def build_component_metrics_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """Build a run with only what component metrics count from a record of the runs table.

    Args:
        run (Dict[str, Any]): The run, as stored.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_component_metrics reads: no message content, and of
            the metrics only the token counts, the cost, the timings and the models of the details.
    """
    return {
        "run_id": run.get("run_id"),
        "session_id": run.get("session_id"),
        "run_type": run.get("run_type"),
        "agent_id": run.get("agent_id"),
        "team_id": run.get("team_id"),
        "workflow_id": run.get("workflow_id"),
        "user_id": run.get("user_id"),
        "parent_run_id": metrics_parent_run_id(run),
        "status": run.get("status"),
        "run_data": _build_component_metrics_run_data(run.get("run_data") or {}),
        "created_at": run.get("created_at"),
    }


def build_component_metrics_legacy_runs(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the runs kept in the legacy runs field of a session, as runs table records with only what component
    metrics count, each reduced before the next one is read."""
    return [build_component_metrics_run(legacy_run) for legacy_run in get_metrics_legacy_runs([session])]


def build_component_metrics_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Build a session with only what component metrics count from a record of the sessions table.

    Args:
        session (Dict[str, Any]): The session, as stored.

    Returns:
        Dict[str, Any]: The session with its type, its owner, its agent, team or workflow, and its metadata.
    """
    return {
        "session_id": session.get("session_id"),
        "session_type": session.get("session_type"),
        "user_id": session.get("user_id"),
        "agent_id": session.get("agent_id"),
        "team_id": session.get("team_id"),
        "workflow_id": session.get("workflow_id"),
        "metadata": session.get("metadata"),
        "created_at": session.get("created_at"),
    }
