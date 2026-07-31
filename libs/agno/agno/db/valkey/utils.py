"""Utility functions for the Valkey database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union, cast
from uuid import UUID

from agno.db.filter_converter import DATETIME_COLUMNS, MAX_FILTER_DEPTH, _normalize_datetime_value
from agno.db.utils import get_sort_value
from agno.utils.log import log_warning

try:
    from glide_sync import ClusterScanCursor, GlideClusterClient

    ValkeyClusterClient: type = GlideClusterClient
except ImportError:
    raise ImportError("`valkey-glide-sync` not installed. Please install it using `pip install valkey-glide-sync`")

if TYPE_CHECKING:
    from glide_sync import GlideClient as ValkeyClientType
    from glide_sync import GlideClusterClient as ValkeyClusterClientType

    AnyValkeyClient = Union[ValkeyClientType, ValkeyClusterClientType]


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


# -- Valkey utils --


def generate_valkey_key(prefix: str, table_type: str, key_id: str) -> str:
    """Generate Valkey key with proper namespacing."""
    return f"{prefix}:{table_type}:{key_id}"


def generate_index_key(prefix: str, table_type: str, index_field: str, index_value: str) -> str:
    """Generate Valkey key for index entries."""
    return f"{prefix}:{table_type}:index:{index_field}:{index_value}"


def get_all_keys_for_table(valkey_client: "AnyValkeyClient", prefix: str, table_type: str) -> List[str]:
    """Get all relevant keys for the given table type.

    Args:
        valkey_client (GlideClient): The Valkey GLIDE client.
        prefix (str): The prefix for the keys.
        table_type (str): The table type.

    Returns:
        List[str]: A list of all relevant keys for the given table type.
    """
    pattern = f"{prefix}:{table_type}:*"
    relevant_keys: List[str] = []

    if isinstance(valkey_client, ValkeyClusterClient):
        # Cluster client uses ClusterScanCursor with .is_finished()
        cluster_cursor = ClusterScanCursor()
        while not cluster_cursor.is_finished():
            cluster_client = cast("ValkeyClusterClientType", valkey_client)
            scan_result = cluster_client.scan(cluster_cursor, match=pattern, count=1000)
            cluster_cursor = cast(ClusterScanCursor, scan_result[0])
            cluster_keys = cast(List[bytes], scan_result[1])
            for key in cluster_keys:
                key_str = _decode_value(key)
                if ":index:" in key_str:
                    continue
                relevant_keys.append(key_str)
    else:
        # Standalone client uses a string cursor starting at "0"
        cursor = "0"
        while True:
            standalone_client = cast("ValkeyClientType", valkey_client)
            result = standalone_client.scan(cursor=cursor, match=pattern, count=1000)
            # scan returns [cursor_bytes, [keys]]
            new_cursor = cast(bytes, result[0])
            scan_keys = cast(List[bytes], result[1]) if len(result) > 1 else []

            for key in scan_keys:
                key_str = _decode_value(key)
                if ":index:" in key_str:
                    continue
                relevant_keys.append(key_str)

            cursor = new_cursor.decode("utf-8") if isinstance(new_cursor, bytes) else str(new_cursor)
            if cursor == "0":
                break

    return relevant_keys


def _decode_value(val: Any) -> str:
    """Decode a bytes value to string if needed."""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


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
        log_warning(f"Error sorting Valkey records: {str(e)}")
        return records


def apply_pagination(
    records: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
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


# -- FilterExpr matching --


def record_matches_filter_expr(
    record: Dict[str, Any],
    filter_dict: Dict[str, Any],
    allowed_keys: Optional[Set[str]] = None,
    _depth: int = 0,
) -> bool:
    """Evaluate a serialized FilterExpr dict against a record dict.

    Python-side counterpart of filter_expr_to_sqlalchemy for records fetched
    from Valkey, with matching semantics: None record values never match a
    single-field operator (SQL NULL behavior), CONTAINS/STARTSWITH are
    case-insensitive, and datetime filter values are normalized to UTC.

    Args:
        record: The record to evaluate.
        filter_dict: Serialized FilterExpr (from to_dict() or JSON body).
        allowed_keys: Set of allowed field names for validation.
            If provided, raises ValueError for unknown fields.
        _depth: Internal parameter tracking recursion depth. Do not pass manually.

    Returns:
        bool: True if the record matches the filter expression.

    Raises:
        ValueError: If filter_dict has invalid structure, unknown operator,
            references a field not in allowed_keys, or exceeds max recursion depth.
    """
    # A record matches only when the expression evaluates to True; a comparison against a
    # missing field is UNKNOWN (None) and, like SQL's WHERE clause, is not a match.
    return _eval_filter_expr(record, filter_dict, allowed_keys, _depth) is True


def _eval_filter_expr(
    record: Dict[str, Any],
    filter_dict: Dict[str, Any],
    allowed_keys: Optional[Set[str]],
    _depth: int,
) -> Optional[bool]:
    """Evaluate a FilterExpr dict with SQL three-valued logic.

    Returns True/False, or None for UNKNOWN when a single-field operator is applied to a
    missing (None) record value. AND/OR/NOT propagate UNKNOWN the way SQL does, so that a
    NOT over a missing field stays UNKNOWN (excluded) instead of flipping to a match.
    """
    if _depth > MAX_FILTER_DEPTH:
        raise ValueError(f"Filter expression exceeds maximum nesting depth of {MAX_FILTER_DEPTH}")

    if not isinstance(filter_dict, dict) or "op" not in filter_dict:
        raise ValueError(f"Invalid filter: must be a dict with 'op' key. Got: {filter_dict}")

    op = filter_dict["op"]

    if op in ("EQ", "NEQ", "GT", "GTE", "LT", "LTE", "CONTAINS", "STARTSWITH"):
        key = filter_dict.get("key")
        value = filter_dict.get("value")

        if key is None or value is None:
            raise ValueError(f"{op} filter requires 'key' and 'value' fields. Got: {filter_dict}")

        if allowed_keys and key not in allowed_keys:
            raise ValueError(f"Invalid filter field: '{key}'. Allowed: {sorted(allowed_keys)}")

        if key in DATETIME_COLUMNS:
            value = _normalize_datetime_value(value)

        record_value = record.get(key)
        if record_value is None:
            return None

        try:
            if op == "EQ":
                return record_value == value
            elif op == "NEQ":
                return record_value != value
            elif op == "GT":
                return record_value > value
            elif op == "GTE":
                return record_value >= value
            elif op == "LT":
                return record_value < value
            elif op == "LTE":
                return record_value <= value
            elif op == "CONTAINS":
                return str(value).lower() in str(record_value).lower()
            elif op == "STARTSWITH":
                return str(record_value).lower().startswith(str(value).lower())
        except TypeError:
            return False

    elif op == "IN":
        key = filter_dict.get("key")
        values = filter_dict.get("values")

        if key is None or values is None:
            raise ValueError(f"IN filter requires 'key' and 'values' fields. Got: {filter_dict}")

        if allowed_keys and key not in allowed_keys:
            raise ValueError(f"Invalid filter field: '{key}'. Allowed: {sorted(allowed_keys)}")

        if key in DATETIME_COLUMNS:
            values = [_normalize_datetime_value(v) for v in values]

        record_value = record.get(key)
        if record_value is None:
            return None
        return record_value in values

    elif op == "AND":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"AND filter requires 'conditions' field. Got: {filter_dict}")
        # Evaluate all branches (no short-circuit) so invalid sub-expressions always raise
        results = [_eval_filter_expr(record, c, allowed_keys, _depth + 1) for c in conditions]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True

    elif op == "OR":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"OR filter requires 'conditions' field. Got: {filter_dict}")
        # Evaluate all branches (no short-circuit) so invalid sub-expressions always raise
        results = [_eval_filter_expr(record, c, allowed_keys, _depth + 1) for c in conditions]
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False

    elif op == "NOT":
        condition = filter_dict.get("condition")
        if not condition:
            raise ValueError(f"NOT filter requires 'condition' field. Got: {filter_dict}")
        inner = _eval_filter_expr(record, condition, allowed_keys, _depth + 1)
        return None if inner is None else not inner

    raise ValueError(f"Unknown filter operator: {op}")


def validate_filter_expr(filter_dict: Dict[str, Any], allowed_keys: Optional[Set[str]] = None) -> None:
    """Validate a FilterExpr dict structure without matching any record.

    Evaluating against an empty record exercises the full expression tree
    (operator, key and depth validation) so invalid filters raise ValueError
    even when there are no records to evaluate.
    """
    record_matches_filter_expr({}, filter_dict, allowed_keys)


def create_index_entries(
    valkey_client: "AnyValkeyClient",
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            cast("ValkeyClientType", valkey_client).sadd(index_key, [record_id])


def remove_index_entries(
    valkey_client: "AnyValkeyClient",
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            cast("ValkeyClientType", valkey_client).srem(index_key, [record_id])


# -- Metrics utils --


def calculate_date_metrics(date_to_process: date, sessions_data: dict, user_isolation: bool = False) -> List[dict]:
    """Calculate metrics for the given date, bucketed per user_id.

    Each session is attributed to its owning user when user_isolation is
    enabled. Sessions without a user_id aggregate under the sentinel
    empty-string bucket.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data.
        user_isolation (bool): Whether to bucket metrics per user_id.

    Returns:
        List[dict]: A list of per-user metrics records.
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
            "user_ids": set(),
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
            session_user_id = session.get("user_id") or ""
            bucket_key = session_user_id if user_isolation else ""
            bucket = per_user.setdefault(bucket_key, _empty_metric_record())
            if session_user_id:
                bucket["user_ids"].add(session_user_id)
            bucket[sessions_count_key] += 1

            runs = session.get("runs") or []
            bucket[runs_count_key] += len(runs)
            for run in runs:
                if model_id := run.get("model"):
                    model_provider = run.get("model_provider", "")
                    key = f"{model_id}:{model_provider}"
                    bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            session_metrics = (session.get("session_data") or {}).get("session_metrics", {})
            for field in bucket["token_metrics"]:
                bucket["token_metrics"][field] += session_metrics.get(field, 0)

    current_time = int(time.time())
    completed = date_to_process < datetime.now(timezone.utc).date()

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        users_count = len(bucket["user_ids"])
        # Create a deterministic ID based on date and user. This simplifies avoiding duplicates
        metric_id = f"{date_to_process.isoformat()}_{user_id}_daily"

        records.append(
            {
                "id": metric_id,
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
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types.

    Args:
        sessions (List[Dict[str, Any]]): The sessions data.
        dates_to_process (list[date]): The dates to process.
        start_timestamp (int): The start timestamp.

    Returns:
        Optional[dict]: A dictionary with the session data for the given dates, for all session types.
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


def get_dates_to_calculate_metrics_for(starting_date: date) -> list[date]:
    """Return the list of dates to calculate metrics for.

    Args:
        starting_date (date): The starting date.

    Returns:
        list[date]: The list of dates to calculate metrics for.
    """
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]
