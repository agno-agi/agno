import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.in_memory.utils import (
    apply_sorting,
    calculate_date_metrics,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    serialize_cultural_knowledge_for_db,
)
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


class InMemoryDb(BaseDb):
    def __init__(self):
        """Interface for in-memory storage."""
        super().__init__()

        # Initialize in-memory storage dictionaries
        self._sessions: List[Dict[str, Any]] = []
        self._memories: List[Dict[str, Any]] = []
        self._metrics: List[Dict[str, Any]] = []
        self._eval_runs: List[Dict[str, Any]] = []
        self._knowledge: List[Dict[str, Any]] = []
        self._cultural_knowledge: List[Dict[str, Any]] = []

    def table_exists(self, table_name: str) -> bool:
        """In-memory implementation, always returns True."""
        return True

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

    # -- Session methods --
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from in-memory storage.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            original_count = len(self._sessions)
            self._sessions = [
                s
                for s in self._sessions
                if not (s.get("session_id") == session_id and (user_id is None or s.get("user_id") == user_id))
            ]

            if len(self._sessions) < original_count:
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True
            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from in-memory storage.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            self._sessions = [
                s
                for s in self._sessions
                if not (s.get("session_id") in session_ids and (user_id is None or s.get("user_id") == user_id))
            ]
            log_debug(f"Successfully deleted sessions with ids: {session_ids}")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")
            raise e

    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[AgentSession, TeamSession, WorkflowSession, Dict[str, Any]]]:
        """Read a session from in-memory storage.

        Args:
            session_id (str): The ID of the session to read.
            session_type (SessionType): The type of the session to read.
            user_id (Optional[str]): The ID of the user to read the session for.
            deserialize (Optional[bool]): Whether to deserialize the session.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs while reading the session.
        """
        try:
            for session_data in self._sessions:
                if session_data.get("session_id") == session_id:
                    if user_id is not None and session_data.get("user_id") != user_id:
                        continue

                    session_data_copy = deepcopy(session_data)

                    if not deserialize:
                        return session_data_copy

                    if session_type == SessionType.AGENT:
                        return AgentSession.from_dict(session_data_copy)
                    elif session_type == SessionType.TEAM:
                        return TeamSession.from_dict(session_data_copy)
                    else:
                        return WorkflowSession.from_dict(session_data_copy)

            return None

        except Exception as e:
            import traceback

            traceback.print_exc()
            log_error(f"Exception reading session: {e}")
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
        """Get all sessions from in-memory storage with filtering and pagination.

        Args:
            session_type (SessionType): The type of the sessions to read.
            user_id (Optional[str]): The ID of the user to read the sessions for.
            component_id (Optional[str]): The ID of the component to read the sessions for.
            session_name (Optional[str]): The name of the session to read.
            start_timestamp (Optional[int]): The start timestamp of the sessions to read.
            end_timestamp (Optional[int]): The end timestamp of the sessions to read.
            limit (Optional[int]): The limit of the sessions to read.
            page (Optional[int]): The page of the sessions to read.
            sort_by (Optional[str]): The field to sort the sessions by.
            sort_order (Optional[str]): The order to sort the sessions by.
            deserialize (Optional[bool]): Whether to deserialize the sessions.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of sessions
                - When deserialize=False: Tuple with list of sessions and total count

        Raises:
            Exception: If an error occurs while reading the sessions.
        """
        try:
            # Apply filters
            filtered_sessions = []
            for session_data in self._sessions:
                if user_id is not None and session_data.get("user_id") != user_id:
                    continue
                if component_id is not None:
                    if session_type == SessionType.AGENT and session_data.get("agent_id") != component_id:
                        continue
                    elif session_type == SessionType.TEAM and session_data.get("team_id") != component_id:
                        continue
                    elif session_type == SessionType.WORKFLOW and session_data.get("workflow_id") != component_id:
                        continue
                if start_timestamp is not None and session_data.get("created_at", 0) < start_timestamp:
                    continue
                if end_timestamp is not None and session_data.get("created_at", 0) > end_timestamp:
                    continue
                if session_name is not None:
                    stored_name = session_data.get("session_data", {}).get("session_name", "")
                    if session_name.lower() not in stored_name.lower():
                        continue
                session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                if session_data.get("session_type") != session_type_value:
                    continue

                filtered_sessions.append(deepcopy(session_data))

            total_count = len(filtered_sessions)

            # Apply sorting
            filtered_sessions = apply_sorting(filtered_sessions, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_sessions = filtered_sessions[start_idx : start_idx + limit]

            if not deserialize:
                return filtered_sessions, total_count

            if session_type == SessionType.AGENT:
                return [AgentSession.from_dict(session) for session in filtered_sessions]  # type: ignore
            elif session_type == SessionType.TEAM:
                return [TeamSession.from_dict(session) for session in filtered_sessions]  # type: ignore
            elif session_type == SessionType.WORKFLOW:
                return [WorkflowSession.from_dict(session) for session in filtered_sessions]  # type: ignore
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Exception reading sessions: {e}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        try:
            for i, session in enumerate(self._sessions):
                if session.get("session_id") == session_id and session.get("session_type") == session_type.value:
                    if user_id is not None and session.get("user_id") != user_id:
                        continue
                    # Update session name in session_data
                    if "session_data" not in session:
                        session["session_data"] = {}
                    session["session_data"]["session_name"] = session_name

                    self._sessions[i] = session

                    log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

                    session_copy = deepcopy(session)
                    if not deserialize:
                        return session_copy

                    if session_type == SessionType.AGENT:
                        return AgentSession.from_dict(session_copy)
                    elif session_type == SessionType.TEAM:
                        return TeamSession.from_dict(session_copy)
                    else:
                        return WorkflowSession.from_dict(session_copy)

            return None

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        try:
            session_dict = session.to_dict()

            # Add session_type based on session instance type
            if isinstance(session, AgentSession):
                session_dict["session_type"] = SessionType.AGENT.value
            elif isinstance(session, TeamSession):
                session_dict["session_type"] = SessionType.TEAM.value
            elif isinstance(session, WorkflowSession):
                session_dict["session_type"] = SessionType.WORKFLOW.value

            # Find existing session to update
            session_updated = False
            for i, existing_session in enumerate(self._sessions):
                if existing_session.get("session_id") == session_dict.get("session_id") and self._matches_session_key(
                    existing_session, session
                ):
                    existing_uid = existing_session.get("user_id")
                    if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                        return None
                    session_dict["updated_at"] = int(time.time())
                    self._sessions[i] = deepcopy(session_dict)
                    session_updated = True
                    break

            if not session_updated:
                session_dict["created_at"] = session_dict.get("created_at", int(time.time()))
                session_dict["updated_at"] = session_dict.get("created_at")
                self._sessions.append(deepcopy(session_dict))

            session_dict_copy = deepcopy(session_dict)
            if not deserialize:
                return session_dict_copy

            if session_dict_copy["session_type"] == SessionType.AGENT:
                return AgentSession.from_dict(session_dict_copy)
            elif session_dict_copy["session_type"] == SessionType.TEAM:
                return TeamSession.from_dict(session_dict_copy)
            else:
                return WorkflowSession.from_dict(session_dict_copy)

        except Exception as e:
            log_error(f"Exception upserting session: {e}")
            raise e

    def _matches_session_key(self, existing_session: Dict[str, Any], session: Session) -> bool:
        """Check if existing session matches the key for the session type."""
        if isinstance(session, AgentSession):
            return existing_session.get("agent_id") == session.agent_id
        elif isinstance(session, TeamSession):
            return existing_session.get("team_id") == session.team_id
        elif isinstance(session, WorkflowSession):
            return existing_session.get("workflow_id") == session.workflow_id
        return False

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
            log_info(f"In-memory database: processing {len(sessions)} sessions with individual upsert operations")

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
        """Delete a user memory from in-memory storage.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user. If provided, verifies the memory belongs to this user before deletion.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            original_count = len(self._memories)

            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                self._memories = [
                    m for m in self._memories if not (m.get("memory_id") == memory_id and m.get("user_id") == user_id)
                ]
            else:
                self._memories = [m for m in self._memories if m.get("memory_id") != memory_id]

            if len(self._memories) < original_count:
                log_debug(f"Successfully deleted user memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple user memories from in-memory storage.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user. If provided, only deletes memories belonging to this user.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            # If user_id is provided, verify ownership before deleting
            if user_id is not None:
                self._memories = [
                    m for m in self._memories if not (m.get("memory_id") in memory_ids and m.get("user_id") == user_id)
                ]
            else:
                self._memories = [m for m in self._memories if m.get("memory_id") not in memory_ids]
            log_debug(f"Successfully deleted {len(memory_ids)} user memories")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")
            raise e

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from in-memory storage.

        Returns:
            List[str]: List of unique topics.

        Raises:
            Exception: If an error occurs while reading topics.
        """
        try:
            topics = set()
            for memory in self._memories:
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)
            return list(topics)

        except Exception as e:
            log_error(f"Exception reading from memory storage: {e}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a user memory from in-memory storage.

        Args:
            memory_id (str): The ID of the memory to retrieve.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user. If provided, only returns the memory if it belongs to this user.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]: The memory object or dictionary, or None if not found.

        Raises:
            Exception: If an error occurs while reading the memory.
        """
        try:
            for memory_data in self._memories:
                if memory_data.get("memory_id") == memory_id:
                    # Filter by user_id if provided
                    if user_id is not None and memory_data.get("user_id") != user_id:
                        continue

                    memory_data_copy = deepcopy(memory_data)
                    if not deserialize:
                        return memory_data_copy
                    return UserMemory.from_dict(memory_data_copy)

            return None

        except Exception as e:
            log_error(f"Exception reading from memory storage: {e}")
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
        try:
            # Apply filters
            filtered_memories = []
            for memory_data in self._memories:
                if user_id is not None and memory_data.get("user_id") != user_id:
                    continue
                if agent_id is not None and memory_data.get("agent_id") != agent_id:
                    continue
                if team_id is not None and memory_data.get("team_id") != team_id:
                    continue
                if topics is not None:
                    memory_topics = memory_data.get("topics", [])
                    if not any(topic in memory_topics for topic in topics):
                        continue
                if search_content is not None:
                    memory_content = str(memory_data.get("memory", ""))
                    if search_content.lower() not in memory_content.lower():
                        continue

                filtered_memories.append(deepcopy(memory_data))

            total_count = len(filtered_memories)

            # Apply sorting
            filtered_memories = apply_sorting(filtered_memories, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_memories = filtered_memories[start_idx : start_idx + limit]

            if not deserialize:
                return filtered_memories, total_count

            return [UserMemory.from_dict(memory) for memory in filtered_memories]

        except Exception as e:
            log_error(f"Exception reading from memory storage: {e}")
            raise e

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory statistics.

        Args:
            limit (Optional[int]): Maximum number of stats to return.
            page (Optional[int]): Page number for pagination.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: List of user memory statistics and total count.

        Raises:
            Exception: If an error occurs while getting stats.
        """
        try:
            user_stats = {}

            for memory in self._memories:
                memory_user_id = memory.get("user_id")
                # filter by user_id if provided
                if user_id is not None and memory_user_id != user_id:
                    continue
                if memory_user_id:
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
            stats_list.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(stats_list)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                stats_list = stats_list[start_idx : start_idx + limit]

            return stats_list, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {e}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        try:
            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            memory_dict = memory.to_dict() if hasattr(memory, "to_dict") else memory.__dict__
            memory_dict["updated_at"] = int(time.time())

            # Find existing memory to update
            memory_updated = False
            for i, existing_memory in enumerate(self._memories):
                if existing_memory.get("memory_id") == memory.memory_id:
                    self._memories[i] = memory_dict
                    memory_updated = True
                    break

            if not memory_updated:
                self._memories.append(memory_dict)

            memory_dict_copy = deepcopy(memory_dict)
            if not deserialize:
                return memory_dict_copy

            return UserMemory.from_dict(memory_dict_copy)

        except Exception as e:
            log_warning(f"Exception upserting user memory: {e}")
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
            log_info(f"In-memory database: processing {len(memories)} memories with individual upsert operations")
            # For in-memory database, individual upserts are actually efficient
            # since we're just manipulating Python lists and dictionaries
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
        """Delete all memories.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            self._memories.clear()

        except Exception as e:
            log_warning(f"Exception deleting all memories: {e}")
            raise e

    # -- Metrics methods --
    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            starting_date = self._get_metrics_calculation_starting_date(self._metrics)
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

            sessions = self._get_all_sessions_for_metrics_calculation(start_timestamp, end_timestamp)
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

                # Upsert metrics record
                existing_record_idx = None
                for i, existing_metric in enumerate(self._metrics):
                    if (
                        existing_metric.get("date") == str(date_to_process)
                        and existing_metric.get("aggregation_period") == "daily"
                    ):
                        existing_record_idx = i
                        break

                if existing_record_idx is not None:
                    self._metrics[existing_record_idx] = metrics_record
                else:
                    self._metrics.append(metrics_record)

                results.append(metrics_record)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_warning(f"Exception refreshing metrics: {e}")
            raise e

    def _get_metrics_calculation_starting_date(self, metrics: List[Dict[str, Any]]) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        if metrics:
            # Sort by date in descending order
            sorted_metrics = sorted(metrics, key=lambda x: x.get("date", ""), reverse=True)
            latest_metric = sorted_metrics[0]

            if latest_metric.get("completed", False):
                latest_date = datetime.strptime(latest_metric["date"], "%Y-%m-%d").date()
                return latest_date + timedelta(days=1)
            else:
                return datetime.strptime(latest_metric["date"], "%Y-%m-%d").date()

        # No metrics records. Return the date of the first recorded session.
        if self._sessions:
            # Sort by created_at
            sorted_sessions = sorted(self._sessions, key=lambda x: x.get("created_at", 0))
            first_session_date = sorted_sessions[0]["created_at"]
            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        return None

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for metrics calculation."""
        try:
            filtered_sessions = []
            for session in self._sessions:
                created_at = session.get("created_at", 0)
                if start_timestamp is not None and created_at < start_timestamp:
                    continue
                if end_timestamp is not None and created_at >= end_timestamp:
                    continue

                # Only include necessary fields for metrics
                filtered_session = {
                    "user_id": session.get("user_id"),
                    "session_data": deepcopy(session.get("session_data")),
                    "runs": deepcopy(session.get("runs")),
                    "created_at": session.get("created_at"),
                    "session_type": session.get("session_type"),
                }
                filtered_sessions.append(filtered_session)

            return filtered_sessions

        except Exception as e:
            log_error(f"Exception reading sessions for metrics: {e}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range."""
        try:
            filtered_metrics = []
            latest_updated_at = None

            for metric in self._metrics:
                metric_date = datetime.strptime(metric.get("date", ""), "%Y-%m-%d").date()

                if starting_date and metric_date < starting_date:
                    continue
                if ending_date and metric_date > ending_date:
                    continue

                filtered_metrics.append(deepcopy(metric))

                updated_at = metric.get("updated_at")
                if updated_at and (latest_updated_at is None or updated_at > latest_updated_at):
                    latest_updated_at = updated_at

            return filtered_metrics, latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {e}")
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from in-memory storage.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            self._knowledge = [item for item in self._knowledge if item.get("id") != id]

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from in-memory storage.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            for item in self._knowledge:
                if item.get("id") == id:
                    return KnowledgeRow.model_validate(item)

            return None

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            raise e

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from in-memory storage.

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
            knowledge_items = [deepcopy(item) for item in self._knowledge]

            # Apply linked_to filter if provided
            if linked_to is not None:
                knowledge_items = [item for item in knowledge_items if item.get("linked_to") == linked_to]

            total_count = len(knowledge_items)

            # Apply sorting
            knowledge_items = apply_sorting(knowledge_items, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                knowledge_items = knowledge_items[start_idx : start_idx + limit]

            return [KnowledgeRow.model_validate(item) for item in knowledge_items], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            knowledge_dict = knowledge_row.model_dump()

            # Find existing item to update
            item_updated = False
            for i, existing_item in enumerate(self._knowledge):
                if existing_item.get("id") == knowledge_row.id:
                    self._knowledge[i] = knowledge_dict
                    item_updated = True
                    break

            if not item_updated:
                self._knowledge.append(knowledge_dict)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {e}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord"""
        try:
            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            self._eval_runs.append(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from in-memory storage."""
        try:
            original_count = len(self._eval_runs)
            self._eval_runs = [run for run in self._eval_runs if run.get("run_id") not in eval_run_ids]

            deleted_count = original_count - len(self._eval_runs)
            if deleted_count > 0:
                log_debug(f"Deleted {deleted_count} eval runs")
            else:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise e

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from in-memory storage."""
        try:
            for run_data in self._eval_runs:
                if run_data.get("run_id") == eval_run_id:
                    run_data_copy = deepcopy(run_data)
                    if not deserialize:
                        return run_data_copy
                    return EvalRunRecord.model_validate(run_data_copy)

            return None

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
        """Get all eval runs from in-memory storage with filtering and pagination."""
        try:
            # Apply filters
            filtered_runs = []
            for run_data in self._eval_runs:
                if agent_id is not None and run_data.get("agent_id") != agent_id:
                    continue
                if team_id is not None and run_data.get("team_id") != team_id:
                    continue
                if workflow_id is not None and run_data.get("workflow_id") != workflow_id:
                    continue
                if model_id is not None and run_data.get("model_id") != model_id:
                    continue
                if eval_type is not None and len(eval_type) > 0:
                    if run_data.get("eval_type") not in eval_type:
                        continue
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT and run_data.get("agent_id") is None:
                        continue
                    elif filter_type == EvalFilterType.TEAM and run_data.get("team_id") is None:
                        continue
                    elif filter_type == EvalFilterType.WORKFLOW and run_data.get("workflow_id") is None:
                        continue

                filtered_runs.append(deepcopy(run_data))

            total_count = len(filtered_runs)

            # Apply sorting (default by created_at desc)
            if sort_by is None:
                filtered_runs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            else:
                filtered_runs = apply_sorting(filtered_runs, sort_by, sort_order)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                filtered_runs = filtered_runs[start_idx : start_idx + limit]

            if not deserialize:
                return filtered_runs, total_count

            return [EvalRunRecord.model_validate(run) for run in filtered_runs]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Rename an eval run."""
        try:
            for i, run_data in enumerate(self._eval_runs):
                if run_data.get("run_id") == eval_run_id:
                    run_data["name"] = name
                    run_data["updated_at"] = int(time.time())
                    self._eval_runs[i] = run_data

                    log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

                    run_data_copy = deepcopy(run_data)
                    if not deserialize:
                        return run_data_copy

                    return EvalRunRecord.model_validate(run_data_copy)

            return None

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {e}")
            raise e

    # -- Culture methods --

    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from in-memory storage."""
        try:
            self._cultural_knowledge = []
        except Exception as e:
            log_error(f"Error clearing cultural knowledge: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural knowledge entry from in-memory storage."""
        try:
            self._cultural_knowledge = [ck for ck in self._cultural_knowledge if ck.get("id") != id]
        except Exception as e:
            log_error(f"Error deleting cultural knowledge: {e}")
            raise e

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get a cultural knowledge entry from in-memory storage."""
        try:
            for ck_data in self._cultural_knowledge:
                if ck_data.get("id") == id:
                    ck_data_copy = deepcopy(ck_data)
                    if not deserialize:
                        return ck_data_copy
                    return deserialize_cultural_knowledge_from_db(ck_data_copy)
            return None
        except Exception as e:
            log_error(f"Error getting cultural knowledge: {e}")
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
        """Get all cultural knowledge from in-memory storage."""
        try:
            filtered_ck = []
            for ck_data in self._cultural_knowledge:
                if name and ck_data.get("name") != name:
                    continue
                if agent_id and ck_data.get("agent_id") != agent_id:
                    continue
                if team_id and ck_data.get("team_id") != team_id:
                    continue
                filtered_ck.append(ck_data)

            # Apply sorting
            if sort_by:
                filtered_ck = apply_sorting(filtered_ck, sort_by, sort_order)

            total_count = len(filtered_ck)

            # Apply pagination
            if limit and page:
                start = (page - 1) * limit
                filtered_ck = filtered_ck[start : start + limit]
            elif limit:
                filtered_ck = filtered_ck[:limit]

            if not deserialize:
                return [deepcopy(ck) for ck in filtered_ck], total_count

            return [deserialize_cultural_knowledge_from_db(deepcopy(ck)) for ck in filtered_ck]
        except Exception as e:
            log_error(f"Error getting all cultural knowledge: {e}")
            raise e

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert a cultural knowledge entry into in-memory storage."""
        try:
            if not cultural_knowledge.id:
                cultural_knowledge.id = str(uuid4())

            # Serialize content, categories, and notes into a dict for DB storage
            content_dict = serialize_cultural_knowledge_for_db(cultural_knowledge)

            # Create the item dict with serialized content
            ck_dict = {
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

            # Remove existing entry with same id
            self._cultural_knowledge = [ck for ck in self._cultural_knowledge if ck.get("id") != cultural_knowledge.id]

            # Add new entry
            self._cultural_knowledge.append(ck_dict)

            return self.get_cultural_knowledge(cultural_knowledge.id, deserialize=deserialize)
        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        raise NotImplementedError

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        raise NotImplementedError

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")

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
        raise NotImplementedError("Learning methods not yet implemented for InMemoryDb")
