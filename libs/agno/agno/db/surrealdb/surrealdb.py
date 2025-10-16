from datetime import date, datetime, timedelta, timezone
from textwrap import dedent
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from agno.db.base import BaseDb, SessionType
from agno.db.postgres.utils import (
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas import UserMemory
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.surrealdb import utils
from agno.db.surrealdb.metrics import (
    bulk_upsert_metrics,
    calculate_date_metrics,
    fetch_all_sessions_data,
    get_all_sessions_for_metrics_calculation,
    get_metrics_calculation_starting_date,
)
from agno.db.surrealdb.models import (
    TableType,
    deserialize_eval_run_record,
    deserialize_knowledge_row,
    deserialize_session,
    deserialize_sessions,
    deserialize_user_memories,
    deserialize_user_memory,
    desurrealize_eval_run_record,
    desurrealize_session,
    desurrealize_user_memory,
    get_schema,
    get_session_type,
    serialize_eval_run_record,
    serialize_knowledge_row,
    serialize_session,
    serialize_user_memory,
)
from agno.db.surrealdb.queries import COUNT_QUERY, WhereClause, order_limit_start
from agno.db.surrealdb.utils import build_client
from agno.session import Session
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID
except ImportError:
    raise ImportError("The `surrealdb` package is not installed. Please install it via `pip install surrealdb`.")


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
            id = generate_id(seed)

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
        self._users_table_name: str = "agno_users"
        self._agents_table_name: str = "agno_agents"
        self._teams_table_name: str = "agno_teams"
        self._workflows_table_name: str = "agno_workflows"

    @property
    def client(self) -> Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection]:
        if self._client is None:
            self._client = build_client(self._db_url, self._db_creds, self._db_ns, self._db_db)
        return self._client

    @property
    def table_names(self) -> dict[TableType, str]:
        return {
            "agents": self._agents_table_name,
            "evals": self.eval_table_name,
            "knowledge": self.knowledge_table_name,
            "memories": self.memory_table_name,
            "sessions": self.session_table_name,
            "teams": self._teams_table_name,
            "users": self._users_table_name,
            "workflows": self._workflows_table_name,
        }

    def _table_exists(self, table_name: str) -> bool:
        response = self._query_one("INFO FOR DB", {}, dict)
        if response is None:
            raise Exception("Failed to retrieve database information")
        return table_name in response.get("tables", [])

    def _create_table(self, table_type: TableType, table_name: str):
        query = get_schema(table_type, table_name)
        self.client.query(query)

    def _get_table(self, table_type: TableType, create_table_if_not_found: bool = True):
        if table_type == "sessions":
            table_name = self.session_table_name
        elif table_type == "memories":
            table_name = self.memory_table_name
        elif table_type == "knowledge":
            table_name = self.knowledge_table_name
        elif table_type == "users":
            table_name = self._users_table_name
        elif table_type == "agents":
            table_name = self._agents_table_name
        elif table_type == "teams":
            table_name = self._teams_table_name
        elif table_type == "workflows":
            table_name = self._workflows_table_name
        elif table_type == "evals":
            table_name = self.eval_table_name
        elif table_type == "metrics":
            table_name = self.metrics_table_name
        else:
            raise NotImplementedError(f"Unknown table type: {table_type}")

        if create_table_if_not_found and not self._table_exists(table_name):
            self._create_table(table_type, table_name)

        return table_name

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
    ) -> Optional[utils.RecordType]:
        return utils.query_one(self.client, query, vars, record_type)

    def _count(self, table: str, where_clause: str, where_vars: dict[str, Any], group_by: Optional[str] = None) -> int:
        total_count_query = COUNT_QUERY.format(
            table=table,
            where_clause=where_clause,
            group_clause="GROUP ALL" if group_by is None else f"GROUP BY {group_by}",
            group_fields="" if group_by is None else f", {group_by}",
        )
        count_result = self._query_one(total_count_query, where_vars, dict)
        total_count = count_result.get("count") if count_result else 0
        assert isinstance(total_count, int), f"Expected int, got {type(total_count)}"
        total_count = int(total_count)
        return total_count

    # --- Sessions ---
    def clear_sessions(self) -> None:
        """Delete all session rows from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("sessions")
        _ = self.client.delete(table)

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
        self.client.query(f"DELETE FROM {table} WHERE id IN $records", {"records": records})

    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        r"""
        Read a session from the database.

        Args:
            session_id (str): ID of the session to read.
            session_type (SessionType): Type of session to get.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        sessions_table = self._get_table("sessions")
        record = RecordID(sessions_table, session_id)
        where = WhereClause()
        if user_id is not None:
            where = where.and_("user_id", user_id)
        if session_type == SessionType.AGENT:
            where = where.and_("agent", None, "!=")
        elif session_type == SessionType.TEAM:
            where = where.and_("team", None, "!=")
        elif session_type == SessionType.WORKFLOW:
            where = where.and_("workflow", None, "!=")
        where_clause, where_vars = where.build()
        query = dedent(f"""
            SELECT *
            FROM ONLY $record
            {where_clause}
        """)
        vars = {"record": record, **where_vars}
        raw = self._query_one(query, vars, dict)
        if raw is None or not deserialize:
            return raw

        return deserialize_session(session_type, raw)

    def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
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
        r"""
        Get all sessions in the given table. Can filter by user_id and entity_id.

        Args:
            session_type (SessionType): The type of session to get.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the agent / team / workflow to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
            page (Optional[int]): The page number to return. Defaults to None.
            sort_by (Optional[str]): The field to sort by. Defaults to None.
            sort_order (Optional[str]): The sort order. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the sessions. Defaults to True.

        Returns:
            Union[List[Session], Tuple[List[Dict], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: Tuple of (session dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("sessions")
        # users_table = self._get_table("users", False) # Not used, commenting out for now.
        agents_table = self._get_table("agents", False)
        teams_table = self._get_table("teams", False)
        workflows_table = self._get_table("workflows", False)

        # -- Filters
        where = WhereClause()

        # user_id
        if user_id is not None:
            where = where.and_("user_id", user_id)

        # component_id
        if component_id is not None:
            if session_type == SessionType.AGENT:
                where = where.and_("agent", RecordID(agents_table, component_id))
            elif session_type == SessionType.TEAM:
                where = where.and_("team", RecordID(teams_table, component_id))
            elif session_type == SessionType.WORKFLOW:
                where = where.and_("workflow", RecordID(workflows_table, component_id))

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
            {where_clause}
            {order_limit_start_clause}
        """)
        sessions_raw = self._query(query, where_vars, dict)
        converted_sessions_raw = [desurrealize_session(session, session_type) for session in sessions_raw]

        if not deserialize:
            return list(converted_sessions_raw), total_count

        if session_type is None:
            raise ValueError("session_type is required when deserialize=True")

        return deserialize_sessions(session_type, list(sessions_raw))

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name for the session.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during renaming.
        """
        table = self._get_table("sessions")
        vars = {"record": RecordID(table, session_id), "name": session_name}

        # Query
        query = dedent("""
            UPDATE ONLY $record
            SET session_name = $name
        """)
        session_raw = self._query_one(query, vars, dict)

        if session_raw is None or not deserialize:
            return session_raw
        return deserialize_session(session_type, session_raw)

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Insert or update a session in the database.

        Args:
            session (Session): The session data to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        session_type = get_session_type(session)
        table = self._get_table("sessions")
        session_raw = self._query_one(
            "UPSERT ONLY $record CONTENT $content",
            {
                "record": RecordID(table, session.session_id),
                "content": serialize_session(session, self.table_names),
            },
            dict,
        )
        if session_raw is None or not deserialize:
            return session_raw

        return deserialize_session(session_type, session_raw)

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk insert or update multiple sessions.

        Args:
            sessions (List[Session]): The list of session data to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []
        session_type = get_session_type(sessions[0])
        table = self._get_table("sessions")
        sessions_raw: List[Dict[str, Any]] = []
        for session in sessions:
            # UPSERT does only work for one record at a time
            session_raw = self._query_one(
                "UPSERT ONLY $record CONTENT $content",
                {
                    "record": RecordID(table, session.session_id),
                    "content": serialize_session(session, self.table_names),
                },
                dict,
            )
            if session_raw:
                sessions_raw.append(session_raw)
        if not deserialize:
            return list(sessions_raw)

        # wrapping with list because of:
        # Type "List[Session]" is not assignable to return type "List[Session | Dict[str, Any]]"
        # Consider switching from "list" to "Sequence" which is covariant
        return list(deserialize_sessions(session_type, sessions_raw))

    # --- Memory ---
    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("memories")
        _ = self.client.delete(table)

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("memories")
        mem_rec_id = RecordID(table, memory_id)
        if user_id is None:
            self.client.delete(mem_rec_id)
        else:
            user_rec_id = RecordID(self._get_table("users"), user_id)
            self.client.query(
                f"DELETE FROM {table} WHERE user = $user AND id = $memory",
                {"user": user_rec_id, "memory": mem_rec_id},
            )

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("memories")
        records = [RecordID(table, memory_id) for memory_id in memory_ids]
        if user_id is None:
            _ = self.client.query(f"DELETE FROM {table} WHERE id IN $records", {"records": records})
        else:
            user_rec_id = RecordID(self._get_table("users"), user_id)
            _ = self.client.query(
                f"DELETE FROM {table} WHERE id IN $records AND user = $user", {"records": records, "user": user_rec_id}
            )

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Returns:
            List[str]: List of memory topics.
        """
        table = self._get_table("memories")
        vars: dict[str, Any] = {}

        # Query
        if user_id is None:
            query = dedent(f"""
                RETURN (
                    SELECT
                        array::flatten(topics) as topics
                    FROM ONLY {table}
                    GROUP ALL
                ).topics.distinct();
            """)
        else:
            query = dedent(f"""
                RETURN (
                    SELECT
                        array::flatten(topics) as topics
                    FROM ONLY {table}
                    WHERE user = $user
                    GROUP ALL
                ).topics.distinct();
            """)
            vars["user"] = RecordID(self._get_table("users"), user_id)

        result = self._query(query, vars, str)
        return list(result)

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table_name = self._get_table("memories")
        record = RecordID(table_name, memory_id)
        vars = {"record": record}

        if user_id is None:
            query = "SELECT * FROM ONLY $record"
        else:
            query = "SELECT * FROM ONLY $record WHERE user = $user"
            vars["user"] = RecordID(self._get_table("users"), user_id)

        result = self._query_one(query, vars, dict)
        if result is None or not deserialize:
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
        """Get all memories from the database as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to serialize the memories. Defaults to True.


        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("memories")
        where = WhereClause()
        if user_id is not None:
            rec_id = RecordID(self._get_table("users"), user_id)
            where.and_("user", rec_id)
        if agent_id is not None:
            rec_id = RecordID(self._get_table("agents"), agent_id)
            where.and_("agent", rec_id)
        if team_id is not None:
            rec_id = RecordID(self._get_table("teams"), team_id)
            where.and_("team", rec_id)
        if topics is not None:
            where.and_("topics", topics, "CONTAINSANY")
        if search_content is not None:
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
        if deserialize:
            return deserialize_user_memories(result)
        return [desurrealize_user_memory(x) for x in result], total_count

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
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

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
        memories_table_name = self._get_table("memories")
        where = WhereClause()

        if user_id is None:
            where.and_("!!user", True, "=")  # this checks that user is not falsy
        else:
            where.and_("user", RecordID(self._get_table("users"), user_id), "=")

        where_clause, where_vars = where.build()
        # Group
        group_clause = "GROUP BY user"
        # Order
        order_limit_start_clause = order_limit_start("last_memory_updated_at", "DESC", limit, page)
        # Total count
        total_count = (
            self._query_one(f"(SELECT user FROM {memories_table_name} GROUP BY user).map(|$x| $x.user).len()", {}, int)
            or 0
        )
        # Query
        query = dedent(f"""
            SELECT
                user,
                count(id) AS total_memories,
                time::max(updated_at) AS last_memory_updated_at
            FROM {memories_table_name}
            {where_clause}
            {group_clause}
            {order_limit_start_clause}
        """)
        result = self._query(query, where_vars, dict)

        # deserialize dates and RecordIDs
        for row in result:
            row["user_id"] = row["user"].id
            del row["user"]
            row["last_memory_updated_at"] = row["last_memory_updated_at"].timestamp()
            row["last_memory_updated_at"] = int(row["last_memory_updated_at"])

        return list(result), total_count

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The user memory to upsert.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        table = self._get_table("memories")
        user_table = self._get_table("users")
        if memory.memory_id:
            record = RecordID(table, memory.memory_id)
            query = "UPSERT ONLY $record CONTENT $content"
            result = self._query_one(
                query, {"record": record, "content": serialize_user_memory(memory, table, user_table)}, dict
            )
        else:
            query = f"CREATE ONLY {table} CONTENT $content"
            result = self._query_one(query, {"content": serialize_user_memory(memory, table, user_table)}, dict)
        if result is None:
            return None
        elif not deserialize:
            return desurrealize_user_memory(result)
        return deserialize_user_memory(result)

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk insert or update multiple memories in the database for improved performance.

        Args:
            memories (List[UserMemory]): The list of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []
        table = self._get_table("memories")
        user_table_name = self._get_table("users")
        raw: list[dict] = []
        for memory in memories:
            if memory.memory_id:
                # UPSERT does only work for one record at a time
                session_raw = self._query_one(
                    "UPSERT ONLY $record CONTENT $content",
                    {
                        "record": RecordID(table, memory.memory_id),
                        "content": serialize_user_memory(memory, table, user_table_name),
                    },
                    dict,
                )
            else:
                session_raw = self._query_one(
                    f"CREATE ONLY {table} CONTENT $content",
                    {"content": serialize_user_memory(memory, table, user_table_name)},
                    dict,
                )
            if session_raw is not None:
                raw.append(session_raw)
        if raw is None or not deserialize:
            return [desurrealize_user_memory(x) for x in raw]
        # wrapping with list because of:
        # Type "List[Session]" is not assignable to return type "List[Session | Dict[str, Any]]"
        # Consider switching from "list" to "Sequence" which is covariant
        return list(deserialize_user_memories(raw))

    # --- Metrics ---
    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("metrics")

        where = WhereClause()

        # starting_date - need to convert date to datetime for comparison
        if starting_date is not None:
            starting_datetime = datetime.combine(starting_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            where = where.and_("date", starting_datetime, ">=")

        # ending_date - need to convert date to datetime for comparison
        if ending_date is not None:
            ending_datetime = datetime.combine(ending_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            where = where.and_("date", ending_datetime, "<=")

        where_clause, where_vars = where.build()

        # Query
        query = dedent(f"""
            SELECT *
            FROM {table}
            {where_clause}
            ORDER BY date ASC
        """)

        results = self._query(query, where_vars, dict)

        # Get the latest updated_at from all results
        latest_update = None
        if results:
            # Find the maximum updated_at timestamp
            latest_update = max(int(r["updated_at"].timestamp()) for r in results)

            # Transform results to match expected format
            transformed_results = []
            for r in results:
                transformed = dict(r)

                # Convert RecordID to string
                if hasattr(transformed.get("id"), "id"):
                    transformed["id"] = transformed["id"].id
                elif isinstance(transformed.get("id"), RecordID):
                    transformed["id"] = str(transformed["id"].id)

                # Convert datetime objects to Unix timestamps
                if isinstance(transformed.get("created_at"), datetime):
                    transformed["created_at"] = int(transformed["created_at"].timestamp())
                if isinstance(transformed.get("updated_at"), datetime):
                    transformed["updated_at"] = int(transformed["updated_at"].timestamp())
                if isinstance(transformed.get("date"), datetime):
                    transformed["date"] = int(transformed["date"].timestamp())

                transformed_results.append(transformed)

            return transformed_results, latest_update

        return [], latest_update

    def calculate_metrics(self) -> Optional[List[Dict[str, Any]]]:  # More specific return type
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[List[Dict[str, Any]]]: The calculated metrics.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        try:
            table = self._get_table("metrics")  # Removed create_table_if_not_found parameter

            starting_date = get_metrics_calculation_starting_date(self.client, table, self.get_sessions)

            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc)
            end_timestamp = datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time()).replace(
                tzinfo=timezone.utc
            )

            sessions = get_all_sessions_for_metrics_calculation(
                self.client, self._get_table("sessions"), start_timestamp, end_timestamp
            )

            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions,  # Added parameter name for clarity
                dates_to_process=dates_to_process,
                start_timestamp=int(start_timestamp.timestamp()),  # This expects int
            )
            if not all_sessions_data:
                log_info("No new session data found. Won't calculate metrics.")
                return None

            metrics_records = []

            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)
                metrics_records.append(metrics_record)

            results = []  # Initialize before the if block
            if metrics_records:
                results = bulk_upsert_metrics(self.client, table, metrics_records)

            log_debug("Updated metrics calculations")
            return results

        except Exception as e:
            log_error(f"Exception refreshing metrics: {e}")
            raise e

    # --- Knowledge ---
    def clear_knowledge(self) -> None:
        """Delete all knowledge rows from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("knowledge")
        _ = self.client.delete(table)

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
        """
        table = self._get_table("knowledge")
        self.client.delete(RecordID(table, id))

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        table = self._get_table("knowledge")
        record_id = RecordID(table, id)
        raw = self._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
        return deserialize_knowledge_row(raw) if raw else None

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

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("knowledge")
        where = WhereClause()
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
        return [deserialize_knowledge_row(row) for row in result], total_count

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow) -> Optional[KnowledgeRow]:
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        knowledge_table_name = self._get_table("knowledge")
        record = RecordID(knowledge_table_name, knowledge_row.id)
        query = "UPSERT ONLY $record CONTENT $content"
        result = self._query_one(
            query, {"record": record, "content": serialize_knowledge_row(knowledge_row, knowledge_table_name)}, dict
        )
        return deserialize_knowledge_row(result) if result else None

    # --- Evals ---
    def clear_evals(self) -> None:
        """Delete all eval rows from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("evals")
        _ = self.client.delete(table)

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during creation.
        """
        table = self._get_table("evals")
        rec_id = RecordID(table, eval_run.run_id)
        query = "CREATE ONLY $record CONTENT $content"
        result = self._query_one(
            query, {"record": rec_id, "content": serialize_eval_run_record(eval_run, self.table_names)}, dict
        )
        return deserialize_eval_run_record(result) if result else None

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
        """
        table = self._get_table("evals")
        records = [RecordID(table, id) for id in eval_run_ids]
        _ = self.client.query(f"DELETE FROM {table} WHERE id IN $records", {"records": records})

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("evals")
        record = RecordID(table, eval_run_id)
        result = self._query_one("SELECT * FROM ONLY $record", {"record": record}, dict)
        if not result or not deserialize:
            return desurrealize_eval_run_record(result) if result is not None else None
        return deserialize_eval_run_record(result)

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
        """Get all eval runs from the database.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            model_id (Optional[str]): The ID of the model to filter by.
            eval_type (Optional[List[EvalType]]): The type of eval to filter by.
            filter_type (Optional[EvalFilterType]): The type of filter to apply.
            deserialize (Optional[bool]): Whether to serialize the eval runs. Defaults to True.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        table = self._get_table("evals")

        where = WhereClause()
        if filter_type is not None:
            if filter_type == EvalFilterType.AGENT:
                where.and_("agent", RecordID(self._get_table("agents"), agent_id))
            elif filter_type == EvalFilterType.TEAM:
                where.and_("team", RecordID(self._get_table("teams"), team_id))
            elif filter_type == EvalFilterType.WORKFLOW:
                where.and_("workflow", RecordID(self._get_table("workflows"), workflow_id))
        if model_id is not None:
            where.and_("model_id", model_id)
        if eval_type is not None:
            where.and_("eval_type", eval_type)
        where_clause, where_vars = where.build()

        # Order
        order_limit_start_clause = order_limit_start(sort_by, sort_order, limit, page)

        # Total count
        total_count = self._count(table, where_clause, where_vars)

        # Query
        query = dedent(f"""
            SELECT *
            FROM {table}
            {where_clause}
            {order_limit_start_clause}
        """)
        result = self._query(query, where_vars, dict)

        if not deserialize:
            return list(result), total_count
        return [deserialize_eval_run_record(x) for x in result]

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Update the name of an eval run in the database.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            name (str): The new name of the eval run.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If there is an error updating the eval run.
        """
        table = self._get_table("evals")
        vars = {"record": RecordID(table, eval_run_id), "name": name}

        # Query
        query = dedent("""
            UPDATE ONLY $record
            SET name = $name
        """)
        raw = self._query_one(query, vars, dict)

        if not raw or not deserialize:
            return raw
        return deserialize_eval_run_record(raw)
