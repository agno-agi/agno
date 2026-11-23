"""Utility functions for the Valkey database class."""

import hashlib
import json
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union, cast
from uuid import UUID

from agno.db.filter_converter import DATETIME_COLUMNS, MAX_FILTER_DEPTH, _normalize_datetime_value
from agno.db.utils import (
    METRICS_NESTED_RUN_KEYS,
    METRICS_REFRESH_ID,
    build_aggregate_metrics_row,
    get_sort_value,
)
from agno.utils.log import log_warning

try:
    from glide_sync import ClusterScanCursor, ExpirySet, ExpiryType, GlideClusterClient, Script

    ValkeyClusterClient: type = GlideClusterClient
except ImportError:
    raise ImportError("`valkey-glide-sync` not installed. Please install it using `pip install valkey-glide-sync`")

if TYPE_CHECKING:
    from glide_sync import GlideClient as ValkeyClientType
    from glide_sync import GlideClusterClient as ValkeyClusterClientType

    AnyValkeyClient = Union[ValkeyClientType, ValkeyClusterClientType]


# Kept small: a batch is a single request, which the client waits 250 milliseconds for by default
VALKEY_BATCH_LIMIT = 100


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

    # Helper namespaces, matched by prefix so a record id that merely contains one
    # of these markers is not dropped from the results
    index_prefix = f"{prefix}:{table_type}:index:"
    runs_by_session_prefix = f"{prefix}:runs:by_session:"

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
                if key_str.startswith(index_prefix):
                    continue
                # Skip helper indexes maintained by the v3+ runs collection
                # (e.g. `<prefix>:runs:by_session:<session_id>` sorted-set indexes)
                if key_str.startswith(runs_by_session_prefix):
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
                if key_str.startswith(index_prefix):
                    continue
                # Skip helper indexes maintained by the v3+ runs collection
                # (e.g. `<prefix>:runs:by_session:<session_id>` sorted-set indexes)
                if key_str.startswith(runs_by_session_prefix):
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

# The metrics refresh is claimed, heartbeated and released, and the rows of a calculation written, by one script each,
# so the check that the calculation holds the refresh and the write run as one step on the server. A GLIDE client sends
# every caller's commands over one connection, so a WATCH would be lifted by another thread's transaction.
_CLAIM_METRICS_REFRESH_LUA = """
local now = tonumber(redis.call('TIME')[1])
local stored = redis.call('GET', KEYS[1])
local row = {id = ARGV[2], finished_at = cjson.null, fingerprint = cjson.null}
if stored then
  row = cjson.decode(stored)
  -- A stale lock is taken over: the process that held it stopped
  if row['locked_by'] ~= cjson.null and row['locked_at'] > now - tonumber(ARGV[3]) then
    return false
  end
end
row['locked_by'] = ARGV[1]
row['locked_at'] = now
row['started_at'] = now
row['status'] = 'running'
row['error'] = cjson.null
local encoded = cjson.encode(row)
redis.call('SET', KEYS[1], encoded)
return encoded
"""

_HEARTBEAT_METRICS_REFRESH_LUA = """
local stored = redis.call('GET', KEYS[1])
if not stored then
  return 0
end
local row = cjson.decode(stored)
if row['locked_by'] ~= ARGV[1] then
  return 0
end
row['locked_at'] = tonumber(redis.call('TIME')[1])
redis.call('SET', KEYS[1], cjson.encode(row))
return 1
"""

