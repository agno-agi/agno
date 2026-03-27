from datetime import date, datetime, timedelta, timezone
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.postgres.utils import (
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas import UserMemory
from agno.db.schemas.context import ContextItem
from agno.db.schemas.culture import CulturalKnowledge
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
    deserialize_context_item,
    deserialize_cultural_knowledge,
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
    serialize_context_item,
    serialize_cultural_knowledge,
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
        culture_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        context_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a SurrealDB database.

        Args:
            client: A blocking connection, either HTTP or WS
            db_url: The URL of the SurrealDB database.
            db_creds: The credentials for the SurrealDB database.
            db_ns: The namespace for the SurrealDB database.
            db_db: The database name for the SurrealDB database.
            session_table: The name of the session table.
            memory_table: The name of the memory table.
            metrics_table: The name of the metrics table.
            eval_table: The name of the eval table.
            knowledge_table: The name of the knowledge table.
            culture_table: The name of the culture table.
            traces_table: The name of the traces table.
            spans_table: The name of the spans table.
            id: The ID of the database.
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
            culture_table=culture_table,
            traces_table=traces_table,
            spans_table=spans_table,
            context_table=context_table,
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
            "context": self.context_table_name,
            "culture": self.culture_table_name,
            "evals": self.eval_table_name,
            "knowledge": self.knowledge_table_name,
            "memories": self.memory_table_name,
            "sessions": self.session_table_name,
            "spans": self.span_table_name,
            "teams": self._teams_table_name,
            "traces": self.trace_table_name,
            "users": self._users_table_name,
            "workflows": self._workflows_table_name,
        }

    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the SurrealDB database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        response = self._query_one("INFO FOR DB", {}, dict)
        if response is None:
            raise Exception("Failed to retrieve database information")
        return table_name in response.get("tables", [])

    def _table_exists(self, table_name: str) -> bool:
        """Deprecated: Use table_exists() instead."""
        return self.table_exists(table_name)

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
        elif table_type == "culture":
            table_name = self.culture_table_name
        elif table_type == "context":
            table_name = self.context_table_name
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
        elif table_type == "traces":
            table_name = self.trace_table_name
        elif table_type == "spans":
            # Ensure traces table exists before spans (for foreign key-like relationship)
            if create_table_if_not_found:
                self._get_table("traces", create_table_if_not_found=True)
            table_name = self.span_table_name
        else:
            raise NotImplementedError(f"Unknown table type: {table_type}")

        if create_table_if_not_found and not self._table_exists(table_name):
            self._create_table(table_type, table_name)

        return table_name

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

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

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        table = self._get_table(table_type="sessions")
        if table is None:
            return False
        if user_id is not None:
            res = self.client.query(
                f"DELETE FROM {table} WHERE id = $record AND user_id = $user_id RETURN BEFORE",
                {"record": RecordID(table, session_id), "user_id": user_id},
            )
            return isinstance(res, list) and len(res) > 0
        res = self.client.delete(RecordID(table, session_id))
        return bool(res)

    def delete_sessions(self, session_ids: list[str], user_id: Optional[str] = None) -> None:
        table = self._get_table(table_type="sessions")
        if table is None:
            return

        records = [RecordID(table, id) for id in session_ids]
        query = f"DELETE FROM {table} WHERE id IN $records"
        params: Dict[str, Any] = {"records": records}
        if user_id is not None:
            query += " AND user_id = $user_id"
            params["user_id"] = user_id
        self.client.query(query, params)

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

        where_clause, where_vars = where.build()
        query = dedent(f"""
            SELECT *
            FROM ONLY $record
            {where_clause}
        """)
        vars = {"record": record, **where_vars}
        raw = self._query_one(query, vars, dict)
        if raw is None:
            return None

        # Verify session type matches
        if session_type == SessionType.AGENT and raw.get("agent") is None:
            return None
        elif session_type == SessionType.TEAM and raw.get("team") is None:
            return None
        elif session_type == SessionType.WORKFLOW and raw.get("workflow") is None:
            return None

        if not deserialize:
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
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during renaming.
        """
        table = self._get_table("sessions")
        vars: Dict[str, Any] = {"record": RecordID(table, session_id), "name": session_name}

        if user_id is not None:
            vars["user_id"] = user_id
            result = self.client.query(
                f"UPDATE {table} SET session_name = $name WHERE id = $record AND user_id = $user_id",
                vars,
            )
            session_raw = (
                result[0] if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) else None
            )
        else:
            session_raw = self._query_one("UPDATE ONLY $record SET session_name = $name", vars, dict)

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

        existing = self.client.query(
            f"SELECT user_id FROM {table} WHERE id = $record",
            {"record": RecordID(table, session.session_id)},
        )
        if isinstance(existing, list) and len(existing) > 0:
            existing_uid = existing[0].get("user_id") if isinstance(existing[0], dict) else None
            if existing_uid is not None and existing_uid != session.user_id:
                return None

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

    # -- Cultural Knowledge methods --
    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("culture")
        _ = self.client.delete(table)

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete cultural knowledge by ID.

        Args:
            id (str): The ID of the cultural knowledge to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("culture")
        rec_id = RecordID(table, id)
        self.client.delete(rec_id)

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get cultural knowledge by ID.

        Args:
            id (str): The ID of the cultural knowledge to retrieve.
            deserialize (Optional[bool]): Whether to deserialize to CulturalKnowledge object. Defaults to True.

        Returns:
            Optional[Union[CulturalKnowledge, Dict[str, Any]]]: The cultural knowledge if found, None otherwise.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("culture")
        rec_id = RecordID(table, id)
        result = self.client.select(rec_id)

        if result is None:
            return None

        if not deserialize:
            return result  # type: ignore

        return deserialize_cultural_knowledge(result)  # type: ignore

    def get_all_cultural_knowledge(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
        """Get all cultural knowledge with filtering and pagination.

        Args:
            agent_id (Optional[str]): Filter by agent ID.
            team_id (Optional[str]): Filter by team ID.
            name (Optional[str]): Filter by name (case-insensitive partial match).
            limit (Optional[int]): Maximum number of results to return.
            page (Optional[int]): Page number for pagination.
            sort_by (Optional[str]): Field to sort by.
            sort_order (Optional[str]): Sort order ('asc' or 'desc').
            deserialize (Optional[bool]): Whether to deserialize to CulturalKnowledge objects. Defaults to True.

        Returns:
            Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of CulturalKnowledge objects
                - When deserialize=False: Tuple with list of dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("culture")

        # Build where clauses
        where_clauses: List[WhereClause] = []
        if agent_id is not None:
            agent_rec_id = RecordID(self._get_table("agents"), agent_id)
            where_clauses.append(("agent", "=", agent_rec_id))  # type: ignore
        if team_id is not None:
            team_rec_id = RecordID(self._get_table("teams"), team_id)
            where_clauses.append(("team", "=", team_rec_id))  # type: ignore
        if name is not None:
            where_clauses.append(("string::lowercase(name)", "CONTAINS", name.lower()))  # type: ignore

        # Build query for total count
        count_query = COUNT_QUERY.format(
            table=table,
            where=""
            if not where_clauses
            else f"WHERE {' AND '.join(f'{w[0]} {w[1]} ${chr(97 + i)}' for i, w in enumerate(where_clauses))}",  # type: ignore
        )
        params = {chr(97 + i): w[2] for i, w in enumerate(where_clauses)}  # type: ignore
        total_count = self._query_one(count_query, params, int) or 0

        # Build main query
        order_limit = order_limit_start(sort_by, sort_order, limit, page)
        query = f"SELECT * FROM {table}"
        if where_clauses:
            query += f" WHERE {' AND '.join(f'{w[0]} {w[1]} ${chr(97 + i)}' for i, w in enumerate(where_clauses))}"  # type: ignore
        query += order_limit

        results = self._query(query, params, list) or []

        if not deserialize:
            return results, total_count  # type: ignore

        return [deserialize_cultural_knowledge(r) for r in results]  # type: ignore

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert cultural knowledge in SurrealDB.

        Args:
            cultural_knowledge (CulturalKnowledge): The cultural knowledge to upsert.
            deserialize (Optional[bool]): Whether to deserialize the result. Defaults to True.

        Returns:
            Optional[Union[CulturalKnowledge, Dict[str, Any]]]: The upserted cultural knowledge.

        Raises:
            Exception: If an error occurs during upsert.
        """
        table = self._get_table("culture", create_table_if_not_found=True)
        serialized = serialize_cultural_knowledge(cultural_knowledge, table)

        result = self.client.upsert(serialized["id"], serialized)

        if result is None:
            return None

        if not deserialize:
            return result  # type: ignore

        return deserialize_cultural_knowledge(result)  # type: ignore

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
        table = self._get_table("knowledge")
        where = WhereClause()

        # Apply linked_to filter if provided
        if linked_to is not None:
            where.and_("linked_to", linked_to)

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

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            table = self._get_table("traces", create_table_if_not_found=True)
            record = RecordID(table, trace.trace_id)

            # Check if trace exists
            existing = self._query_one("SELECT * FROM ONLY $record", {"record": record}, dict)

            if existing:
                # workflow (level 3) > team (level 2) > agent (level 1) > child/unknown (level 0)
                def get_component_level(workflow_id: Any, team_id: Any, agent_id: Any, name: str) -> int:
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
                existing_start_time = existing.get("start_time")
                if isinstance(existing_start_time, datetime):
                    recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)
                else:
                    recalculated_duration_ms = trace.duration_ms

                # Build update query
                update_fields = [
                    "end_time = $end_time",
                    "duration_ms = $duration_ms",
                    "status = $status",
                ]
                update_vars: Dict[str, Any] = {
                    "record": record,
                    "end_time": trace.end_time,
                    "duration_ms": recalculated_duration_ms,
                    "status": trace.status,
                }

                if should_update_name:
                    update_fields.append("name = $name")
                    update_vars["name"] = trace.name

                # Update context fields only if new value is not None
                if trace.run_id is not None:
                    update_fields.append("run_id = $run_id")
                    update_vars["run_id"] = trace.run_id
                if trace.session_id is not None:
                    update_fields.append("session_id = $session_id")
                    update_vars["session_id"] = trace.session_id
                if trace.user_id is not None:
                    update_fields.append("user_id = $user_id")
                    update_vars["user_id"] = trace.user_id
                if trace.agent_id is not None:
                    update_fields.append("agent_id = $agent_id")
                    update_vars["agent_id"] = trace.agent_id
                if trace.team_id is not None:
                    update_fields.append("team_id = $team_id")
                    update_vars["team_id"] = trace.team_id
                if trace.workflow_id is not None:
                    update_fields.append("workflow_id = $workflow_id")
                    update_vars["workflow_id"] = trace.workflow_id

                update_query = f"UPDATE ONLY $record SET {', '.join(update_fields)}"
                self._query_one(update_query, update_vars, dict)
            else:
                # Create new trace
                trace_dict = trace.to_dict()
                trace_dict.pop("total_spans", None)
                trace_dict.pop("error_count", None)

                # Convert datetime fields
                if isinstance(trace_dict.get("start_time"), str):
                    trace_dict["start_time"] = datetime.fromisoformat(trace_dict["start_time"].replace("Z", "+00:00"))
                if isinstance(trace_dict.get("end_time"), str):
                    trace_dict["end_time"] = datetime.fromisoformat(trace_dict["end_time"].replace("Z", "+00:00"))
                if isinstance(trace_dict.get("created_at"), str):
                    trace_dict["created_at"] = datetime.fromisoformat(trace_dict["created_at"].replace("Z", "+00:00"))

                self._query_one(
                    "CREATE ONLY $record CONTENT $content",
                    {"record": record, "content": trace_dict},
                    dict,
                )

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
            table = self._get_table("traces", create_table_if_not_found=False)
            spans_table = self._get_table("spans", create_table_if_not_found=False)

            if trace_id:
                record = RecordID(table, trace_id)
                trace_data = self._query_one("SELECT * FROM ONLY $record", {"record": record}, dict)
            elif run_id:
                query = dedent(f"""
                    SELECT * FROM {table}
                    WHERE run_id = $run_id
                    ORDER BY start_time DESC
                    LIMIT 1
                """)
                trace_data = self._query_one(query, {"run_id": run_id}, dict)
            else:
                log_debug("get_trace called without any filter parameters")
                return None

            if not trace_data:
                return None

            # Calculate total_spans and error_count
            id_obj = trace_data.get("id")
            trace_id_val = trace_data.get("trace_id") or (id_obj.id if id_obj is not None else None)
            if trace_id_val:
                count_query = f"SELECT count() as total FROM {spans_table} WHERE trace_id = $trace_id GROUP ALL"
                count_result = self._query_one(count_query, {"trace_id": trace_id_val}, dict)
                trace_data["total_spans"] = count_result.get("total", 0) if count_result else 0

                error_query = f"SELECT count() as total FROM {spans_table} WHERE trace_id = $trace_id AND status_code = 'ERROR' GROUP ALL"
                error_result = self._query_one(error_query, {"trace_id": trace_id_val}, dict)
                trace_data["error_count"] = error_result.get("total", 0) if error_result else 0

            # Deserialize
            return self._deserialize_trace(trace_data)

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
        """Get traces matching the provided filters with pagination.

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
            table = self._get_table("traces", create_table_if_not_found=False)
            spans_table = self._get_table("spans", create_table_if_not_found=False)

            # Build where clause
            where = WhereClause()
            if run_id:
                where.and_("run_id", run_id)
            if session_id:
                where.and_("session_id", session_id)
            if user_id is not None:
                where.and_("user_id", user_id)
            if agent_id:
                where.and_("agent_id", agent_id)
            if team_id:
                where.and_("team_id", team_id)
            if workflow_id:
                where.and_("workflow_id", workflow_id)
            if status:
                where.and_("status", status)
            if start_time:
                where.and_("start_time", start_time, ">=")
            if end_time:
                where.and_("end_time", end_time, "<=")

            where_clause, where_vars = where.build()

            # Total count
            total_count = self._count(table, where_clause, where_vars)

            # Query with pagination
            order_limit_start_clause = order_limit_start("start_time", "DESC", limit, page)
            query = dedent(f"""
                SELECT * FROM {table}
                {where_clause}
                {order_limit_start_clause}
            """)
            traces_raw = self._query(query, where_vars, dict)

            # Add total_spans and error_count to each trace
            result_traces = []
            for trace_data in traces_raw:
                id_obj = trace_data.get("id")
                trace_id_val = trace_data.get("trace_id") or (id_obj.id if id_obj is not None else None)
                if trace_id_val:
                    count_query = f"SELECT count() as total FROM {spans_table} WHERE trace_id = $trace_id GROUP ALL"
                    count_result = self._query_one(count_query, {"trace_id": trace_id_val}, dict)
                    trace_data["total_spans"] = count_result.get("total", 0) if count_result else 0

                    error_query = f"SELECT count() as total FROM {spans_table} WHERE trace_id = $trace_id AND status_code = 'ERROR' GROUP ALL"
                    error_result = self._query_one(error_query, {"trace_id": trace_id_val}, dict)
                    trace_data["error_count"] = error_result.get("total", 0) if error_result else 0

                result_traces.append(self._deserialize_trace(trace_data))

            return result_traces, total_count

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
            table = self._get_table("traces", create_table_if_not_found=False)

            # Build where clause
            where = WhereClause()
            where.and_("!!session_id", True, "=")  # Ensure session_id is not null
            if user_id is not None:
                where.and_("user_id", user_id)
            if agent_id:
                where.and_("agent_id", agent_id)
            if team_id:
                where.and_("team_id", team_id)
            if workflow_id:
                where.and_("workflow_id", workflow_id)
            if start_time:
                where.and_("created_at", start_time, ">=")
            if end_time:
                where.and_("created_at", end_time, "<=")

            where_clause, where_vars = where.build()

            # Get total count of unique sessions
            count_query = dedent(f"""
                SELECT count() as total FROM (
                    SELECT session_id FROM {table}
                    {where_clause}
                    GROUP BY session_id
                ) GROUP ALL
            """)
            count_result = self._query_one(count_query, where_vars, dict)
            total_count = count_result.get("total", 0) if count_result else 0

            # Query with aggregation
            order_limit_start_clause = order_limit_start("last_trace_at", "DESC", limit, page)
            query = dedent(f"""
                SELECT
                    session_id,
                    user_id,
                    agent_id,
                    team_id,
                    workflow_id,
                    count() AS total_traces,
                    time::min(created_at) AS first_trace_at,
                    time::max(created_at) AS last_trace_at
                FROM {table}
                {where_clause}
                GROUP BY session_id, user_id, agent_id, team_id, workflow_id
                {order_limit_start_clause}
            """)
            results = self._query(query, where_vars, dict)

            # Convert datetime objects
            stats_list = []
            for row in results:
                stat = dict(row)
                if isinstance(stat.get("first_trace_at"), datetime):
                    pass  # Keep as datetime
                if isinstance(stat.get("last_trace_at"), datetime):
                    pass  # Keep as datetime
                stats_list.append(stat)

            return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {e}")
            return [], 0

    def _deserialize_trace(self, trace_data: dict) -> "Trace":
        """Helper to deserialize a trace record from SurrealDB."""
        from agno.tracing.schemas import Trace

        # Handle RecordID for id field
        if isinstance(trace_data.get("id"), RecordID):
            if "trace_id" not in trace_data or not trace_data["trace_id"]:
                trace_data["trace_id"] = trace_data["id"].id
            del trace_data["id"]

        # Convert datetime to ISO string for Trace.from_dict
        for field in ["start_time", "end_time", "created_at"]:
            if isinstance(trace_data.get(field), datetime):
                trace_data[field] = trace_data[field].isoformat()

        return Trace.from_dict(trace_data)

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            table = self._get_table("spans", create_table_if_not_found=True)
            record = RecordID(table, span.span_id)

            span_dict = span.to_dict()

            # Convert datetime fields
            if isinstance(span_dict.get("start_time"), str):
                span_dict["start_time"] = datetime.fromisoformat(span_dict["start_time"].replace("Z", "+00:00"))
            if isinstance(span_dict.get("end_time"), str):
                span_dict["end_time"] = datetime.fromisoformat(span_dict["end_time"].replace("Z", "+00:00"))
            if isinstance(span_dict.get("created_at"), str):
                span_dict["created_at"] = datetime.fromisoformat(span_dict["created_at"].replace("Z", "+00:00"))

            self._query_one(
                "CREATE ONLY $record CONTENT $content",
                {"record": record, "content": span_dict},
                dict,
            )

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
            table = self._get_table("spans", create_table_if_not_found=True)

            for span in spans:
                record = RecordID(table, span.span_id)
                span_dict = span.to_dict()

                # Convert datetime fields
                if isinstance(span_dict.get("start_time"), str):
                    span_dict["start_time"] = datetime.fromisoformat(span_dict["start_time"].replace("Z", "+00:00"))
                if isinstance(span_dict.get("end_time"), str):
                    span_dict["end_time"] = datetime.fromisoformat(span_dict["end_time"].replace("Z", "+00:00"))
                if isinstance(span_dict.get("created_at"), str):
                    span_dict["created_at"] = datetime.fromisoformat(span_dict["created_at"].replace("Z", "+00:00"))

                self._query_one(
                    "CREATE ONLY $record CONTENT $content",
                    {"record": record, "content": span_dict},
                    dict,
                )

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
            table = self._get_table("spans", create_table_if_not_found=False)
            record = RecordID(table, span_id)

            span_data = self._query_one("SELECT * FROM ONLY $record", {"record": record}, dict)
            if not span_data:
                return None

            return self._deserialize_span(span_data)

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
            table = self._get_table("spans", create_table_if_not_found=False)

            # Build where clause
            where = WhereClause()
            if trace_id:
                where.and_("trace_id", trace_id)
            if parent_span_id:
                where.and_("parent_span_id", parent_span_id)

            where_clause, where_vars = where.build()

            # Query
            limit_clause = f"LIMIT {limit}" if limit else ""
            query = dedent(f"""
                SELECT * FROM {table}
                {where_clause}
                ORDER BY start_time ASC
                {limit_clause}
            """)
            spans_raw = self._query(query, where_vars, dict)

            return [self._deserialize_span(s) for s in spans_raw]

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

    def _deserialize_span(self, span_data: dict) -> "Span":
        """Helper to deserialize a span record from SurrealDB."""
        from agno.tracing.schemas import Span

        # Handle RecordID for id field
        if isinstance(span_data.get("id"), RecordID):
            if "span_id" not in span_data or not span_data["span_id"]:
                span_data["span_id"] = span_data["id"].id
            del span_data["id"]

        # Convert datetime to ISO string for Span.from_dict
        for field in ["start_time", "end_time", "created_at"]:
            if isinstance(span_data.get(field), datetime):
                span_data[field] = span_data[field].isoformat()

        return Span.from_dict(span_data)

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
        raise NotImplementedError("Learning methods not yet implemented for SurrealDb")

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
        raise NotImplementedError("Learning methods not yet implemented for SurrealDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for SurrealDb")

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
        raise NotImplementedError("Learning methods not yet implemented for SurrealDb")

    # -- Context methods --

    def clear_context_items(self) -> None:
        """Delete all context items from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("context")
        _ = self.client.delete(table)

    def delete_context_item(self, id: str) -> None:
        """Delete a context item by ID.

        Args:
            id (str): The ID of the context item to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table("context")
        rec_id = RecordID(table, id)
        self.client.delete(rec_id)

    def get_context_item(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[ContextItem, Dict[str, Any]]]:
        """Get a context item by ID.

        Args:
            id (str): The ID of the context item to retrieve.
            deserialize (Optional[bool]): Whether to deserialize to ContextItem object. Defaults to True.

        Returns:
            Optional[Union[ContextItem, Dict[str, Any]]]: The context item if found, None otherwise.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("context")
        rec_id = RecordID(table, id)
        result = self._query_one("SELECT * FROM ONLY $record", {"record": rec_id}, dict)

        if result is None:
            return None

        if not deserialize:
            return result  # type: ignore

        return deserialize_context_item(result)  # type: ignore

    def get_all_context_items(
        self,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[ContextItem], Tuple[List[Dict[str, Any]], int]]:
        """Get all context items with filtering and pagination.

        Args:
            name (Optional[str]): Filter by name.
            metadata (Optional[Dict[str, Any]]): Filter by metadata fields.
            limit (Optional[int]): Maximum number of results to return.
            page (Optional[int]): Page number for pagination.
            sort_by (Optional[str]): Field to sort by.
            sort_order (Optional[str]): Sort order ('asc' or 'desc').
            deserialize (Optional[bool]): Whether to deserialize to ContextItem objects. Defaults to True.

        Returns:
            Union[List[ContextItem], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of ContextItem objects
                - When deserialize=False: Tuple with list of dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table("context")

        # Build where clauses
        where = WhereClause()
        if name is not None:
            where = where.and_("name", name)
        if metadata is not None:
            for key, value in metadata.items():
                where = where.and_(f"metadata.{key}", value)

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

        results = self._query(query, where_vars, dict) or []

        if not deserialize:
            return list(results), total_count  # type: ignore

        return [deserialize_context_item(r) for r in results]  # type: ignore

    def upsert_context_item(
        self, context_item: ContextItem, deserialize: Optional[bool] = True
    ) -> Optional[Union[ContextItem, Dict[str, Any]]]:
        """Upsert a context item in SurrealDB.

        Args:
            context_item (ContextItem): The context item to upsert.
            deserialize (Optional[bool]): Whether to deserialize the result. Defaults to True.

        Returns:
            Optional[Union[ContextItem, Dict[str, Any]]]: The upserted context item.

        Raises:
            Exception: If an error occurs during upsert.
        """
        table = self._get_table("context", create_table_if_not_found=True)

        # Generate ID if not provided
        if context_item.id is None:
            from uuid import uuid4

            context_item.id = str(uuid4())

        serialized = serialize_context_item(context_item, table)
        rec_id = serialized["id"]

        result = self._query_one(
            "UPSERT ONLY $record CONTENT $content",
            {"record": rec_id, "content": serialized},
            dict,
        )

        if result is None:
            return None

        if not deserialize:
            return result  # type: ignore

        return deserialize_context_item(result)  # type: ignore
