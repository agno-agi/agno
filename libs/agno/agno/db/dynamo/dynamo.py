import time
from datetime import date
from os import getenv
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.db.base import BaseDb, SessionType
from agno.db.dynamo.schemas import get_table_schema_definition
from agno.db.dynamo.utils import (
    apply_pagination,
    apply_sorting,
    calculate_date_metrics,
    create_table_if_not_exists,
    deserialize_eval_record,
    deserialize_from_dynamodb_item,
    deserialize_memory_row,
    deserialize_session,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    serialize_memory_row,
    serialize_session_json_fields,
    serialize_to_dynamodb_item,
)
from agno.db.schemas import MemoryRow
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error

try:
    import boto3
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
        user_memory_table: Optional[str] = None,
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
            user_memory_table: The name of the user memory table.
            metrics_table: The name of the metrics table.
            eval_table: The name of the eval table.
            knowledge_table: The name of the knowledge table.
        """
        super().__init__(
            session_table=session_table,
            user_memory_table=user_memory_table,
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
            (self.user_memory_table_name, "user_memories"),
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

    # --- Sessions ---

    def delete_session(self, session_id: Optional[str] = None):
        """
        Delete a session from the database.

        Args:
            session_id: The ID of the session to delete.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        if not session_id:
            return None

        try:
            self.client.delete_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
            )

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
            # Proccess the items to delete in batches of the max allowed size or less
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
            response = self.client.get_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
            )

            item = response.get("Item")
            if item:
                session_raw = deserialize_from_dynamodb_item(item)

                if session_type and session_raw.get("session_type") != session_type.value:
                    return None
                if user_id and session_raw.get("user_id") != user_id:
                    return None

                if not session_raw:
                    return None

                if not deserialize:
                    return deserialize_session(session_raw)

                if session_type == SessionType.AGENT:
                    return AgentSession.from_dict(session_raw)
                elif session_type == SessionType.TEAM:
                    return TeamSession.from_dict(session_raw)
                elif session_type == SessionType.WORKFLOW:
                    return WorkflowSession.from_dict(session_raw)

            return None

        except Exception as e:
            log_error(f"Failed to get session {session_id}: {e}")
            return None

    def get_sessions(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        try:
            if not self.session_table_name:
                raise Exception("Sessions table not found")

            items = fetch_all_sessions_data(
                self.client,
                self.session_table_name,
                session_type.value,
                user_id=user_id,
                component_id=component_id,
                session_name=session_name,
            )

            # Convert DynamoDB items to session data
            sessions_data = []
            for item in items:
                session_data = deserialize_from_dynamodb_item(item)
                if session_data:
                    sessions_data.append(session_data)

            # Apply sorting
            sessions_data = apply_sorting(sessions_data, sort_by, sort_order)

            # Get total count before pagination
            total_count = len(sessions_data)

            # Apply pagination
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
        self, session_id: str, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id: The ID of the session to rename.
            session_name: The new name for the session.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            if not self.session_table_name:
                raise Exception("Sessions table not found")

            response = self.client.update_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}},
                UpdateExpression="SET session_name = :name, updated_at = :updated_at",
                ExpressionAttributeValues={":name": {"S": session_name}, ":updated_at": {"N": str(int(time.time()))}},
                ReturnValues="ALL_NEW",
            )

            item = response.get("Attributes")
            if item:
                session_data = deserialize_from_dynamodb_item(item)
                if not deserialize:
                    return session_data

                session = deserialize_session(session_data)
                return session

            return None

        except Exception as e:
            log_error(f"Failed to rename session {session_id}: {e}")
            return None

    def upsert_session(
        self, session: Session, session_type: SessionType, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Upsert a session into the database.

        Args:
            session (Session): The session to upsert.
            session_type (SessionType): The type of session to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while upserting the session.
        """
        if not self.session_table_name:
            return None

        try:
            serialized_session = serialize_session_json_fields(session.model_dump())
            item = serialize_to_dynamodb_item(serialized_session)

            self.client.put_item(TableName=self.session_table_name, Item=item)

            if not deserialize:
                return serialized_session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(serialized_session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(serialized_session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(serialized_session)

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
            self.client.delete_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})
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

                self.client.batch_write_item(RequestItems={self.user_memory_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete user memories: {e}")

    # TODO:
    def get_all_memory_topics(self) -> List[str]:
        return []

    def get_user_memory_raw(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a user memory from the database as a raw dictionary.

        Args:
            memory_id: The ID of the memory to get.

        Returns:
            Optional[Dict[str, Any]]: The user memory data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the user memory.
        """

        try:
            response = self.client.get_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            return None

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[MemoryRow, Dict[str, Any]]]:
        """
        Get a user memory from the database as a MemoryRow object.

        Args:
            memory_id: The ID of the memory to get.

        Returns:
            Optional[MemoryRow]: The user memory data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the user memory.
        """
        try:
            response = self.client.get_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if not item:
                return None

            if not deserialize:
                return item

            return deserialize_memory_row(item)

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            return None

    # TODO: test all filtering
    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[MemoryRow], List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        """
        Get user memories from the database as a list of MemoryRow objects.

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
            Union[List[MemoryRow], List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]: The user memories data.

        Raises:
            Exception: If any error occurs while getting the user memories.
        """
        try:
            scan_kwargs = {"TableName": self.user_memory_table_name}

            if user_id:
                scan_kwargs["FilterExpression"] = "user_id = :user_id"
                scan_kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}

            if agent_id:
                scan_kwargs["FilterExpression"] = "agent_id = :agent_id"
                scan_kwargs["ExpressionAttributeValues"] = {":agent_id": {"S": agent_id}}

            if team_id:
                scan_kwargs["FilterExpression"] = "team_id = :team_id"
                scan_kwargs["ExpressionAttributeValues"] = {":team_id": {"S": team_id}}

            if workflow_id:
                scan_kwargs["FilterExpression"] = "workflow_id = :workflow_id"
                scan_kwargs["ExpressionAttributeValues"] = {":workflow_id": {"S": workflow_id}}

            if topics:
                scan_kwargs["FilterExpression"] = "topics = :topics"
                scan_kwargs["ExpressionAttributeValues"] = {":topics": {"S": topics}}

            if search_content:
                scan_kwargs["FilterExpression"] = "content = :content"
                scan_kwargs["ExpressionAttributeValues"] = {":content": {"S": search_content}}

            if limit:
                scan_kwargs["Limit"] = str(limit)

            if page:
                scan_kwargs["ExclusiveStartKey"] = {"memory_id": {"S": f"memory_{page}"}}

            # Execute scan
            response = self.client.scan(**scan_kwargs)
            items = response.get("Items", [])

            # Handle pagination for large datasets
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.client.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

            # Convert to session data format
            memories_data = []
            for item in items:
                memory_data = deserialize_from_dynamodb_item(item)
                if memory_data:
                    memories_data.append(memory_data)

            # Apply sorting
            memories_data = apply_sorting(memories_data, sort_by, sort_order)

            # Apply pagination
            memories_data = apply_pagination(memories_data, limit, page)

            if not deserialize:
                return memories_data, len(memories_data)

            memories = []
            for memory_data in memories_data:
                try:
                    memory = MemoryRow.model_validate(memory_data)
                    memories.append(memory)
                except Exception as e:
                    log_error(f"Failed to deserialize memory: {e}")

            return memories

        except Exception as e:
            log_error(f"Failed to get user memories: {e}")
            return [] if deserialize else ([], 0)

    # TODO:
    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        return [], 0

    def upsert_user_memory_raw(self, memory: MemoryRow) -> Optional[Dict[str, Any]]:
        if not self.user_memory_table_name:
            return None

        try:
            item = serialize_memory_row(memory)

            self.client.put_item(TableName=self.user_memory_table_name, Item=item)

            return memory.model_dump()

        except Exception as e:
            log_error(f"Failed to upsert user memory {memory.memory_id}: {e}")
            return None

    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        memory_data = self.upsert_user_memory_raw(memory)
        if memory_data:
            return memory
        return None

    # --- Metrics ---

    # TODO:
    def calculate_metrics(self) -> Optional[Any]:
        if not self.metrics_table_name:
            return None

        try:
            dates_to_calculate = get_dates_to_calculate_metrics_for(self.client, self.metrics_table_name)

            for date_to_calculate in dates_to_calculate:
                metrics_data = calculate_date_metrics(self.client, self.metrics_table_name, date_to_calculate)

            return True

        except Exception as e:
            log_error(f"Failed to calculate metrics: {e}")
            return None

    def get_metrics_raw(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None
    ) -> Tuple[List[Any], Optional[int]]:
        if not self.metrics_table_name:
            return [], 0

        try:
            # Build query parameters
            scan_kwargs = {"TableName": self.metrics_table_name}

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
                metric_data = self._deserialize_from_dynamodb_item(item)
                if metric_data:
                    metrics_data.append(metric_data)

            return metrics_data, len(metrics_data)

        except Exception as e:
            log_error(f"Failed to get metrics: {e}")
            return [], 0

    # --- Knowledge ---

    def get_source_status(self, id: str) -> Optional[str]:
        if not self.knowledge_table_name:
            return None

        try:
            response = self.client.get_item(
                TableName=self.knowledge_table_name, Key={"id": {"S": id}}, ProjectionExpression="status"
            )

            item = response.get("Item")
            if item and "status" in item:
                return item["status"]["S"]
            return None

        except Exception as e:
            log_error(f"Failed to get source status {id}: {e}")
            return None

    def get_knowledge_source(self, id: str) -> Optional[KnowledgeRow]:
        if not self.knowledge_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.knowledge_table_name, Key={"id": {"S": id}})

            item = response.get("Item")
            if item:
                return deserialize_knowledge_row(item)
            return None

        except Exception as e:
            log_error(f"Failed to get knowledge source {id}: {e}")
            return None

    def get_knowledge_sources(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        if not self.knowledge_table_name:
            return [], 0

        try:
            # Execute scan
            response = self.client.scan(TableName=self.knowledge_table_name)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.client.scan(
                    TableName=self.knowledge_table_name, ExclusiveStartKey=response["LastEvaluatedKey"]
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
                knowledge_rows = sorted(knowledge_rows, key=lambda x: getattr(x, sort_by, ""), reverse=reverse)

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
            log_error(f"Failed to get knowledge sources: {e}")
            return [], 0

    def upsert_knowledge_source(self, knowledge_row: KnowledgeRow):
        if not self.knowledge_table_name:
            return

        try:
            item = serialize_knowledge_row(knowledge_row)

            self.client.put_item(TableName=self.knowledge_table_name, Item=item)

        except Exception as e:
            log_error(f"Failed to upsert knowledge source {knowledge_row.knowledge_id}: {e}")

    def delete_knowledge_source(self, id: str):
        if not self.knowledge_table_name:
            return

        try:
            self.client.delete_item(TableName=self.knowledge_table_name, Key={"id": {"S": id}})
            log_debug(f"Deleted knowledge source {id}")
        except Exception as e:
            log_error(f"Failed to delete knowledge source {id}: {e}")

    # --- Eval ---

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[Dict[str, Any]]:
        if not self.eval_table_name:
            return None

        try:
            item = serialize_eval_record(eval_run)

            self.client.put_item(TableName=self.eval_table_name, Item=item)

            return eval_run.model_dump()

        except Exception as e:
            log_error(f"Failed to create eval run {eval_run.eval_run_id}: {e}")
            return None

    # TODO: batch
    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        if not eval_run_ids or not self.eval_table_name:
            return

        try:
            batch_size = 25

            for i in range(0, len(eval_run_ids), batch_size):
                batch = eval_run_ids[i : i + batch_size]

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

    def get_eval_runs_raw(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[List[EvalType]] = None,
        filter_type: Optional[EvalFilterType] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        if not self.eval_table_name:
            return [], 0

        try:
            # Build scan parameters
            scan_kwargs = {"TableName": self.eval_table_name}

            # Add filters if provided
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

            if filter_expressions:
                scan_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
                scan_kwargs["ExpressionAttributeValues"] = expression_values

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

            return eval_data, total_count

        except Exception as e:
            log_error(f"Failed to get eval runs: {e}")
            return [], 0

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[List[EvalType]] = None,
    ) -> List[EvalRunRecord]:
        eval_data, _ = self.get_eval_runs_raw(
            limit, page, sort_by, sort_order, table, agent_id, team_id, workflow_id, model_id, eval_type
        )

        eval_runs = []
        for eval_item in eval_data:
            try:
                eval_run = EvalRunRecord.model_validate(eval_item)
                eval_runs.append(eval_run)
            except Exception as e:
                log_error(f"Failed to deserialize eval run: {e}")

        return eval_runs

    def rename_eval_run(self, eval_run_id: str, name: str) -> Optional[Dict[str, Any]]:
        if not self.eval_table_name:
            return None

        try:
            response = self.client.update_item(
                TableName=self.eval_table_name,
                Key={"run_id": {"S": eval_run_id}},
                UpdateExpression="SET #name = :name, updated_at = :updated_at",
                ExpressionAttributeNames={"#name": "name"},
                ExpressionAttributeValues={":name": {"S": name}, ":updated_at": {"N": str(int(time.time()))}},
                ReturnValues="ALL_NEW",
            )

            item = response.get("Attributes")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to rename eval run {eval_run_id}: {e}")
            return None
