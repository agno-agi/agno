import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from agno.db.schemas import MemoryRow
from agno.db.schemas.knowledge import KnowledgeRow
from agno.eval.schemas import EvalRunRecord
from agno.session import Session
from agno.utils.log import log_debug, log_error, log_info

# TODO: some serialization/deserialization is here because the schema was wrong.
# Confirm what is needed and what not and clean everything


def serialize_to_dynamodb_item(data: Dict[str, Any]) -> Dict[str, Any]:
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
            data[key] = self._deserialize_from_dynamodb_item(value["M"])
        elif "L" in value:
            data[key] = [self._deserialize_from_dynamodb_item({"item": item})["item"] for item in value["L"]]
    return data


def serialize_memory_row(memory: MemoryRow) -> Dict[str, Any]:
    return serialize_to_dynamodb_item(
        {
            "memory_id": memory.id,
            "user_id": memory.user_id,
            "memory": memory.memory,
            "agent_id": getattr(memory, "agent_id", None),
            "team_id": getattr(memory, "team_id", None),
            "workflow_id": getattr(memory, "workflow_id", None),
            "topics": getattr(memory, "topics", None),
            "feedback": getattr(memory, "feedback", None),
            "created_at": int(memory.created_at.timestamp()) if memory.created_at else None,  # type: ignore
            "updated_at": int(memory.updated_at.timestamp()) if memory.updated_at else None,  # type: ignore
        }
    )


def deserialize_memory_row(item: Dict[str, Any]) -> MemoryRow:
    """Convert DynamoDB item to MemoryRow."""
    data = deserialize_from_dynamodb_item(item)
    # Convert timestamp fields back to datetime
    if "created_at" in data and data["created_at"]:
        data["created_at"] = datetime.fromtimestamp(data["created_at"], tz=timezone.utc)
    if "updated_at" in data and data["updated_at"]:
        data["updated_at"] = datetime.fromtimestamp(data["updated_at"], tz=timezone.utc)
    return MemoryRow(
        id=data["memory_id"],
        user_id=data["user_id"],
        memory=data["memory"],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def serialize_knowledge_row(knowledge: KnowledgeRow) -> Dict[str, Any]:
    """Convert KnowledgeRow to DynamoDB item format."""
    return serialize_to_dynamodb_item(
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
    return serialize_to_dynamodb_item(
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
    return EvalRunRecord(
        run_id=data["run_id"],
        eval_type=data["eval_type"],
        eval_data=data["eval_data"],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


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

    def get_sort_key(item: Dict[str, Any]) -> Any:
        value = item.get(sort_by)
        if isinstance(value, dict):
            if "N" in value:
                return float(value["N"])
            elif "S" in value:
                return value["S"]
        return value or 0

    return sorted(items, key=get_sort_key, reverse=reverse)


def serialize_session_json_fields(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize JSON fields in session data for DynamoDB storage."""
    serialized = session_data.copy()

    json_fields = ["session_data", "memory", "tools", "functions", "additional_data"]

    for field in json_fields:
        if field in serialized and serialized[field] is not None:
            if isinstance(serialized[field], (dict, list)):
                serialized[field] = json.dumps(serialized[field])

    return serialized


def deserialize_session_json_fields(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize JSON fields in session data from DynamoDB storage."""
    deserialized = session_data.copy()

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


def deserialize_session(session_data: Dict[str, Any]) -> Optional[Session]:
    """Deserialize session data from DynamoDB format to Session object."""
    try:
        from agno.session import AgentSession, TeamSession, WorkflowSession

        # Deserialize JSON fields
        session_data = deserialize_session_json_fields(session_data)

        # Convert timestamp fields
        for field in ["created_at", "updated_at"]:
            if field in session_data and session_data[field] is not None:
                if isinstance(session_data[field], (int, float)):
                    session_data[field] = datetime.fromtimestamp(session_data[field], tz=timezone.utc)
                elif isinstance(session_data[field], str):
                    try:
                        session_data[field] = datetime.fromisoformat(session_data[field])
                    except ValueError:
                        session_data[field] = datetime.fromtimestamp(float(session_data[field]), tz=timezone.utc)

        session_type = session_data.get("session_type")

        if session_type == "agent":
            return AgentSession.model_validate(session_data)
        elif session_type == "team":
            return TeamSession.model_validate(session_data)
        elif session_type == "workflow":
            return WorkflowSession.model_validate(session_data)
        else:
            log_error(f"Unknown session type: {session_type}")
            return None

    except Exception as e:
        log_error(f"Failed to deserialize session: {e}")
        return None


def fetch_all_sessions_data(
    dynamodb_client,
    table_name: str,
    session_type: str,
    user_id: Optional[str] = None,
    component_id: Optional[str] = None,
    session_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch all sessions data from DynamoDB table."""
    items = []

    try:
        # Build filter expression
        filter_expression = None
        expression_attribute_names = {}
        expression_attribute_values = {}

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

        # Scan with filter
        scan_kwargs = {
            "TableName": table_name,
            "FilterExpression": "session_type = :session_type",
            "ExpressionAttributeValues": {":session_type": {"S": session_type}, **expression_attribute_values},
        }

        if filter_expression:
            scan_kwargs["FilterExpression"] += f" AND {filter_expression}"

        if expression_attribute_names:
            scan_kwargs["ExpressionAttributeNames"] = expression_attribute_names

        response = dynamodb_client.scan(**scan_kwargs)
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = dynamodb_client.scan(**scan_kwargs)
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
