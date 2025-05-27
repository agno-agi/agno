from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import UUID

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import PyMongoError
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it with `pip install pymongo`")


class MongoDbStorage(Storage):
    def __init__(
        self,
        collection_name: str,
        db_url: Optional[str] = None,
        db_name: str = "agno",
        client: Optional[MongoClient] = None,
        mode: Optional[Literal["agent", "team", "workflow"]] = "agent",
    ):
        """
        This class provides agent storage using MongoDB.

        Args:
            collection_name: Name of the collection to store agent sessions
            db_url: MongoDB connection URL
            db_name: Name of the database
            client: Optional existing MongoDB client
        """
        super().__init__(mode)
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
            self.collection.create_index("created_at")
            if self.mode == "agent":
                self.collection.create_index("agent_id")
            elif self.mode == "team":
                self.collection.create_index("team_id")
            elif self.mode == "workflow":
                self.collection.create_index("workflow_id")
        except PyMongoError as e:
            logger.error(f"Error creating indexes: {e}")
            raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Read a Session from MongoDB
        Args:
            session_id: ID of the session to read
            user_id: ID of the user to read
        Returns:
            Optional[Session]: The session if found, otherwise None
        """
        try:
            query = {"session_id": session_id}
            if user_id:
                query["user_id"] = user_id

            doc = self.collection.find_one(query)
            if doc:
                # Remove MongoDB _id before converting to AgentSession
                doc.pop("_id", None)
                if self.mode == "agent":
                    return AgentSession.from_dict(doc)
                elif self.mode == "team":
                    return TeamSession.from_dict(doc)
                elif self.mode == "workflow":
                    return WorkflowSession.from_dict(doc)
            return None
        except PyMongoError as e:
            logger.error(f"Error reading session: {e}")
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """Get all session IDs matching the criteria
        Args:
            user_id: ID of the user to read
            entity_id: ID of the entity to read
        Returns:
            List[str]: List of session IDs
        """
        try:
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            if entity_id is not None:
                if self.mode == "agent":
                    query["agent_id"] = entity_id
                elif self.mode == "team":
                    query["team_id"] = entity_id
                elif self.mode == "workflow":
                    query["workflow_id"] = entity_id

            cursor = self.collection.find(query, {"session_id": 1}).sort("created_at", -1)

            return [str(doc["session_id"]) for doc in cursor]
        except PyMongoError as e:
            logger.error(f"Error getting session IDs: {e}")
            return []

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """Get all sessions matching the criteria
        Args:
            user_id: ID of the user to read
            entity_id: ID of the agent / workflow to read
        Returns:
            List[Session]: List of sessions
        """
        try:
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            if entity_id is not None:
                if self.mode == "agent":
                    query["agent_id"] = entity_id
                elif self.mode == "team":
                    query["team_id"] = entity_id
                elif self.mode == "workflow":
                    query["workflow_id"] = entity_id

            cursor = self.collection.find(query).sort("created_at", -1)
            sessions: List[Session] = []
            for doc in cursor:
                # Remove MongoDB _id before converting to AgentSession
                doc.pop("_id", None)
                if self.mode == "agent":
                    _agent_session = AgentSession.from_dict(doc)
                    if _agent_session is not None:
                        sessions.append(_agent_session)
                elif self.mode == "team":
                    _team_session = TeamSession.from_dict(doc)
                    if _team_session is not None:
                        sessions.append(_team_session)
                elif self.mode == "workflow":
                    _workflow_session = WorkflowSession.from_dict(doc)
                    if _workflow_session is not None:
                        sessions.append(_workflow_session)
            return sessions
        except PyMongoError as e:
            logger.error(f"Error getting sessions: {e}")
            return []

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """Get the last N sessions, ordered by created_at descending.

        Args:
            num_history_sessions: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        try:
            # Build the query
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            if entity_id is not None:
                if self.mode == "agent":
                    query["agent_id"] = entity_id
                elif self.mode == "team":
                    query["team_id"] = entity_id
                elif self.mode == "workflow":
                    query["workflow_id"] = entity_id

            # Execute query with sort and limit
            cursor = self.collection.find(query)
            cursor = cursor.sort("created_at", -1)  # Sort by created_at descending
            if limit is not None:
                cursor = cursor.limit(limit)

            sessions: List[Session] = []
            for doc in cursor:
                # Remove MongoDB _id before converting to Session object
                doc.pop("_id", None)
                session: Optional[Session] = None

                if self.mode == "agent":
                    session = AgentSession.from_dict(doc)
                elif self.mode == "team":
                    session = TeamSession.from_dict(doc)
                elif self.mode == "workflow":
                    session = WorkflowSession.from_dict(doc)

                if session is not None:
                    sessions.append(session)

            return sessions

        except PyMongoError as e:
            logger.error(f"Error getting last {limit} sessions: {e}")
            return []

    def upsert(self, session: Session, create_and_retry: bool = True) -> Optional[Session]:
        """Upsert a session
        Args:
            session (Session): The session to upsert
            create_and_retry (bool): Whether to create a new session if the session_id already exists
        Returns:
            Optional[Session]: The upserted session, otherwise None
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
            logger.warning(f"Error upserting session: {e}")
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
                log_debug(f"No session found with session_id: {session_id}")
            else:
                log_debug(f"Successfully deleted session with session_id: {session_id}")
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
        """Create a deep copy of the MongoDbStorage instance"""
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
