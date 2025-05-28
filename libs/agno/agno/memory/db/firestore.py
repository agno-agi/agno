from typing import Optional, List
from datetime import datetime, timezone

from agno.memory.db import MemoryDb
from agno.memory.row import MemoryRow
from agno.utils.log import logger

try:
    from google.cloud import firestore
    from google.cloud.firestore import Client
    from google.cloud.firestore import CollectionReference, DocumentReference
    from google.cloud.firestore_v1.base_query import FieldFilter, BaseQuery
    import google.auth
except ImportError:
    raise ImportError(
        "`firestore` not installed. Please install it with `pip install google-cloud-firestore`"
    )


class FirestoreMemoryDb(MemoryDb):
    def __init__(
        self,
        collection_name: str = "memory",
        db_name: Optional[str] = "(default)",
        client: Optional[Client] = None,
        project: Optional[str] = None,
    ):
        """
        This class provides a memory store backed by a firestore collection.
        Memories are stored by user_id {self.collection_name}/{user_id}/memories to avoid having a firestore index
        since they are difficult to create on the fly.
        (index is required for a filtered order_by, not required using this model)

        Args:
            collection_name: The name of the collection to store memories
            db_name: Name of the firestore database (Default is to use (default) for the free tier/default database)
            client: Optional existing firestore client
            project: Optional name of the GCP project to use
        """
        self._client: Optional[Client] = client

        if self._client is None:
            self._client = firestore.Client(database=db_name, project=project)

        self.collection_name: str = collection_name
        self.db_name: str = db_name
        self.collection: CollectionReference = self._client.collection(
            self.collection_name
        )

        # store a user id for the collection when we get one
        # for use in the delete method due to the data structure
        self._user_id = None

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
        """Create the collection index
           Avoiding index creation by using a user/memory model

        Returns:
            None
        """
        try:
            logger.info(f"Mocked call to create index for  '{self.collection_name}'")
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists
        Args:
            memory: MemoryRow to check
        Returns:
            bool: True if the memory exists, False otherwise
        """
        try:
            logger.info(f"Checking if memory exists: {memory.id}")
            # save our user_id
            self._user_id = memory.user_id
            result = self.collection.document(memory.id).get().exists
            return result
        except Exception as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def get_user_collection(self, user_id: str) -> CollectionReference:
        return self._client.collection(f"{self.collection_name}/{user_id}/memories")

    def read_memories(self, user_id: str, limit=None, sort=None) -> List[MemoryRow]:
        """Read memories from the collection
            Avoids using an index since they are hard to create on the fly with firestore
        Args:
            user_id: ID of the user to read
            limit: Maximum number of memories to read
            sort: Sort order ("asc" or "desc")
        Returns:
            List[MemoryRow]: List of memories
        """
        memories: List[MemoryRow] = []
        try:
            user_collection = self.get_user_collection(user_id)
            self._user_id = user_id
            query = user_collection.order_by(
                "created_at",
                direction=(
                    firestore.Query.ASCENDING
                    if sort == "asc"
                    else firestore.Query.DESCENDING
                ),
            )
            if limit is not None:
                query = query.limit(limit)

            # Execute query
            docs = query.stream()
            for doc in docs:
                data = doc.to_dict()
                memories.append(
                    MemoryRow(id=data["id"], user_id=user_id, memory=data["memory"])
                )
        except Exception as e:
            logger.error(f"Error reading memories: {e}")
        return memories

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        """Upsert a memory into the user-specific collection
        Args:
            memory: MemoryRow to upsert
            create_and_retry: Whether to create a new memory if the id already exists
        Returns:
            None
        """
        try:
            logger.info(f"Upserting memory: {memory.id} for user: {memory.user_id}")
            # save our user_id
            self._user_id = memory.user_id
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            # Get user-specific collection
            user_collection = self.get_user_collection(memory.user_id)
            doc_ref = user_collection.document(memory.id)

            # Add version field for optimistic locking
            memory_dict = memory.model_dump()
            if "_version" not in memory_dict:
                memory_dict["_version"] = 1
            else:
                memory_dict["_version"] += 1

            update_data = {
                "id": memory.id,
                "memory": memory.memory,
                "updated_at": timestamp,
                "_version": memory_dict["_version"],
            }

            # For new documents, set created_at
            doc = doc_ref.get()
            if not doc.exists:
                update_data["created_at"] = timestamp

            # Use transactions for atomic updates
            @firestore.transactional
            def update_in_transaction(transaction, doc_ref, data):
                transaction.set(doc_ref, data, merge=True)

            transaction = self._client.transaction()
            update_in_transaction(transaction, doc_ref, update_data)

        except Exception as e:
            logger.error(f"Error upserting memory: {e}")
            raise

    def delete_memory(self, id: str) -> None:
        """Delete a memory from the collection
        Args:
            id: ID of the memory to delete
        Returns:
            None
        """
        try:
            logger.debug(f"Call to delete memory with id: {id}")
            # since our memories are stored by user
            # retrieve our copy of the user_id
            if self._user_id:
                user_collection = self.get_user_collection(self._user_id)
                user_collection.document(id).delete()
            else:
                logger.info("No user id provided, skipping delete")

        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            raise

    def drop_table(self) -> None:
        """Drop the collection

        Returns:
            None
        """
        # Caveats https://firebase.google.com/docs/firestore/solutions/delete-collections
        # We can delete all docs

        try:
            self._delete_collection(self.collection)

        except Exception as e:
            logger.error(f"Error dropping collection: {e}")

    def table_exists(self) -> bool:
        """Check if the collection exists
        Returns:
            bool: True if the collection exists, False otherwise
        """
        logger.debug(f"Call to check if collection exists: {self.collection_name}")
        return self.collection_name in [i._path[0] for i in self._client.collections()]

    def clear(self) -> bool:
        """Clear the collection
        Returns:
            bool: True if the collection was cleared, False otherwise
        """
        try:
            self._delete_collection(self.collection)

            return True
        except Exception as e:
            logger.error(f"Error dropping collection: {e}")
