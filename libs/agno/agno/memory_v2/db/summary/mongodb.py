from datetime import datetime, timezone
from typing import List, Optional

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import PyMongoError
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it with `pip install pymongo`")

from agno.memory_v2.db.schema import SummaryRow
from agno.memory_v2.db.summary import SummaryDb
from agno.utils.log import log_debug, logger


class MongoSummaryDb(SummaryDb):
    def __init__(
        self,
        collection_name: str = "summary",
        db_url: Optional[str] = None,
        db_name: str = "agno",
        client: Optional[MongoClient] = None,
    ):
        """
        This class provides a summary store backed by a MongoDB collection.

        Args:
            collection_name: The name of the collection to store summaries
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
        
    def __str__(self) -> str:
        return f"MongoSummaryDb(collection_name={self.collection_name}, db_name={self.db_name})"

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

    def summary_exists(self, summary: SummaryRow) -> bool:
        """Check if a summary exists
        Args:
            summary: SummaryRow to check
        Returns:
            bool: True if the summary exists, False otherwise
        """
        try:
            result = self.collection.find_one({"id": summary.id})
            return result is not None
        except PyMongoError as e:
            logger.error(f"Error checking summary existence: {e}")
            return False

    def read_summaries(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[SummaryRow]:
        """Read summaries from the collection
        Args:
            user_id: ID of the user to read
            limit: Maximum number of summaries to read
            sort: Sort order ("asc" or "desc")
        Returns:
            List[SummaryRow]: List of summaries
        """
        summaries: List[SummaryRow] = []
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
                # Remove MongoDB _id before converting to SummaryRow
                doc.pop("_id", None)
                summaries.append(SummaryRow(user_id=doc["user_id"], summary=doc["summary"]))
        except PyMongoError as e:
            logger.error(f"Error reading summaries: {e}")
        return summaries

    def upsert_summary(self, summary: SummaryRow, create_and_retry: bool = True) -> None:
        """Upsert a summary into the collection
        Args:
            summary: SummaryRow to upsert
            create_and_retry: Whether to create a new summary if the id already exists
        Returns:
            None
        """
        try:
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            # Add version field for optimistic locking
            summary_dict = summary.model_dump()
            if "_version" not in summary_dict:
                summary_dict["_version"] = 1
            else:
                summary_dict["_version"] += 1

            update_data = {
                "user_id": summary.user_id,
                "summary": summary.summary,
                "updated_at": timestamp,
                "_version": summary_dict["_version"],
            }

            # For new documents, set created_at
            query = {"id": summary.id}
            doc = self.collection.find_one(query)
            if not doc:
                update_data["created_at"] = timestamp

            result = self.collection.update_one(query, {"$set": update_data}, upsert=True)

            if not result.acknowledged:
                logger.error("Summary upsert not acknowledged")

        except PyMongoError as e:
            logger.error(f"Error upserting summary: {e}")
            raise

    def delete_summary(self, session_id: str) -> None:
        """Delete a summary from the collection
        Args:
            session_id: ID of the summary to delete
        Returns:
            None
        """
        try:
            result = self.collection.delete_one({"id": session_id})
            if result.deleted_count == 0:
                log_debug(f"No summary found with id: {session_id}")
            else:
                log_debug(f"Successfully deleted summary with id: {session_id}")
        except PyMongoError as e:
            logger.error(f"Error deleting summary: {e}")
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
