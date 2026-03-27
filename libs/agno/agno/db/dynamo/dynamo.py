import json
import time
from datetime import date, datetime, timedelta, timezone
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.dynamo.schemas import get_table_schema_definition
from agno.db.dynamo.utils import (
    apply_pagination,
    apply_sorting,
    build_query_filter_expression,
    build_topic_filter_expression,
    calculate_date_metrics,
    create_table_if_not_exists,
    deserialize_cultural_knowledge_from_db,
    deserialize_eval_record,
    deserialize_from_dynamodb_item,
    deserialize_knowledge_row,
    deserialize_session,
    deserialize_session_result,
    execute_query_with_pagination,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    merge_with_existing_session,
    prepare_session_data,
    serialize_cultural_knowledge_for_db,
    serialize_eval_record,
    serialize_knowledge_row,
    serialize_to_dynamo_item,
)
from agno.db.schemas.context import ContextItem
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    import boto3  # type: ignore[import-untyped]
except ImportError:
    raise ImportError("`boto3` not installed. Please install it using `pip install boto3`")


# DynamoDB batch_write_item has a hard limit of 25 items per request
DYNAMO_BATCH_SIZE_LIMIT = 25


class DynamoDb(BaseDb):
    def __init__(
        self,
        db_client=None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        context_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a DynamoDB database.

        Args:
            db_client: The DynamoDB client to use.
            region_name: AWS region name.
            aws_access_key_id: AWS access key ID.
            aws_secret_access_key: AWS secret access key.
            session_table: The name of the session table.
            culture_table: The name of the culture table.
            memory_table: The name of the memory table.
            metrics_table: The name of the metrics table.
            eval_table: The name of the eval table.
            knowledge_table: The name of the knowledge table.
            traces_table: The name of the traces table.
            spans_table: The name of the spans table.
            context_table: The name of the context table.
            id: ID of the database.
        """
        if id is None:
            seed = str(db_client) if db_client else f"{region_name}_{aws_access_key_id}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            culture_table=culture_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            context_table=context_table,
        )

        if db_client is not None:
            self.client = db_client
        else:
            if not region_name and not getenv("AWS_REGION"):
                raise ValueError("AWS_REGION is not set. Please set the AWS_REGION environment variable.")
            if not aws_access_key_id and not getenv("AWS_ACCESS_KEY_ID"):
                raise ValueError("AWS_ACCESS_KEY_ID is not set. Please set the AWS_ACCESS_KEY_ID environment variable.")
            if not aws_secret_access_key and not getenv("AWS_SECRET_ACCESS_KEY"):
                raise ValueError(
                    "AWS_SECRET_ACCESS_KEY is not set. Please set the AWS_SECRET_ACCESS_KEY environment variable."
                )

            session_kwargs = {}
            session_kwargs["region_name"] = region_name or getenv("AWS_REGION")
            session_kwargs["aws_access_key_id"] = aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")

            session = boto3.Session(**session_kwargs)
            self.client = session.client("dynamodb")

    def table_exists(self, table_name: str) -> bool:
        """Check if a DynamoDB table exists.

        Args:
            table_name: The name of the table to check

        Returns:
            bool: True if the table exists, False otherwise
        """
        try:
            self.client.describe_table(TableName=table_name)
            return True
        except self.client.exceptions.ResourceNotFoundException:
            return False

    def _create_all_tables(self):
        """Create all configured DynamoDB tables if they don't exist."""
        tables_to_create = [
            ("sessions", self.session_table_name),
            ("memories", self.memory_table_name),
            ("metrics", self.metrics_table_name),
            ("evals", self.eval_table_name),
            ("knowledge", self.knowledge_table_name),
            ("culture", self.culture_table_name),
            ("context", self.context_table_name),
        ]

        for table_type, table_name in tables_to_create:
            if not self.table_exists(table_name):
                schema = get_table_schema_definition(table_type)
                schema["TableName"] = table_name
                create_table_if_not_exists(self.client, table_name, schema)

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = True) -> Optional[str]:
        """
        Get table name and ensure the table exists, creating it if needed.

        Args:
            table_type: Type of table ("sessions", "memories", "metrics", "evals", "knowledge", "culture", "traces", "spans")

        Returns:
            str: The table name

        Raises:
            ValueError: If table name is not configured or table type is unknown
        """
        table_name = None

        if table_type == "sessions":
            table_name = self.session_table_name
        elif table_type == "memories":
            table_name = self.memory_table_name
        elif table_type == "metrics":
            table_name = self.metrics_table_name
        elif table_type == "evals":
            table_name = self.eval_table_name
        elif table_type == "knowledge":
            table_name = self.knowledge_table_name
        elif table_type == "culture":
            table_name = self.culture_table_name
        elif table_type == "traces":
            table_name = self.trace_table_name
        elif table_type == "spans":
            # Ensure traces table exists first (spans reference traces)
            self._get_table("traces", create_table_if_not_found=True)
            table_name = self.span_table_name
        elif table_type == "context":
            table_name = self.context_table_name
        else:
            raise ValueError(f"Unknown table type: {table_type}")

        # Check if table exists, create if it doesn't
        if not self.table_exists(table_name) and create_table_if_not_found:
            schema = get_table_schema_definition(table_type)
            schema["TableName"] = table_name
            create_table_if_not_exists(self.client, table_name, schema)

        return table_name

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

    # --- Sessions ---

    def delete_session(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id: The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        if not session_id:
            return False

        try:
            kwargs: Dict[str, Any] = {
                "TableName": self.session_table_name,
                "Key": {"session_id": {"S": session_id}},
            }
            if user_id is not None:
                kwargs["ConditionExpression"] = "user_id = :user_id"
                kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}
            self.client.delete_item(**kwargs)
            return True

        except self.client.exceptions.ConditionalCheckFailedException:
            log_debug(f"No session found to delete with session_id: {session_id} and user_id: {user_id}")
            return False

        except Exception as e:
            log_error(f"Failed to delete session {session_id}: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """
        Delete sessions from the database in batches.

        Args:
            session_ids: List of session IDs to delete
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        if not session_ids or not self.session_table_name:
            return

        try:
            if user_id is not None:
                for session_id in session_ids:
                    try:
                        self.client.delete_item(
                            TableName=self.session_table_name,
                            Key={"session_id": {"S": session_id}},
                            ConditionExpression="user_id = :user_id",
                            ExpressionAttributeValues={":user_id": {"S": user_id}},
                        )
                    except self.client.exceptions.ConditionalCheckFailedException:
                        pass
            else:
                for i in range(0, len(session_ids), DYNAMO_BATCH_SIZE_LIMIT):
                    batch = session_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                    delete_requests = []

                    for session_id in batch:
                        delete_requests.append({"DeleteRequest": {"Key": {"session_id": {"S": session_id}}}})

                    if delete_requests:
                        self.client.batch_write_item(RequestItems={self.session_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete sessions: {e}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Get a session from the database as a Session object.

        Args:
            session_id (str): The ID of the session to get.
            session_type (SessionType): The type of session to get.
            user_id (Optional[str]): The ID of the user to get the session for.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Optional[Session]: The session data as a Session object.

        Raises:
            Exception: If any error occurs while getting the session.
        """
        try:
            table_name = self._get_table("sessions")
            response = self.client.get_item(
                TableName=table_name,
                Key={"session_id": {"S": session_id}},
            )

            item = response.get("Item")
            if not item:
                return None

            session = deserialize_from_dynamodb_item(item)

            if user_id is not None and session.get("user_id") != user_id:
                return None

            if not session:
                return None

            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Failed to get session {session_id}: {e}")
            raise e

    def get_sessions(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        try:
            table_name = self._get_table("sessions")
            if table_name is None:
                return [] if deserialize else ([], 0)

            # Build filter expression for additional filters
            filter_expression = None
            expression_attribute_names = {}
            expression_attribute_values = {":session_type": {"S": session_type.value}}

            if user_id is not None:
                filter_expression = "#user_id = :user_id"
                expression_attribute_names["#user_id"] = "user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

            if component_id:
                # Map component_id to the appropriate field based on session type
                if session_type == SessionType.AGENT:
                    component_filter = "#agent_id = :component_id"
                    expression_attribute_names["#agent_id"] = "agent_id"
                elif session_type == SessionType.TEAM:
                    component_filter = "#team_id = :component_id"
                    expression_attribute_names["#team_id"] = "team_id"
                else:
                    component_filter = "#workflow_id = :component_id"
                    expression_attribute_names["#workflow_id"] = "workflow_id"

                if component_filter:
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

            # Use GSI query for session_type
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

            # Apply sorting
            if sort_by == "created_at":
                query_kwargs["ScanIndexForward"] = sort_order != "desc"  # type: ignore

            # Apply limit at DynamoDB level
            if limit and not page:
                query_kwargs["Limit"] = limit  # type: ignore

            items = []
            response = self.client.query(**query_kwargs)
            items.extend(response.get("Items", []))

            # Handle pagination
            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

            # Convert DynamoDB items to session data
            sessions_data = []
            for item in items:
                session_data = deserialize_from_dynamodb_item(item)
                if session_data:
                    sessions_data.append(session_data)

            # Apply in-memory sorting for fields not supported by DynamoDB
            if sort_by and sort_by != "created_at":
                sessions_data = apply_sorting(sessions_data, sort_by, sort_order)

            # Get total count before pagination
            total_count = len(sessions_data)

            # Apply pagination
            if page:
                sessions_data = apply_pagination(sessions_data, limit, page)

            if not deserialize:
                return sessions_data, total_count

            sessions = []
            for session_data in sessions_data:
                session = deserialize_session(session_data)
                if session:
                    sessions.append(session)

            return sessions

        except Exception as e:
            log_error(f"Failed to get sessions: {e}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id: The ID of the session to rename.
            session_type: The type of session to rename.
            session_name: The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            if not self.session_table_name:
                raise Exception("Sessions table not found")

            # Get current session_data
            get_response = self.client.get_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
            )
            current_item = get_response.get("Item")
            if not current_item:
                return None

            # Verify user_id if provided
            if user_id is not None:
                item_data = deserialize_from_dynamodb_item(current_item)
                if item_data.get("user_id") != user_id:
                    return None

            # Update session_data with the new session_name
            session_data = deserialize_from_dynamodb_item(current_item).get("session_data", {})
            session_data["session_name"] = session_name
            condition_expr = "session_type = :session_type"
            attr_values: Dict[str, Any] = {
                ":session_data": {"S": json.dumps(session_data)},
                ":session_type": {"S": session_type.value},
                ":updated_at": {"N": str(int(time.time()))},
            }
            if user_id is not None:
                condition_expr += " AND user_id = :user_id"
                attr_values[":user_id"] = {"S": user_id}
            response = self.client.update_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
                UpdateExpression="SET session_data = :session_data, updated_at = :updated_at",
                ConditionExpression=condition_expr,
                ExpressionAttributeValues=attr_values,
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if not item:
                return None

            session = deserialize_from_dynamodb_item(item)
            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            else:
                return WorkflowSession.from_dict(session)

        except Exception as e:
            log_error(f"Failed to rename session {session_id}: {e}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Upsert a session into the database.

        This method provides true upsert behavior: creates a new session if it doesn't exist,
        or updates an existing session while preserving important fields.

        Args:
            session (Session): The session to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.
        """
        try:
            table_name = self._get_table("sessions", create_table_if_not_found=True)

            # Get session if it already exists in the db.
            # We need to do this to handle updating nested fields.
            response = self.client.get_item(TableName=table_name, Key={"session_id": {"S": session.session_id}})
            existing_item = response.get("Item")

            if existing_item:
                existing_uid = existing_item.get("user_id", {}).get("S")
                if existing_uid is not None and existing_uid != session.user_id:
                    return None

            # Prepare the session to upsert, merging with existing session if it exists.
            serialized_session = prepare_session_data(session)
            if existing_item:
                serialized_session = merge_with_existing_session(serialized_session, existing_item)
                serialized_session["updated_at"] = int(time.time())
            else:
                serialized_session["updated_at"] = serialized_session["created_at"]

            item = serialize_to_dynamo_item(serialized_session)
            put_kwargs: Dict[str, Any] = {"TableName": table_name, "Item": item}

            expr_names = {"#uid": "user_id"}
            if session.user_id is not None:
                put_kwargs["ConditionExpression"] = (
                    "attribute_not_exists(session_id) OR #uid = :incoming_uid OR attribute_not_exists(#uid)"
                )
                put_kwargs["ExpressionAttributeValues"] = {":incoming_uid": {"S": session.user_id}}
            else:
                put_kwargs["ConditionExpression"] = "attribute_not_exists(session_id) OR attribute_not_exists(#uid)"
            put_kwargs["ExpressionAttributeNames"] = expr_names

            try:
                self.client.put_item(**put_kwargs)
            except self.client.exceptions.ConditionalCheckFailedException:
                return None

            return deserialize_session_result(serialized_session, session, deserialize)

        except Exception as e:
            log_error(f"Failed to upsert session {session.session_id}: {e}")
            raise e

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions for improved performance on large datasets.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            log_info(
                f"DynamoDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
            )

            # Fall back to individual upserts
            results = []
            for session in sessions:
                if session is not None:
                    result = self.upsert_session(session, deserialize=deserialize)
                    if result is not None:
                        results.append(result)
            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert: {e}")
            return []

    # --- User Memory ---

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """
        Delete a user memory from the database.

        Args:
            memory_id: The ID of the memory to delete.
            user_id: The ID of the user (optional, for filtering).

        Raises:
            Exception: If any error occurs while deleting the user memory.
        """
        try:
            # If user_id is provided, verify the memory belongs to the user before deleting
            if user_id is not None:
                response = self.client.get_item(
                    TableName=self.memory_table_name,
                    Key={"memory_id": {"S": memory_id}},
                )
                item = response.get("Item")
                if item:
                    memory_data = deserialize_from_dynamodb_item(item)
                    if memory_data.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                        return

            self.client.delete_item(
                TableName=self.memory_table_name,
                Key={"memory_id": {"S": memory_id}},
            )
            log_debug(f"Deleted user memory {memory_id}")

        except Exception as e:
            log_error(f"Failed to delete user memory {memory_id}: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """
        Delete user memories from the database in batches.

        Args:
            memory_ids: List of memory IDs to delete
            user_id: The ID of the user (optional, for filtering).

        Raises:
            Exception: If any error occurs while deleting the user memories.
        """

        try:
            # If user_id is provided, filter memory_ids to only those belonging to the user
            if user_id is not None:
                filtered_memory_ids = []
                for memory_id in memory_ids:
                    response = self.client.get_item(
                        TableName=self.memory_table_name,
                        Key={"memory_id": {"S": memory_id}},
                    )
                    item = response.get("Item")
                    if item:
                        memory_data = deserialize_from_dynamodb_item(item)
                        if memory_data.get("user_id") == user_id:
                            filtered_memory_ids.append(memory_id)
                memory_ids = filtered_memory_ids

            for i in range(0, len(memory_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = memory_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for memory_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"memory_id": {"S": memory_id}}}})

                self.client.batch_write_item(RequestItems={self.memory_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete user memories: {e}")
            raise e

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id: The ID of the user (optional, for filtering).

        Returns:
            List[str]: List of unique memory topics.
        """
        try:
            table_name = self._get_table("memories")
            if table_name is None:
                return []

            # Build filter expression for user_id if provided
            scan_kwargs = {"TableName": table_name}

            # Scan the table to get memories
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Extract topics from all memories
            all_topics = set()
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                topics = memory_data.get("memory", {}).get("topics", [])
                all_topics.update(topics)

            return list(all_topics)

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            raise e

    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """
        Get a user memory from the database as a UserMemory object.

        Args:
            memory_id: The ID of the memory to get.
            deserialize: Whether to deserialize the memory.
            user_id: The ID of the user (optional, for filtering).

        Returns:
            Optional[UserMemory]: The user memory data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the user memory.
        """
        try:
            table_name = self._get_table("memories")
            response = self.client.get_item(TableName=table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if not item:
                return None

            item = deserialize_from_dynamodb_item(item)

            # Filter by user_id if provided
            if user_id and item.get("user_id") != user_id:
                return None

            if not deserialize:
                return item

            return UserMemory.from_dict(item)

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            raise e

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        """
        Get user memories from the database as a list of UserMemory objects.

        Args:
            user_id: The ID of the user to get the memories for.
            agent_id: The ID of the agent to get the memories for.
            team_id: The ID of the team to get the memories for.
            workflow_id: The ID of the workflow to get the memories for.
            topics: The topics to filter the memories by.
            search_content: The content to search for in the memories.
            limit: The maximum number of memories to return.
            page: The page number to return.
            sort_by: The field to sort the memories by.
            sort_order: The order to sort the memories by.
            deserialize: Whether to deserialize the memories.

        Returns:
            Union[List[UserMemory], List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]: The user memories data.

        Raises:
            Exception: If any error occurs while getting the user memories.
        """
        try:
            table_name = self._get_table("memories")
            if table_name is None:
                return [] if deserialize else ([], 0)

            # Build filter expressions for component filters
            (
                filter_expression,
                expression_attribute_names,
                expression_attribute_values,
            ) = build_query_filter_expression(filters={"agent_id": agent_id, "team_id": team_id})

            # Build topic filter expression if topics provided
            if topics:
                topic_filter, topic_values = build_topic_filter_expression(topics)
                expression_attribute_values.update(topic_values)
                filter_expression = f"{filter_expression} AND {topic_filter}" if filter_expression else topic_filter

            # Add search content filter if provided
            if search_content:
                search_filter = "contains(memory, :search_content)"
                expression_attribute_values[":search_content"] = {"S": search_content}
                filter_expression = f"{filter_expression} AND {search_filter}" if filter_expression else search_filter

            # Determine whether to use GSI query or table scan
            if user_id is not None:
                # Use GSI query when user_id is provided
                key_condition_expression = "#user_id = :user_id"

                # Set up expression attributes for GSI key condition
                expression_attribute_names["#user_id"] = "user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

                # Execute query with pagination
                items = execute_query_with_pagination(
                    self.client,
                    table_name,
                    "user_id-updated_at-index",
                    key_condition_expression,
                    expression_attribute_names,
                    expression_attribute_values,
                    filter_expression,
                    sort_by,
                    sort_order,
                    limit,
                    page,
                )
            else:
                # Use table scan when user_id is None
                scan_kwargs = {"TableName": table_name}

                if filter_expression:
                    scan_kwargs["FilterExpression"] = filter_expression
                if expression_attribute_names:
                    scan_kwargs["ExpressionAttributeNames"] = expression_attribute_names  # type: ignore
                if expression_attribute_values:
                    scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values  # type: ignore

                # Execute scan
                response = self.client.scan(**scan_kwargs)
                items = response.get("Items", [])

                # Handle pagination for scan
                while "LastEvaluatedKey" in response:
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            items = [deserialize_from_dynamodb_item(item) for item in items]

            if sort_by and sort_by != "updated_at":
                items = apply_sorting(items, sort_by, sort_order)

            if page:
                paginated_items = apply_pagination(items, limit, page)

            if not deserialize:
                return paginated_items, len(items)

            return [UserMemory.from_dict(item) for item in items]

        except Exception as e:
            log_error(f"Failed to get user memories: {e}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            Tuple[List[Dict[str, Any]], int]: A list of dictionaries containing user stats and total count.

        Example:
        (
            [
                {
                    "user_id": "123",
                    "total_memories": 10,
                    "last_memory_updated_at": 1714560000,
                },
            ],
            total_count: 1,
        )
        """
        try:
            table_name = self._get_table("memories")

            # Build filter expression for user_id if provided
            filter_expression = None
            expression_attribute_values = {}
            if user_id is not None:
                filter_expression = "user_id = :user_id"
                expression_attribute_values[":user_id"] = {"S": user_id}

            scan_kwargs = {"TableName": table_name}
            if filter_expression:
                scan_kwargs["FilterExpression"] = filter_expression
            if expression_attribute_values:
                scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values  # type: ignore

            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Aggregate stats by user_id
            user_stats = {}
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                current_user_id = memory_data.get("user_id")

                if current_user_id:
                    if current_user_id not in user_stats:
                        user_stats[current_user_id] = {
                            "user_id": current_user_id,
                            "total_memories": 0,
                            "last_memory_updated_at": None,
                        }

                    user_stats[current_user_id]["total_memories"] += 1

                    updated_at = memory_data.get("updated_at")
                    if updated_at:
                        updated_at_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        updated_at_timestamp = int(updated_at_dt.timestamp())

                        if updated_at_timestamp and (
                            user_stats[current_user_id]["last_memory_updated_at"] is None
                            or updated_at_timestamp > user_stats[current_user_id]["last_memory_updated_at"]
                        ):
                            user_stats[current_user_id]["last_memory_updated_at"] = updated_at_timestamp

            # Convert to list and apply sorting
            stats_list = list(user_stats.values())
            stats_list.sort(
                key=lambda x: x["last_memory_updated_at"] if x["last_memory_updated_at"] is not None else 0,
                reverse=True,
            )

            total_count = len(stats_list)

            # Apply pagination
            if limit is not None:
                start_index = 0
                if page is not None and page > 1:
                    start_index = (page - 1) * limit
                stats_list = stats_list[start_index : start_index + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Failed to get user memory stats: {e}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """
        Upsert a user memory into the database.

        Args:
            memory: The memory to upsert.

        Returns:
            Optional[Dict[str, Any]]: The upserted memory data if successful, None otherwise.
        """
        try:
            table_name = self._get_table("memories", create_table_if_not_found=True)
            memory_dict = memory.to_dict()
            memory_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            item = serialize_to_dynamo_item(memory_dict)

            self.client.put_item(TableName=table_name, Item=item)

            if not deserialize:
                return memory_dict

            return UserMemory.from_dict(memory_dict)

        except Exception as e:
            log_error(f"Failed to upsert user memory: {e}")
            raise e

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories for improved performance on large datasets.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            log_info(
                f"DynamoDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
            )

            # Fall back to individual upserts
            results = []
            for memory in memories:
                if memory is not None:
                    result = self.upsert_user_memory(memory, deserialize=deserialize)
                    if result is not None:
                        results.append(result)
            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert: {e}")
            return []

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table_name = self._get_table("memories")

            # Scan the table to get all items
            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination for scan
            while "LastEvaluatedKey" in response:
                response = self.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))

            if not items:
                return

            # Delete items in batches
            for i in range(0, len(items), DYNAMO_BATCH_SIZE_LIMIT):
                batch = items[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for item in batch:
                    # Extract the memory_id from the item
                    memory_id = item.get("memory_id", {}).get("S")
                    if memory_id:
                        delete_requests.append({"DeleteRequest": {"Key": {"memory_id": {"S": memory_id}}}})

                if delete_requests:
                    self.client.batch_write_item(RequestItems={table_name: delete_requests})

        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {e}")
            raise e

    # --- Metrics ---

    def calculate_metrics(self) -> Optional[Any]:
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[Any]: The calculated metrics or None if no metrics table.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        if not self.metrics_table_name:
            return None

        try:
            from agno.utils.log import log_info

            # Get starting date for metrics calculation
            starting_date = self._get_metrics_calculation_starting_date()
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            # Get dates that need metrics calculation
            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            # Get timestamp range for session data
            start_timestamp = int(datetime.combine(dates_to_process[0], datetime.min.time()).timestamp())
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time()).timestamp()
            )

            # Get all sessions for the date range
            sessions = self._get_all_sessions_for_metrics_calculation(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp
            )

            # Process session data for metrics calculation

            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions,
                dates_to_process=dates_to_process,
                start_timestamp=start_timestamp,
            )

            if not all_sessions_data:
                log_info("No new session data found. Won't calculate metrics.")
                return None

            # Calculate metrics for each date
            results = []
            metrics_records = []
            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)
                metrics_records.append(metrics_record)

            # Store metrics in DynamoDB
            if metrics_records:
                results = self._bulk_upsert_metrics(metrics_records)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Failed to calculate metrics: {e}")
            raise e

    def _get_metrics_calculation_starting_date(self) -> Optional[date]:
        """Get the first date for which metrics calculation is needed:
        1. If there are metrics records, return the date of the first day without a complete metrics record.
        2. If there are no metrics records, return the date of the first recorded session.
        3. If there are no metrics records and no sessions records, return None.

        Returns:
            Optional[date]: The starting date for which metrics calculation is needed.
        """
        try:
            metrics_table_name = self._get_table("metrics")

            # 1. Check for existing metrics records
            response = self.client.scan(
                TableName=metrics_table_name,
                ProjectionExpression="#date, completed",
                ExpressionAttributeNames={"#date": "date"},
                Limit=1000,  # Get reasonable number of records to find incomplete ones
            )

            metrics_items = response.get("Items", [])

            # Handle pagination to get all metrics records
            while "LastEvaluatedKey" in response:
                response = self.client.scan(
                    TableName=metrics_table_name,
                    ProjectionExpression="#date, completed",
                    ExpressionAttributeNames={"#date": "date"},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                    Limit=1000,
                )
                metrics_items.extend(response.get("Items", []))

            if metrics_items:
                # Find the latest date with metrics
                latest_complete_date = None
                incomplete_dates = []

                for item in metrics_items:
                    metrics_data = deserialize_from_dynamodb_item(item)
                    record_date = datetime.fromisoformat(metrics_data["date"]).date()
                    is_completed = metrics_data.get("completed", False)

                    if is_completed:
                        if latest_complete_date is None or record_date > latest_complete_date:
                            latest_complete_date = record_date
                    else:
                        incomplete_dates.append(record_date)

                # Return the earliest incomplete date, or the day after the latest complete date
                if incomplete_dates:
                    return min(incomplete_dates)
                elif latest_complete_date:
                    return latest_complete_date + timedelta(days=1)

            # 2. No metrics records. Return the date of the first recorded session.
            sessions_table_name = self._get_table("sessions")

            earliest_session_date = None
            for session_type in ["agent", "team", "workflow"]:
                response = self.client.query(
                    TableName=sessions_table_name,
                    IndexName="session_type-created_at-index",
                    KeyConditionExpression="session_type = :session_type",
                    ExpressionAttributeValues={":session_type": {"S": session_type}},
                    ScanIndexForward=True,  # Ascending order to get earliest
                    Limit=1,
                )

                items = response.get("Items", [])
                if items:
                    first_session = deserialize_from_dynamodb_item(items[0])
                    first_session_timestamp = first_session.get("created_at")

                    if first_session_timestamp:
                        session_date = datetime.fromtimestamp(first_session_timestamp, tz=timezone.utc).date()
                        if earliest_session_date is None or session_date < earliest_session_date:
                            earliest_session_date = session_date

            # 3. Return the earliest session date or None if no sessions exist
            return earliest_session_date

        except Exception as e:
            log_error(f"Failed to get metrics calculation starting date: {e}")
            raise e

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: int, end_timestamp: int
    ) -> List[Dict[str, Any]]:
        """Get all sessions within a timestamp range for metrics calculation.

        Args:
            start_timestamp: Start timestamp (inclusive)
            end_timestamp: End timestamp (exclusive)

        Returns:
            List[Dict[str, Any]]: List of session data dictionaries
        """
        try:
            table_name = self._get_table("sessions")
            all_sessions = []

            # Query sessions by different types within the time range
            for session_type in ["agent", "team", "workflow"]:
                response = self.client.query(
                    TableName=table_name,
                    IndexName="session_type-created_at-index",
                    KeyConditionExpression="session_type = :session_type AND created_at BETWEEN :start_ts AND :end_ts",
                    ExpressionAttributeValues={
                        ":session_type": {"S": session_type},
                        ":start_ts": {"N": str(start_timestamp)},
                        ":end_ts": {"N": str(end_timestamp)},
                    },
                )

                items = response.get("Items", [])

                # Handle pagination
                while "LastEvaluatedKey" in response:
                    response = self.client.query(
                        TableName=table_name,
                        IndexName="session_type-created_at-index",
                        KeyConditionExpression="session_type = :session_type AND created_at BETWEEN :start_ts AND :end_ts",
                        ExpressionAttributeValues={
                            ":session_type": {"S": session_type},
                            ":start_ts": {"N": str(start_timestamp)},
                            ":end_ts": {"N": str(end_timestamp)},
                        },
                        ExclusiveStartKey=response["LastEvaluatedKey"],
                    )
                    items.extend(response.get("Items", []))

                # Deserialize sessions
                for item in items:
                    session_data = deserialize_from_dynamodb_item(item)
                    if session_data:
                        all_sessions.append(session_data)

            return all_sessions

        except Exception as e:
            log_error(f"Failed to get sessions for metrics calculation: {e}")
            raise e

    def _bulk_upsert_metrics(self, metrics_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bulk upsert metrics records into DynamoDB with proper deduplication.

        Args:
            metrics_records: List of metrics records to upsert

        Returns:
            List[Dict[str, Any]]: List of upserted records
        """
        try:
            table_name = self._get_table("metrics")
            if table_name is None:
                return []

            results = []

            # Process each record individually to handle proper upsert
            for record in metrics_records:
                upserted_record = self._upsert_single_metrics_record(table_name, record)
                if upserted_record:
                    results.append(upserted_record)

            return results

        except Exception as e:
            log_error(f"Failed to bulk upsert metrics: {e}")
            raise e

    def _upsert_single_metrics_record(self, table_name: str, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Upsert a single metrics record, checking for existing records with the same date.

        Args:
            table_name: The DynamoDB table name
            record: The metrics record to upsert

        Returns:
            Optional[Dict[str, Any]]: The upserted record or None if failed
        """
        try:
            date_str = record.get("date")
            if not date_str:
                log_error("Metrics record missing date field")
                return None

            # Convert date object to string if needed
            if hasattr(date_str, "isoformat"):
                date_str = date_str.isoformat()

            # Check if a record already exists for this date
            existing_record = self._get_existing_metrics_record(table_name, date_str)

            if existing_record:
                return self._update_existing_metrics_record(table_name, existing_record, record)
            else:
                return self._create_new_metrics_record(table_name, record)

        except Exception as e:
            log_error(f"Failed to upsert single metrics record: {e}")
            raise e

    def _get_existing_metrics_record(self, table_name: str, date_str: str) -> Optional[Dict[str, Any]]:
        """Get existing metrics record for a given date.

        Args:
            table_name: The DynamoDB table name
            date_str: The date string to search for

        Returns:
            Optional[Dict[str, Any]]: The existing record or None if not found
        """
        try:
            # Query using the date-aggregation_period-index
            response = self.client.query(
                TableName=table_name,
                IndexName="date-aggregation_period-index",
                KeyConditionExpression="#date = :date AND aggregation_period = :period",
                ExpressionAttributeNames={"#date": "date"},
                ExpressionAttributeValues={
                    ":date": {"S": date_str},
                    ":period": {"S": "daily"},
                },
                Limit=1,
            )

            items = response.get("Items", [])
            if items:
                return deserialize_from_dynamodb_item(items[0])
            return None

        except Exception as e:
            log_error(f"Failed to get existing metrics record for date {date_str}: {e}")
            raise e

    def _update_existing_metrics_record(
        self,
        table_name: str,
        existing_record: Dict[str, Any],
        new_record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update an existing metrics record.

        Args:
            table_name: The DynamoDB table name
            existing_record: The existing record
            new_record: The new record data

        Returns:
            Optional[Dict[str, Any]]: The updated record or None if failed
        """
        try:
            # Use the existing record's ID
            new_record["id"] = existing_record["id"]
            new_record["updated_at"] = int(time.time())

            # Prepare and serialize the record
            prepared_record = self._prepare_metrics_record_for_dynamo(new_record)
            item = self._serialize_metrics_to_dynamo_item(prepared_record)

            # Update the record
            self.client.put_item(TableName=table_name, Item=item)

            return new_record

        except Exception as e:
            log_error(f"Failed to update existing metrics record: {e}")
            raise e

    def _create_new_metrics_record(self, table_name: str, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new metrics record.

        Args:
            table_name: The DynamoDB table name
            record: The record to create

        Returns:
            Optional[Dict[str, Any]]: The created record or None if failed
        """
        try:
            # Prepare and serialize the record
            prepared_record = self._prepare_metrics_record_for_dynamo(record)
            item = self._serialize_metrics_to_dynamo_item(prepared_record)

            # Create the record
            self.client.put_item(TableName=table_name, Item=item)

            return record

        except Exception as e:
            log_error(f"Failed to create new metrics record: {e}")
            raise e

    def _prepare_metrics_record_for_dynamo(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare a metrics record for DynamoDB serialization by converting all data types properly.

        Args:
            record: The metrics record to prepare

        Returns:
            Dict[str, Any]: The prepared record ready for DynamoDB serialization
        """

        def convert_value(value):
            """Recursively convert values to DynamoDB-compatible types."""
            if value is None:
                return None
            elif isinstance(value, bool):
                return value
            elif isinstance(value, (int, float)):
                return value
            elif isinstance(value, str):
                return value
            elif hasattr(value, "isoformat"):  # date/datetime objects
                return value.isoformat()
            elif isinstance(value, dict):
                return {k: convert_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [convert_value(item) for item in value]
            else:
                return str(value)

        return {key: convert_value(value) for key, value in record.items()}

    def _serialize_metrics_to_dynamo_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize metrics data to DynamoDB item format with proper boolean handling.

        Args:
            data: The metrics data to serialize

        Returns:
            Dict[str, Any]: DynamoDB-ready item
        """
        import json

        item: Dict[str, Any] = {}
        for key, value in data.items():
            if value is not None:
                if isinstance(value, bool):
                    item[key] = {"BOOL": value}
                elif isinstance(value, (int, float)):
                    item[key] = {"N": str(value)}
                elif isinstance(value, str):
                    item[key] = {"S": str(value)}
                elif isinstance(value, (dict, list)):
                    item[key] = {"S": json.dumps(value)}
                else:
                    item[key] = {"S": str(value)}
        return item

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Any], Optional[int]]:
        """
        Get metrics from the database.

        Args:
            starting_date: The starting date to filter metrics by.
            ending_date: The ending date to filter metrics by.

        Returns:
            Tuple[List[Any], Optional[int]]: A tuple containing the metrics data and the total count.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """

        try:
            table_name = self._get_table("metrics")
            if table_name is None:
                return ([], None)

            # Build query parameters
            scan_kwargs: Dict[str, Any] = {"TableName": table_name}

            if starting_date or ending_date:
                filter_expressions = []
                expression_values = {}

                if starting_date:
                    filter_expressions.append("#date >= :start_date")
                    expression_values[":start_date"] = {"S": starting_date.isoformat()}

                if ending_date:
                    filter_expressions.append("#date <= :end_date")
                    expression_values[":end_date"] = {"S": ending_date.isoformat()}

                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
                scan_kwargs["ExpressionAttributeNames"] = {"#date": "date"}
                scan_kwargs["ExpressionAttributeValues"] = expression_values

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Convert to metrics data
            metrics_data = []
            for item in items:
                metric_data = deserialize_from_dynamodb_item(item)
                if metric_data:
                    metrics_data.append(metric_data)

            return metrics_data, len(metrics_data)

        except Exception as e:
            log_error(f"Failed to get metrics: {e}")
            raise e

    # --- Knowledge methods ---

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table_name = self._get_table("knowledge")

            self.client.delete_item(TableName=table_name, Key={"id": {"S": id}})

            log_debug(f"Deleted knowledge content {id}")

        except Exception as e:
            log_error(f"Failed to delete knowledge content {id}: {e}")
            raise e

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        try:
            table_name = self._get_table("knowledge")
            response = self.client.get_item(TableName=table_name, Key={"id": {"S": id}})

            item = response.get("Item")
            if item:
                return deserialize_knowledge_row(item)

            return None

        except Exception as e:
            log_error(f"Failed to get knowledge content {id}: {e}")
            raise e

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table_name = self._get_table("knowledge")
            if table_name is None:
                return [], 0

            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.client.scan(
                    TableName=table_name,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Convert to knowledge rows
            knowledge_rows = []
            for item in items:
                try:
                    knowledge_row = deserialize_knowledge_row(item)
                    knowledge_rows.append(knowledge_row)
                except Exception as e:
                    log_error(f"Failed to deserialize knowledge row: {e}")

            # Apply linked_to filter if provided
            if linked_to is not None:
                knowledge_rows = [row for row in knowledge_rows if row.linked_to == linked_to]

            # Apply sorting
            if sort_by:
                reverse = sort_order == "desc"
                knowledge_rows = sorted(
                    knowledge_rows,
                    key=lambda x: getattr(x, sort_by, ""),
                    reverse=reverse,
                )

            # Get total count before pagination
            total_count = len(knowledge_rows)

            # Apply pagination
            if limit:
                start_index = 0
                if page and page > 1:
                    start_index = (page - 1) * limit
                knowledge_rows = knowledge_rows[start_index : start_index + limit]

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Failed to get knowledge contents: {e}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table_name = self._get_table("knowledge", create_table_if_not_found=True)
            item = serialize_knowledge_row(knowledge_row)

            self.client.put_item(TableName=table_name, Item=item)

            return knowledge_row

        except Exception as e:
            log_error(f"Failed to upsert knowledge content {knowledge_row.id}: {e}")
            raise e

    # --- Eval ---

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an eval run in the database.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during creation.
        """
        try:
            table_name = self._get_table("evals", create_table_if_not_found=True)

            item = serialize_eval_record(eval_run)
            current_time = int(datetime.now(timezone.utc).timestamp())
            item["created_at"] = {"N": str(current_time)}
            item["updated_at"] = {"N": str(current_time)}

            self.client.put_item(TableName=table_name, Item=item)

            return eval_run

        except Exception as e:
            log_error(f"Failed to create eval run: {e}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        if not eval_run_ids or not self.eval_table_name:
            return

        try:
            for i in range(0, len(eval_run_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = eval_run_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for eval_run_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"run_id": {"S": eval_run_id}}}})

                self.client.batch_write_item(RequestItems={self.eval_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete eval runs: {e}")
            raise e

    def get_eval_run_raw(self, eval_run_id: str, table: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.eval_table_name, Key={"run_id": {"S": eval_run_id}})

            item = response.get("Item")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to get eval run {eval_run_id}: {e}")
            raise e

    def get_eval_run(self, eval_run_id: str, table: Optional[Any] = None) -> Optional[EvalRunRecord]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.eval_table_name, Key={"run_id": {"S": eval_run_id}})

            item = response.get("Item")
            if item:
                return deserialize_eval_record(item)
            return None

        except Exception as e:
            log_error(f"Failed to get eval run {eval_run_id}: {e}")
            raise e

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        try:
            table_name = self._get_table("evals")
            if table_name is None:
                return [] if deserialize else ([], 0)

            scan_kwargs = {"TableName": table_name}

            filter_expressions = []
            expression_values = {}

            if agent_id:
                filter_expressions.append("agent_id = :agent_id")
                expression_values[":agent_id"] = {"S": agent_id}

            if team_id:
                filter_expressions.append("team_id = :team_id")
                expression_values[":team_id"] = {"S": team_id}

            if workflow_id:
                filter_expressions.append("workflow_id = :workflow_id")
                expression_values[":workflow_id"] = {"S": workflow_id}

            if model_id:
                filter_expressions.append("model_id = :model_id")
                expression_values[":model_id"] = {"S": model_id}

            if eval_type is not None and len(eval_type) > 0:
                eval_type_conditions = []
                for i, et in enumerate(eval_type):
                    param_name = f":eval_type_{i}"
                    eval_type_conditions.append(f"eval_type = {param_name}")
                    expression_values[param_name] = {"S": str(et.value)}
                filter_expressions.append(f"({' OR '.join(eval_type_conditions)})")

            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    filter_expressions.append("attribute_exists(agent_id)")
                elif filter_type == EvalFilterType.TEAM:
                    filter_expressions.append("attribute_exists(team_id)")
                elif filter_type == EvalFilterType.WORKFLOW:
                    filter_expressions.append("attribute_exists(workflow_id)")

            if filter_expressions:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)

            if expression_values:
                scan_kwargs["ExpressionAttributeValues"] = expression_values  # type: ignore

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Convert to eval data
            eval_data = []
            for item in items:
                eval_item = deserialize_from_dynamodb_item(item)
                if eval_item:
                    eval_data.append(eval_item)

            # Apply sorting
            eval_data = apply_sorting(eval_data, sort_by, sort_order)

            # Get total count before pagination
            total_count = len(eval_data)

            # Apply pagination
            eval_data = apply_pagination(eval_data, limit, page)

            if not deserialize:
                return eval_data, total_count

            eval_runs = []
            for eval_item in eval_data:
                eval_run = EvalRunRecord.model_validate(eval_item)
                eval_runs.append(eval_run)
            return eval_runs

        except Exception as e:
            log_error(f"Failed to get eval runs: {e}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.update_item(
                TableName=self.eval_table_name,
                Key={"run_id": {"S": eval_run_id}},
                UpdateExpression="SET #name = :name, updated_at = :updated_at",
                ExpressionAttributeNames={"#name": "name"},
                ExpressionAttributeValues={
                    ":name": {"S": name},
                    ":updated_at": {"N": str(int(time.time()))},
                },
                ReturnValues="ALL_NEW",
            )

            item = response.get("Attributes")
            if item is None:
                return None

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            item = deserialize_from_dynamodb_item(item)
            return EvalRunRecord.model_validate(item) if deserialize else item

        except Exception as e:
            log_error(f"Failed to rename eval run {eval_run_id}: {e}")
            raise e

    # -- Culture methods --

    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from the database."""
        try:
            table_name = self._get_table("culture")
            response = self.client.scan(TableName=table_name, ProjectionExpression="id")

            with self.client.batch_writer(table_name) as batch:
                for item in response.get("Items", []):
                    batch.delete_item(Key={"id": item["id"]})
        except Exception as e:
            log_error(f"Failed to clear cultural knowledge: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural knowledge entry from the database."""
        try:
            table_name = self._get_table("culture")
            self.client.delete_item(TableName=table_name, Key={"id": {"S": id}})
        except Exception as e:
            log_error(f"Failed to delete cultural knowledge {id}: {e}")
            raise e

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get a cultural knowledge entry from the database."""
        try:
            table_name = self._get_table("culture")
            response = self.client.get_item(TableName=table_name, Key={"id": {"S": id}})

            item = response.get("Item")
            if not item:
                return None

            db_row = deserialize_from_dynamodb_item(item)
            if not deserialize:
                return db_row

            return deserialize_cultural_knowledge_from_db(db_row)
        except Exception as e:
            log_error(f"Failed to get cultural knowledge {id}: {e}")
            raise e

    def get_all_cultural_knowledge(
        self,
        name: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
        """Get all cultural knowledge from the database."""
        try:
            table_name = self._get_table("culture")

            # Build filter expression
            filter_expressions = []
            expression_values = {}

            if name:
                filter_expressions.append("#name = :name")
                expression_values[":name"] = {"S": name}
            if agent_id:
                filter_expressions.append("agent_id = :agent_id")
                expression_values[":agent_id"] = {"S": agent_id}
            if team_id:
                filter_expressions.append("team_id = :team_id")
                expression_values[":team_id"] = {"S": team_id}

            scan_kwargs: Dict[str, Any] = {"TableName": table_name}
            if filter_expressions:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
                scan_kwargs["ExpressionAttributeValues"] = expression_values
                if name:
                    scan_kwargs["ExpressionAttributeNames"] = {"#name": "name"}

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Continue scanning if there's more data
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Deserialize items from DynamoDB format
            db_rows = [deserialize_from_dynamodb_item(item) for item in items]

            # Apply sorting
            if sort_by:
                reverse = sort_order == "desc" if sort_order else False
                db_rows.sort(key=lambda x: x.get(sort_by, ""), reverse=reverse)

            # Apply pagination
            total_count = len(db_rows)
            if limit and page:
                start = (page - 1) * limit
                db_rows = db_rows[start : start + limit]
            elif limit:
                db_rows = db_rows[:limit]

            if not deserialize:
                return db_rows, total_count

            return [deserialize_cultural_knowledge_from_db(row) for row in db_rows]
        except Exception as e:
            log_error(f"Failed to get all cultural knowledge: {e}")
            raise e

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert a cultural knowledge entry into the database."""
        try:
            from uuid import uuid4

            table_name = self._get_table("culture", create_table_if_not_found=True)

            if not cultural_knowledge.id:
                cultural_knowledge.id = str(uuid4())

            # Serialize content, categories, and notes into a dict for DB storage
            content_dict = serialize_cultural_knowledge_for_db(cultural_knowledge)

            # Create the item dict with serialized content
            item_dict = {
                "id": cultural_knowledge.id,
                "name": cultural_knowledge.name,
                "summary": cultural_knowledge.summary,
                "content": content_dict if content_dict else None,
                "metadata": cultural_knowledge.metadata,
                "input": cultural_knowledge.input,
                "created_at": cultural_knowledge.created_at,
                "updated_at": int(time.time()),
                "agent_id": cultural_knowledge.agent_id,
                "team_id": cultural_knowledge.team_id,
            }

            # Convert to DynamoDB format
            item = serialize_to_dynamo_item(item_dict)
            self.client.put_item(TableName=table_name, Item=item)

            return self.get_cultural_knowledge(cultural_knowledge.id, deserialize=deserialize)

        except Exception as e:
            log_error(f"Failed to upsert cultural knowledge: {e}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            table_name = self._get_table("traces", create_table_if_not_found=True)
            if table_name is None:
                return

            # Check if trace already exists
            response = self.client.get_item(
                TableName=table_name,
                Key={"trace_id": {"S": trace.trace_id}},
            )

            existing_item = response.get("Item")
            if existing_item:
                # Update existing trace
                existing = deserialize_from_dynamodb_item(existing_item)

                # Determine component level for name update priority
                def get_component_level(workflow_id, team_id, agent_id, name):
                    is_root_name = ".run" in name or ".arun" in name
                    if not is_root_name:
                        return 0
                    elif workflow_id:
                        return 3
                    elif team_id:
                        return 2
                    elif agent_id:
                        return 1
                    else:
                        return 0

                existing_level = get_component_level(
                    existing.get("workflow_id"),
                    existing.get("team_id"),
                    existing.get("agent_id"),
                    existing.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                # Build update expression
                update_parts = [
                    "end_time = :end_time",
                    "duration_ms = :duration_ms",
                    "#status = :status",
                ]
                expression_attr_names = {"#status": "status"}
                expression_attr_values: Dict[str, Any] = {
                    ":end_time": {"S": trace.end_time.isoformat()},
                    ":duration_ms": {"N": str(recalculated_duration_ms)},
                    ":status": {"S": trace.status},
                }

                if should_update_name:
                    update_parts.append("#name = :name")
                    expression_attr_names["#name"] = "name"
                    expression_attr_values[":name"] = {"S": trace.name}

                if trace.run_id is not None:
                    update_parts.append("run_id = :run_id")
                    expression_attr_values[":run_id"] = {"S": trace.run_id}
                if trace.session_id is not None:
                    update_parts.append("session_id = :session_id")
                    expression_attr_values[":session_id"] = {"S": trace.session_id}
                if trace.user_id is not None:
                    update_parts.append("user_id = :user_id")
                    expression_attr_values[":user_id"] = {"S": trace.user_id}
                if trace.agent_id is not None:
                    update_parts.append("agent_id = :agent_id")
                    expression_attr_values[":agent_id"] = {"S": trace.agent_id}
                if trace.team_id is not None:
                    update_parts.append("team_id = :team_id")
                    expression_attr_values[":team_id"] = {"S": trace.team_id}
                if trace.workflow_id is not None:
                    update_parts.append("workflow_id = :workflow_id")
                    expression_attr_values[":workflow_id"] = {"S": trace.workflow_id}

                self.client.update_item(
                    TableName=table_name,
                    Key={"trace_id": {"S": trace.trace_id}},
                    UpdateExpression="SET " + ", ".join(update_parts),
                    ExpressionAttributeNames=expression_attr_names,
                    ExpressionAttributeValues=expression_attr_values,
                )
            else:
                # Create new trace with initialized counters
                trace_dict = trace.to_dict()
                trace_dict["total_spans"] = 0
                trace_dict["error_count"] = 0
                item = serialize_to_dynamo_item(trace_dict)
                self.client.put_item(TableName=table_name, Item=item)

        except Exception as e:
            log_error(f"Error creating trace: {e}")

    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        """Get a single trace by trace_id or other filters.

        Args:
            trace_id: The unique trace identifier.
            run_id: Filter by run ID (returns first match).

        Returns:
            Optional[Trace]: The trace if found, None otherwise.

        Note:
            If multiple filters are provided, trace_id takes precedence.
            For other filters, the most recent trace is returned.
        """
        try:
            from agno.tracing.schemas import Trace

            table_name = self._get_table("traces")
            if table_name is None:
                return None

            if trace_id:
                # Direct lookup by primary key
                response = self.client.get_item(
                    TableName=table_name,
                    Key={"trace_id": {"S": trace_id}},
                )
                item = response.get("Item")
                if item:
                    trace_data = deserialize_from_dynamodb_item(item)
                    trace_data.setdefault("total_spans", 0)
                    trace_data.setdefault("error_count", 0)
                    return Trace.from_dict(trace_data)
                return None

            elif run_id:
                # Query using GSI
                response = self.client.query(
                    TableName=table_name,
                    IndexName="run_id-start_time-index",
                    KeyConditionExpression="run_id = :run_id",
                    ExpressionAttributeValues={":run_id": {"S": run_id}},
                    ScanIndexForward=False,  # Descending order
                    Limit=1,
                )
                items = response.get("Items", [])
                if items:
                    trace_data = deserialize_from_dynamodb_item(items[0])
                    # Use stored values (default to 0 if not present)
                    trace_data.setdefault("total_spans", 0)
                    trace_data.setdefault("error_count", 0)
                    return Trace.from_dict(trace_data)
                return None

            else:
                log_debug("get_trace called without any filter parameters")
                return None

        except Exception as e:
            log_error(f"Error getting trace: {e}")
            return None

    def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List, int]:
        """Get traces matching the provided filters.

        Args:
            run_id: Filter by run ID.
            session_id: Filter by session ID.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            status: Filter by status (OK, ERROR, UNSET).
            start_time: Filter traces starting after this datetime.
            end_time: Filter traces ending before this datetime.
            limit: Maximum number of traces to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from agno.tracing.schemas import Trace

            table_name = self._get_table("traces")
            if table_name is None:
                return [], 0

            # Determine if we can use a GSI query or need to scan
            use_gsi = False
            gsi_name = None
            key_condition = None
            key_values: Dict[str, Any] = {}

            # Check for GSI-compatible filters (only one can be used as key condition)
            if session_id:
                use_gsi = True
                gsi_name = "session_id-start_time-index"
                key_condition = "session_id = :session_id"
                key_values[":session_id"] = {"S": session_id}
            elif user_id is not None:
                use_gsi = True
                gsi_name = "user_id-start_time-index"
                key_condition = "user_id = :user_id"
                key_values[":user_id"] = {"S": user_id}
            elif agent_id:
                use_gsi = True
                gsi_name = "agent_id-start_time-index"
                key_condition = "agent_id = :agent_id"
                key_values[":agent_id"] = {"S": agent_id}
            elif team_id:
                use_gsi = True
                gsi_name = "team_id-start_time-index"
                key_condition = "team_id = :team_id"
                key_values[":team_id"] = {"S": team_id}
            elif workflow_id:
                use_gsi = True
                gsi_name = "workflow_id-start_time-index"
                key_condition = "workflow_id = :workflow_id"
                key_values[":workflow_id"] = {"S": workflow_id}
            elif run_id:
                use_gsi = True
                gsi_name = "run_id-start_time-index"
                key_condition = "run_id = :run_id"
                key_values[":run_id"] = {"S": run_id}
            elif status:
                use_gsi = True
                gsi_name = "status-start_time-index"
                key_condition = "#status = :status"
                key_values[":status"] = {"S": status}

            # Build filter expression for additional filters
            filter_parts = []
            filter_values: Dict[str, Any] = {}
            expression_attr_names: Dict[str, str] = {}

            if start_time:
                filter_parts.append("start_time >= :start_time")
                filter_values[":start_time"] = {"S": start_time.isoformat()}
            if end_time:
                filter_parts.append("end_time <= :end_time")
                filter_values[":end_time"] = {"S": end_time.isoformat()}

            if status and gsi_name != "status-start_time-index":
                filter_parts.append("#status = :filter_status")
                filter_values[":filter_status"] = {"S": status}
                expression_attr_names["#status"] = "status"

            items = []
            if use_gsi and gsi_name and key_condition:
                # Use GSI query
                query_kwargs: Dict[str, Any] = {
                    "TableName": table_name,
                    "IndexName": gsi_name,
                    "KeyConditionExpression": key_condition,
                    "ExpressionAttributeValues": {**key_values, **filter_values},
                    "ScanIndexForward": False,  # Descending order by start_time
                }
                if gsi_name == "status-start_time-index":
                    expression_attr_names["#status"] = "status"
                if expression_attr_names:
                    query_kwargs["ExpressionAttributeNames"] = expression_attr_names
                if filter_parts:
                    query_kwargs["FilterExpression"] = " AND ".join(filter_parts)

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response:
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))
            else:
                # Use scan
                scan_kwargs: Dict[str, Any] = {"TableName": table_name}
                if filter_parts:
                    scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
                    scan_kwargs["ExpressionAttributeValues"] = filter_values
                if expression_attr_names:
                    scan_kwargs["ExpressionAttributeNames"] = expression_attr_names

                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response:
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            # Deserialize items
            traces_data = [deserialize_from_dynamodb_item(item) for item in items]

            # Sort by start_time descending
            traces_data.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Get total count
            total_count = len(traces_data)

            # Apply pagination
            offset = (page - 1) * limit if page and limit else 0
            paginated_data = traces_data[offset : offset + limit] if limit else traces_data

            # Use stored total_spans and error_count (default to 0 if not present)
            traces = []
            for trace_data in paginated_data:
                # Use stored values - these are updated by create_spans
                trace_data.setdefault("total_spans", 0)
                trace_data.setdefault("error_count", 0)
                traces.append(Trace.from_dict(trace_data))

            return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {e}")
            return [], 0

    def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of sessions to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, workflow_id, total_traces,
                first_trace_at, last_trace_at.
        """
        try:
            table_name = self._get_table("traces")
            if table_name is None:
                return [], 0

            # Fetch all traces and aggregate in memory (DynamoDB doesn't support GROUP BY)
            scan_kwargs: Dict[str, Any] = {"TableName": table_name}

            # Build filter expression
            filter_parts = []
            filter_values: Dict[str, Any] = {}

            if user_id is not None:
                filter_parts.append("user_id = :user_id")
                filter_values[":user_id"] = {"S": user_id}
            if agent_id:
                filter_parts.append("agent_id = :agent_id")
                filter_values[":agent_id"] = {"S": agent_id}
            if team_id:
                filter_parts.append("team_id = :team_id")
                filter_values[":team_id"] = {"S": team_id}
            if workflow_id:
                filter_parts.append("workflow_id = :workflow_id")
                filter_values[":workflow_id"] = {"S": workflow_id}
            if start_time:
                filter_parts.append("created_at >= :start_time")
                filter_values[":start_time"] = {"S": start_time.isoformat()}
            if end_time:
                filter_parts.append("created_at <= :end_time")
                filter_values[":end_time"] = {"S": end_time.isoformat()}

            # Filter for records with session_id
            filter_parts.append("attribute_exists(session_id)")

            if filter_parts:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
            if filter_values:
                scan_kwargs["ExpressionAttributeValues"] = filter_values

            # Scan all matching traces
            items = []
            response = self.client.scan(**scan_kwargs)
            items.extend(response.get("Items", []))

            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Aggregate by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for item in items:
                trace_data = deserialize_from_dynamodb_item(item)
                session_id = trace_data.get("session_id")
                if not session_id:
                    continue

                if session_id not in session_stats:
                    session_stats[session_id] = {
                        "session_id": session_id,
                        "user_id": trace_data.get("user_id"),
                        "agent_id": trace_data.get("agent_id"),
                        "team_id": trace_data.get("team_id"),
                        "workflow_id": trace_data.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": trace_data.get("created_at"),
                        "last_trace_at": trace_data.get("created_at"),
                    }

                session_stats[session_id]["total_traces"] += 1

                created_at = trace_data.get("created_at")
                if (
                    created_at
                    and session_stats[session_id]["first_trace_at"]
                    and session_stats[session_id]["last_trace_at"]
                ):
                    if created_at < session_stats[session_id]["first_trace_at"]:
                        session_stats[session_id]["first_trace_at"] = created_at
                    if created_at > session_stats[session_id]["last_trace_at"]:
                        session_stats[session_id]["last_trace_at"] = created_at

            # Convert to list and sort by last_trace_at descending
            stats_list = list(session_stats.values())
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            # Convert datetime strings to datetime objects
            for stat in stats_list:
                first_trace_at = stat["first_trace_at"]
                last_trace_at = stat["last_trace_at"]
                if isinstance(first_trace_at, str):
                    stat["first_trace_at"] = datetime.fromisoformat(first_trace_at.replace("Z", "+00:00"))
                if isinstance(last_trace_at, str):
                    stat["last_trace_at"] = datetime.fromisoformat(last_trace_at.replace("Z", "+00:00"))

            # Get total count
            total_count = len(stats_list)

            # Apply pagination
            offset = (page - 1) * limit if page and limit else 0
            paginated_stats = stats_list[offset : offset + limit] if limit else stats_list

            return paginated_stats, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {e}")
            return [], 0

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            table_name = self._get_table("spans", create_table_if_not_found=True)
            if table_name is None:
                return

            span_dict = span.to_dict()
            # Serialize attributes as JSON string
            if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                span_dict["attributes"] = json.dumps(span_dict["attributes"])

            item = serialize_to_dynamo_item(span_dict)
            self.client.put_item(TableName=table_name, Item=item)

            # Increment total_spans and error_count on trace
            traces_table_name = self._get_table("traces")
            if traces_table_name:
                try:
                    update_expr = "ADD total_spans :inc"
                    expr_values: Dict[str, Any] = {":inc": {"N": "1"}}

                    if span.status_code == "ERROR":
                        update_expr += ", error_count :inc"

                    self.client.update_item(
                        TableName=traces_table_name,
                        Key={"trace_id": {"S": span.trace_id}},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_values,
                    )
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

        except Exception as e:
            log_error(f"Error creating span: {e}")

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            table_name = self._get_table("spans", create_table_if_not_found=True)
            if table_name is None:
                return

            for i in range(0, len(spans), DYNAMO_BATCH_SIZE_LIMIT):
                batch = spans[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                put_requests = []

                for span in batch:
                    span_dict = span.to_dict()
                    # Serialize attributes as JSON string
                    if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                        span_dict["attributes"] = json.dumps(span_dict["attributes"])

                    item = serialize_to_dynamo_item(span_dict)
                    put_requests.append({"PutRequest": {"Item": item}})

                if put_requests:
                    self.client.batch_write_item(RequestItems={table_name: put_requests})

            # Update trace with total_spans and error_count using ADD (atomic increment)
            trace_id = spans[0].trace_id
            spans_count = len(spans)
            error_count = sum(1 for s in spans if s.status_code == "ERROR")

            traces_table_name = self._get_table("traces")
            if traces_table_name:
                try:
                    # Use ADD for atomic increment - works even if attributes don't exist yet
                    update_expr = "ADD total_spans :spans_inc"
                    expr_values: Dict[str, Any] = {":spans_inc": {"N": str(spans_count)}}

                    if error_count > 0:
                        update_expr += ", error_count :error_inc"
                        expr_values[":error_inc"] = {"N": str(error_count)}

                    self.client.update_item(
                        TableName=traces_table_name,
                        Key={"trace_id": {"S": trace_id}},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_values,
                    )
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

        except Exception as e:
            log_error(f"Error creating spans batch: {e}")

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span

            table_name = self._get_table("spans")
            if table_name is None:
                return None

            response = self.client.get_item(
                TableName=table_name,
                Key={"span_id": {"S": span_id}},
            )

            item = response.get("Item")
            if item:
                span_data = deserialize_from_dynamodb_item(item)
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                return Span.from_dict(span_data)
            return None

        except Exception as e:
            log_error(f"Error getting span: {e}")
            return None

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span

            table_name = self._get_table("spans")
            if table_name is None:
                return []

            items = []

            if trace_id:
                # Use GSI query
                query_kwargs: Dict[str, Any] = {
                    "TableName": table_name,
                    "IndexName": "trace_id-start_time-index",
                    "KeyConditionExpression": "trace_id = :trace_id",
                    "ExpressionAttributeValues": {":trace_id": {"S": trace_id}},
                }
                if limit:
                    query_kwargs["Limit"] = limit

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))

            elif parent_span_id:
                # Use GSI query
                query_kwargs = {
                    "TableName": table_name,
                    "IndexName": "parent_span_id-start_time-index",
                    "KeyConditionExpression": "parent_span_id = :parent_span_id",
                    "ExpressionAttributeValues": {":parent_span_id": {"S": parent_span_id}},
                }
                if limit:
                    query_kwargs["Limit"] = limit

                response = self.client.query(**query_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.query(**query_kwargs)
                    items.extend(response.get("Items", []))

            else:
                # Scan all spans
                scan_kwargs: Dict[str, Any] = {"TableName": table_name}
                if limit:
                    scan_kwargs["Limit"] = limit

                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
                    scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = self.client.scan(**scan_kwargs)
                    items.extend(response.get("Items", []))

            # Deserialize items
            spans = []
            for item in items[:limit] if limit else items:
                span_data = deserialize_from_dynamodb_item(item)
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                spans.append(Span.from_dict(span_data))

            return spans

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

    # -- Learning methods (stubs) --
    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for DynamoDb")

    # -- Context methods --

    def clear_context_items(self) -> None:
        """Delete all context items from the database."""
        try:
            table_name = self._get_table(table_type="context")
            if table_name is None:
                return

            # Scan and delete all items
            response = self.client.scan(TableName=table_name, ProjectionExpression="id")
            items = response.get("Items", [])

            for item in items:
                item_id = deserialize_from_dynamodb_item(item).get("id")
                if item_id:
                    self.client.delete_item(TableName=table_name, Key=serialize_to_dynamo_item({"id": item_id}))

        except Exception as e:
            log_error(f"Exception deleting all context items: {e}")
            raise e

    def delete_context_item(self, id: str) -> None:
        """Delete a context item by ID.

        Args:
            id (str): The ID of the context item to delete.
        """
        try:
            table_name = self._get_table(table_type="context")
            if table_name is None:
                return

            self.client.delete_item(TableName=table_name, Key=serialize_to_dynamo_item({"id": id}))
            log_debug(f"Deleted context item with ID: {id}")

        except Exception as e:
            log_error(f"Error deleting context item: {e}")
            raise e

    def get_context_item(self, id: str) -> Optional[ContextItem]:
        """Get a context item by ID.

        Args:
            id (str): The ID of the context item to retrieve.

        Returns:
            Optional[ContextItem]: The context item if found, None otherwise.
        """
        try:
            table_name = self._get_table(table_type="context")
            if table_name is None:
                return None

            response = self.client.get_item(TableName=table_name, Key=serialize_to_dynamo_item({"id": id}))
            item = response.get("Item")
            if not item:
                return None

            result = deserialize_from_dynamodb_item(item)
            # Ensure content is a string (deserializer might parse JSON strings as dicts)
            if "content" in result and not isinstance(result["content"], str):
                result["content"] = json.dumps(result["content"])
            return ContextItem.from_dict(result)

        except Exception as e:
            log_error(f"Error getting context item: {e}")
            raise e

    def get_all_context_items(
        self,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ContextItem]:
        """Get all context items from the database.

        Args:
            name (Optional[str]): Filter by name.
            metadata (Optional[Dict[str, Any]]): Filter by metadata (containment match).

        Returns:
            List[ContextItem]: List of context items.
        """
        try:
            table_name = self._get_table(table_type="context")
            if table_name is None:
                return []

            # Build filter expression
            filter_parts = []
            expression_values = {}

            if name is not None:
                filter_parts.append("#n = :name")
                expression_values[":name"] = {"S": name}

            scan_kwargs: Dict[str, Any] = {"TableName": table_name}
            if filter_parts:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
                scan_kwargs["ExpressionAttributeValues"] = expression_values
                scan_kwargs["ExpressionAttributeNames"] = {"#n": "name"}

            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            results = [deserialize_from_dynamodb_item(item) for item in items]

            # Filter by metadata if provided (containment match)
            if metadata is not None:
                filtered_results = []
                for r in results:
                    item_metadata = r.get("metadata", {}) or {}
                    if all(item_metadata.get(k) == v for k, v in metadata.items()):
                        filtered_results.append(r)
                results = filtered_results

            # Ensure content is a string for all items (deserializer might parse JSON strings as dicts)
            for r in results:
                if "content" in r and not isinstance(r["content"], str):
                    r["content"] = json.dumps(r["content"])

            return [ContextItem.from_dict(r) for r in results]

        except Exception as e:
            log_error(f"Error getting all context items: {e}")
            raise e

    def upsert_context_item(self, context_item: ContextItem) -> Optional[ContextItem]:
        """Upsert a context item into the database.

        Args:
            context_item (ContextItem): The context item to upsert.

        Returns:
            Optional[ContextItem]: The upserted context item.
        """
        try:
            from uuid import uuid4

            table_name = self._get_table(table_type="context", create_table_if_not_found=True)
            if table_name is None:
                return None

            if not context_item.id:
                context_item.id = str(uuid4())

            item_dict = {
                "id": context_item.id,
                "name": context_item.name,
                "content": context_item.content,
                "description": context_item.description,
                "metadata": context_item.metadata,
                "variables": context_item.variables,
                "version": context_item.version,
                "parent_id": context_item.parent_id,
                "optimization_notes": context_item.optimization_notes,
                "created_at": context_item.created_at if context_item.created_at else int(time.time()),
                "updated_at": context_item.updated_at if context_item.updated_at else int(time.time()),
            }

            # Convert to DynamoDB format
            item = serialize_to_dynamo_item(item_dict)
            self.client.put_item(TableName=table_name, Item=item)

            return self.get_context_item(context_item.id)

        except Exception as e:
            log_error(f"Error upserting context item: {e}")
            raise e
