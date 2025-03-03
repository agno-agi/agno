from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from agno.storage.agent.base import AgentStorage
from agno.storage.agent.session import AgentSession
from agno.utils.log import logger

try:
    from google.cloud import firestore
    from google.cloud.firestore import Client
    from google.cloud.firestore import CollectionReference, DocumentReference
    from google.cloud.firestore_v1.base_query import FieldFilter

except ImportError:
    raise ImportError(
        "`firestore` not installed. Please install it with `pip install google-cloud-firestore`"
    )


class FirestoreAgentStorage(AgentStorage):
    def __init__(
        self,
        collection_name: str,
        db_name: Optional[str] = "(default)",
        project_id: Optional[str] = None,
        client: Optional[Client] = None,
    ):
        """
        This class provides agent storage using Firestore.

        Args:
            collection_name: Name of the collection to store agent sessions
            db_name: Firestore database name (uses free tier (default) if not specified)
            project_id: Google Cloud project ID
            client: Optional existing Firestore client
        """
        self._client: Optional[Client] = client
        if self._client is None:
            self._client = firestore.Client(database=db_name, project=project_id)

        self.collection_name: str = collection_name
        self.collection: CollectionReference = self._client.collection(
            self.collection_name
        )

    # utilities to recursively delete all documents in a collection and the collection itself
    def _delete_document(self, document: DocumentReference):
        logger.debug(f"Deleting document: {document.path}")
        for collection in document.collections():
            self._delete_collection(collection)
        document.delete()

    def _delete_collection(self, collection: CollectionReference):
        for document in collection.list_documents():
            self._delete_document(document)

    def create(self) -> None:
        """Create necessary indexes for the collection. Not needed for Firestore."""
        try:
            logger.info(
                f"Unnecessary call to create index for  '{self.collection_name}'"
            )
        except Exception as e:
            logger.error(f"Error creating indexes for collection: {e}")
            raise

    def read(
        self, session_id: str, user_id: Optional[str] = None
    ) -> Optional[AgentSession]:
        """Read an agent session from Firestore
        Args:
            session_id: ID of the session to read
            user_id: ID of the user associated with the session (optional)
        Returns:
            AgentSession object if found, None otherwise
        """
        try:
            query = self.collection.where(
                filter=FieldFilter("session_id", "==", session_id)
            )
            if user_id:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            docs = query.get()
            for doc in docs:
                return AgentSession.from_dict(doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Error reading session: {e}")
            return None

    def get_all_session_ids(
        self, user_id: Optional[str] = None, agent_id: Optional[str] = None
    ) -> List[str]:
        """Get all session IDs matching the criteria
        Args:
            user_id: ID of the user associated with the session (optional)
            agent_id: ID of the agent associated with the session (optional)
        Returns:
            List of session IDs
        """
        try:
            query = self.collection
            if user_id:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))

            docs = query.get()
            # Sort in memory using Python's sorted function
            sorted_docs = sorted(docs, key=lambda x: x.get("created_at"), reverse=True)
            return [doc.get("session_id") for doc in sorted_docs]
        except Exception as e:
            logger.error(f"Error getting session IDs: {e}")
            return []

    def get_all_sessions(
        self, user_id: Optional[str] = None, agent_id: Optional[str] = None
    ) -> List[AgentSession]:
        """Get all sessions matching the criteria
        Args:
            user_id: ID of the user to read
            agent_id: ID of the agent to read
        Returns:
            List[AgentSession]: List of sessions
        """
        try:
            query = self.collection
            if user_id:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))
            if agent_id:
                query = query.where(filter=FieldFilter("agent_id", "==", agent_id))

            cursor = self.collection.find(query).sort("created_at", -1)
            sessions = []
            docs = query.get()
            # Sort in memory using Python's sorted function
            sorted_docs = sorted(docs, key=lambda x: x.get("created_at"), reverse=True)
            for doc in sorted_docs:
                # Remove _id before converting to AgentSession?
                # doc.pop("_id", None)
                _agent_session = AgentSession.from_dict(doc)
                if _agent_session is not None:
                    sessions.append(_agent_session)
            return sessions
        except Exception as e:
            logger.error(f"Error getting sessions: {e}")
            return []

    def upsert(
        self, session: AgentSession, create_and_retry: bool = True
    ) -> Optional[AgentSession]:
        """Upsert an agent session
        Args:
            session: AgentSession object to upsert
            create_and_retry: If True, create the session if it doesn't exist
        Returns:
            AgentSession object if successful, None otherwise
        """
        try:
            session_dict = session.to_dict()
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            if isinstance(session.session_id, UUID):
                session_dict["session_id"] = str(session.session_id)

            update_data = {**session_dict, "updated_at": timestamp}

            # Check if document exists
            doc_ref = self.collection.document(session_dict["session_id"])
            doc = doc_ref.get()

            if not doc.exists:
                update_data["created_at"] = timestamp

            doc_ref.set(update_data)
            return self.read(session_id=session_dict["session_id"])

        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None) -> None:
        """Delete an agent session
        Args:
            session_id: ID of the session to delete
        """
        if session_id is None:
            logger.warning("No session_id provided for deletion")
            return

        try:
            self.collection.document(session_id).delete()
            logger.debug(f"Successfully deleted session with session_id: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Delete all documents in the collection, dropping the collection"""
        try:
            self._delete_collection(self.collection)
        except Exception as e:
            logger.error(f"Error dropping collection: {e}")

    def upgrade_schema(self) -> None:
        """Placeholder for schema upgrades"""
        pass

    def __deepcopy__(self, memo):
        """Create a deep copy of the FirestoreAgentStorage instance"""
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            if k in {"_client", "collection"}:
                # Reuse Firestore connections without copying
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        return copied_obj
