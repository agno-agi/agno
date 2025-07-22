from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union
import time
from uuid import UUID

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger

try:
    from google.api_core import exceptions as google_exceptions
    from google.cloud.firestore_v1 import (
        Client,
        CollectionReference,
        DocumentReference,
        Query,
    )
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    raise ImportError("`firestore` not installed. Please install it with `pip install google-cloud-firestore`")


class FirestoreStorage(Storage):
    def __init__(
        self,
        collection_name: str,
        db_name: Optional[str] = "(default)",
        project_id: Optional[str] = None,
        client: Optional[Client] = None,
        mode: Optional[Literal["agent", "team", "workflow", "workflow_v2"]] = "agent",
    ):
        super().__init__(mode)
        self.collection_name = collection_name
        self.db_name = db_name
        self.project_id = project_id

        # Initialize Firestore client
        self._client = client
        if self._client is None:
            self._client = self._initialize_client()

        # Get collection reference
        self.collection: CollectionReference = self._client.collection(self.collection_name)
        log_debug(f"Created FirestoreStorage with collection: '{self.collection_name}'")

    def _initialize_client(self) -> Client:
        """Initialize and return a Firestore client with proper error handling."""
        try:
            client = Client(database=self.db_name, project=self.project_id)
            log_debug(f"Firestore client initialized with database: '{self.db_name}'")
            return client
        except google_exceptions.Unauthenticated as e:
            raise ImportError(
                "Failed to authenticate with Google Cloud. Please set up authentication:\n"
                "1. Run: gcloud auth application-default login\n"
                "2. Or set GOOGLE_APPLICATION_CREDENTIALS environment variable"
            ) from e
        except google_exceptions.PermissionDenied as e:
            raise ImportError(
                "Permission denied when accessing Firestore. Please ensure:\n"
                "1. Your service account has the 'Cloud Datastore User' role\n"
                "2. The Firestore API is enabled for your project"
            ) from e
        except Exception as e:
            raise ImportError(f"Failed to initialize Firestore client: {e}") from e

    def _delete_document(self, document: DocumentReference) -> None:
        """Recursively delete a document and all its subcollections."""
        log_debug(f"Deleting document: {document.path}")
        for collection in document.collections():
            self._delete_collection(collection)
        document.delete()

    def _delete_collection(self, collection: CollectionReference) -> None:
        """Recursively delete all documents in a collection."""
        for document in collection.list_documents():
            self._delete_document(document)

    def _build_query(
        self, base_query: CollectionReference, user_id: Optional[str] = None, entity_id: Optional[str] = None
    ) -> Union[Query, CollectionReference]:
        """Build a Firestore query with optional filters."""
        query: Union[Query, CollectionReference] = base_query

        if user_id:
            query = query.where(filter=FieldFilter("user_id", "==", user_id))

        if entity_id:
            if self.mode == "agent":
                query = query.where(filter=FieldFilter("agent_id", "==", entity_id))
            elif self.mode == "team":
                query = query.where(filter=FieldFilter("team_id", "==", entity_id))
            elif self.mode == "workflow":
                query = query.where(filter=FieldFilter("workflow_id", "==", entity_id))
            elif self.mode == "workflow_v2":
                query = query.where(filter=FieldFilter("workflow_id", "==", entity_id))

        return query

    def _parse_session(self, doc_data: Optional[Dict[str, Any]]) -> Optional[Session]:
        """Parse document data into appropriate Session type."""
        if not doc_data:
            return None

        try:
            if self.mode == "agent":
                return AgentSession.from_dict(doc_data)
            elif self.mode == "team":
                return TeamSession.from_dict(doc_data)
            elif self.mode == "workflow":
                return WorkflowSession.from_dict(doc_data)
            elif self.mode == "workflow_v2":
                return WorkflowSessionV2.from_dict(doc_data)
        except Exception as e:
            logger.error(f"Error parsing session data: {e}")
            return None

    def create(self) -> None:
        """
        Create storage if it doesn't exist.
        For Firestore, this is a no-operation as collections are created automatically.
        """
        try:
            if self._client:
                list(self._client.collections())
            log_debug("Firestore connection successful")
        except Exception as e:
            logger.error(f"Could not connect to Firestore: {e}")
            raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Read a session from Firestore."""
        try:
            query = self.collection.where(filter=FieldFilter("session_id", "==", session_id))

            if user_id:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            docs = query.get()
            for doc in docs:
                doc_dict = doc.to_dict()
                if doc_dict:
                    return self._parse_session(doc_dict)

            return None
        except Exception as e:
            logger.error(f"Error reading session: {e}")
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """Get all session IDs, optionally filtered by user_id and/or entity_id."""
        try:
            query = self._build_query(self.collection, user_id, entity_id)
            docs = query.get()

            # Sort by created_at descending and extract session IDs
            session_ids: List[str] = []
            doc_list = []
            for doc in docs:
                doc_data = doc.to_dict()
                if doc_data:
                    doc_list.append(doc_data)

            sorted_docs = sorted(doc_list, key=lambda x: x.get("created_at", 0), reverse=True)

            for doc_data in sorted_docs:
                session_id = doc_data.get("session_id")
                if session_id:
                    session_ids.append(session_id)

            return session_ids
        except Exception as e:
            logger.error(f"Error getting session IDs: {e}")
            return []

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """Get all sessions, optionally filtered by user_id and/or entity_id."""
        sessions: List[Session] = []
        try:
            query = self._build_query(self.collection, user_id, entity_id)
            docs = query.get()

            # Sort by created_at descending
            doc_list = []
            for doc in docs:
                doc_data = doc.to_dict()
                if doc_data:
                    doc_list.append(doc_data)

            sorted_docs = sorted(doc_list, key=lambda x: x.get("created_at", 0), reverse=True)

            for doc_data in sorted_docs:
                session = self._parse_session(doc_data)
                if session:
                    sessions.append(session)

            return sessions
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """Get the last N sessions, ordered by created_at descending."""
        sessions: List[Session] = []
        try:
            query = self._build_query(self.collection, user_id, entity_id)
            docs = query.get()

            # Sort by created_at descending
            doc_list = []
            for doc in docs:
                doc_data = doc.to_dict()
                if doc_data:
                    doc_list.append(doc_data)

            sorted_docs = sorted(doc_list, key=lambda x: x.get("created_at", 0), reverse=True)

            # Apply limit
            if limit is not None:
                sorted_docs = sorted_docs[:limit]

            for doc_data in sorted_docs:
                session = self._parse_session(doc_data)
                if session:
                    sessions.append(session)

            return sessions
        except Exception as e:
            logger.error(f"Error getting recent sessions: {e}")
            return []

    def upsert(self, session: Session, create_and_retry: bool = True) -> Optional[Session]:
        """Insert or update a session in Firestore."""
        try:
            # Prepare session data
            session_dict = session.to_dict()
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            if isinstance(session.session_id, UUID):
                session_dict["session_id"] = str(session.session_id)

            # Add timestamps
            session_dict["updated_at"] = timestamp

            # Get document reference
            doc_ref = self.collection.document(session_dict["session_id"])
            doc = doc_ref.get()

            # Add created_at for new documents
            if not doc.exists:
                session_dict["created_at"] = timestamp

            # Save to Firestore
            doc_ref.set(session_dict)

            # Return the updated session
            return self.read(session_id=session_dict["session_id"])

        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None) -> None:
        """Delete a session from Firestore."""
        if session_id is None:
            logger.warning("No session_id provided for deletion")
            return

        try:
            self.collection.document(session_id).delete()
            log_debug(f"Deleted session: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop all sessions from storage."""
        try:
            self._delete_collection(self.collection)
            log_debug(f"Dropped all sessions in collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Error dropping collection: {e}")

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema of the storage.
        For Firestore, this is a no-op as it's schema-less.
        """
        pass

    def get_workflow_run_status(self, session_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """Fast retrieval of workflow run status from Firestore"""
        try:
            # Query the document by session_id
            query = self.collection.where(filter=FieldFilter("session_id", "==", session_id))
            docs = list(query.get())
            
            if not docs:
                return None
                
            doc_data = docs[0].to_dict()
            if not doc_data:
                return None
                
            # Check if this is the current run
            current_run_id = doc_data.get("current_run_id")
            current_run_status = doc_data.get("current_run_status")
            
            if current_run_id == run_id and current_run_status:
                return {
                    "run_id": run_id,
                    "status": current_run_status,
                    "updated_at": int(time.time())
                }
            
            # Fall back to searching in runs array
            runs = doc_data.get("runs", [])
            for run in runs:
                if isinstance(run, dict) and run.get("run_id") == run_id:
                    return {
                        "run_id": run_id,
                        "status": run.get("status", "unknown"),
                        "updated_at": run.get("updated_at", int(time.time()))
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting workflow run status: {e}")
            return None

    def update_workflow_run_status(self, session_id: str, run_id: str, status: str) -> bool:
        """Update workflow run status in Firestore with atomic operations"""
        try:
            # Query to find the document
            query = self.collection.where(filter=FieldFilter("session_id", "==", session_id))
            docs = list(query.get())
            
            if not docs:
                return False
                
            doc_ref = docs[0].reference
            current_time = int(time.time())
            
            # Use transaction for atomic update
            @self._client.transactional
            def update_in_transaction(transaction):
                # Get current document
                doc_snapshot = doc_ref.get(transaction=transaction)
                if not doc_snapshot.exists:
                    return False
                    
                doc_data = doc_snapshot.to_dict()
                
                # Update the fast-access fields
                updates = {
                    "current_run_id": run_id,
                    "current_run_status": status,
                    "updated_at": current_time
                }
                
                runs = doc_data.get("runs", [])
                run_updated = False
                
                for i, run in enumerate(runs):
                    if isinstance(run, dict) and run.get("run_id") == run_id:
                        runs[i] = {**run, "status": status, "updated_at": current_time}
                        run_updated = True
                        break
                
                if run_updated:
                    updates["runs"] = runs
                
                # Perform atomic update
                transaction.update(doc_ref, updates)
                return True
            
            # Execute transaction
            return update_in_transaction(self._client.transaction())
            
        except Exception as e:
            logger.error(f"Error updating workflow run status: {e}")
            return False
