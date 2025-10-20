import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.redis.utils import (
    apply_filters,
    apply_pagination,
    apply_sorting,
    calculate_date_metrics,
    create_index_entries,
    deserialize_data,
    fetch_all_sessions_data,
    generate_redis_key,
    get_all_keys_for_table,
    get_dates_to_calculate_metrics_for,
    remove_index_entries,
    serialize_data,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    from redis import Redis
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")


class RedisDb(BaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        redis_client: Optional[Redis] = None,
        db_url: Optional[str] = None,
        db_prefix: str = "agno",
        expire: Optional[int] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a Redis database.

        The following order is used to determine the database connection:
            1. Use the redis_client if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            id (Optional[str]): The ID of the database.
            redis_client (Optional[Redis]): Redis client instance to use. If not provided a new client will be created.
            db_url (Optional[str]): Redis connection URL (e.g., "redis://localhost:6379/0" or "rediss://user:pass@host:port/db")
            db_prefix (str): Prefix for all Redis keys
            expire (Optional[int]): TTL for Redis keys in seconds
            session_table (Optional[str]): Name of the table to store sessions
            memory_table (Optional[str]): Name of the table to store memories
            metrics_table (Optional[str]): Name of the table to store metrics
            eval_table (Optional[str]): Name of the table to store evaluation runs
            knowledge_table (Optional[str]): Name of the table to store knowledge documents

        Raises:
            ValueError: If neither redis_client nor db_url is provided.
        """
        if id is None:
            base_seed = db_url or str(redis_client)
            seed = f"{base_seed}#{db_prefix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        self.db_prefix = db_prefix
        self.expire = expire

        if redis_client is not None:
            self.redis_client = redis_client
        elif db_url is not None:
            self.redis_client = Redis.from_url(db_url, decode_responses=True)
        else:
            raise ValueError("One of redis_client or db_url must be provided")

    # -- DB methods --

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

        else:
            raise ValueError(f"Unknown table type: {table_type}")

    def _store_record(
        self, table_type: str, record_id: str, data: Dict[str, Any], index_fields: Optional[List[str]] = None
    ) -> bool:
        """Generic method to store a record in Redis, considering optional indexing.

        Args:
            table_type (str): The type of table to store the record in.
            record_id (str): The ID of the record to store.
            data (Dict[str, Any]): The data to store in the record.
            index_fields (Optional[List[str]]): The fields to index the record by.

        Returns:
            bool: True if the record was stored successfully, False otherwise.
        """
        try:
            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            serialized_data = serialize_data(data)

            self.redis_client.set(key, serialized_data, ex=self.expire)

            if index_fields:
                create_index_entries(
                    redis_client=self.redis_client,
                    prefix=self.db_prefix,
                    table_type=table_type,
                    record_id=record_id,
                    record_data=data,
                    index_fields=index_fields,
                )

            return True

        except Exception as e:
            log_error(f"Error storing Redis record: {e}")
            return False

    def _get_record(self, table_type: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Generic method to get a record from Redis.

        Args:
            table_type (str): The type of table to get the record from.
            record_id (str): The ID of the record to get.

        Returns:
            Optional[Dict[str, Any]]: The record data if found, None otherwise.
        """
        try:
            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)

            data = self.redis_client.get(key)
            if data is None:
                return None

            return deserialize_data(data)  # type: ignore

        except Exception as e:
            log_error(f"Error getting record {record_id}: {e}")
            return None

    def _delete_record(self, table_type: str, record_id: str, index_fields: Optional[List[str]] = None) -> bool:
        """Generic method to delete a record from Redis.

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
                        redis_client=self.redis_client,
                        prefix=self.db_prefix,
                        table_type=table_type,
                        record_id=record_id,
                        record_data=record_data,
                        index_fields=index_fields,
                    )

            key = generate_redis_key(prefix=self.db_prefix, table_type=table_type, key_id=record_id)
            result = self.redis_client.delete(key)
            if result is None or result == 0:
                return False

            return True

        except Exception as e:
            log_error(f"Error deleting record {record_id}: {e}")
            return False

    def _get_all_records(self, table_type: str) -> List[Dict[str, Any]]:
        """Generic method to get all records for a table type.

        Args:
            table_type (str): The type of table to get the records from.

        Returns:
            List[Dict[str, Any]]: The records data if found, None otherwise.

        Raises:
            Exception: If any error occurs while getting the records.
        """
        try:
            keys = get_all_keys_for_table(redis_client=self.redis_client, prefix=self.db_prefix, table_type=table_type)

            records = []
            for key in keys:
                data = self.redis_client.get(key)
                if data:
                    records.append(deserialize_data(data))  # type: ignore

            return records

        except Exception as e:
            log_error(f"Error getting all records for {table_type}: {e}")
            return []

    # -- Session methods --

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from Redis.

        Args:
            session_id (str): The ID of the session to delete.

        Raises:
            Exception: If any error occurs while deleting the session.
        """
        try:
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
            log_error(f"Error deleting session: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str]) -> None:
        """Delete multiple sessions from Redis.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.

        Raises:
            Exception: If any error occurs while deleting the sessions.
        """
        try:
            deleted_count = 0
            for session_id in session_ids:
                if self._delete_record(
                    "sessions",
                    session_id,
                    index_fields=["user_id", "agent_id", "team_id", "workflow_id", "session_type"],
                ):
                    deleted_count += 1
            log_debug(f"Successfully deleted {deleted_count} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Read a session from Redis.

        Args:
            session_id (str): The ID of the session to get.
            session_type (SessionType): The type of session to get.
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
            if session_type is not None and session.get("session_type") != session_type:
                return None

            if not deserialize:
                return session

            if session_type == SessionType.AGENT.value:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM.value:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW.value:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Exception reading session: {e}")
            raise e

    # TODO: optimizable
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
            component_id (Optional[str]): The ID of the component to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            limit (Optional[int]): The maximum number of sessions to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            List[Union[AgentSession, TeamSession, WorkflowSession]]: The list of sessions.
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
            if start_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) >= start_timestamp]
            if end_timestamp is not None:
                filtered_sessions = [s for s in filtered_sessions if s.get("created_at", 0) <= end_timestamp]

            if session_name is not None:
                filtered_sessions = [
                    s
                    for s in filtered_sessions
                    if session_name.lower() in s.get("session_data", {}).get("session_name", "").lower()
                ]

            sorted_sessions = apply_sorting(records=filtered_sessions, sort_by=sort_by, sort_order=sort_order)
            sessions = apply_pagination(records=sorted_sessions, limit=limit, page=page)
            sessions = [record for record in sessions]

            if not deserialize:
                return sessions, len(filtered_sessions)

            if session_type == SessionType.AGENT:
                return [AgentSession.from_dict(record) for record in sessions]  # type: ignore
            elif session_type == SessionType.TEAM:
                return [TeamSession.from_dict(record) for record in sessions]  # type: ignore
            elif session_type == SessionType.WORKFLOW:
                return [WorkflowSession.from_dict(record) for record in sessions]  # type: ignore
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Exception reading sessions: {e}")
            raise e

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in Redis.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.

        Returns:
            Optional[Session]: The renamed session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while renaming the session.
        """
        try:
            session = self._get_record("sessions", session_id)
            if session is None:
                return None

            # Update session_name, in session_data
            if "session_data" not in session:
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

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Error renaming session: {e}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in Redis.

        Args:
            session (Session): The session to upsert.

        Returns:
            Optional[Session]: The upserted session if successful, None otherwise.

        Raises:
            Exception: If any error occurs while upserting the session.
        """
        try:
            session_dict = session.to_dict()

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
            log_error(f"Error upserting session: {e}")
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
                f"RedisDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
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

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from Redis.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deleting.

        Returns:
            bool: True if the memory was deleted, False otherwise.

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
            log_error(f"Error deleting user memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from Redis.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.
        """
        try:
            # TODO: cant we optimize this?
            for memory_id in memory_ids:
                # If user_id is provided, verify ownership before deleting
                if user_id is not None:
                    memory = self._get_record("memories", memory_id)
                    if memory is None:
                        continue
                    if memory.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}, skipping deletion")
                        continue

                self._delete_record(
                    "memories",
                    memory_id,
                    index_fields=["user_id", "agent_id", "team_id", "workflow_id"],
                )

        except Exception as e:
            log_error(f"Error deleting user memories: {e}")
            raise e

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from Redis.

        Returns:
            List[str]: The list of memory topics.
        """
        try:
            all_memories = self._get_all_records("memories")

            topics = set()
            for memory in all_memories:
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)

            return list(topics)

        except Exception as e:
            log_error(f"Exception reading memory topics: {e}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from Redis.

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
            log_error(f"Exception reading memory: {e}")
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
        """Get all memories from Redis as UserMemory objects.

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

            # Apply topic filter
            if topics is not None:
                filtered_memories = [
                    m for m in filtered_memories if any(topic in m.get("topics", []) for topic in topics)
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
            log_error(f"Exception reading memories: {e}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory stats from Redis.

        Args:
            limit (Optional[int]): The maximum number of stats to return.
            page (Optional[int]): The page number to return.

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
                if memory_user_id is None:
                    continue

                if memory_user_id not in user_stats:
                    user_stats[memory_user_id] = {
                        "user_id": memory_user_id,
                        "total_memories": 0,
                        "last_memory_updated_at": 0,
                    }

                user_stats[memory_user_id]["total_memories"] += 1
                updated_at = memory.get("updated_at", 0)
                if updated_at > user_stats[memory_user_id]["last_memory_updated_at"]:
                    user_stats[memory_user_id]["last_memory_updated_at"] = updated_at

            stats_list = list(user_stats.values())

            # Sorting by last_memory_updated_at descending
            stats_list.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(stats_list)

            paginated_stats = apply_pagination(records=stats_list, limit=limit, page=page)

            return paginated_stats, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {e}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in Redis.

        Args:
            memory (UserMemory): The memory to upsert.

        Returns:
            Optional[UserMemory]: The upserted memory data if successful, None otherwise.
        """
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            data = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
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
            log_error(f"Error upserting user memory: {e}")
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
                f"RedisDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
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
            # Get all keys for memories table
            keys = get_all_keys_for_table(redis_client=self.redis_client, prefix=self.db_prefix, table_type="memories")

            if keys:
                # Delete all memory keys in a single batch operation
                self.redis_client.delete(*keys)

        except Exception as e:
            log_error(f"Exception deleting all memories: {e}")
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
            log_error(f"Error reading sessions for metrics: {e}")
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
            log_error(f"Error getting metrics starting date: {e}")
            raise e

    def calculate_metrics(self) -> Optional[list[dict]]:
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

            start_timestamp = int(datetime.combine(dates_to_process[0], datetime.min.time()).timestamp())
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time()).timestamp()
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

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)

                # Check if a record already exists for this date and aggregation period
                existing_record = self._get_record("metrics", metrics_record["id"])
                if existing_record:
                    # Update the existing record while preserving created_at
                    metrics_record["created_at"] = existing_record.get("created_at", metrics_record["created_at"])

                success = self._store_record("metrics", metrics_record["id"], metrics_record)
                if success:
                    results.append(metrics_record)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Error calculating metrics: {e}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter by.
            ending_date (Optional[date]): The ending date to filter by.

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

            # Get latest updated_at
            latest_updated_at = None
            if all_metrics:
                latest_updated_at = max(metric.get("updated_at", 0) for metric in all_metrics)

            return all_metrics, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {e}")
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If any error occurs while deleting the knowledge content.
        """
        try:
            self._delete_record("knowledge", id)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If any error occurs while getting the knowledge content.
        """
        try:
            document_raw = self._get_record("knowledge", id)
            if document_raw is None:
                return None

            return KnowledgeRow.model_validate(document_raw)

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            raise e

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

        Raises:
            Exception: If any error occurs while getting the knowledge contents.
        """
        try:
            all_documents = self._get_all_records("knowledge")
            if len(all_documents) == 0:
                return [], 0

            total_count = len(all_documents)

            # Apply sorting
            sorted_documents = apply_sorting(records=all_documents, sort_by=sort_by, sort_order=sort_order)

            # Apply pagination
            paginated_documents = apply_pagination(records=sorted_documents, limit=limit, page=page)

            return [KnowledgeRow.model_validate(doc) for doc in paginated_documents], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
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
            log_error(f"Error upserting knowledge content: {e}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in Redis.

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
            log_error(f"Error creating eval run: {e}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from Redis.

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
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from Redis.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.

        Raises:
            Exception: If any error occurs while deleting the eval runs.
        """
        try:
            deleted_count = 0
            for eval_run_id in eval_run_ids:
                if self._delete_record(
                    "evals", eval_run_id, index_fields=["agent_id", "team_id", "workflow_id", "model_id", "eval_type"]
                ):
                    deleted_count += 1

            if deleted_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from Redis.

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
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
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
        """Get all eval runs from Redis.

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
            log_error(f"Exception getting eval runs: {e}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Update the name of an eval run in Redis.

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
            log_error(f"Error updating eval run name {eval_run_id}: {e}")
            raise
