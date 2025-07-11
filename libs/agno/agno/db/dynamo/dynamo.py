import time
from datetime import date
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

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
from agno.db.schemas.knowledge import KnowledgeRow
from agno.eval.schemas import EvalFilterType, EvalRunRecord, EvalType
from agno.session import Session
from agno.utils.log import log_debug, log_error

try:
    import boto3
except ImportError:
    raise ImportError("`boto3` not installed. Please install it using `pip install boto3`")


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

    def delete_session(self, session_id: Optional[str] = None, session_type: SessionType = SessionType.AGENT):
        if not session_id or not self.session_table_name:
            return

        try:
            self.client.delete_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}, "session_type": {"S": session_type.value}},
            )
            log_debug(f"Deleted session {session_id}")
        except Exception as e:
            log_error(f"Failed to delete session {session_id}: {e}")

    # TODO: batch_size = 25 because dynamo enforces a limit of 25. find a better way to handle
    def delete_sessions(self, session_ids: List[str]) -> None:
        if not session_ids or not self.session_table_name:
            return

        try:
            batch_size = 25

            for i in range(0, len(session_ids), batch_size):
                batch = session_ids[i : i + batch_size]

                delete_requests = []
                for session_id in batch:
                    try:
                        response = self.client.scan(
                            TableName=self.session_table_name,
                            FilterExpression="session_id = :session_id",
                            ExpressionAttributeValues={":session_id": {"S": session_id}},
                        )

                        for item in response.get("Items", []):
                            delete_requests.append(
                                {
                                    "DeleteRequest": {
                                        "Key": {"session_id": {"S": session_id}, "session_type": item["session_type"]}
                                    }
                                }
                            )
                    except Exception as e:
                        log_error(f"Failed to find session {session_id} for deletion: {e}")

                if delete_requests:
                    self.client.batch_write_item(RequestItems={self.session_table_name: delete_requests})

        except Exception as e:
            log_error(f"Failed to delete sessions: {e}")

    def get_session_raw(
        self, session_id: str, session_type: SessionType, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.session_table_name:
            return None

        try:
            response = self.client.get_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}, "session_type": {"S": session_type.value}},
            )

            item = response.get("Item")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to get session {session_id}: {e}")
            return None

    def get_session(
        self, session_id: str, session_type: SessionType, user_id: Optional[str] = None
    ) -> Optional[Session]:
        session_data = self.get_session_raw(session_id, session_type, user_id)
        if session_data:
            return deserialize_session(session_data)
        return None

    def get_sessions_raw(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        if not self.session_table_name:
            return [], 0

        try:
            # Fetch all sessions data
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

            return sessions_data, total_count

        except Exception as e:
            log_error(f"Failed to get sessions: {e}")
            return [], 0

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
    ) -> List[Session]:
        sessions_data, _ = self.get_sessions_raw(
            session_type, user_id, component_id, session_name, limit, page, sort_by, sort_order
        )

        sessions = []
        for session_data in sessions_data:
            session = deserialize_session(session_data)
            if session:
                sessions.append(session)

        return sessions

    def rename_session(self, session_id: str, session_type: SessionType, session_name: str) -> Optional[Session]:
        if not self.session_table_name:
            return None

        try:
            response = self.client.update_item(
                TableName=self.session_table_name,
                Key={"session_id": {"S": session_id}, "session_type": {"S": session_type.value}},
                UpdateExpression="SET session_name = :name, updated_at = :updated_at",
                ExpressionAttributeValues={":name": {"S": session_name}, ":updated_at": {"N": str(int(time.time()))}},
                ReturnValues="ALL_NEW",
            )

            item = response.get("Attributes")
            if item:
                session_data = deserialize_from_dynamodb_item(item)
                return deserialize_session(session_data)
            return None

        except Exception as e:
            log_error(f"Failed to rename session {session_id}: {e}")
            return None

    def upsert_session(self, session: Session) -> Optional[Session]:
        if not self.session_table_name:
            return None

        try:
            serialized_session = serialize_session_json_fields(session.model_dump())
            item = serialize_to_dynamodb_item(serialized_session)

            # TODO: fix
            self.client.put_item(TableName=self.session_table_name, Item=item)

            return session

        except Exception as e:
            log_error(f"Failed to upsert session {session.session_id}: {e}")
            return None

    # --- User Memory ---

    def delete_user_memory(self, memory_id: str) -> None:
        if not self.user_memory_table_name:
            return

        try:
            self.client.delete_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})
            log_debug(f"Deleted user memory {memory_id}")

        except Exception as e:
            log_error(f"Failed to delete user memory {memory_id}: {e}")

    # TODO: batch
    def delete_user_memories(self, memory_ids: List[str]) -> None:
        if not memory_ids or not self.user_memory_table_name:
            return

        try:
            batch_size = 25

            for i in range(0, len(memory_ids), batch_size):
                batch = memory_ids[i : i + batch_size]

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
        if not self.user_memory_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if item:
                return deserialize_from_dynamodb_item(item)
            return None

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            return None

    def get_user_memory(self, memory_id: str) -> Optional[MemoryRow]:
        if not self.user_memory_table_name:
            return None

        try:
            response = self.client.get_item(TableName=self.user_memory_table_name, Key={"memory_id": {"S": memory_id}})

            item = response.get("Item")
            if item:
                return deserialize_memory_row(item)
            return None

        except Exception as e:
            log_error(f"Failed to get user memory {memory_id}: {e}")
            return None

    def get_user_memories_raw(
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
    ) -> Tuple[List[Dict[str, Any]], int]:
        if not self.user_memory_table_name:
            return [], 0

        try:
            # Build scan parameters
            scan_kwargs = {"TableName": self.user_memory_table_name}

            if user_id:
                scan_kwargs["FilterExpression"] = "user_id = :user_id"
                scan_kwargs["ExpressionAttributeValues"] = {":user_id": {"S": user_id}}

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

            # Get total count before pagination
            total_count = len(memories_data)

            # Apply pagination
            memories_data = apply_pagination(memories_data, limit, page)

            return memories_data, total_count

        except Exception as e:
            log_error(f"Failed to get user memories: {e}")
            return [], 0

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
    ) -> List[MemoryRow]:
        memories_data, _ = self.get_user_memories_raw(
            user_id, agent_id, team_id, workflow_id, topics, search_content, limit, page, sort_by, sort_order
        )

        memories = []
        for memory_data in memories_data:
            try:
                memory = MemoryRow.model_validate(memory_data)
                memories.append(memory)
            except Exception as e:
                log_error(f"Failed to deserialize memory: {e}")

        return memories

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
