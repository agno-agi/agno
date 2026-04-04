import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.json.utils import (
    apply_sorting,
    calculate_date_metrics,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    serialize_cultural_knowledge_for_db,
)
from agno.db.schemas.context import ContextItem
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id


class JsonDb(BaseDb):
    def __init__(
        self,
        db_path: Optional[str] = None,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        context_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with JSON files as database.

        Args:
            db_path (Optional[str]): Path to the directory where JSON files will be stored.
            session_table (Optional[str]): Name of the JSON file to store sessions (without .json extension).
            culture_table (Optional[str]): Name of the JSON file to store cultural knowledge.
            context_table (Optional[str]): Name of the JSON file to store context items.
            memory_table (Optional[str]): Name of the JSON file to store memories.
            metrics_table (Optional[str]): Name of the JSON file to store metrics.
            eval_table (Optional[str]): Name of the JSON file to store evaluation runs.
            knowledge_table (Optional[str]): Name of the JSON file to store knowledge content.
            traces_table (Optional[str]): Name of the JSON file to store run traces.
            spans_table (Optional[str]): Name of the JSON file to store span events.
            id (Optional[str]): ID of the database.
        """
        if id is None:
            seed = db_path or "agno_json_db"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            culture_table=culture_table,
            context_table=context_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
        )

        # Create the directory where the JSON files will be stored, if it doesn't exist
        self.db_path = Path(db_path or os.path.join(os.getcwd(), "agno_json_db"))

    def table_exists(self, table_name: str) -> bool:
        """JSON implementation, always returns True."""
        return True

    def _read_json_file(self, filename: str, create_table_if_not_found: Optional[bool] = True) -> List[Dict[str, Any]]:
        """Read data from a JSON file, creating it if it doesn't exist.

        Args:
            filename (str): The name of the JSON file to read.

        Returns:
            List[Dict[str, Any]]: The data from the JSON file.

        Raises:
            json.JSONDecodeError: If the JSON file is not valid.
        """
        file_path = self.db_path / f"{filename}.json"

        # Create directory if it doesn't exist
        self.db_path.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "r") as f:
                return json.load(f)

        except FileNotFoundError:
            if create_table_if_not_found:
                with open(file_path, "w") as f:
                    json.dump([], f)
            return []

        except json.JSONDecodeError as e:
            log_error(f"Error reading the {file_path} JSON file")
            raise e

    def _write_json_file(self, filename: str, data: List[Dict[str, Any]]) -> None:
        """Write data to a JSON file.

        Args:
            filename (str): The name of the JSON file to write.
            data (List[Dict[str, Any]]): The data to write to the JSON file.

        Raises:
            Exception: If an error occurs while writing to the JSON file.
        """
        file_path = self.db_path / f"{filename}.json"

        # Create directory if it doesn't exist
        self.db_path.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

        except Exception as e:
            log_error(f"Error writing to the {file_path} JSON file: {e}")
            raise e

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from the JSON file.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            sessions = self._read_json_file(self.session_table_name)
            original_count = len(sessions)
            sessions = [
                s
                for s in sessions
                if not (s.get("session_id") == session_id and (user_id is None or s.get("user_id") == user_id))
            ]

            if len(sessions) < original_count:
                self._write_json_file(self.session_table_name, sessions)
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from the JSON file.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            sessions = self._read_json_file(self.session_table_name)
            sessions = [
                s
                for s in sessions
                if not (s.get("session_id") in session_ids and (user_id is None or s.get("user_id") == user_id))
            ]
            self._write_json_file(self.session_table_name, sessions)
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
        """Read a session from the JSON file.

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
            sessions = self._read_json_file(self.session_table_name)

            for session_data in sessions:
                if session_data.get("session_id") == session_id:
                    if user_id is not None and session_data.get("user_id") != user_id:
                        continue

                    if not deserialize:
                        return session_data

                    if session_type == SessionType.AGENT:
                        return AgentSession.from_dict(session_data)
                    elif session_type == SessionType.TEAM:
                        return TeamSession.from_dict(session_data)
                    elif session_type == SessionType.WORKFLOW:
                        return WorkflowSession.from_dict(session_data)
                    else:
                        raise ValueError(f"Invalid session type: {session_type}")

            return None

        except Exception as e:
            log_error(f"Exception reading from session file: {e}")
            raise e

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
        """Get all sessions from the JSON file with filtering and pagination.

        Args:
            session_type (Optional[SessionType]): The type of the sessions to read.
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
            create_table_if_not_found (Optional[bool]): Whether to create a json file to track sessions if it doesn't exist.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of sessions
                - When deserialize=False: Tuple with list of sessions and total count

        Raises:
            Exception: If an error occurs while reading the sessions.
        """
        try:
            sessions = self._read_json_file(self.session_table_name)

            # Apply filters
            filtered_sessions = []
            for session_data in sessions:
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

                filtered_sessions.append(session_data)

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
            log_error(f"Exception reading from session file: {e}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in the JSON file."""
        try:
            sessions = self._read_json_file(self.session_table_name)

            for i, session in enumerate(sessions):
                if session.get("session_id") == session_id and session.get("session_type") == session_type.value:
                    if user_id is not None and session.get("user_id") != user_id:
                        continue
                    # Update session name in session_data
                    if "session_data" not in session:
                        session["session_data"] = {}
                    session["session_data"]["session_name"] = session_name

                    sessions[i] = session
                    self._write_json_file(self.session_table_name, sessions)

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

            return None

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in the JSON file."""
        try:
            sessions = self._read_json_file(self.session_table_name, create_table_if_not_found=True)
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
            for i, existing_session in enumerate(sessions):
                if existing_session.get("session_id") == session_dict.get("session_id") and self._matches_session_key(
                    existing_session, session
                ):
                    existing_uid = existing_session.get("user_id")
                    if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                        return None
                    # Update existing session
                    session_dict["updated_at"] = int(time.time())
                    sessions[i] = session_dict
                    session_updated = True
                    break

            if not session_updated:
                # Add new session
                session_dict["created_at"] = session_dict.get("created_at", int(time.time()))
                session_dict["updated_at"] = session_dict.get("created_at")
                sessions.append(session_dict)

            self._write_json_file(self.session_table_name, sessions)

            if not deserialize:
                return session_dict

            return session

        except Exception as e:
            log_error(f"Exception upserting session: {e}")
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
                f"JsonDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
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

    def _matches_session_key(self, existing_session: Dict[str, Any], session: Session) -> bool:
        """Check if existing session matches the key for the session type."""
        if isinstance(session, AgentSession):
            return existing_session.get("agent_id") == session.agent_id
        elif isinstance(session, TeamSession):
            return existing_session.get("team_id") == session.team_id
        elif isinstance(session, WorkflowSession):
            return existing_session.get("workflow_id") == session.workflow_id
        return False

    # -- Memory methods --
    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the JSON file.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).
        """
        try:
            memories = self._read_json_file(self.memory_table_name)
            original_count = len(memories)

            # If user_id is provided, verify the memory belongs to the user before deleting
            if user_id is not None:
                memory_to_delete = None
                for m in memories:
                    if m.get("memory_id") == memory_id:
                        memory_to_delete = m
                        break

                if memory_to_delete and memory_to_delete.get("user_id") != user_id:
                    log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                    return

            memories = [m for m in memories if m.get("memory_id") != memory_id]

            if len(memories) < original_count:
                self._write_json_file(self.memory_table_name, memories)
                log_debug(f"Successfully deleted user memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple user memories from the JSON file.

        Args:
            memory_ids (List[str]): List of memory IDs to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).
        """
        try:
            memories = self._read_json_file(self.memory_table_name)

            # If user_id is provided, filter memory_ids to only those belonging to the user
            if user_id is not None:
                filtered_memory_ids: List[str] = []
                for memory in memories:
                    if memory.get("memory_id") in memory_ids and memory.get("user_id") == user_id:
                        filtered_memory_ids.append(memory.get("memory_id"))  # type: ignore
                memory_ids = filtered_memory_ids

            memories = [m for m in memories if m.get("memory_id") not in memory_ids]
            self._write_json_file(self.memory_table_name, memories)

            log_debug(f"Successfully deleted {len(memory_ids)} user memories")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")
            raise e

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the JSON file.

        Returns:
            List[str]: List of unique memory topics.
        """
        try:
            memories = self._read_json_file(self.memory_table_name)

            topics = set()
            for memory in memories:
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)
            return list(topics)

        except Exception as e:
            log_error(f"Exception reading from memory file: {e}")
            raise e

    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the JSON file.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]: The user memory data if found, None otherwise.
        """
        try:
            memories = self._read_json_file(self.memory_table_name)

            for memory_data in memories:
                if memory_data.get("memory_id") == memory_id:
                    # Filter by user_id if provided
                    if user_id and memory_data.get("user_id") != user_id:
                        return None

                    if not deserialize:
                        return memory_data
                    return UserMemory.from_dict(memory_data)

            return None

        except Exception as e:
            log_error(f"Exception reading from memory file: {e}")
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
        """Get all memories from the JSON file with filtering and pagination."""
        try:
            memories = self._read_json_file(self.memory_table_name)

            # Apply filters
            filtered_memories = []
            for memory_data in memories:
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

                filtered_memories.append(memory_data)

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
            log_error(f"Exception reading from memory file: {e}")
            raise e

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory statistics.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A list of dictionaries containing user stats and total count.
        """
        try:
            memories = self._read_json_file(self.memory_table_name)
            user_stats = {}

            for memory in memories:
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
        """Upsert a user memory in the JSON file."""
        try:
            memories = self._read_json_file(self.memory_table_name, create_table_if_not_found=True)

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            memory_dict = memory.to_dict() if hasattr(memory, "to_dict") else memory.__dict__
            memory_dict["updated_at"] = int(time.time())

            # Find existing memory to update
            memory_updated = False
            for i, existing_memory in enumerate(memories):
                if existing_memory.get("memory_id") == memory.memory_id:
                    memories[i] = memory_dict
                    memory_updated = True
                    break

            if not memory_updated:
                memories.append(memory_dict)

            self._write_json_file(self.memory_table_name, memories)

            if not deserialize:
                return memory_dict
            return UserMemory.from_dict(memory_dict)

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
            log_info(
                f"JsonDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
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
            # Simply write an empty list to the memory JSON file
            self._write_json_file(self.memory_table_name, [])

        except Exception as e:
            log_warning(f"Exception deleting all memories: {e}")
            raise e

    # -- Metrics methods --
    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            metrics = self._read_json_file(self.metrics_table_name, create_table_if_not_found=True)

            starting_date = self._get_metrics_calculation_starting_date(metrics)
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
                for i, existing_metric in enumerate(metrics):
                    if (
                        existing_metric.get("date") == str(date_to_process)
                        and existing_metric.get("aggregation_period") == "daily"
                    ):
                        existing_record_idx = i
                        break

                if existing_record_idx is not None:
                    metrics[existing_record_idx] = metrics_record
                else:
                    metrics.append(metrics_record)

                results.append(metrics_record)

            if results:
                self._write_json_file(self.metrics_table_name, metrics)

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
        # We need to get sessions of all types, so we'll read directly from the file
        all_sessions = self._read_json_file(self.session_table_name)
        if all_sessions:
            # Sort by created_at
            all_sessions.sort(key=lambda x: x.get("created_at", 0))
            first_session_date = all_sessions[0]["created_at"]
            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        return None

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for metrics calculation."""
        try:
            sessions = self._read_json_file(self.session_table_name)

            filtered_sessions = []
            for session in sessions:
                created_at = session.get("created_at", 0)
                if start_timestamp is not None and created_at < start_timestamp:
                    continue
                if end_timestamp is not None and created_at >= end_timestamp:
                    continue

                # Only include necessary fields for metrics
                filtered_session = {
                    "user_id": session.get("user_id"),
                    "session_data": session.get("session_data"),
                    "runs": session.get("runs"),
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
            metrics = self._read_json_file(self.metrics_table_name)

            filtered_metrics = []
            latest_updated_at = None

            for metric in metrics:
                metric_date = datetime.strptime(metric.get("date", ""), "%Y-%m-%d").date()

                if starting_date and metric_date < starting_date:
                    continue
                if ending_date and metric_date > ending_date:
                    continue

                filtered_metrics.append(metric)

                updated_at = metric.get("updated_at")
                if updated_at and (latest_updated_at is None or updated_at > latest_updated_at):
                    latest_updated_at = updated_at

            return filtered_metrics, latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {e}")
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)
            knowledge_items = [item for item in knowledge_items if item.get("id") != id]
            self._write_json_file(self.knowledge_table_name, knowledge_items)

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
            Exception: If an error occurs during retrieval.
        """
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)

            for item in knowledge_items:
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
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)

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
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name, create_table_if_not_found=True)
            knowledge_dict = knowledge_row.model_dump()

            # Find existing item to update
            item_updated = False
            for i, existing_item in enumerate(knowledge_items):
                if existing_item.get("id") == knowledge_row.id:
                    knowledge_items[i] = knowledge_dict
                    item_updated = True
                    break

            if not item_updated:
                knowledge_items.append(knowledge_dict)

            self._write_json_file(self.knowledge_table_name, knowledge_items)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {e}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name, create_table_if_not_found=True)

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            eval_runs.append(eval_dict)
            self._write_json_file(self.eval_table_name, eval_runs)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)
            original_count = len(eval_runs)
            eval_runs = [run for run in eval_runs if run.get("run_id") != eval_run_id]

            if len(eval_runs) < original_count:
                self._write_json_file(self.eval_table_name, eval_runs)
                log_debug(f"Deleted eval run with ID: {eval_run_id}")
            else:
                log_debug(f"No eval run found with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)
            original_count = len(eval_runs)
            eval_runs = [run for run in eval_runs if run.get("run_id") not in eval_run_ids]

            deleted_count = original_count - len(eval_runs)
            if deleted_count > 0:
                self._write_json_file(self.eval_table_name, eval_runs)
                log_debug(f"Deleted {deleted_count} eval runs")
            else:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise e

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)

            for run_data in eval_runs:
                if run_data.get("run_id") == eval_run_id:
                    if not deserialize:
                        return run_data
                    return EvalRunRecord.model_validate(run_data)

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
        """Get all eval runs from the JSON file with filtering and pagination."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)

            # Apply filters
            filtered_runs = []
            for run_data in eval_runs:
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

                filtered_runs.append(run_data)

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
        """Rename an eval run in the JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)

            for i, run_data in enumerate(eval_runs):
                if run_data.get("run_id") == eval_run_id:
                    run_data["name"] = name
                    run_data["updated_at"] = int(time.time())
                    eval_runs[i] = run_data
                    self._write_json_file(self.eval_table_name, eval_runs)

                    log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

                    if not deserialize:
                        return run_data

                    return EvalRunRecord.model_validate(run_data)

            return None

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {e}")
            raise e

    # -- Culture methods --

    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from JSON file."""
        try:
            self._write_json_file(self.culture_table_name, [])
        except Exception as e:
            log_error(f"Error clearing cultural knowledge: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural knowledge entry from JSON file."""
        try:
            cultural_knowledge = self._read_json_file(self.culture_table_name)
            cultural_knowledge = [ck for ck in cultural_knowledge if ck.get("id") != id]
            self._write_json_file(self.culture_table_name, cultural_knowledge)
        except Exception as e:
            log_error(f"Error deleting cultural knowledge: {e}")
            raise e

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get a cultural knowledge entry from JSON file."""
        try:
            cultural_knowledge = self._read_json_file(self.culture_table_name)
            for ck in cultural_knowledge:
                if ck.get("id") == id:
                    if not deserialize:
                        return ck
                    return deserialize_cultural_knowledge_from_db(ck)
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
        """Get all cultural knowledge from JSON file."""
        try:
            cultural_knowledge = self._read_json_file(self.culture_table_name)

            # Filter
            filtered = []
            for ck in cultural_knowledge:
                if name and ck.get("name") != name:
                    continue
                if agent_id and ck.get("agent_id") != agent_id:
                    continue
                if team_id and ck.get("team_id") != team_id:
                    continue
                filtered.append(ck)

            # Sort
            if sort_by:
                filtered = apply_sorting(filtered, sort_by, sort_order)

            total_count = len(filtered)

            # Paginate
            if limit and page:
                start = (page - 1) * limit
                filtered = filtered[start : start + limit]
            elif limit:
                filtered = filtered[:limit]

            if not deserialize:
                return filtered, total_count

            return [deserialize_cultural_knowledge_from_db(ck) for ck in filtered]
        except Exception as e:
            log_error(f"Error getting all cultural knowledge: {e}")
            raise e

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert a cultural knowledge entry into JSON file."""
        try:
            if not cultural_knowledge.id:
                cultural_knowledge.id = str(uuid4())

            all_cultural_knowledge = self._read_json_file(self.culture_table_name, create_table_if_not_found=True)

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

            # Remove existing entry
            all_cultural_knowledge = [ck for ck in all_cultural_knowledge if ck.get("id") != cultural_knowledge.id]

            # Add new entry
            all_cultural_knowledge.append(ck_dict)

            self._write_json_file(self.culture_table_name, all_cultural_knowledge)

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
        try:
            traces = self._read_json_file(self.trace_table_name, create_table_if_not_found=True)

            # Check if trace exists
            existing_idx = None
            for i, existing in enumerate(traces):
                if existing.get("trace_id") == trace.trace_id:
                    existing_idx = i
                    break

            if existing_idx is not None:
                existing = traces[existing_idx]

                # workflow (level 3) > team (level 2) > agent (level 1) > child/unknown (level 0)
                def get_component_level(workflow_id, team_id, agent_id, name):
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
                existing_start_time_str = existing.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                # Update existing trace
                existing["end_time"] = trace.end_time.isoformat()
                existing["duration_ms"] = recalculated_duration_ms
                existing["status"] = trace.status
                if should_update_name:
                    existing["name"] = trace.name

                # Update context fields only if new value is not None
                if trace.run_id is not None:
                    existing["run_id"] = trace.run_id
                if trace.session_id is not None:
                    existing["session_id"] = trace.session_id
                if trace.user_id is not None:
                    existing["user_id"] = trace.user_id
                if trace.agent_id is not None:
                    existing["agent_id"] = trace.agent_id
                if trace.team_id is not None:
                    existing["team_id"] = trace.team_id
                if trace.workflow_id is not None:
                    existing["workflow_id"] = trace.workflow_id

                traces[existing_idx] = existing
            else:
                # Add new trace
                trace_dict = trace.to_dict()
                trace_dict.pop("total_spans", None)
                trace_dict.pop("error_count", None)
                traces.append(trace_dict)

            self._write_json_file(self.trace_table_name, traces)

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
        """
        try:
            from agno.tracing.schemas import Trace

            traces = self._read_json_file(self.trace_table_name, create_table_if_not_found=False)
            if not traces:
                return None

            # Get spans for calculating total_spans and error_count
            spans = self._read_json_file(self.span_table_name, create_table_if_not_found=False)

            # Filter traces
            filtered = []
            for t in traces:
                if trace_id and t.get("trace_id") == trace_id:
                    filtered.append(t)
                    break
                elif run_id and t.get("run_id") == run_id:
                    filtered.append(t)

            if not filtered:
                return None

            # Sort by start_time desc and get first
            filtered.sort(key=lambda x: x.get("start_time", ""), reverse=True)
            trace_data = filtered[0]

            # Calculate total_spans and error_count
            trace_spans = [s for s in spans if s.get("trace_id") == trace_data.get("trace_id")]
            trace_data["total_spans"] = len(trace_spans)
            trace_data["error_count"] = sum(1 for s in trace_spans if s.get("status_code") == "ERROR")

            return Trace.from_dict(trace_data)

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
            from agno.tracing.schemas import Trace

            traces = self._read_json_file(self.trace_table_name, create_table_if_not_found=False)
            if not traces:
                return [], 0

            # Get spans for calculating total_spans and error_count
            spans = self._read_json_file(self.span_table_name, create_table_if_not_found=False)

            # Apply filters
            filtered = []
            for t in traces:
                if run_id and t.get("run_id") != run_id:
                    continue
                if session_id and t.get("session_id") != session_id:
                    continue
                if user_id and t.get("user_id") != user_id:
                    continue
                if agent_id and t.get("agent_id") != agent_id:
                    continue
                if team_id and t.get("team_id") != team_id:
                    continue
                if workflow_id and t.get("workflow_id") != workflow_id:
                    continue
                if status and t.get("status") != status:
                    continue
                if start_time:
                    trace_start = t.get("start_time", "")
                    if trace_start < start_time.isoformat():
                        continue
                if end_time:
                    trace_end = t.get("end_time", "")
                    if trace_end > end_time.isoformat():
                        continue
                filtered.append(t)

            total_count = len(filtered)

            # Sort by start_time desc
            filtered.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Apply pagination
            if limit and page:
                start_idx = (page - 1) * limit
                filtered = filtered[start_idx : start_idx + limit]

            # Add total_spans and error_count to each trace
            result_traces = []
            for t in filtered:
                trace_spans = [s for s in spans if s.get("trace_id") == t.get("trace_id")]
                t["total_spans"] = len(trace_spans)
                t["error_count"] = sum(1 for s in trace_spans if s.get("status_code") == "ERROR")
                result_traces.append(Trace.from_dict(t))

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
        """
        try:
            traces = self._read_json_file(self.trace_table_name, create_table_if_not_found=False)
            if not traces:
                return [], 0

            # Group by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}

            for t in traces:
                session_id = t.get("session_id")
                if not session_id:
                    continue

                # Apply filters
                if user_id and t.get("user_id") != user_id:
                    continue
                if agent_id and t.get("agent_id") != agent_id:
                    continue
                if team_id and t.get("team_id") != team_id:
                    continue
                if workflow_id and t.get("workflow_id") != workflow_id:
                    continue

                created_at = t.get("created_at", "")
                if start_time and created_at < start_time.isoformat():
                    continue
                if end_time and created_at > end_time.isoformat():
                    continue

                if session_id not in session_stats:
                    session_stats[session_id] = {
                        "session_id": session_id,
                        "user_id": t.get("user_id"),
                        "agent_id": t.get("agent_id"),
                        "team_id": t.get("team_id"),
                        "workflow_id": t.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": created_at,
                        "last_trace_at": created_at,
                    }

                session_stats[session_id]["total_traces"] += 1
                if created_at < session_stats[session_id]["first_trace_at"]:
                    session_stats[session_id]["first_trace_at"] = created_at
                if created_at > session_stats[session_id]["last_trace_at"]:
                    session_stats[session_id]["last_trace_at"] = created_at

            stats_list = list(session_stats.values())
            total_count = len(stats_list)

            # Sort by last_trace_at desc
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            # Apply pagination
            if limit and page:
                start_idx = (page - 1) * limit
                stats_list = stats_list[start_idx : start_idx + limit]

            # Convert ISO strings to datetime objects
            for stat in stats_list:
                first_at = stat.get("first_trace_at", "")
                last_at = stat.get("last_trace_at", "")
                if first_at:
                    stat["first_trace_at"] = datetime.fromisoformat(first_at.replace("Z", "+00:00"))
                if last_at:
                    stat["last_trace_at"] = datetime.fromisoformat(last_at.replace("Z", "+00:00"))

            return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {e}")
            return [], 0

    # --- Spans ---
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            spans = self._read_json_file(self.span_table_name, create_table_if_not_found=True)
            spans.append(span.to_dict())
            self._write_json_file(self.span_table_name, spans)

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
            existing_spans = self._read_json_file(self.span_table_name, create_table_if_not_found=True)
            for span in spans:
                existing_spans.append(span.to_dict())
            self._write_json_file(self.span_table_name, existing_spans)

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
            from agno.tracing.schemas import Span

            spans = self._read_json_file(self.span_table_name, create_table_if_not_found=False)

            for s in spans:
                if s.get("span_id") == span_id:
                    return Span.from_dict(s)

            return None

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
            from agno.tracing.schemas import Span

            spans = self._read_json_file(self.span_table_name, create_table_if_not_found=False)
            if not spans:
                return []

            # Apply filters
            filtered = []
            for s in spans:
                if trace_id and s.get("trace_id") != trace_id:
                    continue
                if parent_span_id and s.get("parent_span_id") != parent_span_id:
                    continue
                filtered.append(s)

            # Apply limit
            if limit:
                filtered = filtered[:limit]

            return [Span.from_dict(s) for s in filtered]

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

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
        raise NotImplementedError("Learning methods not yet implemented for JsonDb")

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
        raise NotImplementedError("Learning methods not yet implemented for JsonDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for JsonDb")

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
        raise NotImplementedError("Learning methods not yet implemented for JsonDb")

    # -- Context methods --

    def clear_context_items(self) -> None:
        """Delete all context items from JSON file."""
        try:
            self._write_json_file(self.context_table_name, [])
        except Exception as e:
            log_error(f"Error clearing context items: {e}")
            raise e

    def delete_context_item(self, id: str) -> None:
        """Delete a context item entry from JSON file."""
        try:
            context_items = self._read_json_file(self.context_table_name)
            context_items = [ci for ci in context_items if ci.get("id") != id]
            self._write_json_file(self.context_table_name, context_items)
        except Exception as e:
            log_error(f"Error deleting context item: {e}")
            raise e

    def get_context_item(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[ContextItem, Dict[str, Any]]]:
        """Get a context item entry from JSON file."""
        try:
            context_items = self._read_json_file(self.context_table_name)
            for ci in context_items:
                if ci.get("id") == id:
                    if not deserialize:
                        return ci
                    return ContextItem.from_dict(ci)
            return None
        except Exception as e:
            log_error(f"Error getting context item: {e}")
            raise e

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
        """Get all context items from JSON file."""
        try:
            context_items = self._read_json_file(self.context_table_name)

            # Filter
            filtered = []
            for ci in context_items:
                if name and name.lower() not in ci.get("name", "").lower():
                    continue
                if metadata:
                    item_metadata = ci.get("metadata", {}) or {}
                    if not all(item_metadata.get(k) == v for k, v in metadata.items()):
                        continue
                filtered.append(ci)

            # Sort
            if sort_by:
                filtered = apply_sorting(filtered, sort_by, sort_order)

            total_count = len(filtered)

            # Paginate
            if limit and page:
                start = (page - 1) * limit
                filtered = filtered[start : start + limit]
            elif limit:
                filtered = filtered[:limit]

            if not deserialize:
                return filtered, total_count

            return [ContextItem.from_dict(ci) for ci in filtered]
        except Exception as e:
            log_error(f"Error getting all context items: {e}")
            raise e

    def upsert_context_item(
        self, context_item: ContextItem, deserialize: Optional[bool] = True
    ) -> Optional[Union[ContextItem, Dict[str, Any]]]:
        """Upsert a context item entry into JSON file."""
        try:
            if not context_item.id:
                context_item.id = str(uuid4())

            all_context_items = self._read_json_file(self.context_table_name, create_table_if_not_found=True)

            # Create the item dict
            ci_dict = {
                "id": context_item.id,
                "name": context_item.name,
                "content": context_item.content,
                "description": context_item.description,
                "metadata": context_item.metadata,
                "variables": context_item.variables,
                "version": context_item.version,
                "parent_id": context_item.parent_id,
                "optimization_notes": context_item.optimization_notes,
                "created_at": context_item.created_at if context_item.created_at else int(time.time()),
                "updated_at": context_item.updated_at if context_item.updated_at else int(time.time()),
            }

            # Remove existing entry
            all_context_items = [ci for ci in all_context_items if ci.get("id") != context_item.id]

            # Add new entry
            all_context_items.append(ci_dict)

            self._write_json_file(self.context_table_name, all_context_items)

            return self.get_context_item(context_item.id, deserialize=deserialize)
        except Exception as e:
            log_error(f"Error upserting context item: {e}")
            raise e