_RELEASE_METRICS_REFRESH_LUA = """
local stored = redis.call('GET', KEYS[1])
if ARGV[1] == '' and not stored then
  -- Before any refresh there is no row to update
  local now = tonumber(redis.call('TIME')[1])
  local row = {
    id = ARGV[6], locked_by = cjson.null, locked_at = cjson.null, started_at = now, finished_at = cjson.null,
    fingerprint = cjson.null, status = 'failed', error = ARGV[4]
  }
  redis.call('SET', KEYS[1], cjson.encode(row))
  return 1
end
if not stored then
  return 0
end
local row = cjson.decode(stored)
-- An empty ARGV[1] writes the row only while no process holds it
local holder = cjson.null
if ARGV[1] ~= '' then
  holder = ARGV[1]
end
if row['locked_by'] ~= holder then
  return 0
end
row['locked_by'] = cjson.null
row['locked_at'] = cjson.null
if ARGV[2] == 'stopped' then
  -- The days it did not reach stay open for the next calculation; a first one that stopped has none to show
  if row['finished_at'] == cjson.null then
    row['status'] = 'failed'
    row['error'] = ARGV[4]
  else
    row['status'] = 'completed'
    row['error'] = cjson.null
  end
elseif ARGV[2] == 'completed' then
  row['status'] = 'completed'
  row['error'] = cjson.null
  row['finished_at'] = tonumber(redis.call('TIME')[1])
  local stored_fingerprint = row['fingerprint']
  row['fingerprint'] = cjson.decode(ARGV[3])
  -- A rebuild that marked the fingerprint after the claim keeps its mark, so the next calculation rebuilds
  -- yesterday and today. Compared value by value: cjson and json.dumps encode a list with different separators
  local changed = type(stored_fingerprint) == 'table'
  if ARGV[5] ~= 'null' then
    local claimed = cjson.decode(ARGV[5])
    changed = not changed or #stored_fingerprint ~= #claimed
    local index = 1
    while not changed and index <= #claimed do
      changed = stored_fingerprint[index] ~= claimed[index]
      index = index + 1
    end
  end
  if changed then
    row['fingerprint'] = stored_fingerprint
  end
else
  row['status'] = 'failed'
  row['error'] = ARGV[4]
end
redis.call('SET', KEYS[1], cjson.encode(row))
return 1
"""

_MARK_METRICS_REFRESH_REBUILD_LUA = """
local stored = redis.call('GET', KEYS[1])
if not stored then
  return 0
end
local row = cjson.decode(stored)
row['fingerprint'] = cjson.decode(ARGV[1])
redis.call('SET', KEYS[1], cjson.encode(row))
return 1
"""

# Runs the recorded writes, each [command, index of its key in KEYS, arguments...], while ARGV[1] holds the refresh
_FENCED_METRICS_WRITES_LUA = """
local stored = redis.call('GET', KEYS[1])
if not stored or cjson.decode(stored)['locked_by'] ~= ARGV[1] then
  return 0
end
for _, command in ipairs(cjson.decode(ARGV[2])) do
  command[2] = KEYS[command[2]]
  redis.call(unpack(command))
end
return 1
"""

# The everyone row stays completed only while it still has the version read before its period's rows, as
# aggregate_metrics_row_to_store keeps it; created_at is never overwritten
_UPSERT_AGGREGATE_METRICS_ROW_LUA = """
local stored = redis.call('GET', KEYS[1])
if not stored or cjson.decode(stored)['locked_by'] ~= ARGV[1] then
  return 0
end
local fields = cjson.decode(ARGV[3])
local version = redis.call('HGET', KEYS[2], 'version')
if version then
  if ARGV[2] == '' or tonumber(version) ~= tonumber(ARGV[2]) then
    fields['completed'] = 'false'
  end
  local created_at = redis.call('HGET', KEYS[2], 'created_at')
  if created_at then
    fields['created_at'] = created_at
  end
  fields['version'] = tostring(tonumber(version) + 1)
else
  fields['version'] = '1'
end
for column, value in pairs(fields) do
  redis.call('HSET', KEYS[2], column, value)
end
if ARGV[4] ~= '' then
  redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
end
redis.call('SADD', KEYS[3], ARGV[5])
redis.call('SADD', KEYS[4], ARGV[5])
return 1
"""

_CLAIM_METRICS_REFRESH_SCRIPT = Script(_CLAIM_METRICS_REFRESH_LUA)
_HEARTBEAT_METRICS_REFRESH_SCRIPT = Script(_HEARTBEAT_METRICS_REFRESH_LUA)
_RELEASE_METRICS_REFRESH_SCRIPT = Script(_RELEASE_METRICS_REFRESH_LUA)
_MARK_METRICS_REFRESH_REBUILD_SCRIPT = Script(_MARK_METRICS_REFRESH_REBUILD_LUA)
_FENCED_METRICS_WRITES_SCRIPT = Script(_FENCED_METRICS_WRITES_LUA)
_UPSERT_AGGREGATE_METRICS_ROW_SCRIPT = Script(_UPSERT_AGGREGATE_METRICS_ROW_LUA)


