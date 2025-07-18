import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.utils.log import log_debug, logger

try:
    from google.api_core import exceptions as google_exceptions
    from google.cloud.firestore_v1 import (
        Client,
        CollectionReference,
        DocumentReference,
        Query,
        Transaction,
        transactional,
    )
except ImportError:
    raise ImportError(
        "`google-cloud-firestore` not installed. Please install it using `pip install google-cloud-firestore`"
    )


class FirestoreMemoryDb(MemoryDb):
    def __init__(
        self,
        collection_name: str = "memory",
        db_name: Optional[str] = "(default)",
        client: Optional[Client] = None,
        project_id: Optional[str] = None,
    ):
        """
        This class provides a memory store backed by a Firestore collection.

        Args:
            collection_name: The name of the collection to store memories
            db_name: Name of the Firestore database (Default is "(default)" for free tier)
            client: Optional existing Firestore client
            project_id: Optional name of the GCP project to use
        """
        self.collection_name = collection_name
        self.db_name = db_name
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")

        # Initialize Firestore client
        self._client = client
        if self._client is None:
            self._client = self._initialize_client()

        # Get root collection reference
        self.collection: CollectionReference = self._client.collection(self.collection_name)

        # Store user_id for delete operations due to the data structure
        self._user_id: Optional[str] = None

        log_debug(f"Created FirestoreMemoryDb with collection: '{self.collection_name}'")

    def _initialize_client(self) -> Client:
        """Initialize and return a Firestore client with proper error handling."""
        try:
            client = Client(database=self.db_name, project=self.project_id)
            # Test the connection by listing collections
            list(client.collections())
            log_debug(f"Firestore client initialized with database: '{self.db_name}'")
            return client
        except google_exceptions.Unauthenticated as e:
            logger.error(
                "Firestore authentication failed. Please ensure you have proper Google Cloud credentials set up."
            )
            logger.error("Run 'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS")
            raise ImportError(
                "Failed to authenticate with Google Cloud. Please set up authentication:\n"
                "1. Run: gcloud auth application-default login\n"
                "2. Or set GOOGLE_APPLICATION_CREDENTIALS environment variable"
            ) from e
        except google_exceptions.PermissionDenied as e:
            logger.error(
                "Permission denied. Please ensure your service account has the necessary Firestore permissions."
            )
            raise ImportError(
                "Permission denied when accessing Firestore. Please ensure:\n"
                "1. Your service account has the 'Cloud Datastore User' role\n"
                "2. The Firestore API is enabled for your project"
            ) from e
        except google_exceptions.InvalidArgument as e:
            if "database" in str(e).lower():
                logger.error(f"Invalid database name '{self.db_name}'. Use '(default)' for the default database.")
                raise ImportError(
                    f"Invalid database name '{self.db_name}'. For free tier, use '(default)' as the database name."
                ) from e
            else:
                logger.error(f"Invalid argument when initializing Firestore: {e}")
                raise
        except Exception as e:
            logger.error(f"Failed to initialize Firestore client: {e}")
            raise

    def get_user_collection(self, user_id: str) -> CollectionReference:
        """Get the user-specific collection for storing memories."""
        if self._client is None:
            raise RuntimeError("Firestore client is not initialized")
        return self._client.collection(f"{self.collection_name}/{user_id}/memories")

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

    def create(self) -> None:
        """
        Create the collection index.
        For Firestore using user/memory model, this is a no-op to avoid index creation.
        """
        try:
            # Test connection
            if self._client:
                list(self._client.collections())
            log_debug("Firestore connection successful")
        except Exception as e:
            logger.error(f"Could not connect to Firestore: {e}")
            raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists."""
        try:
            log_debug(f"Checking if memory exists: {memory.id}")
            # Save user_id for potential future operations
            self._user_id = memory.user_id

            # Check in the user-specific collection
            if memory.user_id is None:
                # Return False when no user_id is provided (internal Memory v2 operations)
                return False

            user_collection = self.get_user_collection(memory.user_id)
            doc = user_collection.document(memory.id).get()
            return doc.exists
        except Exception as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """
        Read memories from the collection.

        Args:
            user_id: ID of the user to read
            limit: Maximum number of memories to read
            sort: Sort order ("asc" or "desc")

        Returns:
            List[MemoryRow]: List of memories
        """
        memories: List[MemoryRow] = []

        if user_id is None:
            return memories

        try:
            # Save user_id for potential future operations
            self._user_id = user_id

            # Get user-specific collection
            user_collection = self.get_user_collection(user_id)

            # Build query with ordering
            query = user_collection.order_by(
                "created_at",
                direction=(Query.ASCENDING if sort == "asc" else Query.DESCENDING),
            )

            # Apply limit if specified
            if limit is not None:
                query = query.limit(limit)

            # Execute query and build results
            for doc in query.stream():
                data = doc.to_dict()
                if data is None:
                    continue

                # Get timestamps for last_updated
                updated_at = data.get("updated_at")
                created_at = data.get("created_at")
                last_updated = None
                if updated_at:
                    last_updated = datetime.fromtimestamp(updated_at, tz=timezone.utc)
                elif created_at:
                    last_updated = datetime.fromtimestamp(created_at, tz=timezone.utc)

                memories.append(
                    MemoryRow(
                        id=data.get("id"),
                        user_id=data.get("user_id", user_id),
                        memory=data.get("memory", {}),
                        last_updated=last_updated,
                    )
                )

            return memories
        except Exception as e:
            logger.error(f"Error reading memories: {e}")
            return []

    def upsert_memory(self, memory: MemoryRow) -> None:
        """
        Upsert a memory into the user-specific collection.

        Args:
            memory: MemoryRow to upsert

        Returns:
            None
        """
        try:
            log_debug(f"Upserting memory: {memory.id} for user: {memory.user_id}")

            # Save user_id for potential future operations
            self._user_id = memory.user_id

            # Prepare timestamp
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            # Get user-specific collection and document reference
            if memory.user_id is None:
                # Skip upsert when no user_id is provided (internal Memory v2 operations)
                return

            user_collection = self.get_user_collection(memory.user_id)
            doc_ref = user_collection.document(memory.id)

            # Prepare memory data with version for optimistic locking
            memory_dict = memory.model_dump()
            if "_version" not in memory_dict:
                memory_dict["_version"] = 1
            else:
                memory_dict["_version"] += 1

            # Build update data - include all fields
            update_data: Dict[str, Any] = {
                "id": memory.id,
                "user_id": memory.user_id,
                "memory": memory.memory,
                "updated_at": timestamp,
                "_version": memory_dict["_version"],
            }

            # Check if document exists to set created_at
            doc = doc_ref.get()
            if not doc.exists:
                update_data["created_at"] = timestamp
            else:
                # Preserve existing created_at
                existing_data = doc.to_dict()
                if existing_data and "created_at" in existing_data:
                    update_data["created_at"] = existing_data["created_at"]

            # Use a transaction for atomic update
            if self._client is None:
                raise RuntimeError("Firestore client is not initialized")

            transaction = self._client.transaction()

            @transactional
            def update_in_transaction(transaction: Transaction) -> None:
                # Re-read within transaction to ensure consistency
                _ = doc_ref.get(transaction=transaction)  # Read for consistency check
                transaction.set(doc_ref, update_data)

            # Execute the transaction
            update_in_transaction(transaction)

        except Exception as e:
            logger.error(f"Error upserting memory: {e}")
            raise

    def delete_memory(self, memory_id: str) -> None:
        """
        Delete a memory from the collection.

        Args:
            memory_id: ID of the memory to delete
        """
        try:
            log_debug(f"Deleting memory with id: {memory_id}")

            if self._user_id:
                user_collection = self.get_user_collection(self._user_id)
                user_collection.document(memory_id).delete()
                log_debug(f"Successfully deleted memory with id: {memory_id}")
            else:
                # Skip deletion when no user_id is available
                pass

        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            raise

    def clear(self) -> bool:
        """Clear all memories from the collection."""
        try:
            for doc in self.collection.list_documents():
                self._delete_document(doc)
            log_debug(f"Cleared all memories in collection: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            return False

    def drop_table(self) -> None:
        """Drop the collection."""
        try:
            for doc in self.collection.list_documents():
                self._delete_document(doc)
            log_debug(f"Dropped collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Error dropping collection: {e}")
            raise

    def table_exists(self) -> bool:
        """Check if the collection exists."""
        try:
            # Try to stream one document to check if collection exists
            _ = list(self.collection.limit(1).stream())
            return True
        except Exception as e:
            logger.error(f"Error checking collection existence: {e}")
            return False
