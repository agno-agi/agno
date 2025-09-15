from textwrap import dedent
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from agno.db.surrealdb.utils import build_client

try:
    from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID
except ImportError as e:
    msg = "The `surrealdb` package is not installed. Please install it via `pip install surrealdb`."
    raise ImportError(msg) from e

from agno.db.base import BaseDb, SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.queries import CREATE_TABLE_QUERY
from agno.db.utils import deserialize_session_json_fields, generate_deterministic_id
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, logger


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

    def _query(
        self,
        table_type: str,
        query: str,
        vars: dict[str, Any],
        record_type: type[utils.RecordType],
    ) -> Sequence[utils.RecordType]:
        return utils.query(self.client, table_type, query, vars, record_type)

    def _query_one(
        self,
        table_type: str,
        query: str,
        vars: dict[str, Any],
        record_type: type[utils.RecordType],
    ) -> utils.RecordType:
        return utils.query_one(self.client, table_type, query, vars, record_type)

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
        result = self._query_one(table_type, query, vars, dict)

        session_raw = deserialize_session_json_fields(result)
        if not session_raw or not deserialize:
            return session_raw

        if session_type == SessionType.AGENT:
            return AgentSession.from_dict(session_raw)
        elif session_type == SessionType.TEAM:
            return TeamSession.from_dict(session_raw)
        elif session_type == SessionType.WORKFLOW:
            return WorkflowSession.from_dict(session_raw)
        else:
            raise ValueError(f"Invalid session type: {session_type}")

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
        vars = {
            "session_type": session_type,
            "user": RecordID(self._users_table, user_id or ""),
        }

        # -- Filters
        # user_id
        user_filter = "AND user = $user" if user_id is not None else ""
        # component_id
        if component_id is not None:
            component_filter = "AND agent = $component"
            if session_type == SessionType.AGENT:
                vars["component"] = RecordID("agent", component_id)
            elif session_type == SessionType.TEAM:
                vars["component"] = RecordID("team", component_id)
            elif session_type == SessionType.WORKFLOW:
                vars["component"] = RecordID("workflow", component_id)
        else:
            component_filter = ""
        # session_name
        if session_name is not None:
            session_filter = "AND session_data.session_name ~ $session_name"
            vars["session_name"] = session_name
        else:
            session_filter = ""
        # start_timestamp
        if start_timestamp is not None:
            start_filter = "AND time.created_at >= $start_timestamp"
            vars["start_timestamp"] = start_timestamp
        else:
            start_filter = ""
        # end_timestamp
        if end_timestamp is not None:
            end_filter = "AND time.created_at <= $end_timestamp"
            vars["end_timestamp"] = end_timestamp
        else:
            end_filter = ""

        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        start_clause = f"START {page * limit}" if page is not None and limit is not None else ""
        order_clause = f"ORDER BY {sort_by} {sort_order or ''}" if sort_by is not None else ""

        # Total count query
        total_count_query = dedent(f"""
            (SELECT count(id) AS count
            FROM {table}
            WHERE session_type = $session_type
            {user_filter}
            {component_filter}
            {session_filter}
            GROUP BY id)[0] OR {{count: 0}}
        """)
        count_result = self._query_one(table_type, total_count_query, vars, dict)
        total_count = count_result.get("count", 0)

        # Query
        query = dedent(f"""
            SELECT *
            FROM {table}
            WHERE session_type = $session_type
            {user_filter}
            {component_filter}
            {session_filter}
            {start_filter}
            {end_filter}
            {order_clause}
            {limit_clause}
            {start_clause}
        """)
        result = self._query(table_type, query, vars, dict)

        sessions_raw = [deserialize_session_json_fields(x) for x in result]
        if not deserialize:
            return sessions_raw, total_count

        if session_type == SessionType.AGENT:
            return [y for y in [AgentSession.from_dict(x) for x in sessions_raw] if y is not None]
        elif session_type == SessionType.TEAM:
            return [y for y in [TeamSession.from_dict(x) for x in sessions_raw] if y is not None]
        elif session_type == SessionType.WORKFLOW:
            return [y for y in [WorkflowSession.from_dict(x) for x in sessions_raw] if y is not None]
        else:
            raise ValueError(f"Invalid session type: {session_type}")

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
        result = self._query_one(table_type, query, vars, dict)

        session_raw = deserialize_session_json_fields(result)
        if not session_raw or not deserialize:
            return session_raw

        if session_type == SessionType.AGENT:
            return AgentSession.from_dict(session_raw)
        elif session_type == SessionType.TEAM:
            return TeamSession.from_dict(session_raw)
        elif session_type == SessionType.WORKFLOW:
            return WorkflowSession.from_dict(session_raw)
        else:
            raise ValueError(f"Invalid session type: {session_type}")

    # --- Other ---

    def create(self) -> None:
        """Create indexes for the table"""
        if not self.table_exists():
            log_debug(f"Creating table: {self.table}")
            query = CREATE_TABLE_QUERY.format(table=self.table)
            self.client.query(query)

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists

        Args:
            memory: MemoryRow to check
        Returns:
            bool: True if the memory exists, False otherwise
        """
        try:
            result = self.client.select(RecordID(self.table, memory.id))
            logger.debug(f"Found: {result}")
            return bool(result)
        except Exception as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """Read memories from the table

        Args:
            user_id: ID of the user to read
            limit: Maximum number of memories to read
            sort: Sort order ("asc" or "desc")
        Returns:
            List[MemoryRow]: List of memories
        """
        filter_clause = "WHERE user = $user" if user_id is not None else ""
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        order_clause = f"ORDER BY time.created_at {sort}" if sort is not None else ""
        query = dedent(f"""
            SELECT *
            FROM {self.table}
            {filter_clause}
            {order_clause}
            {limit_clause}
        """)
        try:
            response = self.client.query(
                query, {"table": self.table, "user": RecordID(self.users_table, user_id or "")}
            )
            logger.debug(f"Read memories: {response}. Query: {query}")
        except Exception as e:
            logger.error(f"Error reading memories: {e}")
            raise e
        if isinstance(response, list):
            memories: List[MemoryRow] = []
            for row in response:
                memory_rec_id = row.get("id")
                user_rec_id = row.get("user")
                assert isinstance(user_rec_id, RecordID)
                assert isinstance(memory_rec_id, RecordID)
                memories.append(MemoryRow(id=memory_rec_id.id, user_id=user_rec_id.id, memory=row.get("memory", {})))
            return memories
        else:
            raise ValueError(f"Unexpected response type: {type(response)}")

    def upsert_memory(self, memory: MemoryRow) -> None:
        """Upsert a memory into the table

        Args:
            memory: MemoryRow to upsert
        Returns:
            None
        """
        response = self.client.upsert(
            RecordID(self.table, memory.id),
            {"memory": memory.memory, "user": RecordID(self.users_table, memory.user_id)},
        )
        logger.debug(f"Upserted memory with id {memory.id}: {response}")

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory from the table

        Args:
            memory_id: ID of the memory to delete
        Returns:
            None
        """
        self.client.delete(RecordID(self.table, memory_id))

    def drop_table(self) -> None:
        """Drop the table

        Returns:
            None
        """
        self.client.query(f"REMOVE TABLE IF EXISTS {self.table}")

    def table_exists(self) -> bool:
        """Check if the table exists

        Returns:
            bool: True if the table exists, False otherwise
        """
        log_debug(f"Checking if table exists: {self.table}")
        response = self.client.query("INFO FOR DB;")
        if isinstance(response, dict) and "tables" in response:
            return self.table in response["tables"]
        else:
            logger.error(f"Unexpected response from SurrealDB: {response}")
        return False

    def clear(self) -> bool:
        """Clear the table

        Returns:
            bool: True if the table was cleared, False otherwise
        """
        response = self.client.delete(self.table)
        logger.debug(f"Cleared table {self.table}: {response}")
        return False
