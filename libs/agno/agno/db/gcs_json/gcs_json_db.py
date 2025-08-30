import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.gcs_json.utils import (
    apply_sorting,
    calculate_date_metrics,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from google.cloud import storage as gcs  # type: ignore
except ImportError:
    raise ImportError("`google-cloud-storage` not installed. Please install it with `pip install google-cloud-storage`")


class GcsJsonDb(BaseDb):
    def __init__(
        self,
        bucket_name: str,
        prefix: Optional[str] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        project: Optional[str] = None,
        credentials: Optional[Any] = None,
    ):
        """
        Interface for interacting with JSON files stored in Google Cloud Storage as database.

        Args:
            bucket_name (str): Name of the GCS bucket where JSON files will be stored.
            prefix (Optional[str]): Path prefix for organizing files in the bucket. Defaults to "agno/".
            session_table (Optional[str]): Name of the JSON file to store sessions (without .json extension).
            memory_table (Optional[str]): Name of the JSON file to store user memories.
            metrics_table (Optional[str]): Name of the JSON file to store metrics.
            eval_table (Optional[str]): Name of the JSON file to store evaluation runs.
            knowledge_table (Optional[str]): Name of the JSON file to store knowledge content.
            project (Optional[str]): GCP project ID. If None, uses default project.
            location (Optional[str]): GCS bucket location. If None, uses default location.
            credentials (Optional[Any]): GCP credentials. If None, uses default credentials.
        """
        super().__init__(
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        self.bucket_name = bucket_name
        self.prefix = prefix or "agno/"
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix += "/"

        # Initialize GCS client and bucket
        self.client = gcs.Client(project=project, credentials=credentials)
        self.bucket = self.client.bucket(self.bucket_name)

    def _get_blob_name(self, filename: str) -> str:
        """Get the full blob name including prefix for a given filename."""
        return f"{self.prefix}{filename}.json"

    def _read_json_file(self, filename: str, create_table_if_not_found: Optional[bool] = False) -> List[Dict[str, Any]]:
        """Read data from a JSON file in GCS, creating it if it doesn't exist.

        Args:
            filename (str): The name of the JSON file to read.

        Returns:
            List[Dict[str, Any]]: The data from the JSON file.

        Raises:
            json.JSONDecodeError: If the JSON file is not valid.
        """
        blob_name = self._get_blob_name(filename)
        blob = self.bucket.blob(blob_name)

        try:
            data_str = blob.download_as_bytes().decode("utf-8")
            return json.loads(data_str)

        except Exception as e:
            # Check if it's a 404 (file not found) error
            if "404" in str(e) or "Not Found" in str(e):
                if create_table_if_not_found:
                    log_debug(f"Creating new GCS JSON file: {blob_name}")
                    blob.upload_from_string("[]", content_type="application/json")
                return []
            else:
                log_error(f"Error reading the {blob_name} JSON file from GCS: {e}")
                raise json.JSONDecodeError(f"Error reading {blob_name}", "", 0)

    def _write_json_file(self, filename: str, data: List[Dict[str, Any]]) -> None:
        """Write data to a JSON file in GCS.

        Args:
            filename (str): The name of the JSON file to write.
            data (List[Dict[str, Any]]): The data to write to the JSON file.

        Raises:
            Exception: If an error occurs while writing to the JSON file.
        """
        blob_name = self._get_blob_name(filename)
        blob = self.bucket.blob(blob_name)

        try:
            json_data = json.dumps(data, indent=2, default=str)
            blob.upload_from_string(json_data, content_type="application/json")

        except Exception as e:
            log_error(f"Error writing to the {blob_name} JSON file in GCS: {e}")
            return

    # -- Session methods --

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from the GCS JSON file.

        Args:
            session_id (str): The ID of the session to delete.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            sessions = self._read_json_file(self.session_table_name)
            original_count = len(sessions)
            sessions = [s for s in sessions if s.get("session_id") != session_id]

            if len(sessions) < original_count:
                self._write_json_file(self.session_table_name, sessions)
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

            else:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False

        except Exception as e:
            log_warning(f"Error deleting session: {e}")
            return False

    def delete_sessions(self, session_ids: List[str]) -> None:
        """Delete multiple sessions from the GCS JSON file.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            sessions = self._read_json_file(self.session_table_name)
            sessions = [s for s in sessions if s.get("session_id") not in session_ids]
            self._write_json_file(self.session_table_name, sessions)
            log_debug(f"Successfully deleted sessions with ids: {session_ids}")

        except Exception as e:
            log_warning(f"Error deleting sessions: {e}")

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[AgentSession, TeamSession, WorkflowSession, Dict[str, Any]]]:
        """Read a session from the GCS JSON file.

        Args:
            session_id (str): The ID of the session to read.
            session_type (Optional[SessionType]): The type of the session to read.
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

                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    if session_data.get("session_type") != session_type_value:
                        continue

                    if not deserialize:
                        return session_data

                    if session_type == SessionType.AGENT:
                        return AgentSession.from_dict(session_data)
                    elif session_type == SessionType.TEAM:
                        return TeamSession.from_dict(session_data)
                    elif session_type == SessionType.WORKFLOW:
                        return WorkflowSession.from_dict(session_data)

            return None

        except Exception as e:
            log_warning(f"Exception reading from session file: {e}")
            return None

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
        """Get all sessions from the GCS JSON file with filtering and pagination.

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
            create_table_if_not_found (Optional[bool]): Whether to create a file to track sessions if it doesn't exist.

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
            log_warning(f"Exception reading from session file: {e}")
            return [] if deserialize else ([], 0)

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in the GCS JSON file."""
        try:
            sessions = self._read_json_file(self.session_table_name)

            for i, session_data in enumerate(sessions):
                if (
                    session_data.get("session_id") == session_id
                    and session_data.get("session_type") == session_type.value
                ):
                    # Update session name in session_data
                    if "session_data" not in session_data:
                        session_data["session_data"] = {}
                    session_data["session_data"]["session_name"] = session_name

                    sessions[i] = session_data
                    self._write_json_file(self.session_table_name, sessions)

                    if not deserialize:
                        return session_data

                    if session_type == SessionType.AGENT:
                        return AgentSession.from_dict(session_data)
                    elif session_type == SessionType.TEAM:
                        return TeamSession.from_dict(session_data)
                    elif session_type == SessionType.WORKFLOW:
                        return WorkflowSession.from_dict(session_data)

            return None
        except Exception as e:
            log_warning(f"Exception renaming session: {e}")
            return None

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in the GCS JSON file."""
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
            log_warning(f"Exception upserting session: {e}")
            return None

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
    def delete_user_memory(self, memory_id: str) -> None:
        """Delete a user memory from the GCS JSON file."""
        try:
            memories = self._read_json_file(self.memory_table_name)
            original_count = len(memories)
            memories = [m for m in memories if m.get("memory_id") != memory_id]

            if len(memories) < original_count:
                self._write_json_file(self.memory_table_name, memories)
                log_debug(f"Successfully deleted user memory id: {memory_id}")

            else:
                log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_warning(f"Error deleting user memory: {e}")

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        """Delete multiple user memories from the GCS JSON file."""
        try:
            memories = self._read_json_file(self.memory_table_name)
            memories = [m for m in memories if m.get("memory_id") not in memory_ids]
            self._write_json_file(self.memory_table_name, memories)
            log_debug(f"Successfully deleted user memories with ids: {memory_ids}")
        except Exception as e:
            log_warning(f"Error deleting user memories: {e}")

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the GCS JSON file."""
        try:
            memories = self._read_json_file(self.memory_table_name)
            topics = set()
            for memory in memories:
                memory_topics = memory.get("topics", [])
                if isinstance(memory_topics, list):
                    topics.update(memory_topics)
            return list(topics)

        except Exception as e:
            log_warning(f"Exception reading from memory file: {e}")
            return []

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the GCS JSON file."""
        try:
            memories = self._read_json_file(self.memory_table_name)

            for memory_data in memories:
                if memory_data.get("memory_id") == memory_id:
                    if not deserialize:
                        return memory_data

                    return UserMemory.from_dict(memory_data)

            return None
        except Exception as e:
            log_warning(f"Exception reading from memory file: {e}")
            return None

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
        """Get all memories from the GCS JSON file with filtering and pagination."""
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
            log_warning(f"Exception reading from memory file: {e}")
            return [] if deserialize else ([], 0)

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memory statistics."""
        try:
            memories = self._read_json_file(self.memory_table_name)
            user_stats = {}

            for memory in memories:
                user_id = memory.get("user_id")
                if user_id:
                    if user_id not in user_stats:
                        user_stats[user_id] = {"user_id": user_id, "total_memories": 0, "last_memory_updated_at": 0}
                    user_stats[user_id]["total_memories"] += 1
                    updated_at = memory.get("updated_at", 0)
                    if updated_at > user_stats[user_id]["last_memory_updated_at"]:
                        user_stats[user_id]["last_memory_updated_at"] = updated_at

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
            log_warning(f"Exception getting user memory stats: {e}")
            return [], 0

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the GCS JSON file."""
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
            log_error(f"Exception upserting user memory: {e}")
            return None

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

            return results

        except Exception as e:
            log_warning(f"Exception refreshing metrics: {e}")
            return None

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
            log_warning(f"Exception reading sessions for metrics: {e}")
            return []

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
            log_warning(f"Exception getting metrics: {e}")
            return [], None

    # -- Knowledge methods --
    def delete_knowledge_content(self, id: str):
        """Delete knowledge content by ID."""
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)
            knowledge_items = [item for item in knowledge_items if item.get("id") != id]
            self._write_json_file(self.knowledge_table_name, knowledge_items)
        except Exception as e:
            log_warning(f"Error deleting knowledge content: {e}")

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get knowledge content by ID."""
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)

            for item in knowledge_items:
                if item.get("id") == id:
                    return KnowledgeRow.model_validate(item)

            return None
        except Exception as e:
            log_warning(f"Error getting knowledge content: {e}")
            return None

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the GCS JSON file."""
        try:
            knowledge_items = self._read_json_file(self.knowledge_table_name)

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
            log_warning(f"Error getting knowledge contents: {e}")
            return [], 0

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the GCS JSON file."""
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
            log_warning(f"Error upserting knowledge row: {e}")
            return None

    # -- Eval methods --
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the GCS JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name, create_table_if_not_found=True)

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            eval_runs.append(eval_dict)
            self._write_json_file(self.eval_table_name, eval_runs)

            return eval_run
        except Exception as e:
            log_warning(f"Error creating eval run: {e}")
            return None

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the GCS JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)
            original_count = len(eval_runs)
            eval_runs = [run for run in eval_runs if run.get("run_id") != eval_run_id]

            if len(eval_runs) < original_count:
                self._write_json_file(self.eval_table_name, eval_runs)
                log_debug(f"Deleted eval run with ID: {eval_run_id}")
            else:
                log_warning(f"No eval run found with ID: {eval_run_id}")
        except Exception as e:
            log_warning(f"Error deleting eval run {eval_run_id}: {e}")

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the GCS JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)
            original_count = len(eval_runs)
            eval_runs = [run for run in eval_runs if run.get("run_id") not in eval_run_ids]

            deleted_count = original_count - len(eval_runs)
            if deleted_count > 0:
                self._write_json_file(self.eval_table_name, eval_runs)
                log_debug(f"Deleted {deleted_count} eval runs")
            else:
                log_warning(f"No eval runs found with IDs: {eval_run_ids}")
        except Exception as e:
            log_warning(f"Error deleting eval runs {eval_run_ids}: {e}")

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the GCS JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)

            for run_data in eval_runs:
                if run_data.get("run_id") == eval_run_id:
                    if not deserialize:
                        return run_data
                    return EvalRunRecord.model_validate(run_data)

            return None
        except Exception as e:
            log_warning(f"Exception getting eval run {eval_run_id}: {e}")
            return None

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
        """Get all eval runs from the GCS JSON file with filtering and pagination."""
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
            log_warning(f"Exception getting eval runs: {e}")
            return [] if deserialize else ([], 0)

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Rename an eval run in the GCS JSON file."""
        try:
            eval_runs = self._read_json_file(self.eval_table_name)

            for i, run_data in enumerate(eval_runs):
                if run_data.get("run_id") == eval_run_id:
                    run_data["name"] = name
                    run_data["updated_at"] = int(time.time())
                    eval_runs[i] = run_data
                    self._write_json_file(self.eval_table_name, eval_runs)

                    if not deserialize:
                        return run_data
                    return EvalRunRecord.model_validate(run_data)

            return None
        except Exception as e:
            log_warning(f"Error renaming eval run {eval_run_id}: {e}")
            return None
