import json
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from agno.db.base import SessionType
from agno.db.schemas import MemoryRow
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.session import Session
from agno.session.summarizer import SessionSummary
from agno.utils.log import log_debug, log_error, log_info

# TODO:
# Some serialization/deserialization is here because the schema was wrong.
# Confirm what is needed and what not and clean everything


def serialize_session_json_fields(session: Dict[str, Any]) -> Dict[str, Any]:
    """Parse dict fields in the given session to JSON strings"""
    serialized = session.copy()

    json_fields = ["session_data", "memory", "tools", "functions", "additional_data"]

    for field in json_fields:
        if field in serialized and serialized[field] is not None:
            if isinstance(serialized[field], (dict, list)):
                serialized[field] = json.dumps(serialized[field])

    return serialized


def deserialize_session_json_fields(session: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize JSON fields in session data from DynamoDB storage."""
    deserialized = session.copy()

    json_fields = ["session_data", "memory", "tools", "functions", "additional_data"]

    for field in json_fields:
        if field in deserialized and deserialized[field] is not None:
            if isinstance(deserialized[field], str):
                try:
                    deserialized[field] = json.loads(deserialized[field])
                except json.JSONDecodeError:
                    log_error(f"Failed to deserialize {field} field")
                    deserialized[field] = None

    return deserialized


def deserialize_session(session: Dict[str, Any]) -> Optional[Session]:
    """Deserialize session data from DynamoDB format to Session object."""
    try:
        # Deserialize JSON fields
        session = deserialize_session_json_fields(session)

        # Convert timestamp fields
        for field in ["created_at", "updated_at"]:
            if field in session and session[field] is not None:
                if isinstance(session[field], (int, float)):
                    session[field] = datetime.fromtimestamp(session[field], tz=timezone.utc)
                elif isinstance(session[field], str):
                    try:
                        session[field] = datetime.fromisoformat(session[field])
                    except ValueError:
                        session[field] = datetime.fromtimestamp(float(session[field]), tz=timezone.utc)

        return Session.from_dict(session)

    except Exception as e:
        log_error(f"Failed to deserialize session: {e}")
        return None


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
                item[key] = {"BOOL": value}
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


def serialize_memory_row(memory: MemoryRow) -> Dict[str, Any]:
    """Serialize a MemoryRow to a DynamoDB item."""
    return serialize_to_dynamo_item(memory.to_dict())


def serialize_knowledge_row(knowledge: KnowledgeRow) -> Dict[str, Any]:
    """Convert KnowledgeRow to DynamoDB item format."""
    return serialize_to_dynamo_item(
        {
            "id": knowledge.id,
            "name": knowledge.name,
            "description": knowledge.description,
            "user_id": getattr(knowledge, "user_id", None),
            "type": getattr(knowledge, "type", None),
            "status": getattr(knowledge, "status", None),
            "metadata": getattr(knowledge, "metadata", None),
            "size": getattr(knowledge, "size", None),
            "linked_to": getattr(knowledge, "linked_to", None),
            "access_count": getattr(knowledge, "access_count", None),
            "created_at": int(knowledge.created_at.timestamp()) if knowledge.created_at else None,
            "updated_at": int(knowledge.updated_at.timestamp()) if knowledge.updated_at else None,
        }
    )


def deserialize_knowledge_row(item: Dict[str, Any]) -> KnowledgeRow:
    """Convert DynamoDB item to KnowledgeRow."""
    data = deserialize_from_dynamodb_item(item)
    # Convert timestamp fields back to datetime
    if "created_at" in data and data["created_at"]:
        data["created_at"] = datetime.fromtimestamp(data["created_at"], tz=timezone.utc)
    if "updated_at" in data and data["updated_at"]:
        data["updated_at"] = datetime.fromtimestamp(data["updated_at"], tz=timezone.utc)
    return KnowledgeRow(
        id=data["id"],
        name=data["name"],
        description=data["description"],
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
            "created_at": int(eval_record.created_at.timestamp()) if eval_record.created_at else None,
            "updated_at": int(eval_record.updated_at.timestamp()) if eval_record.updated_at else None,
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


def hydrate_session(session: dict) -> dict:
    """Convert nested dictionaries to their corresponding object types.

    Args:
        session (dict): The session dictionary to hydrate.

    Returns:
        dict: The hydrated session dictionary.
    """
    if session.get("summary") is not None:
        session["summary"] = SessionSummary.from_dict(session["summary"])
    if session.get("runs") is not None:
        if session["session_type"] == SessionType.AGENT:
            session["runs"] = [RunResponse.from_dict(run) for run in session["runs"]]
        elif session["session_type"] == SessionType.TEAM:
            session["runs"] = [TeamRunResponse.from_dict(run) for run in session["runs"]]

    return session


# -- Session Upsert Helpers --


def prepare_session_data(session: "Session") -> Dict[str, Any]:
    """Prepare session data for storage by serializing JSON fields and setting session type."""
    from agno.session import AgentSession, TeamSession, WorkflowSession

    serialized_session = serialize_session_json_fields(session.to_dict())

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


# TODO: typing
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


# -- DB Utils --


def create_table_if_not_exists(dynamodb_client, table_name: str, schema: Dict[str, Any]) -> bool:
    """Create DynamoDB table if it doesn't exist."""
    try:
        dynamodb_client.describe_table(TableName=table_name)
        log_debug(f"Table {table_name} already exists")
        return True
    except dynamodb_client.exceptions.ResourceNotFoundException:
        log_info(f"Creating table {table_name}")
        try:
            dynamodb_client.create_table(**schema)
            # Wait for table to be created
            waiter = dynamodb_client.get_waiter("table_exists")
            waiter.wait(TableName=table_name)
            log_info(f"Table {table_name} created successfully")
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


# -- Metrics Utils --


def fetch_all_sessions_data(
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

            request_items = {table_name: []}

            for metric in batch:
                request_items[table_name].append({"PutRequest": {"Item": metric}})

            dynamodb_client.batch_write_item(RequestItems=request_items)

    except Exception as e:
        log_error(f"Failed to bulk upsert metrics: {e}")


def calculate_date_metrics(
    dynamodb_client, table_name: str, date_to_calculate: date, user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Calculate metrics for a specific date."""
    try:
        # Query metrics for the date
        date_str = date_to_calculate.isoformat()

        query_kwargs = {
            "TableName": table_name,
            "IndexName": "user_id-date-index" if user_id else "date-index",
            "KeyConditionExpression": "#date = :date",
            "ExpressionAttributeNames": {"#date": "date"},
            "ExpressionAttributeValues": {":date": {"S": date_str}},
        }

        if user_id:
            query_kwargs["KeyConditionExpression"] = "#user_id = :user_id AND #date = :date"
            query_kwargs["ExpressionAttributeNames"]["#user_id"] = "user_id"
            query_kwargs["ExpressionAttributeValues"][":user_id"] = {"S": user_id}

        response = dynamodb_client.query(**query_kwargs)
        items = response.get("Items", [])

        # Calculate aggregated metrics
        total_requests = len(items)
        total_tokens = sum(int(item.get("tokens", {}).get("N", "0")) for item in items)
        total_cost = sum(float(item.get("cost", {}).get("N", "0")) for item in items)

        return {
            "date": date_str,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
        }

    except Exception as e:
        log_error(f"Failed to calculate date metrics: {e}")
        return {}


def get_dates_to_calculate_metrics_for(
    dynamodb_client, table_name: str, user_id: Optional[str] = None, days_back: int = 30
) -> List[date]:
    """Get dates that need metrics calculation."""
    dates = []

    try:
        # Get recent dates that have data
        from datetime import timedelta

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days_back)

        current_date = start_date
        while current_date <= end_date:
            dates.append(current_date)
            current_date += timedelta(days=1)

    except Exception as e:
        log_error(f"Failed to get dates for metrics calculation: {e}")

    return dates


# -- Query Building Utils --


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
        query_kwargs["ScanIndexForward"] = sort_order != "desc"

    # Apply limit at DynamoDB level if no pagination
    if limit and not page:
        query_kwargs["Limit"] = limit

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
    deserialize_func: Optional[callable] = None,
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
