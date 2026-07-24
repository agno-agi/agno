import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import deserialize_session, deserialize_sessions
from agno.db.valkey.utils import (
    apply_filters,
    apply_pagination,
    apply_sorting,
    calculate_date_metrics,
    create_index_entries,
    deserialize_data,
    fetch_all_sessions_data,
    generate_index_key,
    generate_valkey_key,
    get_all_keys_for_table,
    get_dates_to_calculate_metrics_for,
    record_matches_filter_expr,
    remove_index_entries,
    serialize_data,
    validate_filter_expr,
)
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    from glide_sync import (
        Batch,
        ClusterBatch,
        ExpirySet,
        ExpiryType,
        GlideClient,
        GlideClientConfiguration,
        GlideClusterClient,
        NodeAddress,
        RequestError,
        ServerCredentials,
    )
except ImportError:
    raise ImportError("`valkey-glide-sync` not installed. Please install it using `pip install valkey-glide-sync`")


class ValkeyDb(BaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        valkey_client: Optional[Union[GlideClient, GlideClusterClient]] = None,
        host: str = "localhost",
        port: int = 6379,
        database_id: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = False,
        request_timeout: Optional[int] = None,
        db_prefix: str = "agno",
        client_name: str = "agno_db_client",
        expire: Optional[int] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a Valkey database using valkey-glide.

        The following order is used to determine the database connection:
            1. Use the valkey_client if provided
            2. Create a new GlideClient from host/port and optional auth/TLS settings
            3. Raise an error if client creation fails

        Args:
            id (Optional[str]): The ID of the database.
            valkey_client (Optional[Union[GlideClient, GlideClusterClient]]): Valkey GLIDE client instance to use.
                If not provided a new client will be created.
            host (str): Valkey server host. Defaults to "localhost".
            port (int): Valkey server port. Defaults to 6379.
            database_id (Optional[int]): Index of the logical database to connect to (e.g. 0-15).
                If not set, the server default (database 0) is used.
            username (Optional[str]): Username for Valkey server authentication.
                If not supplied, the server's "default" user is used.
            password (Optional[str]): Password for Valkey server authentication.
                Required when username is set.
            use_tls (bool): Whether to use TLS for the connection. Defaults to False.
            request_timeout (Optional[int]): Duration in milliseconds to wait for a request to complete.
                If not set, the client default (250 milliseconds) is used.
            db_prefix (str): Prefix for all Valkey keys
            client_name (str): Connection name set via CLIENT SETNAME, visible in CLIENT LIST.
            expire (Optional[int]): TTL for Valkey keys in seconds
            session_table (Optional[str]): Name of the table to store sessions
            memory_table (Optional[str]): Name of the table to store memories
            metrics_table (Optional[str]): Name of the table to store metrics
            eval_table (Optional[str]): Name of the table to store evaluation runs
            knowledge_table (Optional[str]): Name of the table to store knowledge documents
            traces_table (Optional[str]): Name of the table to store traces
            spans_table (Optional[str]): Name of the table to store spans
            learnings_table (Optional[str]): Name of the table to store learnings

        Raises:
            ValueError: If username is provided without a password.
        """
        if id is None:
            base_seed = f"{host}:{port}" if valkey_client is None else str(valkey_client)
            seed = f"{base_seed}#{db_prefix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            learnings_table=learnings_table,
        )

        self.db_prefix = db_prefix
        self.expire = expire

        if valkey_client is not None:
            self.valkey_client = valkey_client
        else:
            if username and not password:
                raise ValueError("password must be provided when username is set")
            credentials = ServerCredentials(password=password, username=username) if password else None
            config = GlideClientConfiguration(
                addresses=[NodeAddress(host=host, port=port)],
                database_id=database_id,
                credentials=credentials,
                use_tls=use_tls,
                request_timeout=request_timeout,
                client_name=client_name,
            )
            self.valkey_client = GlideClient.create(config)

    # -- DB methods --

    def _create_pipeline(self) -> Union[Batch, ClusterBatch]:
        """Create a non-atomic batch (pipeline) appropriate for the client type."""
        if isinstance(self.valkey_client, GlideClusterClient):
            return ClusterBatch(is_atomic=False)
        return Batch(is_atomic=False)

    def _exec_pipeline(self, pipeline: Union[Batch, ClusterBatch]) -> Optional[List[Any]]:
        """Execute a batch pipeline on the appropriate client."""
        if isinstance(self.valkey_client, GlideClusterClient) and isinstance(pipeline, ClusterBatch):
            return self.valkey_client.exec(pipeline, raise_on_error=False)
        elif isinstance(self.valkey_client, GlideClient) and isinstance(pipeline, Batch):
            return self.valkey_client.exec(pipeline, raise_on_error=False)
        return None

    def table_exists(self, table_name: str) -> bool:
        """Required by BaseDb. Valkey has no tables and keys are created on
        first write, so existence checks always pass."""
        return True

    def _get_table_name(self, table_type: str) -> str:
        """Get the active table name for the given table type."""
        if table_type == "sessions":
            return self.session_table_name

        elif table_type == "memories":
            return self.memory_table_name

        elif table_type == "metrics":
            return self.metrics_table_name

        elif table_type == "evals":
            return self.eval_table_name

        elif table_type == "knowledge":
            return self.knowledge_table_name

        elif table_type == "traces":
            return self.trace_table_name

        elif table_type == "spans":
            return self.span_table_name

        elif table_type == "learnings":
            return self.learnings_table_name

        raise ValueError(f"Unknown table type: {table_type}")

    def _store_record(
        self, table_type: str, record_id: str, data: Dict[str, Any], index_fields: Optional[List[str]] = None
    ) -> bool:
        """Generic method to store a record in Valkey, considering optional indexing.

        Args:
            table_type (str): The type of table to store the record in.
            record_id (str): The ID of the record to store.
            data (Dict[str, Any]): The data to store in the record.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was stored successfully, False otherwise.
        """
        try:
            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            serialized_data = serialize_data(data)

            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            self.valkey_client.set(key, serialized_data, expiry=expiry)

            if index_fields:
                create_index_entries(
                    valkey_client=self.valkey_client,
                    prefix=self.db_prefix,
                    table_type=table_type,
                    record_id=record_id,
                    record_data=data,
                    index_fields=index_fields,
                )

            return True

        except Exception as e:
            log_error(f"Error storing Valkey record: {str(e)}")
            return False

    def _get_record(self, table_type: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Generic method to get a record from Valkey.

        Args:
            table_type (str): The type of table to get the record from.
            record_id (str): The ID of the record to get.

        Returns:
            Optional[Dict[str, Any]]: The record data if found, None otherwise.
        """
        try:
            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)

            data = self.valkey_client.get(key)
            if data is None:
                return None

            # glide returns bytes, decode if needed
            data_str: str = data.decode("utf-8") if isinstance(data, bytes) else data

            return deserialize_data(data_str)  # type: ignore

        except Exception as e:
            log_error(f"Error getting record {record_id}: {str(e)}")
            return None

    def _delete_record(self, table_type: str, record_id: str, index_fields: Optional[List[str]] = None) -> bool:
        """Generic method to delete a record from Valkey.

        Args:
            table_type (str): The type of table to delete the record from.
            record_id (str): The ID of the record to delete.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.

        Raises:
            Exception: If any error occurs while deleting the record.
        """
        try:
            # Handle index deletion first
            if index_fields:
                record_data = self._get_record(table_type, record_id)
                if record_data:
                    remove_index_entries(
                        valkey_client=self.valkey_client,
                        prefix=self.db_prefix,
                        table_type=table_type,
                        record_id=record_id,
                        record_data=record_data,
                        index_fields=index_fields,
                    )

            key = generate_valkey_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            result = self.valkey_client.delete([key])
            if result is None or result == 0:
                return False

            return True

        except Exception as e:
            log_error(f"Error deleting record {record_id}: {str(e)}")
            return False

    def _get_all_records(self, table_type: str) -> List[Dict[str, Any]]:
        """Generic method to get all records for a table type using pipeline batching.

        Args:
            table_type (str): The type of table to get the records from.

        Returns:
            List[Dict[str, Any]]: The records data if found, empty list otherwise.

        Raises:
            Exception: If any error occurs while getting the records.
        """
        try:
            keys = get_all_keys_for_table(
                valkey_client=self.valkey_client, prefix=self.db_prefix, table_type=table_type
            )

            if not keys:
                return []

            # Batch all GETs in a single pipeline round trip
            pipeline = self._create_pipeline()
            for key in keys:
                pipeline.get(key)

            results = self._exec_pipeline(pipeline)
            if not results:
                return []

            records = []
            for raw in results:
                if raw is None or isinstance(raw, RequestError):
                    continue
                data_str: str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else ""
                if data_str:
                    records.append(deserialize_data(data_str))

            return records

        except Exception as e:
            log_error(f"Error getting all records for {table_type}: {str(e)}")
            return []

    def get_latest_schema_version(self, table_name: str = ""):
        """Get the latest version of the database schema.

        Args:
            table_name: The table name (accepted for BaseDb interface compatibility,
                but unused since Valkey is schemaless).
        """
        pass

    def upsert_schema_version(self, table_name: str = "", version: str = "") -> None:
        """Upsert the schema version into the database.

        Args:
            table_name: The table name (accepted for BaseDb interface compatibility,
                but unused since Valkey is schemaless).
            version: The schema version string.
        """
        pass

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from Valkey.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        try:
            if user_id is not None:
                session = self._get_record("sessions", session_id)
                if session is None or session.get("user_id") != user_id:
                    log_debug(f"No session found to delete with session_id: {session_id} and user_id: {user_id}")
                    return False
            if self._delete_record(
                table_type="sessions",
                record_id=session_id,
                index_fields=["user_id", "agent_id", "team_id", "workflow_id", "session_type"],
            ):
                log_debug(f"Successfully deleted session: {session_id}")
                return True
            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        if not session_ids:
            return

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id", "session_type"]

            # Phase 1: Batch-read all sessions (needed for index cleanup and user_id filtering)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for session_id in session_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0

            for i, session_id in enumerate(session_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                # Filter by user_id if provided
                if user_id is not None and record_data.get("user_id") != user_id:
                    continue

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "sessions", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [session_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

            log_debug(f"Successfully deleted {delete_count} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Read a session from Valkey.

        Args:
            session_id (str): The ID of the session to get.
            session_type (Optional[SessionType]): The type of session to get.
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            Optional[Union[AgentSession, TeamSession, WorkflowSession]]: The session if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the session.
        """
        try:
            session = self._get_record("sessions", session_id)
            if session is None:
                return None

            # Apply filters
            if user_id is not None and session.get("user_id") != user_id:
                return None

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception reading session: {str(e)}")
            raise e

    # TODO: Use index sets (agno:sessions:index:user_id:<id>) to avoid full scan when filtering by user_id/agent_id
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
        create_index_if_not_found: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """Get all sessions matching the given filters.

        Args:
            session_type (Optional[SessionType]): The type of session to filter by.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the component (agent/team/workflow) to filter by.
            session_name (Optional[str]): The name of the session to filter by (case-insensitive substring).
            start_timestamp (Optional[int]): Unix timestamp lower bound on created_at.
            end_timestamp (Optional[int]): Unix timestamp upper bound on created_at.
            limit (Optional[int]): The maximum number of sessions to return.
            page (Optional[int]): The 1-based page number (used with limit).
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The sort direction ('asc' or 'desc').
            deserialize (Optional[bool]): If True, return typed Session objects; if False,
                return a tuple of (raw dicts, total_count).

        Returns:
            Union[List[Session], Tuple[List[Dict[str, Any]], int]]: Deserialized session
                objects when deserialize=True, or a (records, total_count) tuple otherwise.
        """
        try:
            all_sessions = self._get_all_records("sessions")

            conditions: Dict[str, Any] = {}
            if session_type is not None:
                conditions["session_type"] = session_type
            if user_id is not None:
                conditions["user_id"] = user_id

            filtered_sessions = apply_filters(records=all_sessions, conditions=conditions)

            if component_id is not None:
                if session_type == SessionType.AGENT:
                    filtered_sessions = [s for s in filtered_sessions if s.get("agent_id") == component_id]
                elif session_type == SessionType.TEAM:
                    filtered_sessions = [s for s in filtered_sessions if s.get("team_id") == component_id]
                elif session_type == SessionType.WORKFLOW:
                    filtered_sessions = [s for s in filtered_sessions if s.get("workflow_id") == component_id]
                elif session_type is None:
                    filtered_sessions = [
                        s
                        for s in filtered_sessions
                        if s.get("agent_id") == component_id
                        or s.get("team_id") == component_id
                        or s.get("workflow_id") == component_id
                    ]
            if start_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) >= start_timestamp]
            if end_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) <= end_timestamp]

            if session_name is not None:
                filtered_sessions = [
                    s
                    for s in filtered_sessions
                    if session_name.lower() in ((s.get("session_data") or {}).get("session_name") or "").lower()
                ]

            sorted_sessions = apply_sorting(records=filtered_sessions, sort_by=sort_by, sort_order=sort_order)
            sessions = apply_pagination(records=sorted_sessions, limit=limit, page=page)

            if not deserialize:
                return sessions, len(filtered_sessions)

            return deserialize_sessions(session_type, sessions)

        except Exception as e:
            log_error(f"Exception reading sessions: {str(e)}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in Valkey.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            session = self._get_record("sessions", session_id)
            if session is None:
                return None

            if user_id is not None and session.get("user_id") != user_id:
                return None

            if session_type is not None and session.get("session_type") != session_type.value:
                return None

            # Update session_name, in session_data
            if "session_data" not in session or session["session_data"] is None:
                session["session_data"] = {}
            session["session_data"]["session_name"] = session_name
            session["updated_at"] = int(time.time())

            # Store updated session
            success = self._store_record("sessions", session_id, session)
            if not success:
                return None

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Error renaming session: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in Valkey.

        Args:
            session (Session): The session to upsert.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while upserting the session.
        """
        try:
            session_dict = session.to_dict()

            existing = self._get_record(table_type="sessions", record_id=session.session_id)
            if (
                existing
                and existing.get("user_id") is not None
                and existing.get("user_id") != session_dict.get("user_id")
            ):
                return None

            if isinstance(session, AgentSession):
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.AGENT.value,
                    "agent_id": session_dict.get("agent_id"),
                    "team_id": session_dict.get("team_id"),
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "agent_data": session_dict.get("agent_data"),
                    "team_data": session_dict.get("team_data"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                }

                success = self._store_record(
                    table_type="sessions",
                    record_id=session.session_id,
                    data=data,
                    index_fields=["user_id", "agent_id", "session_type"],
                )
                if not success:
                    return None

                if not deserialize:
                    return data

                return AgentSession.from_dict(data)

            elif isinstance(session, TeamSession):
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.TEAM.value,
                    "agent_id": None,
                    "team_id": session_dict.get("team_id"),
                    "workflow_id": None,
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "team_data": session_dict.get("team_data"),
                    "agent_data": None,
                    "workflow_data": None,
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                }

                success = self._store_record(
                    table_type="sessions",
                    record_id=session.session_id,
                    data=data,
                    index_fields=["user_id", "team_id", "session_type"],
                )
                if not success:
                    return None

                if not deserialize:
                    return data

                return TeamSession.from_dict(data)

            else:
                data = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.WORKFLOW.value,
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at") or int(time.time()),
                    "updated_at": int(time.time()),
                    "agent_id": None,
                    "team_id": None,
                    "agent_data": None,
                    "team_data": None,
                    "summary": None,
                }

                success = self._store_record(
                    table_type="sessions",
                    record_id=session.session_id,
                    data=data,
                    index_fields=["user_id", "workflow_id", "session_type"],
                )
                if not success:
                    return None

                if not deserialize:
                    return data

                return WorkflowSession.from_dict(data)

        except Exception as e:
            log_error(f"Error upserting session: {str(e)}")
            raise e

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.
            preserve_updated_at (bool): Whether to preserve the existing updated_at timestamp.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            valid_sessions = [s for s in sessions if s is not None]
            if not valid_sessions:
                return []

            now = int(time.time())

            # Phase 1: Batch-read existing sessions to check user_id ownership
            read_pipeline = self._create_pipeline()
            session_keys: List[str] = []
            for session in valid_sessions:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session.session_id)
                session_keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Build map of existing sessions
            existing_map: Dict[str, Dict[str, Any]] = {}
            if read_results:
                for i, raw in enumerate(read_results):
                    if raw is not None and not isinstance(raw, RequestError):
                        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                        if raw_str:
                            existing_map[valid_sessions[i].session_id] = deserialize_data(raw_str)

            # Phase 2: Prepare data and batch-write
            write_pipeline = self._create_pipeline()
            prepared: List[Tuple[Session, Dict[str, Any], int]] = []
            write_cmd_count = 0

            for session in valid_sessions:
                session_dict = session.to_dict()

                # Check user_id ownership
                existing = existing_map.get(session.session_id)
                if (
                    existing
                    and existing.get("user_id") is not None
                    and existing.get("user_id") != session_dict.get("user_id")
                ):
                    continue

                if isinstance(session, AgentSession):
                    data = {
                        "session_id": session_dict.get("session_id"),
                        "session_type": SessionType.AGENT.value,
                        "agent_id": session_dict.get("agent_id"),
                        "team_id": session_dict.get("team_id"),
                        "workflow_id": session_dict.get("workflow_id"),
                        "user_id": session_dict.get("user_id"),
                        "runs": session_dict.get("runs"),
                        "agent_data": session_dict.get("agent_data"),
                        "team_data": session_dict.get("team_data"),
                        "workflow_data": session_dict.get("workflow_data"),
                        "session_data": session_dict.get("session_data"),
                        "summary": session_dict.get("summary"),
                        "metadata": session_dict.get("metadata"),
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
                    }
                    index_fields = ["user_id", "agent_id", "session_type"]
                elif isinstance(session, TeamSession):
                    data = {
                        "session_id": session_dict.get("session_id"),
                        "session_type": SessionType.TEAM.value,
                        "agent_id": None,
                        "team_id": session_dict.get("team_id"),
                        "workflow_id": None,
                        "user_id": session_dict.get("user_id"),
                        "runs": session_dict.get("runs"),
                        "team_data": session_dict.get("team_data"),
                        "agent_data": None,
                        "workflow_data": None,
                        "session_data": session_dict.get("session_data"),
                        "summary": session_dict.get("summary"),
                        "metadata": session_dict.get("metadata"),
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
                    }
                    index_fields = ["user_id", "team_id", "session_type"]
                else:
                    data = {
                        "session_id": session_dict.get("session_id"),
                        "session_type": SessionType.WORKFLOW.value,
                        "workflow_id": session_dict.get("workflow_id"),
                        "user_id": session_dict.get("user_id"),
                        "runs": session_dict.get("runs"),
                        "workflow_data": session_dict.get("workflow_data"),
                        "session_data": session_dict.get("session_data"),
                        "metadata": session_dict.get("metadata"),
                        "created_at": session_dict.get("created_at") or now,
                        "updated_at": session_dict.get("updated_at") if preserve_updated_at else now,
                        "agent_id": None,
                        "team_id": None,
                        "agent_data": None,
                        "team_data": None,
                        "summary": None,
                    }
                    index_fields = ["user_id", "workflow_id", "session_type"]

                key = generate_valkey_key(prefix=self.db_prefix, table_type="sessions", key_id=session.session_id)
                expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
                set_cmd_index = write_cmd_count
                write_pipeline.set(key, serialize_data(data), expiry=expiry)
                write_cmd_count += 1

                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "sessions", field, str(data[field]))
                        write_pipeline.sadd(index_key, [session.session_id])
                        write_cmd_count += 1

                prepared.append((session, data, set_cmd_index))

            write_results = self._exec_pipeline(write_pipeline) if prepared else None

            # Build return values, skipping records whose SET failed
            results: List[Union[Session, Dict[str, Any]]] = []
            for session, data, set_cmd_index in prepared:
                if write_results is None or isinstance(write_results[set_cmd_index], RequestError):
                    continue
                if not deserialize:
                    results.append(data)
                    continue
                deserialized_session: Optional[Session] = None
                if isinstance(session, AgentSession):
                    deserialized_session = AgentSession.from_dict(data)
                elif isinstance(session, TeamSession):
                    deserialized_session = TeamSession.from_dict(data)
                else:
                    deserialized_session = WorkflowSession.from_dict(data)
                if deserialized_session is not None:
                    results.append(deserialized_session)
            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert: {str(e)}")
            return []

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """Delete a user memory from Valkey.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deleting.

        Raises:
            Exception: If any error occurs while deleting the memory.
        """
        try:
            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                memory = self._get_record("memories", memory_id)
                if memory is None:
                    log_debug(f"No user memory found with id: {memory_id}")
                    return
                if memory.get("user_id") != user_id:
                    log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                    return

            if self._delete_record(
                "memories", memory_id, index_fields=["user_id", "agent_id", "team_id", "workflow_id"]
            ):
                log_debug(f"Successfully deleted user memory id: {memory_id}")
            else:
                log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.
        """
        if not memory_ids:
            return

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id"]

            # Phase 1: Batch-read all memories (needed for index cleanup and user_id filtering)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for memory_id in memory_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=memory_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0

            for i, memory_id in enumerate(memory_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                # Filter by user_id if provided
                if user_id is not None and record_data.get("user_id") != user_id:
                    log_debug(f"Memory {memory_id} does not belong to user {user_id}, skipping deletion")
                    continue

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "memories", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [memory_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from Valkey.

        Args:
            user_id: If provided, only return topics from memories belonging to this user.

        Returns:
            List[str]: The list of memory topics.
        """
        try:
            all_memories = self._get_all_records("memories")

            topics = set()
            for memory in all_memories:
                if user_id is not None and memory.get("user_id") != user_id:
                    continue
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)

            return list(topics)

        except Exception as e:
            log_error(f"Exception reading memory topics: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from Valkey.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user. If provided, only returns the memory if it belongs to this user.

        Returns:
            Optional[UserMemory]: The memory data if found, None otherwise.
        """
        try:
            memory_raw = self._get_record("memories", memory_id)
            if memory_raw is None:
                return None

            # Filter by user_id if provided
            if user_id is not None and memory_raw.get("user_id") != user_id:
                return None

            if not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading memory: {str(e)}")
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
        """Get all memories from Valkey as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to deserialize the memories.

        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If any error occurs while reading the memories.
        """
        try:
            all_memories = self._get_all_records("memories")

            # Apply filters
            conditions = {}
            if user_id is not None:
                conditions["user_id"] = user_id
            if agent_id is not None:
                conditions["agent_id"] = agent_id
            if team_id is not None:
                conditions["team_id"] = team_id

            filtered_memories = apply_filters(records=all_memories, conditions=conditions)

            # Apply topic filter ("topics" may be stored as None, so coalesce to an empty list)
            if topics is not None:
                filtered_memories = [
                    m for m in filtered_memories if any(topic in (m.get("topics") or []) for topic in topics)
                ]

            # Apply content search
            if search_content is not None:
                filtered_memories = [
                    m for m in filtered_memories if search_content.lower() in str(m.get("memory", "")).lower()
                ]

            sorted_memories = apply_sorting(records=filtered_memories, sort_by=sort_by, sort_order=sort_order)
            paginated_memories = apply_pagination(records=sorted_memories, limit=limit, page=page)

            if not deserialize:
                return paginated_memories, len(filtered_memories)

            return [UserMemory.from_dict(record) for record in paginated_memories]

        except Exception as e:
            log_error(f"Exception reading memories: {str(e)}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory stats from Valkey.

        Args:
            limit (Optional[int]): The maximum number of stats to return.
            page (Optional[int]): The page number to return.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the list of stats and the total number of stats.

        Raises:
            Exception: If any error occurs while getting the user memory stats.
        """
        try:
            all_memories = self._get_all_records("memories")

            # Group by user_id
            user_stats = {}
            for memory in all_memories:
                memory_user_id = memory.get("user_id")
                # filter by user_id if provided
                if user_id is not None and memory_user_id != user_id:
                    continue
                if memory_user_id is None:
                    continue

                if memory_user_id not in user_stats:
                    user_stats[memory_user_id] = {
                        "user_id": memory_user_id,
                        "total_memories": 0,
                        "last_memory_updated_at": 0,
                    }

                user_stats[memory_user_id]["total_memories"] += 1
                updated_at = memory.get("updated_at") or 0
                if updated_at > user_stats[memory_user_id]["last_memory_updated_at"]:
                    user_stats[memory_user_id]["last_memory_updated_at"] = updated_at

            stats_list = list(user_stats.values())

            # Sorting by last_memory_updated_at descending
            stats_list.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(stats_list)

            paginated_stats = apply_pagination(records=stats_list, limit=limit, page=page)

            return paginated_stats, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in Valkey.

        Args:
            memory (UserMemory): The memory to upsert.

        Returns:
            Optional[UserMemory]: The upserted memory data if successful, None otherwise.
        """
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            created_at = memory.created_at
            existing_record = self._get_record("memories", memory.memory_id)
            if existing_record:
                # Update the existing record while preserving created_at
                created_at = existing_record.get("created_at", memory.created_at)

            data = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
                "input": memory.input,
                "feedback": memory.feedback,
                "created_at": created_at,
                "updated_at": int(time.time()),
            }

            success = self._store_record(
                "memories", memory.memory_id, data, index_fields=["user_id", "agent_id", "team_id", "workflow_id"]
            )

            if not success:
                return None

            if not deserialize:
                return data

            return UserMemory.from_dict(data)

        except Exception as e:
            log_error(f"Error upserting user memory: {str(e)}")
            raise e

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): Whether to preserve the existing updated_at timestamp.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            index_fields = ["user_id", "agent_id", "team_id", "workflow_id"]
            now = int(time.time())

            valid_memories = [m for m in memories if m is not None]
            for memory in valid_memories:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

            # Phase 1: Batch-read existing memories to preserve created_at, as the
            # single-record upsert_user_memory path does.
            read_pipeline = self._create_pipeline()
            for memory in valid_memories:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=str(memory.memory_id))
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)
            existing_map: Dict[str, Dict[str, Any]] = {}
            if read_results:
                for i, raw in enumerate(read_results):
                    if raw is None or isinstance(raw, RequestError):
                        continue
                    raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                    if raw_str:
                        existing_map[str(valid_memories[i].memory_id)] = deserialize_data(raw_str)

            # Prepare all memory data
            prepared: List[Dict[str, Any]] = []
            for memory in valid_memories:
                existing = existing_map.get(str(memory.memory_id))
                created_at = existing.get("created_at", memory.created_at) if existing else memory.created_at

                data = {
                    "user_id": memory.user_id,
                    "agent_id": memory.agent_id,
                    "team_id": memory.team_id,
                    "memory_id": memory.memory_id,
                    "memory": memory.memory,
                    "topics": memory.topics,
                    "input": memory.input,
                    "feedback": memory.feedback,
                    "created_at": created_at,
                    "updated_at": memory.updated_at if preserve_updated_at else now,
                }
                prepared.append(data)

            if not prepared:
                return []

            # Batch all writes in a single pipeline
            pipeline = self._create_pipeline()
            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            set_cmd_indices: List[int] = []
            write_cmd_count = 0
            for data in prepared:
                memory_id = str(data["memory_id"])
                key = generate_valkey_key(prefix=self.db_prefix, table_type="memories", key_id=memory_id)
                set_cmd_indices.append(write_cmd_count)
                pipeline.set(key, serialize_data(data), expiry=expiry)
                write_cmd_count += 1

                # Add index entries
                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "memories", field, str(data[field]))
                        pipeline.sadd(index_key, [memory_id])
                        write_cmd_count += 1

            write_results = self._exec_pipeline(pipeline)

            # Build return values, skipping records whose SET failed
            results: List[Union[UserMemory, Dict[str, Any]]] = []
            for data, set_cmd_index in zip(prepared, set_cmd_indices):
                if write_results is None or isinstance(write_results[set_cmd_index], RequestError):
                    continue
                if deserialize:
                    results.append(UserMemory.from_dict(data))
                else:
                    results.append(data)
            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert: {str(e)}")
            return []

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            # Get all keys for memories table
            keys = get_all_keys_for_table(
                valkey_client=self.valkey_client, prefix=self.db_prefix, table_type="memories"
            )

            if keys:
                # Delete all memory keys in a single batch operation
                self.valkey_client.delete(keys)  # type: ignore[arg-type]

        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for metrics calculation.

        Args:
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.

        Returns:
            List[Dict[str, Any]]: The list of sessions.

        Raises:
            Exception: If any error occurs while getting the sessions.
        """
        try:
            all_sessions = self._get_all_records("sessions")

            # Filter by timestamp if provided
            if start_timestamp is not None or end_timestamp is not None:
                filtered_sessions = []
                for session in all_sessions:
                    created_at = session.get("created_at", 0)
                    if start_timestamp is not None and created_at < start_timestamp:
                        continue
                    if end_timestamp is not None and created_at > end_timestamp:
                        continue
                    filtered_sessions.append(session)
                return filtered_sessions

            return all_sessions

        except Exception as e:
            log_error(f"Error reading sessions for metrics: {str(e)}")
            raise e

    def _get_metrics_calculation_starting_date(self) -> Optional[date]:
        """Get the first date for which metrics calculation is needed.

        Returns:
            Optional[date]: The first date for which metrics calculation is needed.

        Raises:
            Exception: If any error occurs while getting the metrics calculation starting date.
        """
        try:
            all_metrics = self._get_all_records("metrics")

            if all_metrics:
                # Find the latest completed metric
                completed_metrics = [m for m in all_metrics if m.get("completed", False)]
                if completed_metrics:
                    latest_completed = max(completed_metrics, key=lambda x: x.get("date", ""))
                    return datetime.fromisoformat(latest_completed["date"]).date() + timedelta(days=1)
                else:
                    # Find the earliest incomplete metric
                    incomplete_metrics = [m for m in all_metrics if not m.get("completed", False)]
                    if incomplete_metrics:
                        earliest_incomplete = min(incomplete_metrics, key=lambda x: x.get("date", ""))
                        return datetime.fromisoformat(earliest_incomplete["date"]).date()

            # No metrics records, find first session
            sessions_raw, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
            if sessions_raw:
                first_session_date = sessions_raw[0]["created_at"]  # type: ignore
                return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

            return None

        except Exception as e:
            log_error(f"Error getting metrics starting date: {str(e)}")
            raise e

    def calculate_metrics(self, user_isolation: bool = False) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[list[dict]]: The list of metrics.

        Raises:
            Exception: If any error occurs while calculating the metrics.
        """
        try:
            starting_date = self._get_metrics_calculation_starting_date()
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = int(
                datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )

            sessions = self._get_all_sessions_for_metrics_calculation(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp
            )
            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions, dates_to_process=dates_to_process, start_timestamp=start_timestamp
            )
            if not all_sessions_data:
                log_info("No new session data found. Won't calculate metrics.")
                return None

            results = []
            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                # calculate_date_metrics returns a LIST: one record per
                # distinct user_id (plus the empty-string bucket for unowned
                # sessions). Iterate and upsert each.
                for metrics_record in calculate_date_metrics(
                    date_to_process, sessions_for_date, user_isolation=user_isolation
                ):
                    # Preserve created_at across re-runs.
                    existing_record = self._get_record("metrics", metrics_record["id"])
                    if existing_record:
                        metrics_record["created_at"] = existing_record.get("created_at", metrics_record["created_at"])

                    success = self._store_record("metrics", metrics_record["id"], metrics_record)
                    if success:
                        results.append(metrics_record)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Error calculating metrics: {str(e)}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter by.
            ending_date (Optional[date]): The ending date to filter by.
            user_id (Optional[str]): When provided, returns only that user's
                per-user bucket. When ``None``, returns ALL buckets including
                the empty-string unowned bucket.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the list of metrics and the latest updated_at.

        Raises:
            Exception: If any error occurs while getting the metrics.
        """
        try:
            all_metrics = self._get_all_records("metrics")

            # Filter by date range
            if starting_date is not None or ending_date is not None:
                filtered_metrics = []
                for metric in all_metrics:
                    metric_date = datetime.fromisoformat(metric.get("date", "")).date()
                    if starting_date is not None and metric_date < starting_date:
                        continue
                    if ending_date is not None and metric_date > ending_date:
                        continue
                    filtered_metrics.append(metric)
                all_metrics = filtered_metrics

            # Filter by user_id if requested.
            if user_id is not None:
                all_metrics = [m for m in all_metrics if m.get("user_id") == user_id]

            # Get latest updated_at
            latest_updated_at = None
            if all_metrics:
                latest_updated_at = max(metric.get("updated_at", 0) for metric in all_metrics)

            # Map the sentinel empty-string user_id back to None.
            cleaned: List[dict] = []
            for metric in all_metrics:
                row = dict(metric)
                if row.get("user_id") == "":
                    row["user_id"] = None
                cleaned.append(row)
            return cleaned, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {str(e)}")
            raise e

    # -- Knowledge methods --
    # Valkey stores records as serialized dicts; we filter in Python. A row
    # is visible if its ``user_id`` matches the caller OR is unset. When the
    # caller passes ``user_id=None`` we skip the check entirely.

    @staticmethod
    def _knowledge_doc_is_visible(doc: Dict[str, Any], user_id: Optional[str]) -> bool:
        if user_id is None:
            return True
        owner = doc.get("user_id")
        return owner is None or owner == user_id

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): Owner-scoping filter. When set, only
                deletes if the row is owned by ``user_id`` OR is unowned.

        Raises:
            Exception: If any error occurs while deleting the knowledge content.
        """
        try:
            if user_id is not None:
                existing = self._get_record("knowledge", id)
                if existing is not None and not self._knowledge_doc_is_visible(existing, user_id):
                    log_debug(f"Skipping delete of knowledge content {id}: not owned by {user_id}")
                    return
            self._delete_record("knowledge", id)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): Owner-scoping filter; see module note.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If any error occurs while getting the knowledge content.
        """
        try:
            document_raw = self._get_record("knowledge", id)
            if document_raw is None:
                return None
            if not self._knowledge_doc_is_visible(document_raw, user_id):
                return None

            return KnowledgeRow.model_validate(document_raw)

        except Exception as e:
            log_error(f"Error getting knowledge content: {str(e)}")
            raise e

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).
            user_id (Optional[str]): Owner-scoping filter; see module note.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If any error occurs while getting the knowledge contents.
        """
        try:
            all_documents = self._get_all_records("knowledge")
            if len(all_documents) == 0:
                return [], 0

            # Apply linked_to filter if provided
            if linked_to is not None:
                all_documents = [doc for doc in all_documents if doc.get("linked_to") == linked_to]

            # Owner scoping: drop rows the caller isn't allowed to see.
            if user_id is not None:
                all_documents = [doc for doc in all_documents if self._knowledge_doc_is_visible(doc, user_id)]

            total_count = len(all_documents)

            # Apply sorting
            sorted_documents = apply_sorting(records=all_documents, sort_by=sort_by, sort_order=sort_order)

            # Apply pagination
            paginated_documents = apply_pagination(records=sorted_documents, limit=limit, page=page)

            return [KnowledgeRow.model_validate(doc) for doc in paginated_documents], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If any error occurs while upserting the knowledge content.
        """
        try:
            data = knowledge_row.model_dump()
            success = self._store_record("knowledge", knowledge_row.id, data)  # type: ignore

            return knowledge_row if success else None

        except Exception as e:
            log_error(f"Error upserting knowledge content: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in Valkey.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run if successful, None otherwise.

        Raises:
            Exception: If any error occurs while creating the eval run.
        """
        try:
            current_time = int(time.time())
            data = {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}

            success = self._store_record(
                "evals",
                eval_run.run_id,
                data,
                index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"],
            )

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run if success else None

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from Valkey.

        Args:
            eval_run_id (str): The ID of the eval run to delete.

        Raises:
            Exception: If any error occurs while deleting the eval run.
        """
        try:
            if self._delete_record(
                "evals", eval_run_id, index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]
            ):
                log_debug(f"Deleted eval run with ID: {eval_run_id}")
            else:
                log_debug(f"No eval run found with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from Valkey using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.

        Raises:
            Exception: If any error occurs while deleting the eval runs.
        """
        if not eval_run_ids:
            return

        try:
            index_fields = ["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]

            # Phase 1: Batch-read all eval runs (needed for index cleanup)
            read_pipeline = self._create_pipeline()
            keys: List[str] = []
            for eval_run_id in eval_run_ids:
                key = generate_valkey_key(prefix=self.db_prefix, table_type="evals", key_id=eval_run_id)
                keys.append(key)
                read_pipeline.get(key)

            read_results = self._exec_pipeline(read_pipeline)

            # Phase 2: Build delete pipeline
            delete_pipeline = self._create_pipeline()
            delete_count = 0

            for i, eval_run_id in enumerate(eval_run_ids):
                raw = read_results[i] if read_results else None
                if raw is None or isinstance(raw, RequestError):
                    continue

                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else None
                if not raw_str:
                    continue

                record_data = deserialize_data(raw_str)

                # Remove index entries
                for field in index_fields:
                    if field in record_data and record_data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "evals", field, str(record_data[field]))
                        delete_pipeline.srem(index_key, [eval_run_id])

                delete_pipeline.delete([keys[i]])
                delete_count += 1

            if delete_count > 0:
                self._exec_pipeline(delete_pipeline)

            if delete_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {delete_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from Valkey.

        Args:
            eval_run_id (str): The ID of the eval run to get.

        Returns:
            Optional[EvalRunRecord]: The eval run if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the eval run.
        """
        try:
            eval_run_raw = self._get_record("evals", eval_run_id)
            if eval_run_raw is None:
                return None

            if not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
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
        """Get all eval runs from Valkey.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            List[EvalRunRecord]: The list of eval runs.

        Raises:
            Exception: If any error occurs while getting the eval runs.
        """
        try:
            all_eval_runs = self._get_all_records("evals")

            # Apply filters
            filtered_runs = []
            for run in all_eval_runs:
                # Agent/team/workflow filters
                if agent_id is not None and run.get("agent_id") != agent_id:
                    continue
                if team_id is not None and run.get("team_id") != team_id:
                    continue
                if workflow_id is not None and run.get("workflow_id") != workflow_id:
                    continue
                if model_id is not None and run.get("model_id") != model_id:
                    continue

                # Eval type filter
                if eval_type is not None and len(eval_type) > 0:
                    if run.get("eval_type") not in eval_type:
                        continue

                # Filter type
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT and run.get("agent_id") is None:
                        continue
                    elif filter_type == EvalFilterType.TEAM and run.get("team_id") is None:
                        continue
                    elif filter_type == EvalFilterType.WORKFLOW and run.get("workflow_id") is None:
                        continue

                filtered_runs.append(run)

            if sort_by is None:
                sort_by = "created_at"
                sort_order = "desc"

            sorted_runs = apply_sorting(records=filtered_runs, sort_by=sort_by, sort_order=sort_order)
            paginated_runs = apply_pagination(records=sorted_runs, limit=limit, page=page)

            if not deserialize:
                return paginated_runs, len(filtered_runs)

            return [EvalRunRecord.model_validate(row) for row in paginated_runs]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Update the name of an eval run in Valkey.

        Args:
            eval_run_id (str): The ID of the eval run to rename.
            name (str): The new name of the eval run.

        Returns:
            Optional[Dict[str, Any]]: The updated eval run data if successful, None otherwise.

        Raises:
            Exception: If any error occurs while updating the eval run name.
        """
        try:
            eval_run_data = self._get_record("evals", eval_run_id)
            if eval_run_data is None:
                return None

            eval_run_data["name"] = name
            eval_run_data["updated_at"] = int(time.time())

            success = self._store_record("evals", eval_run_id, eval_run_data)
            if not success:
                return None

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not deserialize:
                return eval_run_data

            return EvalRunRecord.model_validate(eval_run_data)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {str(e)}")
            raise

    # -- Cultural Knowledge methods --
    # These methods raise NotImplementedError to satisfy the BaseDb interface.

    def clear_cultural_knowledge(self) -> None:
        raise NotImplementedError("Cultural knowledge is not supported for ValkeyDb")

    def delete_cultural_knowledge(self, id: str) -> None:
        raise NotImplementedError("Cultural knowledge is not supported for ValkeyDb")

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        raise NotImplementedError("Cultural knowledge is not supported for ValkeyDb")

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
        raise NotImplementedError("Cultural knowledge is not supported for ValkeyDb")

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        raise NotImplementedError("Cultural knowledge is not supported for ValkeyDb")

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            # Check if trace already exists
            existing = self._get_record("traces", trace.trace_id)

            if existing:
                # workflow (level 3) > team (level 2) > agent (level 1) > child/unknown (level 0)
                def get_component_level(
                    workflow_id: Optional[str], team_id: Optional[str], agent_id: Optional[str], name: str
                ) -> int:
                    # Check if name indicates a root span
                    is_root_name = ".run" in name or ".arun" in name

                    if not is_root_name:
                        return 0  # Child span (not a root)
                    elif workflow_id:
                        return 3  # Workflow root
                    elif team_id:
                        return 2  # Team root
                    elif agent_id:
                        return 1  # Agent root
                    else:
                        return 0  # Unknown

                existing_level = get_component_level(
                    existing.get("workflow_id"),
                    existing.get("team_id"),
                    existing.get("agent_id"),
                    existing.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)

                # Only update name if new trace is from a higher or equal level
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                # Update existing record
                existing["end_time"] = trace.end_time.isoformat()
                existing["duration_ms"] = recalculated_duration_ms
                existing["status"] = trace.status
                if should_update_name:
                    existing["name"] = trace.name

                # Preserve existing non-null context values: only fill in fields
                # that the existing row left blank. Otherwise a later upsert from
                # a child span (e.g. a post-hook agent's run with a different
                # session_id) would overwrite the trace's already-correct context.
                if existing.get("run_id") is None and trace.run_id is not None:
                    existing["run_id"] = trace.run_id
                if existing.get("session_id") is None and trace.session_id is not None:
                    existing["session_id"] = trace.session_id
                if existing.get("user_id") is None and trace.user_id is not None:
                    existing["user_id"] = trace.user_id
                if existing.get("agent_id") is None and trace.agent_id is not None:
                    existing["agent_id"] = trace.agent_id
                if existing.get("team_id") is None and trace.team_id is not None:
                    existing["team_id"] = trace.team_id
                if existing.get("workflow_id") is None and trace.workflow_id is not None:
                    existing["workflow_id"] = trace.workflow_id

                log_debug(
                    f"  Updating trace with context: run_id={existing.get('run_id', 'unchanged')}, "
                    f"session_id={existing.get('session_id', 'unchanged')}, "
                    f"user_id={existing.get('user_id', 'unchanged')}, "
                    f"agent_id={existing.get('agent_id', 'unchanged')}, "
                    f"team_id={existing.get('team_id', 'unchanged')}, "
                )

                self._store_record(
                    "traces",
                    trace.trace_id,
                    existing,
                    index_fields=["run_id", "session_id", "user_id", "agent_id", "team_id", "workflow_id", "status"],
                )
            else:
                trace_dict = trace.to_dict()
                trace_dict.pop("total_spans", None)
                trace_dict.pop("error_count", None)
                self._store_record(
                    "traces",
                    trace.trace_id,
                    trace_dict,
                    index_fields=["run_id", "session_id", "user_id", "agent_id", "team_id", "workflow_id", "status"],
                )

        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")
            # Don't raise - tracing should not break the main application flow

    def _get_span_stats_for_trace(self, trace_id: str) -> tuple[int, int]:
        """Get total_spans and error_count for a trace using the trace_id index.

        Uses the spans index set to fetch only spans belonging to this trace
        via a single pipeline round trip, instead of scanning all spans.

        Args:
            trace_id: The trace ID to look up spans for.

        Returns:
            tuple[int, int]: (total_spans, error_count)
        """
        index_key = generate_index_key(self.db_prefix, "spans", "trace_id", trace_id)
        span_ids = self.valkey_client.smembers(index_key)
        if not span_ids:
            return 0, 0

        # Pipeline-fetch all span records in one round trip
        pipeline = self._create_pipeline()
        for span_id in span_ids:
            sid = span_id.decode("utf-8") if isinstance(span_id, bytes) else str(span_id)
            key = generate_valkey_key(prefix=self.db_prefix, table_type="spans", key_id=sid)
            pipeline.get(key)

        results = self._exec_pipeline(pipeline)
        if not results:
            return 0, 0

        total = 0
        errors = 0
        for raw in results:
            if raw is None or isinstance(raw, RequestError):
                continue
            total += 1
            data_str: str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw) if raw else ""
            if data_str:
                span_data = deserialize_data(data_str)
                if span_data.get("status_code") == "ERROR":
                    errors += 1

        return total, errors

    def _enrich_trace_with_span_stats(self, trace_data: Dict[str, Any]) -> None:
        """Add total_spans and error_count to a trace dict in-place."""
        tid = trace_data.get("trace_id", "")
        if tid:
            total_spans, error_count = self._get_span_stats_for_trace(tid)
        else:
            total_spans, error_count = 0, 0
        trace_data["total_spans"] = total_spans
        trace_data["error_count"] = error_count

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
            from agno.tracing.schemas import Trace as TraceSchema

            if trace_id:
                result = self._get_record("traces", trace_id)
                if result:
                    self._enrich_trace_with_span_stats(result)
                    return TraceSchema.from_dict(result)
                return None

            elif run_id:
                all_traces = self._get_all_records("traces")
                matching = [t for t in all_traces if t.get("run_id") == run_id]
                if matching:
                    # Sort by start_time descending and get most recent
                    matching.sort(key=lambda x: x.get("start_time", ""), reverse=True)
                    result = matching[0]
                    self._enrich_trace_with_span_stats(result)
                    return TraceSchema.from_dict(result)
                return None

            else:
                log_debug("get_trace called without any filter parameters")
                return None

        except Exception as e:
            log_error(f"Error getting trace: {str(e)}")
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
        filter_expr: Optional[Dict[str, Any]] = None,
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
            filter_expr: Serialized FilterExpr dict to apply on trace fields.

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from agno.db.filter_converter import TRACE_COLUMNS
            from agno.tracing.schemas import Trace as TraceSchema

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, "
                f"user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            if filter_expr is not None:
                validate_filter_expr(filter_expr, TRACE_COLUMNS)

            all_traces = self._get_all_records("traces")

            # Apply filters
            filtered_traces = []
            for trace in all_traces:
                if run_id and trace.get("run_id") != run_id:
                    continue
                if session_id and trace.get("session_id") != session_id:
                    continue
                if user_id and trace.get("user_id") != user_id:
                    continue
                if agent_id and trace.get("agent_id") != agent_id:
                    continue
                if team_id and trace.get("team_id") != team_id:
                    continue
                if workflow_id and trace.get("workflow_id") != workflow_id:
                    continue
                if status and trace.get("status") != status:
                    continue
                if start_time:
                    trace_start = trace.get("start_time", "")
                    if trace_start and trace_start < start_time.isoformat():
                        continue
                if end_time:
                    trace_end = trace.get("end_time", "")
                    if trace_end and trace_end > end_time.isoformat():
                        continue
                if filter_expr is not None and not record_matches_filter_expr(trace, filter_expr, TRACE_COLUMNS):
                    continue

                filtered_traces.append(trace)

            total_count = len(filtered_traces)

            # Sort by start_time descending
            filtered_traces.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Apply pagination
            paginated_traces = apply_pagination(records=filtered_traces, limit=limit, page=page)

            # Enrich only the paginated traces with span stats (index-based lookup per trace)
            traces = []
            for row in paginated_traces:
                self._enrich_trace_with_span_stats(row)
                traces.append(TraceSchema.from_dict(row))

            return traces, total_count

        except ValueError:
            # Re-raise ValueError for proper 400 response at the API layer
            raise
        except Exception as e:
            log_error(f"Error getting traces: {str(e)}")
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
        filter_expr: Optional[Dict[str, Any]] = None,
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
            filter_expr: Serialized FilterExpr dict to apply on trace fields.

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at, last_trace_at.
        """
        try:
            from agno.db.filter_converter import TRACE_COLUMNS

            log_debug(
                f"get_trace_stats called with filters: user_id={user_id}, agent_id={agent_id}, "
                f"workflow_id={workflow_id}, team_id={team_id}, "
                f"start_time={start_time}, end_time={end_time}, page={page}, limit={limit}"
            )

            if filter_expr is not None:
                validate_filter_expr(filter_expr, TRACE_COLUMNS)

            all_traces = self._get_all_records("traces")

            # Filter traces and group by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for trace in all_traces:
                trace_session_id = trace.get("session_id")
                if not trace_session_id:
                    continue

                # Apply filters
                if user_id and trace.get("user_id") != user_id:
                    continue
                if agent_id and trace.get("agent_id") != agent_id:
                    continue
                if team_id and trace.get("team_id") != team_id:
                    continue
                if workflow_id and trace.get("workflow_id") != workflow_id:
                    continue

                created_at = trace.get("created_at", "")
                if start_time and created_at < start_time.isoformat():
                    continue
                if end_time and created_at > end_time.isoformat():
                    continue
                if filter_expr is not None and not record_matches_filter_expr(trace, filter_expr, TRACE_COLUMNS):
                    continue

                if trace_session_id not in session_stats:
                    session_stats[trace_session_id] = {
                        "session_id": trace_session_id,
                        "user_id": trace.get("user_id"),
                        "agent_id": trace.get("agent_id"),
                        "team_id": trace.get("team_id"),
                        "workflow_id": trace.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": created_at,
                        "last_trace_at": created_at,
                    }

                session_stats[trace_session_id]["total_traces"] += 1
                if created_at < session_stats[trace_session_id]["first_trace_at"]:
                    session_stats[trace_session_id]["first_trace_at"] = created_at
                if created_at > session_stats[trace_session_id]["last_trace_at"]:
                    session_stats[trace_session_id]["last_trace_at"] = created_at

            # Convert to list and sort by last_trace_at descending
            stats_list = list(session_stats.values())
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            total_count = len(stats_list)

            # Apply pagination
            paginated_stats = apply_pagination(records=stats_list, limit=limit, page=page)

            # Convert ISO strings to datetime objects
            for stat in paginated_stats:
                first_trace_at_str = stat["first_trace_at"]
                last_trace_at_str = stat["last_trace_at"]
                stat["first_trace_at"] = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                stat["last_trace_at"] = datetime.fromisoformat(last_trace_at_str.replace("Z", "+00:00"))

            return paginated_stats, total_count

        except ValueError:
            # Re-raise ValueError for proper 400 response at the API layer
            raise
        except Exception as e:
            log_error(f"Error getting trace stats: {str(e)}")
            return [], 0

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            self._store_record(
                "spans",
                span.span_id,
                span.to_dict(),
                index_fields=["trace_id", "parent_span_id"],
            )

        except Exception as e:
            log_error(f"Error creating span: {str(e)}")

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database using GLIDE Batch (pipeline) for reduced round trips.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            index_fields = ["trace_id", "parent_span_id"]
            pipeline = self._create_pipeline()

            expiry = ExpirySet(ExpiryType.SEC, self.expire) if self.expire is not None else None
            for span in spans:
                data = span.to_dict()
                key = generate_valkey_key(prefix=self.db_prefix, table_type="spans", key_id=span.span_id)
                pipeline.set(key, serialize_data(data), expiry=expiry)

                for field in index_fields:
                    if field in data and data[field] is not None:
                        index_key = generate_index_key(self.db_prefix, "spans", field, str(data[field]))
                        pipeline.sadd(index_key, [span.span_id])

            self._exec_pipeline(pipeline)

        except Exception as e:
            log_error(f"Error creating spans batch: {str(e)}")

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span as SpanSchema

            result = self._get_record("spans", span_id)
            if result:
                return SpanSchema.from_dict(result)
            return None

        except Exception as e:
            log_error(f"Error getting span: {str(e)}")
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
            from agno.tracing.schemas import Span as SpanSchema

            all_spans = self._get_all_records("spans")

            # Apply filters
            filtered_spans = []
            for span in all_spans:
                if trace_id and span.get("trace_id") != trace_id:
                    continue
                if parent_span_id and span.get("parent_span_id") != parent_span_id:
                    continue
                filtered_spans.append(span)

            # Apply limit
            if limit:
                filtered_spans = filtered_spans[:limit]

            return [SpanSchema.from_dict(s) for s in filtered_spans]

        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    # -- Learning methods --

    def _learning_matches(self, record: Dict[str, Any], **filters: Optional[str]) -> bool:
        """Check a learning record against the provided filters. None filters are skipped."""
        return all(record.get(field) == value for field, value in filters.items() if value is not None)

    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        try:
            for record in self._get_all_records("learnings"):
                if record.get("learning_type") != learning_type:
                    continue
                if self._learning_matches(
                    record,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                ):
                    return {"content": record.get("content")}
            return None

        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

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
        """Insert or update a learning record.

        On update only content, metadata and updated_at change; created_at and
        the identity fields keep their stored values.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        try:
            current_time = int(time.time())
            existing = self._get_record("learnings", id)

            if existing is not None:
                data = {**existing, "content": content, "metadata": metadata, "updated_at": current_time}
            else:
                data = {
                    "learning_id": id,
                    "learning_type": learning_type,
                    "namespace": namespace,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "team_id": team_id,
                    "session_id": session_id,
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "content": content,
                    "metadata": metadata,
                    "created_at": current_time,
                    "updated_at": current_time,
                }

            self._store_record(
                "learnings",
                id,
                data,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )
            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    def delete_learning(self, id: str) -> bool:
        """Delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            return self._delete_record(
                "learnings",
                id,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )

        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    def update_learning(self, id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Update an existing learning record in place. Does NOT insert.

        Args:
            id: The learning ID to update.
            content: Replacement content.
            metadata: Replacement metadata.

        Returns:
            True if a record was updated, False if no record with that id exists.
        """
        try:
            existing = self._get_record("learnings", id)
            if existing is None:
                return False

            data = {**existing, "content": content, "metadata": metadata, "updated_at": int(time.time())}
            return self._store_record(
                "learnings",
                id,
                data,
                index_fields=[
                    "learning_type",
                    "namespace",
                    "user_id",
                    "agent_id",
                    "team_id",
                    "session_id",
                    "entity_id",
                    "entity_type",
                ],
            )

        except Exception as e:
            log_error(f"Error updating learning: {e}")
            raise e

    def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        """Delete every learning record owned by a user.

        Records with no owner (user_id None) are not affected.

        Args:
            user_id: The user whose learnings should be deleted.
            learning_type: When provided, restrict deletion to this single learning type.

        Returns:
            The number of records deleted.
        """
        try:
            deleted_count = 0
            for record in self._get_all_records("learnings"):
                if record.get("user_id") != user_id:
                    continue
                if learning_type is not None and record.get("learning_type") != learning_type:
                    continue
                record_id = record.get("learning_id")
                if record_id and self._delete_record(
                    "learnings",
                    record_id,
                    index_fields=[
                        "learning_type",
                        "namespace",
                        "user_id",
                        "agent_id",
                        "team_id",
                        "session_id",
                        "entity_id",
                        "entity_type",
                    ],
                ):
                    deleted_count += 1

            return deleted_count

        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise e

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get multiple learning records, most recently updated first.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        try:
            filtered_records = [
                record
                for record in self._get_all_records("learnings")
                if self._learning_matches(
                    record,
                    learning_type=learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                )
            ]

            sorted_records = apply_sorting(records=filtered_records, sort_by="updated_at", sort_order="desc")

            if limit is not None:
                sorted_records = sorted_records[:limit]

            return sorted_records

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Get a learning record by its ID.

        Args:
            id: The learning ID to retrieve.

        Returns:
            The learning record if found, None otherwise.
        """
        try:
            return self._get_record("learnings", id)

        except Exception as e:
            log_error(f"Error getting learning by id: {e}")
            raise e

    def list_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        include_global: bool = False,
        limit: int = 100,
        page: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get learning records with filtering, sorting and pagination.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace.
            entity_id: Filter by entity ID.
            entity_type: Filter by entity type.
            include_global: When filtering by user_id, also include unowned records.
            limit: Maximum number of records to return per page.
            page: Page number (1-indexed).
            sort_by: Field to sort by.
            sort_order: Sort order ('asc' or 'desc').

        Returns:
            Tuple of (list of learning records, total count).
        """
        try:
            filtered_records = []
            for record in self._get_all_records("learnings"):
                if user_id is not None:
                    record_user_id = record.get("user_id")
                    if include_global:
                        if record_user_id != user_id and record_user_id is not None:
                            continue
                    elif record_user_id != user_id:
                        continue
                if self._learning_matches(
                    record,
                    learning_type=learning_type,
                    agent_id=agent_id,
                    team_id=team_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                ):
                    filtered_records.append(record)

            sorted_records = apply_sorting(
                records=filtered_records, sort_by=sort_by or "updated_at", sort_order=sort_order or "desc"
            )
            paginated_records = apply_pagination(records=sorted_records, limit=limit, page=page)

            return paginated_records, len(filtered_records)

        except Exception as e:
            log_error(f"Error listing learnings: {e}")
            raise e

    def get_learnings_user_stats(
        self,
        learning_type: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get learning statistics grouped by user.

        Args:
            learning_type: Filter by learning type.
            limit: Maximum number of users to return per page.
            page: Page number (1-indexed).
            user_id: Filter by user ID.
            sort_by: Field to sort by ('user_id' or 'last_learning_updated_at').
            sort_order: Sort order ('asc' or 'desc').

        Returns:
            Tuple of (list of user stats dicts, total count).
        """
        try:
            user_stats: Dict[str, Dict[str, Any]] = {}
            for record in self._get_all_records("learnings"):
                if learning_type is not None and record.get("learning_type") != learning_type:
                    continue
                record_user_id = record.get("user_id")
                if user_id is not None:
                    if record_user_id != user_id:
                        continue
                elif record_user_id is None:
                    continue

                updated_at = record.get("updated_at") or 0
                stats = user_stats.get(record_user_id)
                if stats is None or updated_at > (stats["last_learning_updated_at"] or 0):
                    user_stats[record_user_id] = {
                        "user_id": record_user_id,
                        "last_learning_updated_at": updated_at,
                    }

            stats_list = list(user_stats.values())
            reverse = sort_order != "asc"
            if sort_by == "user_id":
                stats_list.sort(key=lambda s: s["user_id"] or "", reverse=reverse)
            else:
                stats_list.sort(key=lambda s: s["last_learning_updated_at"] or 0, reverse=reverse)

            total_count = len(stats_list)
            if limit is not None:
                start = ((page - 1) * limit) if page is not None else 0
                stats_list = stats_list[start : start + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise e
