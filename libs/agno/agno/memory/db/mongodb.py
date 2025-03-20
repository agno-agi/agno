from datetime import datetime, timezone
from typing import List, Optional

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import PyMongoError
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it with `pip install pymongo`")

from agno.memory.db import MemoryDb
from agno.memory.row import MemoryRow
from agno.utils.log import log_debug, logger


class MongoMemoryDb(MemoryDb):
    def __init__(
        self,
        collection_name: str = "memory",
        db_url: Optional[str] = None,
        db_name: str = "agno",
        client: Optional[MongoClient] = None,
    ):
        """
        This class provides a memory store backed by a MongoDB collection.

        Args:
            collection_name: The name of the collection to store memories
            db_url: MongoDB connection URL
            db_name: Name of the database
            client: Optional existing MongoDB client
        """
        self._client: Optional[MongoClient] = client
        if self._client is None and db_url is not None:
            self._client = MongoClient(db_url)

        if self._client is None:
            raise ValueError("Must provide either db_url or client")

        self.collection_name: str = collection_name
        self.db_name: str = db_name
        self.db: Database = self._client[self.db_name]
        self.collection: Collection = self.db[self.collection_name]

    def create(self) -> None:
        """Create indexes for the collection"""
        try:
            # Create indexes
            self.collection.create_index("id", unique=True)
            self.collection.create_index("user_id")
            self.collection.create_index("created_at")
        except PyMongoError as e:
            logger.error(f"Error creating indexes for collection '{self.collection_name}': {e}")
            raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists
        Args:
            memory: MemoryRow to check
        Returns:
            bool: True if the memory exists, False otherwise
        """
        try:
            result = self.collection.find_one({"id": memory.id})
            return result is not None
        except PyMongoError as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """Read memories from the collection
        Args:
            user_id: ID of the user to read
            limit: Maximum number of memories to read
            sort: Sort order ("asc" or "desc")
        Returns:
            List[MemoryRow]: List of memories
        """
        memories: List[MemoryRow] = []
        try:
            # Build query
            query = {}
            if user_id is not None:
                query["user_id"] = user_id

            # Build sort order
            sort_order = -1 if sort != "asc" else 1
            cursor = self.collection.find(query).sort("created_at", sort_order)

            if limit is not None:
                cursor = cursor.limit(limit)

            for doc in cursor:
                # Remove MongoDB _id before converting to MemoryRow
                doc.pop("_id", None)
                memories.append(MemoryRow(user_id=doc["user_id"], memory=doc["memory"]))
        except PyMongoError as e:
            logger.error(f"Error reading memories: {e}")
        return memories

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        """Upsert a memory into the collection
        Args:
            memory: MemoryRow to upsert
            create_and_retry: Whether to create a new memory if the id already exists
        Returns:
            None
        """
        try:
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            # Add version field for optimistic locking
            memory_dict = memory.model_dump()
            if "_version" not in memory_dict:
                memory_dict["_version"] = 1
            else:
                memory_dict["_version"] += 1

            update_data = {
                "user_id": memory.user_id,
                "memory": memory.memory,
                "updated_at": timestamp,
                "_version": memory_dict["_version"],
            }

            # For new documents, set created_at
            query = {"id": memory.id}
            doc = self.collection.find_one(query)
            if not doc:
                update_data["created_at"] = timestamp

            result = self.collection.update_one(query, {"$set": update_data}, upsert=True)

            if not result.acknowledged:
                logger.error("Memory upsert not acknowledged")

        except PyMongoError as e:
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
            result = self.collection.delete_one({"id": id})
            if result.deleted_count == 0:
                log_debug(f"No memory found with id: {id}")
            else:
                log_debug(f"Successfully deleted memory with id: {id}")
        except PyMongoError as e:
            logger.error(f"Error deleting memory: {e}")
            raise

    def drop_table(self) -> None:
        """Drop the collection
        Returns:
            None
        """
        try:
            self.collection.drop()
        except PyMongoError as e:
            logger.error(f"Error dropping collection: {e}")

    def table_exists(self) -> bool:
        """Check if the collection exists
        Returns:
            bool: True if the collection exists, False otherwise
        """
        return self.collection_name in self.db.list_collection_names()

    def clear(self) -> bool:
        """Clear the collection
        Returns:
            bool: True if the collection was cleared, False otherwise
        """
        try:
            result = self.collection.delete_many({})
            return result.acknowledged
        except PyMongoError as e:
            logger.error(f"Error clearing collection: {e}")
            return False
