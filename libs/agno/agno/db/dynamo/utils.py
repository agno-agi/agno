import json
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.utils import METRICS_REFRESH_ID, build_aggregate_metrics_row, get_sort_value
from agno.session import Session
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id


def batch_write_with_retry(
    client,
    request_items: Dict[Any, List[Dict[str, Any]]],
    max_retries: int = 5,
    initial_backoff_seconds: float = 0.1,
) -> None:
    """Wrap ``client.batch_write_item`` with exponential-backoff retries for
    ``UnprocessedItems``.

    ``batch_write_item`` returns partial success — DynamoDB may reject some
    writes due to throttling, provisioned-throughput exceeded, or other
    transient conditions, and return them in ``UnprocessedItems``. Silently
    ignoring that response causes data loss. This helper retries the
    unprocessed subset with exponential backoff and raises if some items
    are still unprocessed after ``max_retries``.
    """
    remaining = request_items
    backoff = initial_backoff_seconds
    for attempt in range(max_retries + 1):
        response = client.batch_write_item(RequestItems=remaining)
        unprocessed = response.get("UnprocessedItems") or {}
        if not unprocessed:
            return
        # Some items were rejected — retry with just those.
        remaining_counts = {t: len(v) for t, v in unprocessed.items()}
        if attempt < max_retries:
            log_warning(
                f"Dynamo batch_write_item returned UnprocessedItems "
                f"{remaining_counts}; retry {attempt + 1}/{max_retries} "
                f"after {backoff:.2f}s"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)
            remaining = unprocessed
        else:
            raise RuntimeError(
                f"DynamoDB batch_write_item still had UnprocessedItems "
                f"after {max_retries} retries: {remaining_counts}. "
                "Data loss will occur if we don't propagate this."
            )


def batch_get_with_retry(
    client,
    request_items: Dict[str, Any],
    max_retries: int = 5,
    initial_backoff_seconds: float = 0.1,
) -> Dict[str, List[Dict[str, Any]]]:
    """Wrap ``client.batch_get_item`` with exponential-backoff retries for ``UnprocessedKeys``, as
    ``batch_write_with_retry`` does for ``UnprocessedItems``. Returns the items read, by table.
    """
    responses: Dict[str, List[Dict[str, Any]]] = {}
    remaining = request_items
    backoff = initial_backoff_seconds
    for attempt in range(max_retries + 1):
        response = client.batch_get_item(RequestItems=remaining)
        for table_name, items in response.get("Responses", {}).items():
            responses.setdefault(table_name, []).extend(items)
        unprocessed = response.get("UnprocessedKeys") or {}
        if not unprocessed:
            break
        # Some keys were not read — retry with just those.
        remaining_counts = {t: len(v["Keys"]) for t, v in unprocessed.items()}
        if attempt < max_retries:
            log_warning(
                f"Dynamo batch_get_item returned UnprocessedKeys "
                f"{remaining_counts}; retry {attempt + 1}/{max_retries} "
                f"after {backoff:.2f}s"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)
            remaining = unprocessed
        else:
            raise RuntimeError(
                f"DynamoDB batch_get_item still had UnprocessedKeys after {max_retries} retries: {remaining_counts}"
            )
    return responses


# -- Serialization utils --


