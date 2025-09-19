from datetime import date
from textwrap import dedent
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from agno.db.surrealdb.utils import (
    build_client,
    deserialize_session,
    deserialize_sessions,
    deserialize_user_memories,
    deserialize_user_memory,
    get_session_type,
    serialize_session,
    serialize_user_memory,
)

try:
    from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID
except ImportError as e:
    msg = "The `surrealdb` package is not installed. Please install it via `pip install surrealdb`."
    raise ImportError(msg) from e

from agno.db.base import BaseDb, SessionType
from agno.db.schemas import UserMemory
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.surrealdb import utils
from agno.db.surrealdb.queries import COUNT_QUERY, WhereClause, order_limit_start
from agno.db.utils import generate_deterministic_id
from agno.session import Session


class SurrealDb(BaseDb):
    def __init__(
        self,
        client: Optional[Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection]],
        db_url: str,
        db_creds: dict[str, str],
        db_ns: str,
        db_db: str,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a SurrealDB database.

        Args:
            client: A blocking connection, either HTTP or WS
        """
        if id is None:
            base_seed = db_url
            seed = f"{base_seed}#{db_db}"
            id = generate_deterministic_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )
        self._client = client
        self._db_url = db_url
        self._db_creds = db_creds
        self._db_ns = db_ns
        self._db_db = db_db
        self._users_table: str = "user"

    @property
    def client(self) -> BlockingWsSurrealConnection | BlockingHttpSurrealConnection:
        if self._client is None:
            self._client = build_client(self._db_url, self._db_creds, self._db_ns, self._db_db)
        return self._client

    def _get_table(self, table_type: str):
        raise NotImplementedError(f"TODO for {table_type}")

    def _query(
        self,
        query: str,
        vars: dict[str, Any],
        record_type: type[utils.RecordType],
    ) -> Sequence[utils.RecordType]:
        return utils.query(self.client, query, vars, record_type)

    def _query_one(
        self,
        query: str,
        vars: dict[str, Any],
        record_type: type[utils.RecordType],
    ) -> utils.RecordType:
        return utils.query_one(self.client, query, vars, record_type)

    def _count(self, table: str, where_clause: str, where_vars: dict[str, Any]) -> int:
        total_count_query = COUNT_QUERY.format(table=table, where_clause=where_clause)
        count_result = self._query_one(total_count_query, where_vars, dict)
        total_count = count_result.get("count")
        assert isinstance(total_count, int), f"Expected int, got {type(total_count)}"
        total_count = int(total_count)
        return total_count

    # --- Sessions ---
    def delete_session(self, session_id: str) -> bool:
        table = self._get_table(table_type="sessions")
        if table is None:
            return False
        res = self.client.delete(RecordID(table, session_id))
        return bool(res)

    def delete_sessions(self, session_ids: list[str]) -> None:
        table = self._get_table(table_type="sessions")
        if table is None:
            return

        records = [RecordID(table, id) for id in session_ids]
        self.client.query("DELETE FROM $table WHERE id IN $records", {"table": table, "records": records})

    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        table_type = "sessions"
        table = self._get_table(table_type)
        record = RecordID(table, session_id)
        filter_clause = "AND user = $user" if user_id is not None else ""
        query = dedent(f"""
            SELECT VALUE *
            FROM ONLY $record
            WHERE session_type = $session_type
            {filter_clause}
        """)
        vars = {
            "record": record,
            "session_type": session_type,
            "user": RecordID(self._users_table, user_id or ""),
        }
        raw = self._query_one(query, vars, dict)
        if not raw or not deserialize:
            return raw
        return deserialize_session(session_type, raw)

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
        table_type = "sessions"
        table = self._get_table(table_type)

        # -- Filters
        where = WhereClause()

        # session_type
        where = where.and_("session_type", session_type)

        # user_id
        where = where.and_("user", RecordID("user", user_id))

        # component_id
        if component_id is not None:
            if session_type == SessionType.AGENT:
                where = where.and_("agent", RecordID("agent", component_id))
            elif session_type == SessionType.TEAM:
                where = where.and_("agent", RecordID("team", component_id))
            elif session_type == SessionType.WORKFLOW:
                where = where.and_("agent", RecordID("workflow", component_id))

        # session_name
        if session_name is not None:
            where = where.and_("session_name", session_name, "~")

        # start_timestamp
        if start_timestamp is not None:
            where = where.and_("start_timestamp", start_timestamp, ">=")

        # end_timestamp
        if end_timestamp is not None:
            where = where.and_("end_timestamp", end_timestamp, "<=")

        where_clause, where_vars = where.build()

        # Total count
        total_count = self._count(table, where_clause, where_vars)

        # Query
        order_limit_start_clause = order_limit_start(sort_by, sort_order, limit, page)
        query = dedent(f"""
            SELECT *
            FROM {table}
            WHERE session_type = $session_type
            {where_clause}
            {order_limit_start_clause}
        """)
        sessions_raw = self._query(query, where_vars, dict)

        if not deserialize:
            return list(sessions_raw), total_count
        return deserialize_sessions(session_type, list(sessions_raw))

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        table_type = "sessions"
        table = self._get_table(table_type)
        vars = {"record": RecordID(table, session_id), "name": session_name}

        # Query
        query = dedent("""
            UPDATE ONLY $record
            SET session_name = $name
        """)
        session_raw = self._query_one(query, vars, dict)

        if not session_raw or not deserialize:
            return session_raw
        return deserialize_session(session_type, session_raw)

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        table_type = "sessions"
        session_type = get_session_type(session)
        table = self._get_table(table_type)
        session_raw = self._query_one(
            "UPSERT $record CONTENT $content",
            {
                "record": RecordID(table, session.session_id),
                "content": serialize_session(session),
            },
            dict,
        )
        if not session_raw or not deserialize:
            return session_raw
        return deserialize_session(session_type, session_raw)

    # --- Memory ---

    def clear_memories(self) -> None:
        table_type = "memories"
        table = self._get_table(table_type)
        _ = self.client.delete(table)

    def delete_user_memory(self, memory_id: str) -> None:
        table_type = "memories"
        table = self._get_table(table_type)
        self.client.delete(RecordID(table, memory_id))

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        table_type = "memories"
        table = self._get_table(table_type)
        records = [RecordID(table, memory_id) for memory_id in memory_ids]
        _ = self.client.query(f"DELETE FROM {table} WHERE id IN $records", {"records": records})

    def get_all_memory_topics(self) -> List[str]:
        table_type = "memories"
        table = self._get_table(table_type)
        vars = {}

        # Query
        query = dedent(f"""
            RETURN (
                SELECT
                    array::flatten(topics).distinct() as topics
                FROM ONLY {table}
                GROUP ALL
                LIMIT 1
            ).topics;
        """)
        result = self._query_one(query, vars, list[str])
        return result

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        table_type = "memories"
        record = RecordID(table_type, memory_id)
        result = self._query_one(f"SELECT * FROM {record}", {"record": record}, dict)
        if not result or not deserialize:
            return result
        return deserialize_user_memory(result)

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
        table_type = "memories"
        table = self._get_table(table_type)
        where = WhereClause()
        where.and_("user", user_id)
        where.and_("agent", agent_id)
        where.and_("team", team_id)
        where.and_("topics", topics, "CONTAINSANY")
        where.and_("memory", search_content, "~")
        where_clause, where_vars = where.build()

        # Total count
        total_count = self._count(table, where_clause, where_vars)

        # Query
        order_limit_start_clause = order_limit_start(sort_by, sort_order, limit, page)
        query = dedent(f"""
            SELECT *
            FROM {table}
            {where_clause}
            {order_limit_start_clause}
        """)
        result = self._query(query, where_vars, dict)
        if not result or not deserialize:
            return list(result), total_count
        return deserialize_user_memories(result)

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        table_type = "memories"
        table = self._get_table(table_type)
        record = RecordID(table, memory.memory_id)
        query = "UPSERT $record CONTENT $content"
        result = self._query_one(query, {"record": record, "content": serialize_user_memory(memory)}, dict)
        if not result or not deserialize:
            return result
        return deserialize_user_memory(result)

    # --- Metrics ---
    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        raise NotImplementedError

    def calculate_metrics(self) -> Optional[Any]:
        raise NotImplementedError

    # --- Knowledge ---
    def delete_knowledge_content(self, id: str):
        raise NotImplementedError

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        raise NotImplementedError

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        raise NotImplementedError

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        raise NotImplementedError

    # --- Evals ---
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        raise NotImplementedError

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError

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
        raise NotImplementedError

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError

    # def create(self) -> None:
    #     """Create indexes for the table"""
    #     if not self.table_exists():
    #         log_debug(f"Creating table: {self.table}")
    #         query = CREATE_TABLE_QUERY.format(table=self.table)
    #         self.client.query(query)

    # def memory_exists(self, memory: MemoryRow) -> bool:
    #     """Check if a memory exists

    #     Args:
    #         memory: MemoryRow to check
    #     Returns:
    #         bool: True if the memory exists, False otherwise
    #     """
    #     try:
    #         result = self.client.select(RecordID(self.table, memory.id))
    #         logger.debug(f"Found: {result}")
    #         return bool(result)
    #     except Exception as e:
    #         logger.error(f"Error checking memory existence: {e}")
    #         return False

    # def read_memories(
    #     self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    # ) -> List[MemoryRow]:
    #     """Read memories from the table

    #     Args:
    #         user_id: ID of the user to read
    #         limit: Maximum number of memories to read
    #         sort: Sort order ("asc" or "desc")
    #     Returns:
    #         List[MemoryRow]: List of memories
    #     """
    #     filter_clause = "WHERE user = $user" if user_id is not None else ""
    #     limit_clause = f"LIMIT {limit}" if limit is not None else ""
    #     order_clause = f"ORDER BY time.created_at {sort}" if sort is not None else ""
    #     query = dedent(f"""
    #         SELECT *
    #         FROM {self.table}
    #         {filter_clause}
    #         {order_clause}
    #         {limit_clause}
    #     """)
    #     try:
    #         response = self.client.query(
    #             query, {"table": self.table, "user": RecordID(self.users_table, user_id or "")}
    #         )
    #         logger.debug(f"Read memories: {response}. Query: {query}")
    #     except Exception as e:
    #         logger.error(f"Error reading memories: {e}")
    #         raise e
    #     if isinstance(response, list):
    #         memories: List[MemoryRow] = []
    #         for row in response:
    #             memory_rec_id = row.get("id")
    #             user_rec_id = row.get("user")
    #             assert isinstance(user_rec_id, RecordID)
    #             assert isinstance(memory_rec_id, RecordID)
    #             memories.append(MemoryRow(id=memory_rec_id.id, user_id=user_rec_id.id, memory=row.get("memory", {})))
    #         return memories
    #     else:
    #         raise ValueError(f"Unexpected response type: {type(response)}")

    # def drop_table(self) -> None:
    #     """Drop the table

    #     Returns:
    #         None
    #     """
    #     self.client.query(f"REMOVE TABLE IF EXISTS {self.table}")

    # def table_exists(self) -> bool:
    #     """Check if the table exists

    #     Returns:
    #         bool: True if the table exists, False otherwise
    #     """
    #     log_debug(f"Checking if table exists: {self.table}")
    #     response = self.client.query("INFO FOR DB;")
    #     if isinstance(response, dict) and "tables" in response:
    #         return self.table in response["tables"]
    #     else:
    #         logger.error(f"Unexpected response from SurrealDB: {response}")
    #     return False
