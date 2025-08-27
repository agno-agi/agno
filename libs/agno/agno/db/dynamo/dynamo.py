import json
import time
from datetime import date, datetime, timedelta, timezone
from os import getenv
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.db.base import BaseDb, SessionType
from agno.db.dynamo.schemas import get_table_schema_definition
from agno.db.dynamo.utils import (
    apply_pagination,
    apply_sorting,
    build_query_filter_expression,
    build_topic_filter_expression,
    calculate_date_metrics,
    create_table_if_not_exists,
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
    serialize_eval_record,
    serialize_knowledge_row,
    serialize_to_dynamo_item,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error

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
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a DynamoDB database.

        Args:
            db_client: The DynamoDB client to use.
            region_name: AWS region name.
            aws_access_key_id: AWS access key ID.
            aws_secret_access_key: AWS secret access key.
            session_table: The name of the session table.
            memory_table: The name of the memory table.
            metrics_table: The name of the metrics table.
            eval_table: The name of the eval table.
            knowledge_table: The name of the knowledge table.
        """
        super().__init__(
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
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

    def _create_tables(self):
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge_sources"),
        ]

        for table_name, table_type in tables_to_create:
            if table_name:
                try:
                    schema = get_table_schema_definition(table_type)
                    schema["TableName"] = table_name
                    create_table_if_not_exists(self.client, table_name, schema)

                except Exception as e:
                    log_error(f"Failed to create table {table_name}: {e}")

    def _table_exists(self, table_name: str) -> bool:
        """Check if a DynamoDB table with the given name exists.

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
        except Exception as e:
            log_error(f"Error checking if table {table_name} exists: {e}")
            return False

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = True) -> Optional[str]:
        """
        Get table name and ensure the table exists, creating it if needed.

        Args:
            table_type: Type of table ("sessions", "memories", "metrics", "evals", "knowledge_sources")

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
        else:
            raise ValueError(f"Unknown table type: {table_type}")

        # Check if table exists, create if it doesn't
        if not self._table_exists(table_name) and create_table_if_not_found:
            schema = get_table_schema_definition(table_type)
            schema["TableName"] = table_name
            create_table_if_not_exists(self.client, table_name, schema)

        return table_name

    # --- Sessions ---

    def delete_session(self, session_id: Optional[str] = None, session_type: Optional[SessionType] = None) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id: The ID of the session to delete.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        if not session_id:
            return False

        try:
            self.client.delete_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
            )
            return True

        except Exception as e:
            log_error(f"Failed to delete session {session_id}: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str]) -> None:
        """
        Delete sessions from the database in batches.

        Args:
            session_ids: List of session IDs to delete

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        if not session_ids or not self.session_table_name:
            return

        try:
            # Process the items to delete in batches of the max allowed size or less
            for i in range(0, len(session_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = session_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]
                delete_requests = []

                for session_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"session_id": {"S": session_id}}}})

                if delete_requests:
                    self.client.batch_write_item(RequestItems={self.session_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete sessions: {e}")

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Get a session from the database as a Session object.

        Args:
            session_id (str): The ID of the session to get.
            session_type (Optional[SessionType]): The type of session to get.
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

            if session_type and session.get("session_type") != session_type.value:
                return None
            if user_id and session.get("user_id") != user_id:
                return None

            if not session:
                return None

            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            else:
                return WorkflowSession.from_dict(session)

        except Exception as e:
            log_error(f"Failed to get session {session_id}: {e}")
            return None

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

            if user_id:
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
            return []

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id: The ID of the session to rename.
            session_type: The type of session to rename.
            session_name: The new name for the session.

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

            # Update session_data with the new session_name
            session_data = deserialize_from_dynamodb_item(current_item).get("session_data", {})
            session_data["session_name"] = session_name
            response = self.client.update_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
                UpdateExpression="SET session_data = :session_data, updated_at = :updated_at",
                ConditionExpression="session_type = :session_type",
                ExpressionAttributeValues={
                    ":session_data": {"S": json.dumps(session_data)},
                    ":session_type": {"S": session_type.value},
                    ":updated_at": {"N": str(int(time.time()))},
                },
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
            return None

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

            # Prepare the session to upsert, merging with existing session if it exists.
            serialized_session = prepare_session_data(session)
            if existing_item:
                serialized_session = merge_with_existing_session(serialized_session, existing_item)
                serialized_session["updated_at"] = int(time.time())
            else:
                serialized_session["updated_at"] = serialized_session["created_at"]

            # Upsert
            item = serialize_to_dynamo_item(serialized_session)
            self.client.put_item(TableName=table_name, Item=item)

            log_debug(f"Upserted session with id '{session.session_id}'")

            return deserialize_session_result(serialized_session, session, deserialize)

        except Exception as e:
            log_error(f"Failed to upsert session {session.session_id}: {e}")
            return None

    # --- User Memory ---

    def delete_user_memory(self, memory_id: str) -> None:
        """
        Delete a user memory from the database.

        Args:
            memory_id: The ID of the memory to delete.

        Raises:
            Exception: If any error occurs while deleting the user memory.
        """
        try:
            self.client.delete_item(
                TableName=self.memory_table_name,
                Key={"memory_id": {"S": memory_id}},
            )
            log_debug(f"Deleted user memory {memory_id}")

        except Exception as e:
            log_error(f"Failed to delete user memory {memory_id}: {e}")

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        """
        Delete user memories from the database in batches.

        Args:
            memory_ids: List of memory IDs to delete

        Raises:
            Exception: If any error occurs while deleting the user memories.
        """

        try:
            for i in range(0, len(memory_ids), DYNAMO_BATCH_SIZE_LIMIT):
                batch = memory_ids[i : i + DYNAMO_BATCH_SIZE_LIMIT]

                delete_requests = []
                for memory_id in batch:
                    delete_requests.append({"DeleteRequest": {"Key": {"memory_id": {"S": memory_id}}}})

                self.client.batch_write_item(RequestItems={self.memory_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete user memories: {e}")

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: List of unique memory topics.
        """
        try:
            table_name = self._get_table("memories")
            if table_name is None:
                return []

            # Scan the entire table to get all memories
            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
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
            return []

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """
        Get a user memory from the database as a UserMemory object.

        Args:
            memory_id: The ID of the memory to get.

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
            if not deserialize:
                return item

            return UserMemory.from_dict(item)

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            return None

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
            if user_id:
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
            return [] if deserialize else ([], 0)

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.

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

            response = self.client.scan(TableName=table_name)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))

            # Aggregate stats by user_id
            user_stats = {}
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                user_id = memory_data.get("user_id")

                if user_id:
                    if user_id not in user_stats:
                        user_stats[user_id] = {
                            "user_id": user_id,
                            "total_memories": 0,
                            "last_memory_updated_at": None,
                        }

                    user_stats[user_id]["total_memories"] += 1

                    updated_at = memory_data.get("updated_at")
                    if updated_at:
                        updated_at_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        updated_at_timestamp = int(updated_at_dt.timestamp())

                        if updated_at_timestamp and (
                            user_stats[user_id]["last_memory_updated_at"] is None
                            or updated_at_timestamp > user_stats[user_id]["last_memory_updated_at"]
                        ):
                            user_stats[user_id]["last_memory_updated_at"] = updated_at_timestamp

            # Convert to list and apply sorting
            stats_list = list(user_stats.values())
            stats_list.sort(
                key=lambda x: (x["last_memory_updated_at"] if x["last_memory_updated_at"] is not None else 0),
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
            return [], 0

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

            log_debug(f"Upserted user memory with id '{memory.memory_id}'")

            if not deserialize:
                return memory_dict

            return UserMemory.from_dict(memory_dict)

        except Exception as e:
            log_error(f"Failed to upsert user memory: {e}")
            return None

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
            return None

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
            return None

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
            return []

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
            return []

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
            return None

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
            return None

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
            return None

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
            return None

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

        item = {}
        for key, value in data.items():
            if value is not None:
                if isinstance(value, bool):
                    item[key] = {"BOOL": str(value)}
                elif isinstance(value, (int, float)):
                    item[key] = {"N": str(value)}
                elif isinstance(value, str):
                    item[key] = {"S": str(value)}
                elif isinstance(value, (dict, list)):
                    item[key] = {"S": json.dumps(str(value))}
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
            return [], 0

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
            return None

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

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
            return [], 0

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

            log_debug(f"Upserted knowledge content with id '{knowledge_row.id}'")

            return knowledge_row

        except Exception as e:
            log_error(f"Failed to upsert knowledge content {knowledge_row.id}: {e}")
            return None

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
            return None

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
            return None

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
            return None

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
                    filter_expressions.append("agent_id IS NOT NULL")
                elif filter_type == EvalFilterType.TEAM:
                    filter_expressions.append("team_id IS NOT NULL")
                elif filter_type == EvalFilterType.WORKFLOW:
                    filter_expressions.append("workflow_id IS NOT NULL")

            if filter_expressions:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
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
            return [] if deserialize else ([], 0)

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
            return None