def serialize_to_dynamo_item(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the given dict to a valid DynamoDB item

    Args:
        data: The dict to serialize

    Returns:
        A DynamoDB-ready dict with the serialized data

    """
    item: Dict[str, Any] = {}
    for key, value in data.items():
        if value is not None:
            # bool first: bool is a subclass of int, so the numeric arm would
            # otherwise write {"N": "True"}, which DynamoDB rejects.
            if isinstance(value, bool):
                item[key] = {"BOOL": value}
            elif isinstance(value, (int, float)):
                item[key] = {"N": str(value)}
            elif isinstance(value, str):
                item[key] = {"S": value}
            elif isinstance(value, (dict, list)):
                item[key] = {"S": json.dumps(value)}
            else:
                item[key] = {"S": str(value)}
    return item


def deserialize_from_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    data = {}
    for key, value in item.items():
        if "S" in value:
            # Only dicts and lists are JSON-encoded on write; decoding anything else turns "42" into int 42.
            raw = value["S"]
            try:
                decoded = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data[key] = raw
            else:
                data[key] = decoded if isinstance(decoded, (dict, list)) else raw
        elif "N" in value:
            data[key] = float(value["N"]) if "." in value["N"] else int(value["N"])
        elif "BOOL" in value:
            data[key] = value["BOOL"]
        elif "SS" in value:
            data[key] = value["SS"]
        elif "NS" in value:
            data[key] = [float(n) if "." in n else int(n) for n in value["NS"]]
        elif "M" in value:
            data[key] = deserialize_from_dynamodb_item(value["M"])
        elif "L" in value:
            data[key] = [deserialize_from_dynamodb_item({"item": item})["item"] for item in value["L"]]
    return data


def serialize_knowledge_row(knowledge: KnowledgeRow) -> Dict[str, Any]:
    """Convert KnowledgeRow to DynamoDB item format."""
    return serialize_to_dynamo_item(
        {
            "id": knowledge.id,
            "name": knowledge.name,
            "description": knowledge.description,
            "type": getattr(knowledge, "type", None),
            "status": getattr(knowledge, "status", None),
            "status_message": getattr(knowledge, "status_message", None),
            "metadata": getattr(knowledge, "metadata", None),
            "size": getattr(knowledge, "size", None),
            "linked_to": getattr(knowledge, "linked_to", None),
            "access_count": getattr(knowledge, "access_count", None),
            "user_id": getattr(knowledge, "user_id", None),
            "created_at": int(knowledge.created_at) if knowledge.created_at else None,
            "updated_at": int(knowledge.updated_at) if knowledge.updated_at else None,
        }
    )


def deserialize_knowledge_row(item: Dict[str, Any]) -> KnowledgeRow:
    """Convert DynamoDB item to KnowledgeRow."""
    data = deserialize_from_dynamodb_item(item)
    return KnowledgeRow(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        metadata=data.get("metadata"),
        type=data.get("type"),
        size=data.get("size"),
        linked_to=data.get("linked_to"),
        access_count=data.get("access_count"),
        status=data.get("status"),
        status_message=data.get("status_message"),
        user_id=data.get("user_id"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def serialize_eval_record(eval_record: EvalRunRecord) -> Dict[str, Any]:
    """Convert EvalRunRecord to DynamoDB item format."""
    return serialize_to_dynamo_item(
        {
            "run_id": eval_record.run_id,
            "eval_type": eval_record.eval_type,
            "eval_data": eval_record.eval_data,
            "name": getattr(eval_record, "name", None),
            "agent_id": getattr(eval_record, "agent_id", None),
            "team_id": getattr(eval_record, "team_id", None),
            "workflow_id": getattr(eval_record, "workflow_id", None),
            "model_id": getattr(eval_record, "model_id", None),
            "model_provider": getattr(eval_record, "model_provider", None),
            "evaluated_component_name": getattr(eval_record, "evaluated_component_name", None),
        }
    )


def deserialize_eval_record(item: Dict[str, Any]) -> EvalRunRecord:
    """Convert DynamoDB item to EvalRunRecord."""
    data = deserialize_from_dynamodb_item(item)
    # Convert timestamp fields back to datetime
    if "created_at" in data and data["created_at"]:
        data["created_at"] = datetime.fromtimestamp(data["created_at"], tz=timezone.utc)
    if "updated_at" in data and data["updated_at"]:
        data["updated_at"] = datetime.fromtimestamp(data["updated_at"], tz=timezone.utc)
    return EvalRunRecord(run_id=data["run_id"], eval_type=data["eval_type"], eval_data=data["eval_data"])


# -- DB Utils --


def create_table_if_not_exists(dynamodb_client, table_name: str, schema: Dict[str, Any]) -> bool:
    """Create DynamoDB table if it doesn't exist."""
    try:
        dynamodb_client.describe_table(TableName=table_name)
        return True

    except dynamodb_client.exceptions.ResourceNotFoundException:
        log_info(f"Creating table {table_name}")
        try:
            dynamodb_client.create_table(**schema)
            # Wait for table to be created
            waiter = dynamodb_client.get_waiter("table_exists")
            waiter.wait(TableName=table_name)

            log_debug(f"Table {table_name} created successfully")

            return True

        except dynamodb_client.exceptions.ResourceInUseException:
            # Another process created it first: it is ready once the waiter finds it
            dynamodb_client.get_waiter("table_exists").wait(TableName=table_name)
            return True

        except Exception as e:
            log_error(f"Failed to create table {table_name}: {str(e)}")
            return False


def apply_pagination(
    items: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination to a list of items.

    Raises ``ValueError`` when ``page`` is provided without ``limit`` — see
    ``agno.db.utils.validate_pagination``.
    """
    from agno.db.utils import validate_pagination

    validate_pagination(limit, page)
    if limit is None:
        return items

    start_index = 0
    if page is not None and page > 1:
        start_index = (page - 1) * limit

    return items[start_index : start_index + limit]


def apply_sorting(
    items: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to a list of items.

    Args:
        items: The list of dictionaries to sort
        sort_by: The field to sort by (defaults to 'created_at')
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The sorted list

    Note:
        If sorting by "updated_at", will fallback to "created_at" in case of None.
    """
    if not items:
        return items

    if sort_by is None:
        sort_by = "created_at"

    is_descending = sort_order == "desc"

    # Sort using the helper function that handles updated_at -> created_at fallback
    sorted_records = sorted(
        items,
        key=lambda x: (get_sort_value(x, sort_by) is None, get_sort_value(x, sort_by)),
        reverse=is_descending,
    )

    return sorted_records


# -- Session utils --


def prepare_session_data(session: "Session", include_runs: bool = True) -> Dict[str, Any]:
    """Prepare session data for storage by serializing JSON fields and setting session type."""
    from agno.session import AgentSession, TeamSession, WorkflowSession

    serialized_session = session.to_dict(include_runs=include_runs)

    # Handle JSON fields
    json_fields = ["session_data", "memory", "tools", "functions", "additional_data"]
    for field in json_fields:
        if field in serialized_session and serialized_session[field] is not None:
            if isinstance(serialized_session[field], (dict, list)):
                serialized_session[field] = json.dumps(serialized_session[field])

    # Set the session type
    if isinstance(session, AgentSession):
        serialized_session["session_type"] = SessionType.AGENT.value
    elif isinstance(session, TeamSession):
        serialized_session["session_type"] = SessionType.TEAM.value
    elif isinstance(session, WorkflowSession):
        serialized_session["session_type"] = SessionType.WORKFLOW.value

    return serialized_session


def merge_with_existing_session(new_session: Dict[str, Any], existing_item: Dict[str, Any]) -> Dict[str, Any]:
    """Merge new session data with existing session, preserving important fields."""
    existing_session = deserialize_from_dynamodb_item(existing_item)

    # Start with existing session as base
    merged_session = existing_session.copy()

    if "session_data" in new_session:
        merged_session_data = merge_session_data(
            existing_session.get("session_data", {}), new_session.get("session_data", {})
        )
        merged_session["session_data"] = json.dumps(merged_session_data)

    for key, value in new_session.items():
        if key != "created_at" and key != "session_data" and value is not None:
            merged_session[key] = value

    # Always preserve created_at and set updated_at
    merged_session["created_at"] = existing_session.get("created_at")
    merged_session["updated_at"] = int(time.time())

    return merged_session


def merge_session_data(existing_data: Any, new_data: Any) -> Dict[str, Any]:
    """Merge session_data fields, handling JSON string conversion."""

    # Parse existing session_data
    if isinstance(existing_data, str):
        existing_data = json.loads(existing_data)
    existing_data = existing_data or {}

    # Parse new session_data
    if isinstance(new_data, str):
        new_data = json.loads(new_data)
    new_data = new_data or {}

    # Merge letting new data take precedence
    return {**existing_data, **new_data}


def deserialize_session_result(
    serialized_session: Dict[str, Any], original_session: "Session", deserialize: Optional[bool]
) -> Optional[Union["Session", Dict[str, Any]]]:
    """Deserialize the session result based on the deserialize flag and session type."""
    from agno.session import AgentSession, TeamSession, WorkflowSession

    if not deserialize:
        return serialized_session

    if isinstance(original_session, AgentSession):
        return AgentSession.from_dict(serialized_session)
    elif isinstance(original_session, TeamSession):
        return TeamSession.from_dict(serialized_session)
    elif isinstance(original_session, WorkflowSession):
        return WorkflowSession.from_dict(serialized_session)

    return None


# -- Metrics utils --


def deserialize_metrics_date(value: Any) -> Any:
    """Return a metrics record's stored day as a ``date``, the shape every other adapter returns.

    DynamoDB has no date type, so the day is written as the ISO string "2026-08-11". Readers
    render that day as a timestamp, and a string parses back without a timezone: the day then
    reads as local midnight and shifts for anyone outside UTC. A value that is not a day is
    handed back untouched, so records callers already skip keep behaving as they did.
    """
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return value
    return value


# -- Component metrics utils --


def component_metrics_record_id(row: Dict[str, Any]) -> str:
    """Return the id a component metrics row is stored under beside its date, from its user, component, parent and
    root."""
    return generate_id(
        json.dumps(
            [
                row["user_id"],
                row["component_type"],
                row["component_id"],
                row["parent_component_id"],
                row["root_component_id"],
            ]
        )
    )


def serialize_component_metrics_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a component metrics row to a DynamoDB item.

    Args:
        row: The component metrics row, as calculate_date_component_metrics builds it.

    Returns:
        A DynamoDB-ready dict. The day is written as an ISO string.
    """
    data = dict(row)
    data["id"] = component_metrics_record_id(row)
    data["date"] = row["date"].isoformat()
    return serialize_to_dynamo_item(data)


def aggregate_metrics_period_user_id(aggregation_period: str, user_id: str) -> str:
    """Return the hash key of the aggregate metrics rows of a period and user: the period alone for the everyone
    rows."""
    return f"{aggregation_period}#{user_id}" if user_id else aggregation_period


def aggregate_metrics_key(aggregation_period: str, row_date: date, user_id: str) -> Dict[str, Any]:
    """Return the key of an aggregate metrics row: its period and user, and its day."""
    return {
        "period_user_id": {"S": aggregate_metrics_period_user_id(aggregation_period, user_id)},
        "date": {"S": row_date.isoformat()},
    }


def serialize_aggregate_metrics_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize an aggregate metrics row to a DynamoDB item, with its key and its day as an ISO string, and an open
    everyone row with its period as open_period, the key of the index of the open rows."""
    item = serialize_to_dynamo_item({**row, "date": row["date"].isoformat()})
    item.update(aggregate_metrics_key(row["aggregation_period"], row["date"], row["user_id"]))
    if row["user_id"] == "" and not row["completed"]:
        item["open_period"] = {"S": row["aggregation_period"]}
    return item


def deserialize_metrics_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize a DynamoDB item to a component metrics or aggregate metrics row.

    Args:
        item: The DynamoDB item.

    Returns:
        The row, with the day as a date.
    """
    row = deserialize_from_dynamodb_item(item)
    row["date"] = deserialize_metrics_date(row.get("date"))
    return row


def heartbeat_metrics_refresh_update(table_name: str, worker_id: str) -> Dict[str, Any]:
    """Build the update that refreshes locked_at for this worker's metrics refresh, on the condition that it holds it."""
    return {
        "TableName": table_name,
        "Key": {"id": {"S": METRICS_REFRESH_ID}},
        "UpdateExpression": "SET #locked_at = :now",
        "ConditionExpression": "#locked_by = :worker_id",
        "ExpressionAttributeNames": {"#locked_by": "locked_by", "#locked_at": "locked_at"},
        "ExpressionAttributeValues": {":worker_id": {"S": worker_id}, ":now": {"N": str(int(time.time()))}},
    }


def reopen_metrics_row(dynamodb_client, table_name: str, row_date: date, aggregation_period: str) -> None:
    """Reopen a day's or a month's everyone row of the aggregate metrics table, putting an empty open row when it has
    none."""
    # Moved in the write, so two writers reopening the same row never give it the same version
    reopen_kwargs: Dict[str, Any] = {
        "TableName": table_name,
        "Key": aggregate_metrics_key(aggregation_period, row_date, ""),
        "UpdateExpression": "SET #completed = :false, #open_period = :period ADD #version :one",
        "ExpressionAttributeNames": {"#completed": "completed", "#open_period": "open_period", "#version": "version"},
        "ExpressionAttributeValues": {
            ":false": {"BOOL": False},
            ":period": {"S": aggregation_period},
            ":one": {"N": "1"},
        },
    }
    try:
        dynamodb_client.update_item(**reopen_kwargs, ConditionExpression="attribute_exists(period_user_id)")
    except dynamodb_client.exceptions.ConditionalCheckFailedException:
        try:
            dynamodb_client.put_item(
                TableName=table_name,
                Item=serialize_aggregate_metrics_row(
                    {**build_aggregate_metrics_row([], aggregation_period, row_date, completed=False), "version": 1}
                ),
                ConditionExpression="attribute_not_exists(period_user_id)",
            )
        except dynamodb_client.exceptions.ConditionalCheckFailedException:
            dynamodb_client.update_item(**reopen_kwargs)


def reopen_metrics_day(dynamodb_client, table_name: str, day: date) -> None:
    """Reopen a day's everyone row of the aggregate metrics table, so the next calculation rebuilds the day.

    Args:
        dynamodb_client: DynamoDB client
        table_name: The aggregate metrics table.
        day: The day, from metrics_day_to_reopen.
    """
    reopen_metrics_row(dynamodb_client, table_name, day, "daily")


def reopen_metrics_month(dynamodb_client, table_name: str, month_start: date) -> None:
    """Reopen a month's everyone row of the aggregate metrics table, so the next calculation rebuilds the month.

    Args:
        dynamodb_client: DynamoDB client
        table_name: The aggregate metrics table.
        month_start: The first day of the month.
    """
    reopen_metrics_row(dynamodb_client, table_name, month_start, "monthly")


def reopen_metrics_days_from(dynamodb_client, table_name: str, starting_date: date) -> None:
    """Reopen every day's everyone row of the aggregate metrics table from the given date on, as a write reopens a day,
    so the next calculation rebuilds them.

    Args:
        dynamodb_client: DynamoDB client
        table_name: The aggregate metrics table.
        starting_date: The first day to reopen.
    """
    items = query_all_items(
        dynamodb_client,
        {
            "TableName": table_name,
            "KeyConditionExpression": "#period_user_id = :period AND #date >= :start_date",
            "ExpressionAttributeNames": {"#period_user_id": "period_user_id", "#date": "date"},
            "ExpressionAttributeValues": {":period": {"S": "daily"}, ":start_date": {"S": starting_date.isoformat()}},
            "ProjectionExpression": "#period_user_id, #date",
            "ConsistentRead": True,
        },
    )
    for item in items:
        dynamodb_client.update_item(
            TableName=table_name,
            Key=item,
            UpdateExpression="SET #completed = :false, #open_period = :period ADD #version :one",
            ExpressionAttributeNames={"#completed": "completed", "#open_period": "open_period", "#version": "version"},
            ExpressionAttributeValues={":false": {"BOOL": False}, ":period": {"S": "daily"}, ":one": {"N": "1"}},
        )


# -- Query utils --


def query_all_items(dynamodb_client, query_kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run a DynamoDB query through every page of its results.

    Args:
        dynamodb_client: DynamoDB client
        query_kwargs: The query arguments

    Returns:
        List of DynamoDB items
    """
    items = []
    response = dynamodb_client.query(**query_kwargs)
    items.extend(response.get("Items", []))

    # Handle pagination
    while "LastEvaluatedKey" in response:
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = dynamodb_client.query(**query_kwargs)
        items.extend(response.get("Items", []))

    return items


def build_query_filter_expression(filters: Dict[str, Any]) -> tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    """Build DynamoDB query filter expression from filters dictionary.

    Args:
        filters: Dictionary of filter key-value pairs

    Returns:
        Tuple of (filter_expression, expression_attribute_names, expression_attribute_values)
    """
    filter_expressions = []
    expression_attribute_names = {}
    expression_attribute_values = {}

    for field, value in filters.items():
        if value is not None:
            filter_expressions.append(f"#{field} = :{field}")
            expression_attribute_names[f"#{field}"] = field
            expression_attribute_values[f":{field}"] = {"S": value}

    filter_expression = " AND ".join(filter_expressions) if filter_expressions else None
    return filter_expression, expression_attribute_names, expression_attribute_values


def build_topic_filter_expression(topics: List[str]) -> tuple[str, Dict[str, Any]]:
    """Build DynamoDB filter expression for topics.

    Args:
        topics: List of topics to filter by

    Returns:
        Tuple of (filter_expression, expression_attribute_values)
    """
    topic_filters = []
    expression_attribute_values = {}

    for i, topic in enumerate(topics):
        topic_key = f":topic_{i}"
        topic_filters.append(f"contains(topics, {topic_key})")
        expression_attribute_values[topic_key] = {"S": topic}

    filter_expression = f"({' OR '.join(topic_filters)})"
    return filter_expression, expression_attribute_values


def execute_query_with_pagination(
    dynamodb_client,
    table_name: str,
    index_name: str,
    key_condition_expression: str,
    expression_attribute_names: Dict[str, str],
    expression_attribute_values: Dict[str, Any],
    filter_expression: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    limit: Optional[int] = None,
    page: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Execute DynamoDB query with pagination support.

    Args:
        dynamodb_client: DynamoDB client
        table_name: Table name
        index_name: Index name for query
        key_condition_expression: Key condition expression
        expression_attribute_names: Expression attribute names
        expression_attribute_values: Expression attribute values
        filter_expression: Optional filter expression
        sort_by: Field to sort by
        sort_order: Sort order (asc/desc)
        limit: Limit for pagination
        page: Page number

    Returns:
        List of DynamoDB items
    """
    query_kwargs = {
        "TableName": table_name,
        "IndexName": index_name,
        "KeyConditionExpression": key_condition_expression,
        "ExpressionAttributeValues": expression_attribute_values,
    }

    if expression_attribute_names:
        query_kwargs["ExpressionAttributeNames"] = expression_attribute_names

    if filter_expression:
        query_kwargs["FilterExpression"] = filter_expression

    # Apply sorting at query level if sorting by created_at
    if sort_by == "created_at":
        query_kwargs["ScanIndexForward"] = sort_order != "desc"  # type: ignore

    # Apply limit at DynamoDB level if no pagination
    if limit and not page:
        query_kwargs["Limit"] = limit  # type: ignore

    items = []
    response = dynamodb_client.query(**query_kwargs)
    items.extend(response.get("Items", []))

    # Handle pagination
    while "LastEvaluatedKey" in response:
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = dynamodb_client.query(**query_kwargs)
        items.extend(response.get("Items", []))

    return items


def process_query_results(
    items: List[Dict[str, Any]],
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    limit: Optional[int] = None,
    page: Optional[int] = None,
    deserialize_func: Optional[Callable] = None,
    deserialize: bool = True,
) -> Union[List[Any], tuple[List[Any], int]]:
    """Process query results with sorting, pagination, and deserialization.

    Args:
        items: List of DynamoDB items
        sort_by: Field to sort by
        sort_order: Sort order (asc/desc)
        limit: Limit for pagination
        page: Page number
        deserialize_func: Function to deserialize items
        deserialize: Whether to deserialize items

    Returns:
        List of processed items or tuple of (items, total_count)
    """
    # Convert DynamoDB items to data
    processed_data = []
    for item in items:
        data = deserialize_from_dynamodb_item(item)
        if data:
            processed_data.append(data)

    # Apply in-memory sorting for fields not handled by DynamoDB
    if sort_by and sort_by != "created_at":
        processed_data = apply_sorting(processed_data, sort_by, sort_order)

    # Get total count before pagination
    total_count = len(processed_data)

    # Apply pagination
    if page:
        processed_data = apply_pagination(processed_data, limit, page)

    if not deserialize or not deserialize_func:
        return processed_data, total_count

    # Deserialize items
    deserialized_items = []
    for data in processed_data:
        try:
            item = deserialize_func(data)
            if item:
                deserialized_items.append(item)
        except Exception as e:
            log_error(f"Failed to deserialize item: {str(e)}")

    return deserialized_items