class MetricsWrites:
    """The writes of metrics rows, recorded as a GLIDE batch records them, so _FENCED_METRICS_WRITES_LUA runs them in
    one step with the check that the calculation still holds the metrics refresh."""

    def __init__(self, refresh_key: str):
        self.keys: List[Any] = [refresh_key]
        self.commands: List[List[Any]] = []

    def _add(self, command: str, key: str, *args: Any) -> None:
        if key not in self.keys:
            self.keys.append(key)
        # Lua tables count from 1
        self.commands.append([command, self.keys.index(key) + 1, *args])

    def set(self, key: str, value: str, expiry: Optional[ExpirySet] = None) -> None:
        self._add("SET", key, value, *(expiry.get_cmd_args() if expiry is not None else []))

    def delete(self, keys: List[str]) -> None:
        for key in keys:
            self._add("DEL", key)

    def sadd(self, key: str, members: List[str]) -> None:
        self._add("SADD", key, *members)

    def srem(self, key: str, members: List[str]) -> None:
        self._add("SREM", key, *members)

    def hset(self, key: str, field_value_map: Dict[str, str]) -> None:
        self._add("HSET", key, *[item for field_value in field_value_map.items() for item in field_value])

    def hsetnx(self, key: str, field: str, value: str) -> None:
        self._add("HSETNX", key, field, value)

    def hincrby(self, key: str, field: str, amount: int) -> None:
        self._add("HINCRBY", key, field, amount)

    def expire(self, key: str, seconds: int) -> None:
        self._add("EXPIRE", key, seconds)


def generate_created_at_index_key(prefix: str, table_type: str) -> str:
    """Generate the key of the sorted set that lists the records of a table by created_at, so the records of a day are
    read without scanning the table."""
    return f"{prefix}:{table_type}:index:created_at"


def generate_metrics_prefix(prefix: str) -> str:
    """Generate the prefix of every key of the metrics tables. The braces make it the keys' hash tag, so they share one
    cluster slot and a script can write a batch of metrics rows together with the metrics refresh."""
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


def aggregate_metrics_record_id(aggregation_period: str, row_date: date, user_id: str) -> str:
    """The id of the key a row of the aggregate metrics table is stored under, one per period, day and user."""
    user_segment = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"{row_date.isoformat()}_{user_segment}_{aggregation_period}"


def metrics_record_key(record_id: Any) -> Tuple[date, str]:
    """Read the day and the period off the id of a component metrics or aggregate metrics row."""
    record_id = _decode_value(record_id)
    return date.fromisoformat(record_id[:10]), record_id.rsplit("_", 1)[1]


def metrics_day_start(day: date) -> int:
    """The timestamp of the start of the given UTC day."""
    return int(datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())


def deserialize_component_metrics_record(data: Any) -> Dict[str, Any]:
    """Deserialize a stored component metrics row, with its day read back as a date."""
    record = deserialize_data(_decode_value(data))
    record["date"] = date.fromisoformat(record["date"])
    return record


def serialize_aggregate_metrics_record(record: Dict[str, Any]) -> Dict[str, str]:
    """Serialize each column of an aggregate metrics row to a field of the hash it is stored in."""
    return {column: json.dumps(value, ensure_ascii=False, cls=CustomEncoder) for column, value in record.items()}


