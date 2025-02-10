from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import PyMongoError
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it with `pip install pymongo`")

from agno.storage.agent.base import AgentStorage
from agno.storage.agent.session import AgentSession
from agno.utils.log import logger


class MongoDbAgentStorage(AgentStorage):
    def __init__(
        self,
        collection_name: str,
        db_url: Optional[str] = None,
        db_name: str = "agno",
        client: Optional[MongoClient] = None,
    ):
        """
        This class provides agent storage using MongoDB.

        Args:
            collection_name: Name of the collection to store agent sessions
            db_url: MongoDB connection URL
            db_name: Name of the database
            client: Optional existing MongoDB client
        """
        self._client: Optional[MongoClient] = client
        if self._client is None and db_url is not None:
            self._client = MongoClient(db_url)
        elif self._client is None:
            self._client = MongoClient()

        if self._client is None:
            raise ValueError("Must provide either db_url or client")

        self.collection_name: str = collection_name
        self.db_name: str = db_name
        self.db: Database = self._client[self.db_name]
        self.collection: Collection = self.db[self.collection_name]

    def create(self) -> None:
        """Create necessary indexes for the collection"""
        try:
            # Create indexes
            self.collection.create_index("session_id", unique=True)
            self.collection.create_index("user_id")
            self.collection.create_index("agent_id")
            self.collection.create_index("created_at")
        except PyMongoError as e:
            logger.error(f"Error creating indexes: {e}")
            raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read an agent session from MongoDB
        Args:
            session_id: ID of the session to read
            user_id: ID of the user to read
        Returns:
            AgentSession: The session if found, otherwise None
        """
        try:
            query = {"session_id": session_id}
            if user_id:
                query["user_id"] = user_id

            doc = self.collection.find_one(query)
            if doc:
                # Remove MongoDB _id before converting to AgentSession
                doc.pop("_id", None)
                return AgentSession.from_dict(doc)
            return None
        except PyMongoError as e:
            logger.error(f"Error reading session: {e}")
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[str]:
        """Get all session IDs matching the criteria
        Args:
            user_id: ID of the user to read
            agent_id: ID of the agent to read
        Returns:
            List[str]: List of session IDs
        """
        try:
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id

            cursor = self.collection.find(query, {"session_id": 1}).sort("created_at", -1)

            return [str(doc["session_id"]) for doc in cursor]
        except PyMongoError as e:
            logger.error(f"Error getting session IDs: {e}")
            return []

    def get_all_sessions(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[AgentSession]:
        """Get all sessions matching the criteria
        Args:
            user_id: ID of the user to read
            agent_id: ID of the agent to read
        Returns:
            List[AgentSession]: List of sessions
        """
        try:
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id

            cursor = self.collection.find(query).sort("created_at", -1)
            sessions = []
            for doc in cursor:
                # Remove MongoDB _id before converting to AgentSession
                doc.pop("_id", None)
                _agent_session = AgentSession.from_dict(doc)
                if _agent_session is not None:
                    sessions.append(_agent_session)
            return sessions
        except PyMongoError as e:
            logger.error(f"Error getting sessions: {e}")
            return []

    def upsert(self, session: AgentSession, create_and_retry: bool = True) -> Optional[AgentSession]:
        """Upsert an agent session
        Args:
            session: AgentSession to upsert
            create_and_retry: Whether to create a new session if the session_id already exists
        Returns:
            AgentSession: The session if upserted, otherwise None
        """
        try:
            # Convert session to dict and add timestamps
            session_dict = session.to_dict()
            now = datetime.now(timezone.utc)
            timestamp = int(now.timestamp())

            # Handle UUID serialization
            if isinstance(session.session_id, UUID):
                session_dict["session_id"] = str(session.session_id)

            # Add version field for optimistic locking
            if "_version" not in session_dict:
                session_dict["_version"] = 1
            else:
                session_dict["_version"] += 1

            update_data = {**session_dict, "updated_at": timestamp}

            # For new documents, set created_at
            query = {"session_id": session_dict["session_id"]}

            doc = self.collection.find_one(query)
            if not doc:
                update_data["created_at"] = timestamp

            result = self.collection.update_one(query, {"$set": update_data}, upsert=True)

            if result.acknowledged:
                return self.read(session_id=session_dict["session_id"])
            return None

        except PyMongoError as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None) -> None:
        """Delete an agent session
        Args:
            session_id: ID of the session to delete
        Returns:
            None
        """
        if session_id is None:
            logger.warning("No session_id provided for deletion")
            return

        try:
            result = self.collection.delete_one({"session_id": session_id})
            if result.deleted_count == 0:
                logger.debug(f"No session found with session_id: {session_id}")
            else:
                logger.debug(f"Successfully deleted session with session_id: {session_id}")
        except PyMongoError as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop the collection
        Returns:
            None
        """
        try:
            self.collection.drop()
        except PyMongoError as e:
            logger.error(f"Error dropping collection: {e}")

    def upgrade_schema(self) -> None:
        """Placeholder for schema upgrades"""
        pass

    def __deepcopy__(self, memo):
        """Create a deep copy of the MongoDbAgentStorage instance"""
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            if k in {"_client", "db", "collection"}:
                # Reuse MongoDB connections without copying
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        return copied_obj
