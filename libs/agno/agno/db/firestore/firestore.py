import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.firestore.utils import (
    apply_pagination,
    apply_pagination_to_records,
    apply_sorting,
    apply_sorting_to_records,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_collection_indexes,
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
from agno.db.utils import deserialize_session_json_fields
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    from google.cloud.firestore import Client, FieldFilter  # type: ignore[import-untyped]
except ImportError:
    raise ImportError(
        "`google-cloud-firestore` not installed. Please install it using `pip install google-cloud-firestore`"
    )


class FirestoreDb(BaseDb):
    def __init__(
        self,
        db_client: Optional[Client] = None,
        project_id: Optional[str] = None,
        session_collection: Optional[str] = None,
        memory_collection: Optional[str] = None,
        metrics_collection: Optional[str] = None,
        eval_collection: Optional[str] = None,
        knowledge_collection: Optional[str] = None,
        culture_collection: Optional[str] = None,
        traces_collection: Optional[str] = None,
        spans_collection: Optional[str] = None,
        context_collection: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a Firestore database.

        Args:
            db_client (Optional[Client]): The Firestore client to use.
            project_id (Optional[str]): The GCP project ID for Firestore.
            session_collection (Optional[str]): Name of the collection to store sessions.
            memory_collection (Optional[str]): Name of the collection to store memories.
            metrics_collection (Optional[str]): Name of the collection to store metrics.
            eval_collection (Optional[str]): Name of the collection to store evaluation runs.
            knowledge_collection (Optional[str]): Name of the collection to store knowledge documents.
            culture_collection (Optional[str]): Name of the collection to store cultural knowledge.
            traces_collection (Optional[str]): Name of the collection to store traces.
            spans_collection (Optional[str]): Name of the collection to store spans.
            context_collection (Optional[str]): Name of the collection to store context items.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If neither project_id nor db_client is provided.
        """
        if id is None:
            seed = project_id or str(db_client)
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_collection,
            memory_table=memory_collection,
            metrics_table=metrics_collection,
            eval_table=eval_collection,
            knowledge_table=knowledge_collection,
            culture_table=culture_collection,
            traces_table=traces_collection,
            spans_table=spans_collection,
            context_table=context_collection,
        )

        _client: Optional[Client] = db_client
        if _client is None and project_id is not None:
            _client = Client(project=project_id)
        if _client is None:
            raise ValueError("One of project_id or db_client must be provided")

        self.project_id: Optional[str] = project_id
        self.db_client: Client = _client

    # -- DB methods --

    def table_exists(self, table_name: str) -> bool:
        """Check if a collection with the given name exists in the Firestore database.

        Args:
            table_name: Name of the collection to check

        Returns:
            bool: True if the collection exists in the database, False otherwise
        """
        return table_name in self.db_client.list_collections()

    def _get_collection(self, table_type: str, create_collection_if_not_found: Optional[bool] = True):
        """Get or create a collection based on table type.

        Args:
            table_type (str): The type of table to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            CollectionReference: The collection reference.
        """
        if table_type == "sessions":
            if self.session_table_name is None:
                raise ValueError("Session collection was not provided on initialization")
            self.session_collection = self._get_or_create_collection(
                collection_name=self.session_table_name,
                collection_type="sessions",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.session_collection

        if table_type == "memories":
            if self.memory_table_name is None:
                raise ValueError("Memory collection was not provided on initialization")
            self.memory_collection = self._get_or_create_collection(
                collection_name=self.memory_table_name,
                collection_type="memories",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.memory_collection

        if table_type == "metrics":
            if self.metrics_table_name is None:
                raise ValueError("Metrics collection was not provided on initialization")
            self.metrics_collection = self._get_or_create_collection(
                collection_name=self.metrics_table_name,
                collection_type="metrics",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.metrics_collection

        if table_type == "evals":
            if self.eval_table_name is None:
                raise ValueError("Eval collection was not provided on initialization")
            self.eval_collection = self._get_or_create_collection(
                collection_name=self.eval_table_name,
                collection_type="evals",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.eval_collection

        if table_type == "knowledge":
            if self.knowledge_table_name is None:
                raise ValueError("Knowledge collection was not provided on initialization")
            self.knowledge_collection = self._get_or_create_collection(
                collection_name=self.knowledge_table_name,
                collection_type="knowledge",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.knowledge_collection

        if table_type == "culture":
            if self.culture_table_name is None:
                raise ValueError("Culture collection was not provided on initialization")
            self.culture_collection = self._get_or_create_collection(
                collection_name=self.culture_table_name,
                collection_type="culture",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.culture_collection

        if table_type == "traces":
            if self.trace_table_name is None:
                raise ValueError("Traces collection was not provided on initialization")
            self.traces_collection = self._get_or_create_collection(
                collection_name=self.trace_table_name,
                collection_type="traces",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.traces_collection

        if table_type == "spans":
            # Ensure traces collection exists first (spans reference traces)
            if create_collection_if_not_found:
                self._get_collection("traces", create_collection_if_not_found=True)
            if self.span_table_name is None:
                raise ValueError("Spans collection was not provided on initialization")
            self.spans_collection = self._get_or_create_collection(
                collection_name=self.span_table_name,
                collection_type="spans",
                create_collection_if_not_found=create_collection_if_not_found,
            )
            return self.spans_collection

        if table_type == "context":
            if not hasattr(self, "context_collection"):
                if self.context_table_name is None:
                    raise ValueError("Context collection was not provided on initialization")
                self.context_collection = self._get_or_create_collection(
                    collection_name=self.context_table_name,
                    collection_type="context",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.context_collection

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_collection(
        self, collection_name: str, collection_type: str, create_collection_if_not_found: Optional[bool] = True
    ):
        """Get or create a collection with proper indexes.

        Args:
            collection_name (str): The name of the collection to get or create.
            collection_type (str): The type of collection to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Optional[CollectionReference]: The collection reference.
        """
        try:
            collection_ref = self.db_client.collection(collection_name)

            if not hasattr(self, f"_{collection_name}_initialized"):
                if not create_collection_if_not_found:
                    return None
                create_collection_indexes(self.db_client, collection_name, collection_type)
                setattr(self, f"_{collection_name}_initialized", True)

            return collection_ref

        except Exception as e:
            log_error(f"Error getting collection {collection_name}: {e}")
            raise

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session from the database.

        Args:
            session_id (str): The ID of the session to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            docs = query.stream()

            for doc in docs:
                doc.reference.delete()
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

            log_debug(f"No session found to delete with session_id: {session_id}")
            return False

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from the database.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            batch = self.db_client.batch()

            deleted_count = 0
            for session_id in session_ids:
                query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
                if user_id is not None:
                    query = query.where(filter=FieldFilter("user_id", "==", user_id))
                docs = query.stream()
                for doc in docs:
                    batch.delete(doc.reference)
                    deleted_count += 1

            batch.commit()

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
        """Read a session from the database.

        Args:
            session_id (str): The ID of the session to get.
            session_type (SessionType): The type of session to get.
            user_id (Optional[str]): The ID of the user to get the session for.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error reading the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            docs = query.stream()
            result = None
            for doc in docs:
                result = doc.to_dict()
                break

            if result is None:
                return None

            session = deserialize_session_json_fields(result)

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
            log_error(f"Exception reading session: {e}")
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
        """Get all sessions.

        Args:
            session_type (Optional[SessionType]): The type of session to get.
            user_id (Optional[str]): The ID of the user to get the session for.
            component_id (Optional[str]): The ID of the component to get the session for.
            session_name (Optional[str]): The name of the session to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter sessions by.
            end_timestamp (Optional[int]): The end timestamp to filter sessions by.
            limit (Optional[int]): The limit of the sessions to get.
            page (Optional[int]): The page number to get.
            sort_by (Optional[str]): The field to sort the sessions by.
            sort_order (Optional[str]): The order to sort the sessions by.
            deserialize (Optional[bool]): Whether to serialize the sessions. Defaults to True.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: List of session dictionaries and the total count

        Raises:
            Exception: If there is an error reading the sessions.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if session_type is not None:
                query = query.where(filter=FieldFilter("session_type", "==", session_type.value))
            if component_id is not None:
                if session_type == SessionType.AGENT:
                    query = query.where(filter=FieldFilter("agent_id", "==", component_id))
                elif session_type == SessionType.TEAM:
                    query = query.where(filter=FieldFilter("team_id", "==", component_id))
                elif session_type == SessionType.WORKFLOW:
                    query = query.where(filter=FieldFilter("workflow_id", "==", component_id))
            if start_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", ">=", start_timestamp))
            if end_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", "<=", end_timestamp))
            if session_name is not None:
                query = query.where(filter=FieldFilter("session_data.session_name", "==", session_name))

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Get all documents for counting before pagination
            all_docs = query.stream()
            all_records = [doc.to_dict() for doc in all_docs]

            if not all_records:
                return [] if deserialize else ([], 0)

            all_sessions_raw = [deserialize_session_json_fields(record) for record in all_records]

            # Get total count before pagination
            total_count = len(all_sessions_raw)

            # Apply pagination to the results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                sessions_raw = all_sessions_raw[start_index:end_index]
            elif limit is not None:
                sessions_raw = all_sessions_raw[:limit]
            else:
                sessions_raw = all_sessions_raw

            if not deserialize:
                return sessions_raw, total_count

            sessions: List[Union[AgentSession, TeamSession, WorkflowSession]] = []
            for session in sessions_raw:
                if session["session_type"] == SessionType.AGENT.value:
                    agent_session = AgentSession.from_dict(session)
                    if agent_session is not None:
                        sessions.append(agent_session)
                elif session["session_type"] == SessionType.TEAM.value:
                    team_session = TeamSession.from_dict(session)
                    if team_session is not None:
                        sessions.append(team_session)
                elif session["session_type"] == SessionType.WORKFLOW.value:
                    workflow_session = WorkflowSession.from_dict(session)
                    if workflow_session is not None:
                        sessions.append(workflow_session)

            if not sessions:
                return [] if deserialize else ([], 0)

            return sessions

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
        """Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error renaming the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions")

            query = collection_ref.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            docs = query.stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                return None

            # Check if session_data is stored as JSON string (legacy) or native map.
            # Legacy sessions stored session_data as a JSON string, but Firestore's dot notation
            # (e.g., "session_data.session_name") only works with native maps. Using dot notation
            # on a JSON string overwrites the entire field, causing data loss.
            # For legacy sessions, we use read-modify-write which also migrates them to native maps.
            current_doc = doc_ref.get()
            if not current_doc.exists:
                return None

            current_data = current_doc.to_dict()
            session_data = current_data.get("session_data") if current_data else None

            if session_data is None or isinstance(session_data, str):
                existing_session = self.get_session(session_id, session_type, user_id=user_id, deserialize=True)
                if existing_session is None:
                    return None
                existing_session = cast(Session, existing_session)
                if existing_session.session_data is None:
                    existing_session.session_data = {}
                existing_session.session_data["session_name"] = session_name
                return self.upsert_session(existing_session, deserialize=deserialize)

            # Native map format - use efficient dot notation update
            doc_ref.update({"session_data.session_name": session_name, "updated_at": int(time.time())})

            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()
            if result is None:
                return None
            deserialized_session = deserialize_session_json_fields(result)

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            if not deserialize:
                return deserialized_session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(deserialized_session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(deserialized_session)
            else:
                return WorkflowSession.from_dict(deserialized_session)

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in the database.

        Args:
            session (Session): The session to upsert.

        Returns:
            Optional[Session]: The upserted session.

        Raises:
            Exception: If there is an error upserting the session.
        """
        try:
            collection_ref = self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            session_dict = session.to_dict()

            if isinstance(session, AgentSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.AGENT.value,
                    "agent_id": session_dict.get("agent_id"),
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "agent_data": session_dict.get("agent_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

            elif isinstance(session, TeamSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.TEAM.value,
                    "team_id": session_dict.get("team_id"),
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "team_data": session_dict.get("team_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

            elif isinstance(session, WorkflowSession):
                record = {
                    "session_id": session_dict.get("session_id"),
                    "session_type": SessionType.WORKFLOW.value,
                    "workflow_id": session_dict.get("workflow_id"),
                    "user_id": session_dict.get("user_id"),
                    "runs": session_dict.get("runs"),
                    "workflow_data": session_dict.get("workflow_data"),
                    "session_data": session_dict.get("session_data"),
                    "summary": session_dict.get("summary"),
                    "metadata": session_dict.get("metadata"),
                    "created_at": session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

            # Find existing document or create new one
            docs = collection_ref.where(filter=FieldFilter("session_id", "==", record["session_id"])).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is not None:
                existing_doc = doc_ref.get()
                if existing_doc.exists:
                    existing_data = existing_doc.to_dict()
                    if (
                        existing_data
                        and existing_data.get("user_id") is not None
                        and existing_data.get("user_id") != record.get("user_id")
                    ):
                        return None
            else:
                # Create new document
                doc_ref = collection_ref.document()

            doc_ref.set(record, merge=True)

            # Get the updated document
            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()
            if result is None:
                return None
            deserialized_session = deserialize_session_json_fields(result)

            if not deserialize:
                return deserialized_session

            if isinstance(session, AgentSession):
                return AgentSession.from_dict(deserialized_session)
            elif isinstance(session, TeamSession):
                return TeamSession.from_dict(deserialized_session)
            else:
                return WorkflowSession.from_dict(deserialized_session)

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
                f"FirestoreDb doesn't support efficient bulk operations, falling back to individual upserts for {len(sessions)} sessions"
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
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            bool: True if the memory was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")

            # If user_id is provided, verify the memory belongs to the user before deleting
            if user_id is not None:
                docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                for doc in docs:
                    data = doc.to_dict()
                    if data.get("user_id") != user_id:
                        log_debug(f"Memory {memory_id} does not belong to user {user_id}")
                        return
                    doc.reference.delete()
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                    return
            else:
                docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                deleted_count = 0
                for doc in docs:
                    doc.reference.delete()
                    deleted_count += 1

                success = deleted_count > 0
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Raises:
            Exception: If there is an error deleting the memories.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            batch = self.db_client.batch()
            deleted_count = 0

            # If user_id is provided, filter memory_ids to only those belonging to the user
            if user_id is not None:
                for memory_id in memory_ids:
                    docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                    for doc in docs:
                        data = doc.to_dict()
                        if data.get("user_id") == user_id:
                            batch.delete(doc.reference)
                            deleted_count += 1
            else:
                for memory_id in memory_ids:
                    docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()
                    for doc in docs:
                        batch.delete(doc.reference)
                        deleted_count += 1

            batch.commit()

            if deleted_count == 0:
                log_info(f"No memories found with ids: {memory_ids}")
            else:
                log_info(f"Successfully deleted {deleted_count} memories")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")
            raise e

    def get_all_memory_topics(self, create_collection_if_not_found: Optional[bool] = True) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: The topics.

        Raises:
            Exception: If there is an error getting the topics.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            if collection_ref is None:
                return []

            docs = collection_ref.stream()

            all_topics = set()
            for doc in docs:
                data = doc.to_dict()
                topics = data.get("topics", [])
                if topics:
                    all_topics.update(topics)

            return [topic for topic in all_topics if topic]

        except Exception as e:
            log_error(f"Exception getting all memory topics: {e}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user (optional, for filtering).

        Returns:
            Optional[UserMemory]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error getting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            docs = collection_ref.where(filter=FieldFilter("memory_id", "==", memory_id)).stream()

            result = None
            for doc in docs:
                result = doc.to_dict()
                break

            if result is None:
                return None

            # Filter by user_id if provided
            if user_id and result.get("user_id") != user_id:
                return None

            if not deserialize:
                return result

            return UserMemory.from_dict(result)

        except Exception as e:
            log_error(f"Exception getting user memory: {e}")
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
        """Get all memories from the database as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to get the memories for.
            agent_id (Optional[str]): The ID of the agent to get the memories for.
            team_id (Optional[str]): The ID of the team to get the memories for.
            topics (Optional[List[str]]): The topics to filter the memories by.
            search_content (Optional[str]): The content to filter the memories by.
            limit (Optional[int]): The limit of the memories to get.
            page (Optional[int]): The page number to get.
            sort_by (Optional[str]): The field to sort the memories by.
            sort_order (Optional[str]): The order to sort the memories by.
            deserialize (Optional[bool]): Whether to serialize the memories. Defaults to True.
            create_table_if_not_found: Whether to create the index if it doesn't exist.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories and the total count.

        Raises:
            Exception: If there is an error getting the memories.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if topics is not None and len(topics) > 0:
                query = query.where(filter=FieldFilter("topics", "array_contains_any", topics))
            if search_content is not None:
                query = query.where(filter=FieldFilter("memory", "==", search_content))

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Get all documents
            docs = query.stream()
            all_records = [doc.to_dict() for doc in docs]

            total_count = len(all_records)

            # Apply pagination to the filtered results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                records = all_records[start_index:end_index]
            elif limit is not None:
                records = all_records[:limit]
            else:
                records = all_records
            if not deserialize:
                return records, total_count

            return [UserMemory.from_dict(record) for record in records]

        except Exception as e:
            log_error(f"Exception getting user memories: {e}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The limit of the memories to get.
            page (Optional[int]): The page number to get.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories stats and the total count.

        Raises:
            Exception: If there is an error getting the memories stats.
        """
        try:
            collection_ref = self._get_collection(table_type="memories")

            if user_id is not None:
                query = collection_ref.where(filter=FieldFilter("user_id", "==", user_id))
            else:
                query = collection_ref.where(filter=FieldFilter("user_id", "!=", None))

            docs = query.stream()

            user_stats = {}
            for doc in docs:
                data = doc.to_dict()
                current_user_id = data.get("user_id")
                if current_user_id:
                    if current_user_id not in user_stats:
                        user_stats[current_user_id] = {
                            "user_id": current_user_id,
                            "total_memories": 0,
                            "last_memory_updated_at": 0,
                        }
                    user_stats[current_user_id]["total_memories"] += 1
                    updated_at = data.get("updated_at", 0)
                    if updated_at > user_stats[current_user_id]["last_memory_updated_at"]:
                        user_stats[current_user_id]["last_memory_updated_at"] = updated_at

            # Convert to list and sort
            formatted_results = list(user_stats.values())
            formatted_results.sort(key=lambda x: x["last_memory_updated_at"], reverse=True)

            total_count = len(formatted_results)

            # Apply pagination
            if limit is not None:
                start_idx = 0
                if page is not None:
                    start_idx = (page - 1) * limit
                formatted_results = formatted_results[start_idx : start_idx + limit]

            return formatted_results, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {e}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The memory to upsert.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error upserting the memory.
        """
        try:
            collection_ref = self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection_ref is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            update_doc = memory.to_dict()
            update_doc["updated_at"] = int(time.time())

            # Find existing document or create new one
            docs = collection_ref.where("memory_id", "==", memory.memory_id).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                doc_ref = collection_ref.document()

            doc_ref.set(update_doc, merge=True)

            if not deserialize:
                return update_doc

            return UserMemory.from_dict(update_doc)

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
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
                f"FirestoreDb doesn't support efficient bulk operations, falling back to individual upserts for {len(memories)} memories"
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
            collection_ref = self._get_collection(table_type="memories")

            # Get all documents in the collection
            docs = collection_ref.stream()

            # Delete all documents in batches
            batch = self.db_client.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1

                # Firestore batch has a limit of 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

        except Exception as e:
            log_error(f"Exception deleting all memories: {e}")
            raise e

    # -- Cultural Knowledge methods --
    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection_ref = self._get_collection(table_type="culture")

            # Get all documents in the collection
            docs = collection_ref.stream()

            # Delete all documents in batches
            batch = self.db_client.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1

                # Firestore batch has a limit of 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

        except Exception as e:
            log_error(f"Exception deleting all cultural knowledge: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete cultural knowledge by ID.

        Args:
            id (str): The ID of the cultural knowledge to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection_ref = self._get_collection(table_type="culture")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).stream()

            for doc in docs:
                doc.reference.delete()
                log_debug(f"Deleted cultural knowledge with ID: {id}")

        except Exception as e:
            log_error(f"Error deleting cultural knowledge: {e}")
            raise e

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
        try:
            collection_ref = self._get_collection(table_type="culture")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).limit(1).stream()

            for doc in docs:
                result = doc.to_dict()
                if not deserialize:
                    return result
                return deserialize_cultural_knowledge_from_db(result)

            return None

        except Exception as e:
            log_error(f"Error getting cultural knowledge: {e}")
            raise e

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
        try:
            collection_ref = self._get_collection(table_type="culture")

            # Build query with filters
            query = collection_ref
            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))

            # Get all matching documents
            docs = query.stream()
            results = [doc.to_dict() for doc in docs]

            # Apply name filter (Firestore doesn't support regex in queries)
            if name is not None:
                results = [r for r in results if name.lower() in r.get("name", "").lower()]

            total_count = len(results)

            # Apply sorting and pagination to in-memory results
            sorted_results = apply_sorting_to_records(records=results, sort_by=sort_by, sort_order=sort_order)
            paginated_results = apply_pagination_to_records(records=sorted_results, limit=limit, page=page)

            if not deserialize:
                return paginated_results, total_count

            return [deserialize_cultural_knowledge_from_db(item) for item in paginated_results]

        except Exception as e:
            log_error(f"Error getting all cultural knowledge: {e}")
            raise e

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert cultural knowledge in Firestore.

        Args:
            cultural_knowledge (CulturalKnowledge): The cultural knowledge to upsert.
            deserialize (Optional[bool]): Whether to deserialize the result. Defaults to True.

        Returns:
            Optional[Union[CulturalKnowledge, Dict[str, Any]]]: The upserted cultural knowledge.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection_ref = self._get_collection(table_type="culture", create_collection_if_not_found=True)

            # Serialize content, categories, and notes into a dict for DB storage
            content_dict = serialize_cultural_knowledge_for_db(cultural_knowledge)

            # Create the update document with serialized content
            update_doc = {
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

            # Find and update or create new document
            docs = collection_ref.where(filter=FieldFilter("id", "==", cultural_knowledge.id)).limit(1).stream()

            doc_found = False
            for doc in docs:
                doc.reference.set(update_doc)
                doc_found = True
                break

            if not doc_found:
                collection_ref.add(update_doc)

            if not deserialize:
                return update_doc

            return deserialize_cultural_knowledge_from_db(update_doc)

        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions of all types for metrics calculation."""
        try:
            collection_ref = self._get_collection(table_type="sessions")

            query = collection_ref
            if start_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", ">=", start_timestamp))
            if end_timestamp is not None:
                query = query.where(filter=FieldFilter("created_at", "<=", end_timestamp))

            docs = query.stream()
            results = []
            for doc in docs:
                data = doc.to_dict()
                # Only include required fields for metrics
                result = {
                    "user_id": data.get("user_id"),
                    "session_data": data.get("session_data"),
                    "runs": data.get("runs"),
                    "created_at": data.get("created_at"),
                    "session_type": data.get("session_type"),
                }
                results.append(result)

            return results

        except Exception as e:
            log_error(f"Exception getting all sessions for metrics calculation: {e}")
            raise e

    def _get_metrics_calculation_starting_date(self, collection_ref) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        try:
            query = collection_ref.order_by("date", direction="DESCENDING").limit(1)
            docs = query.stream()

            for doc in docs:
                data = doc.to_dict()
                result_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                if data.get("completed"):
                    return result_date + timedelta(days=1)
                else:
                    return result_date

            # No metrics records. Return the date of the first recorded session.
            first_session_result = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
            first_session_date = None

            if isinstance(first_session_result, list) and len(first_session_result) > 0:
                first_session_date = first_session_result[0].created_at  # type: ignore
            elif isinstance(first_session_result, tuple) and len(first_session_result[0]) > 0:
                first_session_date = first_session_result[0][0].get("created_at")

            if first_session_date is None:
                return None

            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        except Exception as e:
            log_error(f"Exception getting metrics calculation starting date: {e}")
            raise e

    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            collection_ref = self._get_collection(table_type="metrics", create_collection_if_not_found=True)

            starting_date = self._get_metrics_calculation_starting_date(collection_ref)
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
            metrics_records = []

            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)
                metrics_records.append(metrics_record)

            if metrics_records:
                results = bulk_upsert_metrics(collection_ref, metrics_records)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Exception calculating metrics: {e}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range."""
        try:
            collection_ref = self._get_collection(table_type="metrics")
            if collection_ref is None:
                return [], None

            query = collection_ref
            if starting_date:
                query = query.where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
            if ending_date:
                query = query.where(filter=FieldFilter("date", "<=", ending_date.isoformat()))

            docs = query.stream()
            records = []
            latest_updated_at = 0

            for doc in docs:
                data = doc.to_dict()
                records.append(data)
                updated_at = data.get("updated_at", 0)
                if updated_at > latest_updated_at:
                    latest_updated_at = updated_at

            if not records:
                return [], None

            return records, latest_updated_at

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
            collection_ref = self._get_collection(table_type="knowledge")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).stream()

            for doc in docs:
                doc.reference.delete()

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
            collection_ref = self._get_collection(table_type="knowledge")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).stream()

            for doc in docs:
                data = doc.to_dict()
                return KnowledgeRow.model_validate(data)

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
            collection_ref = self._get_collection(table_type="knowledge")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply linked_to filter if provided
            if linked_to is not None:
                query = query.where("linked_to", "==", linked_to)

            # Apply sorting
            query = apply_sorting(query, sort_by, sort_order)

            # Apply pagination
            query = apply_pagination(query, limit, page)

            docs = query.stream()
            records = []
            for doc in docs:
                records.append(doc.to_dict())

            knowledge_rows = [KnowledgeRow.model_validate(record) for record in records]
            total_count = len(knowledge_rows)  # Simplified count

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            collection_ref = self._get_collection(table_type="knowledge", create_collection_if_not_found=True)
            if collection_ref is None:
                return None

            update_doc = knowledge_row.model_dump()

            # Find existing document or create new one
            docs = collection_ref.where(filter=FieldFilter("id", "==", knowledge_row.id)).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                doc_ref = collection_ref.document()

            doc_ref.set(update_doc, merge=True)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {e}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            collection_ref = self._get_collection(table_type="evals", create_collection_if_not_found=True)

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            doc_ref = collection_ref.document()
            doc_ref.set(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database."""
        try:
            collection_ref = self._get_collection(table_type="evals")
            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()

            deleted_count = 0
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1

            if deleted_count == 0:
                log_info(f"No eval run found with ID: {eval_run_id}")
            else:
                log_info(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): The IDs of the eval runs to delete.

        Raises:
            Exception: If there is an error deleting the eval runs.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            batch = self.db_client.batch()
            deleted_count = 0

            for eval_run_id in eval_run_ids:
                docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()
                for doc in docs:
                    batch.delete(doc.reference)
                    deleted_count += 1

            batch.commit()

            if deleted_count == 0:
                log_info(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_info(f"Deleted {deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise e

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
            Exception: If there is an error getting the eval run.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if not collection_ref:
                return None

            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()

            eval_run_raw = None
            for doc in docs:
                eval_run_raw = doc.to_dict()
                break

            if not eval_run_raw:
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
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        try:
            collection_ref = self._get_collection(table_type="evals")
            if collection_ref is None:
                return [] if deserialize else ([], 0)

            query = collection_ref

            if agent_id is not None:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id is not None:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id is not None:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if model_id is not None:
                query = query.where(filter=FieldFilter("model_id", "==", model_id))
            if eval_type is not None and len(eval_type) > 0:
                eval_values = [et.value for et in eval_type]
                query = query.where(filter=FieldFilter("eval_type", "in", eval_values))
            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    query = query.where(filter=FieldFilter("agent_id", "!=", None))
                elif filter_type == EvalFilterType.TEAM:
                    query = query.where(filter=FieldFilter("team_id", "!=", None))
                elif filter_type == EvalFilterType.WORKFLOW:
                    query = query.where(filter=FieldFilter("workflow_id", "!=", None))

            # Apply default sorting by created_at desc if no sort parameters provided
            if sort_by is None:
                from google.cloud.firestore import Query

                query = query.order_by("created_at", direction=Query.DESCENDING)
            else:
                query = apply_sorting(query, sort_by, sort_order)

            # Get all documents for counting before pagination
            all_docs = query.stream()
            all_records = [doc.to_dict() for doc in all_docs]

            if not all_records:
                return [] if deserialize else ([], 0)

            # Get total count before pagination
            total_count = len(all_records)

            # Apply pagination to the results
            if limit is not None and page is not None:
                start_index = (page - 1) * limit
                end_index = start_index + limit
                records = all_records[start_index:end_index]
            elif limit is not None:
                records = all_records[:limit]
            else:
                records = all_records

            if not deserialize:
                return records, total_count

            return [EvalRunRecord.model_validate(row) for row in records]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            raise e

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
        try:
            collection_ref = self._get_collection(table_type="evals")
            if not collection_ref:
                return None

            docs = collection_ref.where(filter=FieldFilter("run_id", "==", eval_run_id)).stream()
            doc_ref = next((doc.reference for doc in docs), None)

            if doc_ref is None:
                return None

            doc_ref.update({"name": name, "updated_at": int(time.time())})

            updated_doc = doc_ref.get()
            if not updated_doc.exists:
                return None

            result = updated_doc.to_dict()

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not result or not deserialize:
                return result

            return EvalRunRecord.model_validate(result)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {e}")
            raise e

    # --- Traces ---
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            collection_ref = self._get_collection(table_type="traces", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            # Check if trace already exists
            docs = collection_ref.where(filter=FieldFilter("trace_id", "==", trace.trace_id)).limit(1).stream()
            existing_doc = None
            existing_data = None
            for doc in docs:
                existing_doc = doc
                existing_data = doc.to_dict()
                break

            if existing_data and existing_doc is not None:
                # Update existing trace
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
                    existing_data.get("workflow_id"),
                    existing_data.get("team_id"),
                    existing_data.get("agent_id"),
                    existing_data.get("name", ""),
                )
                new_level = get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)
                should_update_name = new_level > existing_level

                # Parse existing start_time to calculate correct duration
                existing_start_time_str = existing_data.get("start_time")
                if isinstance(existing_start_time_str, str):
                    existing_start_time = datetime.fromisoformat(existing_start_time_str.replace("Z", "+00:00"))
                else:
                    existing_start_time = trace.start_time

                recalculated_duration_ms = int((trace.end_time - existing_start_time).total_seconds() * 1000)

                update_values: Dict[str, Any] = {
                    "end_time": trace.end_time.isoformat(),
                    "duration_ms": recalculated_duration_ms,
                    "status": trace.status,
                }

                if should_update_name:
                    update_values["name"] = trace.name

                # Update context fields only if new value is not None
                if trace.run_id is not None:
                    update_values["run_id"] = trace.run_id
                if trace.session_id is not None:
                    update_values["session_id"] = trace.session_id
                if trace.user_id is not None:
                    update_values["user_id"] = trace.user_id
                if trace.agent_id is not None:
                    update_values["agent_id"] = trace.agent_id
                if trace.team_id is not None:
                    update_values["team_id"] = trace.team_id
                if trace.workflow_id is not None:
                    update_values["workflow_id"] = trace.workflow_id

                existing_doc.reference.update(update_values)
            else:
                # Create new trace with initialized counters
                trace_dict = trace.to_dict()
                trace_dict["total_spans"] = 0
                trace_dict["error_count"] = 0
                collection_ref.add(trace_dict)

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
            from agno.tracing.schemas import Trace

            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return None

            if trace_id:
                docs = collection_ref.where(filter=FieldFilter("trace_id", "==", trace_id)).limit(1).stream()
            elif run_id:
                from google.cloud.firestore import Query

                docs = (
                    collection_ref.where(filter=FieldFilter("run_id", "==", run_id))
                    .order_by("start_time", direction=Query.DESCENDING)
                    .limit(1)
                    .stream()
                )
            else:
                log_debug("get_trace called without any filter parameters")
                return None

            for doc in docs:
                trace_data = doc.to_dict()
                # Use stored values (default to 0 if not present)
                trace_data.setdefault("total_spans", 0)
                trace_data.setdefault("error_count", 0)
                return Trace.from_dict(trace_data)

            return None

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
        try:
            from agno.tracing.schemas import Trace

            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply filters
            if run_id:
                query = query.where(filter=FieldFilter("run_id", "==", run_id))
            if session_id:
                query = query.where(filter=FieldFilter("session_id", "==", session_id))
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if status:
                query = query.where(filter=FieldFilter("status", "==", status))
            if start_time:
                query = query.where(filter=FieldFilter("start_time", ">=", start_time.isoformat()))
            if end_time:
                query = query.where(filter=FieldFilter("end_time", "<=", end_time.isoformat()))

            # Get all matching documents
            docs = query.stream()
            all_records = [doc.to_dict() for doc in docs]

            # Sort by start_time descending
            all_records.sort(key=lambda x: x.get("start_time", ""), reverse=True)

            # Get total count
            total_count = len(all_records)

            # Apply pagination
            if limit and page:
                offset = (page - 1) * limit
                paginated_records = all_records[offset : offset + limit]
            elif limit:
                paginated_records = all_records[:limit]
            else:
                paginated_records = all_records

            # Convert to Trace objects with stored span counts
            traces = []
            for trace_data in paginated_records:
                trace_data.setdefault("total_spans", 0)
                trace_data.setdefault("error_count", 0)
                traces.append(Trace.from_dict(trace_data))

            return traces, total_count

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
            collection_ref = self._get_collection(table_type="traces")
            if collection_ref is None:
                return [], 0

            query = collection_ref

            # Apply filters
            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
            if team_id:
                query = query.where(filter=FieldFilter("team_id", "==", team_id))
            if workflow_id:
                query = query.where(filter=FieldFilter("workflow_id", "==", workflow_id))
            if start_time:
                query = query.where(filter=FieldFilter("created_at", ">=", start_time.isoformat()))
            if end_time:
                query = query.where(filter=FieldFilter("created_at", "<=", end_time.isoformat()))

            # Get all matching documents
            docs = query.stream()

            # Aggregate by session_id
            session_stats: Dict[str, Dict[str, Any]] = {}
            for doc in docs:
                trace_data = doc.to_dict()
                session_id = trace_data.get("session_id")
                if not session_id:
                    continue

                if session_id not in session_stats:
                    session_stats[session_id] = {
                        "session_id": session_id,
                        "user_id": trace_data.get("user_id"),
                        "agent_id": trace_data.get("agent_id"),
                        "team_id": trace_data.get("team_id"),
                        "workflow_id": trace_data.get("workflow_id"),
                        "total_traces": 0,
                        "first_trace_at": trace_data.get("created_at"),
                        "last_trace_at": trace_data.get("created_at"),
                    }

                session_stats[session_id]["total_traces"] += 1

                created_at = trace_data.get("created_at")
                if (
                    created_at
                    and session_stats[session_id]["first_trace_at"]
                    and session_stats[session_id]["last_trace_at"]
                ):
                    if created_at < session_stats[session_id]["first_trace_at"]:
                        session_stats[session_id]["first_trace_at"] = created_at
                    if created_at > session_stats[session_id]["last_trace_at"]:
                        session_stats[session_id]["last_trace_at"] = created_at

            # Convert to list and sort by last_trace_at descending
            stats_list = list(session_stats.values())
            stats_list.sort(key=lambda x: x.get("last_trace_at", ""), reverse=True)

            # Convert datetime strings to datetime objects
            for stat in stats_list:
                first_trace_at = stat["first_trace_at"]
                last_trace_at = stat["last_trace_at"]
                if isinstance(first_trace_at, str):
                    stat["first_trace_at"] = datetime.fromisoformat(first_trace_at.replace("Z", "+00:00"))
                if isinstance(last_trace_at, str):
                    stat["last_trace_at"] = datetime.fromisoformat(last_trace_at.replace("Z", "+00:00"))

            # Get total count
            total_count = len(stats_list)

            # Apply pagination
            if limit and page:
                offset = (page - 1) * limit
                paginated_stats = stats_list[offset : offset + limit]
            elif limit:
                paginated_stats = stats_list[:limit]
            else:
                paginated_stats = stats_list

            return paginated_stats, total_count

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
            collection_ref = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            span_dict = span.to_dict()
            # Serialize attributes as JSON string
            if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                span_dict["attributes"] = json.dumps(span_dict["attributes"])

            collection_ref.add(span_dict)

            # Increment total_spans and error_count on trace
            traces_collection = self._get_collection(table_type="traces")
            if traces_collection:
                try:
                    docs = (
                        traces_collection.where(filter=FieldFilter("trace_id", "==", span.trace_id)).limit(1).stream()
                    )
                    for doc in docs:
                        trace_data = doc.to_dict()
                        current_total = trace_data.get("total_spans", 0)
                        current_errors = trace_data.get("error_count", 0)

                        update_values = {"total_spans": current_total + 1}
                        if span.status_code == "ERROR":
                            update_values["error_count"] = current_errors + 1

                        doc.reference.update(update_values)
                        break
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

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
            collection_ref = self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection_ref is None:
                return

            # Firestore batch has a limit of 500 operations
            batch = self.db_client.batch()
            batch_count = 0

            for span in spans:
                span_dict = span.to_dict()
                # Serialize attributes as JSON string
                if "attributes" in span_dict and isinstance(span_dict["attributes"], dict):
                    span_dict["attributes"] = json.dumps(span_dict["attributes"])

                doc_ref = collection_ref.document()
                batch.set(doc_ref, span_dict)
                batch_count += 1

                # Commit batch if reaching limit
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

            # Update trace with total_spans and error_count
            trace_id = spans[0].trace_id
            spans_count = len(spans)
            error_count = sum(1 for s in spans if s.status_code == "ERROR")

            traces_collection = self._get_collection(table_type="traces")
            if traces_collection:
                try:
                    docs = traces_collection.where(filter=FieldFilter("trace_id", "==", trace_id)).limit(1).stream()
                    for doc in docs:
                        trace_data = doc.to_dict()
                        current_total = trace_data.get("total_spans", 0)
                        current_errors = trace_data.get("error_count", 0)

                        doc.reference.update(
                            {
                                "total_spans": current_total + spans_count,
                                "error_count": current_errors + error_count,
                            }
                        )
                        break
                except Exception as update_error:
                    log_debug(f"Could not update trace span counts: {update_error}")

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

            collection_ref = self._get_collection(table_type="spans")
            if collection_ref is None:
                return None

            docs = collection_ref.where(filter=FieldFilter("span_id", "==", span_id)).limit(1).stream()

            for doc in docs:
                span_data = doc.to_dict()
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                return Span.from_dict(span_data)

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

            collection_ref = self._get_collection(table_type="spans")
            if collection_ref is None:
                return []

            query = collection_ref

            if trace_id:
                query = query.where(filter=FieldFilter("trace_id", "==", trace_id))
            if parent_span_id:
                query = query.where(filter=FieldFilter("parent_span_id", "==", parent_span_id))

            if limit:
                query = query.limit(limit)

            docs = query.stream()

            spans = []
            for doc in docs:
                span_data = doc.to_dict()
                # Deserialize attributes from JSON string
                if "attributes" in span_data and isinstance(span_data["attributes"], str):
                    span_data["attributes"] = json.loads(span_data["attributes"])
                spans.append(Span.from_dict(span_data))

            return spans

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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

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
        raise NotImplementedError("Learning methods not yet implemented for FirestoreDb")

    # -- Context methods --

    def clear_context_items(self) -> None:
        """Delete all context items from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection_ref = self._get_collection(table_type="context")

            # Get all documents in the collection
            docs = collection_ref.stream()

            # Delete all documents in batches
            batch = self.db_client.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1

                # Firestore batch has a limit of 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db_client.batch()
                    batch_count = 0

            # Commit remaining operations
            if batch_count > 0:
                batch.commit()

        except Exception as e:
            log_error(f"Exception deleting all context items: {e}")
            raise e

    def delete_context_item(self, id: str) -> None:
        """Delete a context item by ID.

        Args:
            id (str): The ID of the context item to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection_ref = self._get_collection(table_type="context")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).stream()

            for doc in docs:
                doc.reference.delete()
                log_debug(f"Deleted context item with ID: {id}")

        except Exception as e:
            log_error(f"Error deleting context item: {e}")
            raise e

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
        try:
            collection_ref = self._get_collection(table_type="context")
            docs = collection_ref.where(filter=FieldFilter("id", "==", id)).limit(1).stream()

            for doc in docs:
                result = doc.to_dict()
                if not deserialize:
                    return result
                return ContextItem.from_dict(result)

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
        """Get all context items with filtering and pagination.

        Args:
            name (Optional[str]): Filter by name (case-insensitive partial match).
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
        try:
            collection_ref = self._get_collection(table_type="context")

            # Get all documents
            query = collection_ref
            docs = query.stream()
            results = [doc.to_dict() for doc in docs]

            # Apply name filter (Firestore doesn't support regex in queries)
            if name is not None:
                results = [r for r in results if name.lower() in r.get("name", "").lower()]

            # Apply metadata filter
            if metadata is not None:
                filtered_results = []
                for r in results:
                    item_metadata = r.get("metadata", {}) or {}
                    if all(item_metadata.get(k) == v for k, v in metadata.items()):
                        filtered_results.append(r)
                results = filtered_results

            total_count = len(results)

            # Apply sorting and pagination to in-memory results
            sorted_results = apply_sorting_to_records(records=results, sort_by=sort_by, sort_order=sort_order)
            paginated_results = apply_pagination_to_records(records=sorted_results, limit=limit, page=page)

            if not deserialize:
                return paginated_results, total_count

            return [ContextItem.from_dict(item) for item in paginated_results]

        except Exception as e:
            log_error(f"Error getting all context items: {e}")
            raise e

    def upsert_context_item(
        self, context_item: ContextItem, deserialize: Optional[bool] = True
    ) -> Optional[Union[ContextItem, Dict[str, Any]]]:
        """Upsert a context item in Firestore.

        Args:
            context_item (ContextItem): The context item to upsert.
            deserialize (Optional[bool]): Whether to deserialize the result. Defaults to True.

        Returns:
            Optional[Union[ContextItem, Dict[str, Any]]]: The upserted context item.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection_ref = self._get_collection(table_type="context", create_collection_if_not_found=True)

            if context_item.id is None:
                context_item.id = str(uuid4())

            # Create the update document
            update_doc = {
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

            # Find and update or create new document
            docs = collection_ref.where(filter=FieldFilter("id", "==", context_item.id)).limit(1).stream()

            doc_found = False
            for doc in docs:
                doc.reference.set(update_doc)
                doc_found = True
                break

            if not doc_found:
                collection_ref.add(update_doc)

            if not deserialize:
                return update_doc

            return ContextItem.from_dict(update_doc)

        except Exception as e:
            log_error(f"Error upserting context item: {e}")
            raise e