def deserialize_aggregate_metrics_record(fields: Dict[Any, Any]) -> Dict[str, Any]:
    """Deserialize the fields of a stored aggregate metrics row, with its day read back as a date."""
    record = {
        _decode_value(column): json.loads(_decode_value(value)) for column, value in fields.items() if value is not None
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
        key = generate_valkey_key(prefix=prefix, table_type="component_metrics", key_id=record_id)
        expiry = ExpirySet(ExpiryType.SEC, expire) if expire is not None else None
        pipe.set(key, serialize_data(record), expiry=expiry)
        create_index_entries(
            valkey_client=pipe,
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
            valkey_client=pipe,
            prefix=prefix,
            table_type="component_metrics",
            record_id=record_id,
            record_data=record,
            index_fields=["date", "user_id"],
        )
        pipe.delete([generate_valkey_key(prefix=prefix, table_type="component_metrics", key_id=record_id)])


def upsert_aggregate_metrics_row(
    valkey_client: "AnyValkeyClient",
    prefix: str,
    aggregate_metrics_row: Dict[str, Any],
    read_version: Optional[int],
    worker_id: str,
    expire: Optional[int] = None,
) -> bool:
    """Upsert an aggregate metrics row into the database, only while the given worker still holds the metrics refresh.

    The holder check, the version compare and the write run in one script on the server, so no write of another
    process or another thread lands between them.

    Args:
        valkey_client (GlideClient): The Valkey GLIDE client.
        prefix (str): The prefix of the metrics keys.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
        worker_id (str): The id of the calculation that holds the metrics refresh.
        expire (Optional[int]): The TTL of the key in seconds.

    Returns:
        bool: False when another process took the metrics refresh over, and nothing was written.
    """
    record_id = aggregate_metrics_record_id(
        aggregate_metrics_row["aggregation_period"], aggregate_metrics_row["date"], aggregate_metrics_row["user_id"]
    )
    written = valkey_client.invoke_script(
        _UPSERT_AGGREGATE_METRICS_ROW_SCRIPT,
        keys=[
            generate_valkey_key(prefix=prefix, table_type="metrics_refreshes", key_id=METRICS_REFRESH_ID),
            generate_valkey_key(prefix=prefix, table_type="aggregate_metrics", key_id=record_id),
            generate_index_key(prefix, "aggregate_metrics", "date", str(aggregate_metrics_row["date"])),
            generate_index_key(prefix, "aggregate_metrics", "user_id", aggregate_metrics_row["user_id"]),
        ],
        args=[
            worker_id,
            str(read_version) if read_version is not None else "",
            json.dumps(serialize_aggregate_metrics_record(aggregate_metrics_row)),
            str(expire) if expire is not None else "",
            record_id,
        ],
    )
    return written == 1


def bulk_upsert_aggregate_metrics_rows(
    pipe: Any, prefix: str, aggregate_metrics_rows: List[Dict[str, Any]], expire: Optional[int] = None
) -> None:
    """Upsert the user rows of a period into the aggregate metrics table, in the given pipeline.

    A user row is written with its period's everyone row, so its completed is never compared. Every write moves its
    version by one in the same pipeline, so two writers never give it the same version, and created_at is never
    overwritten.

    Args:
        pipe (Any): The pipeline to upsert in.
        prefix (str): The prefix of the metrics keys.
        aggregate_metrics_rows (List[Dict[str, Any]]): The user rows, from build_aggregate_metrics_rows.
        expire (Optional[int]): The TTL of the keys in seconds.
    """
    for aggregate_metrics_row in aggregate_metrics_rows:
        record_id = aggregate_metrics_record_id(
            aggregate_metrics_row["aggregation_period"], aggregate_metrics_row["date"], aggregate_metrics_row["user_id"]
        )
        key = generate_valkey_key(prefix=prefix, table_type="aggregate_metrics", key_id=record_id)
        fields = serialize_aggregate_metrics_record(aggregate_metrics_row)
        created_at = fields.pop("created_at")
        pipe.hset(key, fields)
        pipe.hsetnx(key, "created_at", created_at)
        pipe.hincrby(key, "version", 1)
        if expire is not None:
            pipe.expire(key, expire)
        create_index_entries(
            valkey_client=pipe,
            prefix=prefix,
            table_type="aggregate_metrics",
            record_id=record_id,
            record_data=aggregate_metrics_row,
            index_fields=["date", "user_id"],
        )


def delete_aggregate_metrics_rows(pipe: Any, prefix: str, aggregate_metrics_rows: List[Dict[str, Any]]) -> None:
    """Delete the given stored user rows of the aggregate metrics table, in the given pipeline.

    Args:
        pipe (Any): The pipeline to delete in.
        prefix (str): The prefix of the metrics keys.
        aggregate_metrics_rows (List[Dict[str, Any]]): The stored rows to delete.
    """
    for aggregate_metrics_row in aggregate_metrics_rows:
        record_id = aggregate_metrics_record_id(
            aggregate_metrics_row["aggregation_period"], aggregate_metrics_row["date"], aggregate_metrics_row["user_id"]
        )
        remove_index_entries(
            valkey_client=pipe,
            prefix=prefix,
            table_type="aggregate_metrics",
            record_id=record_id,
            record_data=aggregate_metrics_row,
            index_fields=["date", "user_id"],
        )
        pipe.delete([generate_valkey_key(prefix=prefix, table_type="aggregate_metrics", key_id=record_id)])


def _reopen_metrics_row(pipe: Any, prefix: str, row_date: date, aggregation_period: str, expire: Optional[int]) -> None:
    """Add the reopen of a day's or a month's everyone row of the aggregate metrics table to the given pipeline.

    Every field of an empty open row is set only where the row has none, then the row is opened and its version moved
    by one, so the reopen never reads the row: a period with no row gets an empty open row at version 1.
    """
    record_id = aggregate_metrics_record_id(aggregation_period, row_date, "")
    key = generate_valkey_key(prefix=prefix, table_type="aggregate_metrics", key_id=record_id)
    empty_row = {**build_aggregate_metrics_row([], aggregation_period, row_date, completed=False), "version": 0}
    for column, value in serialize_aggregate_metrics_record(empty_row).items():
        pipe.hsetnx(key, column, value)
    pipe.hset(key, {"completed": json.dumps(False)})
    pipe.hincrby(key, "version", 1)
    if expire is not None:
        pipe.expire(key, expire)
    create_index_entries(
        valkey_client=pipe,
        prefix=prefix,
        table_type="aggregate_metrics",
        record_id=record_id,
        record_data=empty_row,
        index_fields=["date", "user_id"],
    )


def reopen_metrics_day(pipe: Any, prefix: str, day: date, expire: Optional[int] = None) -> None:
    """Reopen a day's aggregate metrics row, in the given pipeline, so the next calculation rebuilds the day.

    Args:
        pipe (Any): The pipeline of the write that changed the day.
        prefix (str): The prefix of the metrics keys.
        day (date): The day, from metrics_day_to_reopen.
        expire (Optional[int]): The TTL of the key in seconds.
    """
    _reopen_metrics_row(pipe, prefix, day, "daily", expire)


def reopen_metrics_month(pipe: Any, prefix: str, month_start: date, expire: Optional[int] = None) -> None:
    """Reopen a month's aggregate metrics row, in the given pipeline, so the next calculation rebuilds the month.

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
    """Reopen every day's everyone row of the aggregate metrics table from the given date on, as a write reopens a day,
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


def _build_component_metrics_tool_calls(run_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each tool call of a stored run with only what tool_metrics counts, skipping those a forked run copied, never its
    arguments or result."""
    # The id of each tool call answered in the first messages, the ones a forked run copied from the run it was forked
    # from
    copied_tool_call_ids = {
        message["tool_call_id"]
        for message in (run_data.get("messages") or [])[: run_data.get("forked_from_message_index") or 0]
        if isinstance(message, dict) and message.get("role") == "tool" and message.get("tool_call_id")
    }
    return [
        {
            "toolkit": tool_call.get("toolkit"),
            "tool_name": tool_call.get("tool_name"),
            "tool_call_error": tool_call.get("tool_call_error"),
            "requires_confirmation": tool_call.get("requires_confirmation"),
            "confirmed": tool_call.get("confirmed"),
            "requires_user_input": tool_call.get("requires_user_input"),
            "external_execution_required": tool_call.get("external_execution_required"),
            "metrics": {"duration": (tool_call.get("metrics") or {}).get("duration")},
        }
        for tool_call in run_data.get("tools") or []
        if isinstance(tool_call, dict) and tool_call.get("tool_call_id") not in copied_tool_call_ids
    ]


def _build_component_metrics_run_data(run_data: Dict[str, Any]) -> Dict[str, Any]:
    """The run_data of a stored run, or of a run nested inside it, with only what component metrics count."""
    trimmed: Dict[str, Any] = {
        "run_id": run_data.get("run_id"),
        "agent_id": run_data.get("agent_id"),
        "team_id": run_data.get("team_id"),
        "session_id": run_data.get("session_id"),
        "parent_run_id": run_data.get("parent_run_id"),
        "metrics": run_data.get("metrics"),
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
        "tools": _build_component_metrics_tool_calls(run_data),
    }
    for key in METRICS_NESTED_RUN_KEYS:
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
            the tool calls only what tool_metrics counts.
    """
    return {
        "run_id": run.get("run_id"),
        "session_id": run.get("session_id"),
        "run_type": run.get("run_type"),
        "agent_id": run.get("agent_id"),
        "team_id": run.get("team_id"),
        "workflow_id": run.get("workflow_id"),
        "user_id": run.get("user_id"),
        "parent_run_id": run.get("parent_run_id"),
        "status": run.get("status"),
        "run_data": _build_component_metrics_run_data(run.get("run_data") or {}),
        "created_at": run.get("created_at"),
    }


def build_component_metrics_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Build a session with only what component metrics count from a record of the sessions table.

    Args:
        session (Dict[str, Any]): The session, as stored.

    Returns:
        Dict[str, Any]: The session with its type, its owner, its agent, team or workflow, its metadata, and the
            compaction metrics of its session_data.
    """
    return {
        "session_id": session.get("session_id"),
        "session_type": session.get("session_type"),
        "user_id": session.get("user_id"),
        "agent_id": session.get("agent_id"),
        "team_id": session.get("team_id"),
        "workflow_id": session.get("workflow_id"),
        "metadata": session.get("metadata"),
        "compaction_metrics": (session.get("session_data") or {}).get("compaction_metrics"),
        "created_at": session.get("created_at"),
    }
