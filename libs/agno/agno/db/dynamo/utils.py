import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.session import Session
from agno.utils.log import log_debug, log_error, log_info

# -- Serialization utils --


def serialize_to_dynamo_item(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the given dict to a valid DynamoDB item

    Args:
        data: The dict to serialize

    Returns:
        A DynamoDB-ready dict with the serialized data

    """
    item = {}
    for key, value in data.items():
        if value is not None:
            if isinstance(value, (int, float)):
                item[key] = {"N": str(value)}
            elif isinstance(value, str):
                item[key] = {"S": value}
            elif isinstance(value, bool):
                item[key] = {"BOOL": str(value)}
            elif isinstance(value, (dict, list)):
                item[key] = {"S": json.dumps(value)}
            else:
                item[key] = {"S": str(value)}
    return item


def deserialize_from_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    data = {}
    for key, value in item.items():
        if "S" in value:
            try:
                data[key] = json.loads(value["S"])
            except (json.JSONDecodeError, TypeError):
                data[key] = value["S"]
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

        except Exception as e:
            log_error(f"Failed to create table {table_name}: {e}")
            return False


def apply_pagination(
    items: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination to a list of items."""
    if limit is None:
        return items

    start_index = 0
    if page is not None and page > 1:
        start_index = (page - 1) * limit

    return items[start_index : start_index + limit]


def apply_sorting(
    items: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to a list of items."""
    if sort_by is None:
        sort_by = "created_at"

    reverse = sort_order == "desc"

    return sorted(items, key=lambda x: x.get(sort_by, ""), reverse=reverse)


# -- Session utils --


def prepare_session_data(session: "Session") -> Dict[str, Any]:
    """Prepare session data for storage by serializing JSON fields and setting session type."""
    from agno.session import AgentSession, TeamSession, WorkflowSession

    serialized_session = session.to_dict()

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


def deserialize_session(session: Dict[str, Any]) -> Optional[Session]:
    """Deserialize session data from DynamoDB format to Session object."""
    try:
        deserialized = session.copy()

        # Handle JSON fields
        json_fields = ["session_data", "memory", "tools", "functions", "additional_data"]
        for field in json_fields:
            if field in deserialized and deserialized[field] is not None:
                if isinstance(deserialized[field], str):
                    try:
                        deserialized[field] = json.loads(deserialized[field])
                    except json.JSONDecodeError:
                        log_error(f"Failed to deserialize {field} field")
                        deserialized[field] = None

        # Handle timestamp fields
        for field in ["created_at", "updated_at"]:
            if field in deserialized and deserialized[field] is not None:
                if isinstance(deserialized[field], (int, float)):
                    deserialized[field] = datetime.fromtimestamp(deserialized[field], tz=timezone.utc)
                elif isinstance(deserialized[field], str):
                    try:
                        deserialized[field] = datetime.fromisoformat(deserialized[field])
                    except ValueError:
                        deserialized[field] = datetime.fromtimestamp(float(deserialized[field]), tz=timezone.utc)

        return Session.from_dict(deserialized)  # type: ignore

    except Exception as e:
        log_error(f"Failed to deserialize session: {e}")
        return None


# -- Metrics utils --


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> dict:
    """Calculate metrics for the given single date.
    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.
    Returns:
        dict: The calculated metrics.
    """
    metrics = {
        "users_count": 0,
        "agent_sessions_count": 0,
        "team_sessions_count": 0,
        "workflow_sessions_count": 0,
        "agent_runs_count": 0,
        "team_runs_count": 0,
        "workflow_runs_count": 0,
    }
    token_metrics = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "audio_total_tokens": 0,
        "audio_input_tokens": 0,
        "audio_output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    model_counts: Dict[str, int] = {}
    session_types = [
        ("agent", "agent_sessions_count", "agent_runs_count"),
        ("team", "team_sessions_count", "team_runs_count"),
        ("workflow", "workflow_sessions_count", "workflow_runs_count"),
    ]
    all_user_ids = set()
    for session_type, sessions_count_key, runs_count_key in session_types:
        sessions = sessions_data.get(session_type, [])
        metrics[sessions_count_key] = len(sessions)
        for session in sessions:
            if session.get("user_id"):
                all_user_ids.add(session["user_id"])
            metrics[runs_count_key] += len(session.get("runs", []))
            if runs := session.get("runs", []):
                for run in runs:
                    if model_id := run.get("model"):
                        model_provider = run.get("model_provider", "")
                        model_counts[f"{model_id}:{model_provider}"] = (
                            model_counts.get(f"{model_id}:{model_provider}", 0) + 1
                        )
            session_metrics = session.get("session_data", {}).get("session_metrics", {})
            for field in token_metrics:
                token_metrics[field] += session_metrics.get(field, 0)
    model_metrics = []
    for model, count in model_counts.items():
        model_id, model_provider = model.split(":")
        model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})
    metrics["users_count"] = len(all_user_ids)
    current_time = int(time.time())
    return {
        "id": str(uuid4()),
        "date": date_to_process,
        "completed": date_to_process < datetime.now(timezone.utc).date(),
        "token_metrics": token_metrics,
        "model_metrics": model_metrics,
        "created_at": current_time,
        "updated_at": current_time,
        "aggregation_period": "daily",
        **metrics,
    }


def get_dates_to_calculate_metrics_for(starting_date: date) -> list[date]:
    """Return the list of dates to calculate metrics for.
    Args:
        starting_date (date): The starting date to calculate metrics for.
    Returns:
        list[date]: The list of dates to calculate metrics for.
    """
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types.
    Args:
        sessions: List of session data dictionaries
        dates_to_process (list[date]): The dates to fetch session data for.
        start_timestamp: The start timestamp for the range
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
        session_date = (
            datetime.fromtimestamp(session.get("created_at", start_timestamp), tz=timezone.utc).date().isoformat()
        )
        if session_date in all_sessions_data:
            all_sessions_data[session_date][session["session_type"]].append(session)
    return all_sessions_data


def fetch_all_sessions_data_by_type(
    dynamodb_client,
    table_name: str,
    session_type: str,
    user_id: Optional[str] = None,
    component_id: Optional[str] = None,
    session_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch all sessions data from DynamoDB table using GSI for session_type."""
    items = []

    try:
        # Build filter expression for additional filters
        filter_expression = None
        expression_attribute_names = {}
        expression_attribute_values = {":session_type": {"S": session_type}}

        if user_id:
            filter_expression = "#user_id = :user_id"
            expression_attribute_names["#user_id"] = "user_id"
            expression_attribute_values[":user_id"] = {"S": user_id}

        if component_id:
            component_filter = "#component_id = :component_id"
            expression_attribute_names["#component_id"] = "component_id"
            expression_attribute_values[":component_id"] = {"S": component_id}

            if filter_expression:
                filter_expression += f" AND {component_filter}"
            else:
                filter_expression = component_filter

        if session_name:
            name_filter = "#session_name = :session_name"
            expression_attribute_names["#session_name"] = "session_name"
            expression_attribute_values[":session_name"] = {"S": session_name}

            if filter_expression:
                filter_expression += f" AND {name_filter}"
            else:
                filter_expression = name_filter

        # Use GSI query for session_type (more efficient than scan)
        query_kwargs = {
            "TableName": table_name,
            "IndexName": "session_type-created_at-index",
            "KeyConditionExpression": "session_type = :session_type",
            "ExpressionAttributeValues": expression_attribute_values,
        }

        if filter_expression:
            query_kwargs["FilterExpression"] = filter_expression

        if expression_attribute_names:
            query_kwargs["ExpressionAttributeNames"] = expression_attribute_names

        response = dynamodb_client.query(**query_kwargs)
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = dynamodb_client.query(**query_kwargs)
            items.extend(response.get("Items", []))

    except Exception as e:
        log_error(f"Failed to fetch sessions: {e}")

    return items


def bulk_upsert_metrics(dynamodb_client, table_name: str, metrics_data: List[Dict[str, Any]]) -> None:
    """Bulk upsert metrics data to DynamoDB."""
    try:
        # DynamoDB batch write has a limit of 25 items
        batch_size = 25

        for i in range(0, len(metrics_data), batch_size):
            batch = metrics_data[i : i + batch_size]

            request_items: Dict[str, List[Dict[str, Any]]] = {table_name: []}

            for metric in batch:
                request_items[table_name].append({"PutRequest": {"Item": metric}})

            dynamodb_client.batch_write_item(RequestItems=request_items)

    except Exception as e:
        log_error(f"Failed to bulk upsert metrics: {e}")


# -- Query utils --


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
            log_error(f"Failed to deserialize item: {e}")

    return deserialized_items
