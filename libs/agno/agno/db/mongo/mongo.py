import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.mongo.utils import (
    apply_pagination,
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_collection_indexes,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import deserialize_session_json_fields, serialize_session_json_fields
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info

try:
    from pymongo import MongoClient, ReturnDocument
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")


class MongoDb(BaseDb):
    def __init__(
        self,
        db_client: Optional[MongoClient] = None,
        db_name: Optional[str] = None,
        db_url: Optional[str] = None,
        session_collection: Optional[str] = None,
        memory_collection: Optional[str] = None,
        metrics_collection: Optional[str] = None,
        eval_collection: Optional[str] = None,
        knowledge_collection: Optional[str] = None,
    ):
        """
        Interface for interacting with a MongoDB database.

        Args:
            db_client (Optional[MongoClient]): The MongoDB client to use.
            db_name (Optional[str]): The name of the database to use.
            db_url (Optional[str]): The database URL to connect to.
            session_collection (Optional[str]): Name of the collection to store sessions.
            memory_collection (Optional[str]): Name of the collection to store memories.
            metrics_collection (Optional[str]): Name of the collection to store metrics.
            eval_collection (Optional[str]): Name of the collection to store evaluation runs.
            knowledge_collection (Optional[str]): Name of the collection to store knowledge documents.

        Raises:
            ValueError: If neither db_url nor db_client is provided.
        """
        super().__init__(
            session_table=session_collection,
            memory_table=memory_collection,
            metrics_table=metrics_collection,
            eval_table=eval_collection,
            knowledge_table=knowledge_collection,
        )

        _client: Optional[MongoClient] = db_client
        if _client is None and db_url is not None:
            _client = MongoClient(db_url)
        if _client is None:
            raise ValueError("One of db_url or db_client must be provided")

        self.db_url: Optional[str] = db_url
        self.db_client: MongoClient = _client
        self.db_name: str = db_name if db_name is not None else "agno"

        self._database: Optional[Database] = None

    @property
    def database(self) -> Database:
        if self._database is None:
            self._database = self.db_client[self.db_name]
        return self._database

    # -- DB methods --

    def _get_collection(
        self, table_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[Collection]:
        """Get or create a collection based on table type.

        Args:
            table_type (str): The type of table to get or create.

        Returns:
            Collection: The collection object.
        """
        if table_type == "sessions":
            if not hasattr(self, "session_collection"):
                if self.session_table_name is None:
                    raise ValueError("Session collection was not provided on initialization")
                self.session_collection = self._get_or_create_collection(
                    collection_name=self.session_table_name,
                    collection_type="sessions",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.session_collection

        if table_type == "memories":
            if not hasattr(self, "memory_collection"):
                if self.memory_table_name is None:
                    raise ValueError("Memory collection was not provided on initialization")
                self.memory_collection = self._get_or_create_collection(
                    collection_name=self.memory_table_name,
                    collection_type="memories",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.memory_collection

        if table_type == "metrics":
            if not hasattr(self, "metrics_collection"):
                if self.metrics_table_name is None:
                    raise ValueError("Metrics collection was not provided on initialization")
                self.metrics_collection = self._get_or_create_collection(
                    collection_name=self.metrics_table_name,
                    collection_type="metrics",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.metrics_collection

        if table_type == "evals":
            if not hasattr(self, "eval_collection"):
                if self.eval_table_name is None:
                    raise ValueError("Eval collection was not provided on initialization")
                self.eval_collection = self._get_or_create_collection(
                    collection_name=self.eval_table_name,
                    collection_type="evals",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.eval_collection

        if table_type == "knowledge":
            if not hasattr(self, "knowledge_collection"):
                if self.knowledge_table_name is None:
                    raise ValueError("Knowledge collection was not provided on initialization")
                self.knowledge_collection = self._get_or_create_collection(
                    collection_name=self.knowledge_table_name,
                    collection_type="knowledge",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.knowledge_collection

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_collection(
        self, collection_name: str, collection_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[Collection]:
        """Get or create a collection with proper indexes.

        Args:
            collection_name (str): The name of the collection to get or create.
            collection_type (str): The type of collection to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Optional[Collection]: The collection object.
        """
        try:
            collection = self.database[collection_name]

            if not hasattr(self, f"_{collection_name}_initialized"):
                if not create_collection_if_not_found:
                    return None
                create_collection_indexes(collection, collection_type)
                setattr(self, f"_{collection_name}_initialized", True)
                log_debug(f"Initialized collection '{collection_name}'")
            else:
                log_debug(f"Collection '{collection_name}' already initialized")

            return collection

        except Exception as e:
            log_error(f"Error getting collection {collection_name}: {e}")
            raise

    # -- Session methods --

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from the database.

        Args:
            session_id (str): The ID of the session to delete.

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the session.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return False

            result = collection.delete_one({"session_id": session_id})
            if result.deleted_count == 0:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False
            else:
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            return False

    def delete_sessions(self, session_ids: List[str]) -> None:
        """Delete multiple sessions from the database.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return

            result = collection.delete_many({"session_id": {"$in": session_ids}})
            log_debug(f"Successfully deleted {result.deleted_count} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")

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
            user_id (Optional[str]): The ID of the user to get the session for.
            session_type (Optional[SessionType]): The type of session to get.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error reading the session.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return None

            query = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            if session_type is not None:
                query["session_type"] = session_type

            result = collection.find_one(query)
            if result is None:
                return None

            session = deserialize_session_json_fields(result)

            if not deserialize:
                return session

            if session_type == SessionType.AGENT.value:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM.value:
                return TeamSession.from_dict(session)
            else:
                return WorkflowSession.from_dict(session)

        except Exception as e:
            log_error(f"Exception reading session: {e}")
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
            create_table_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: List of session dictionaries and the total count

        Raises:
            Exception: If there is an error reading the sessions.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return [] if deserialize else ([], 0)

            # Filtering
            query: Dict[str, Any] = {}
            if user_id is not None:
                query["user_id"] = user_id
            if session_type is not None:
                query["session_type"] = session_type
            if component_id is not None:
                if session_type == SessionType.AGENT:
                    query["agent_id"] = component_id
                elif session_type == SessionType.TEAM:
                    query["team_id"] = component_id
                elif session_type == SessionType.WORKFLOW:
                    query["workflow_id"] = component_id
            if start_timestamp is not None:
                query["created_at"] = {"$gte": start_timestamp}
            if end_timestamp is not None:
                if "created_at" in query:
                    query["created_at"]["$lte"] = end_timestamp
                else:
                    query["created_at"] = {"$lte": end_timestamp}
            if session_name is not None:
                query["session_data.session_name"] = {"$regex": session_name, "$options": "i"}

            # Get total count
            total_count = collection.count_documents(query)

            cursor = collection.find(query)

            # Sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)

            # Pagination
            query_args = apply_pagination({}, limit, page)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if records is None:
                return [] if deserialize else ([], 0)

            sessions_raw = [deserialize_session_json_fields(record) for record in records]

            if not deserialize:
                return sessions_raw, total_count

            sessions: List[Union[AgentSession, TeamSession, WorkflowSession]] = []
            for record in sessions_raw:
                if session_type == SessionType.AGENT.value:
                    agent_session = AgentSession.from_dict(record)
                    if agent_session is not None:
                        sessions.append(agent_session)
                elif session_type == SessionType.TEAM.value:
                    team_session = TeamSession.from_dict(record)
                    if team_session is not None:
                        sessions.append(team_session)
                elif session_type == SessionType.WORKFLOW.value:
                    workflow_session = WorkflowSession.from_dict(record)
                    if workflow_session is not None:
                        sessions.append(workflow_session)

            return sessions

        except Exception as e:
            log_error(f"Exception reading sessions: {e}")
            return [] if deserialize else ([], 0)

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name of the session.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If there is an error renaming the session.
        """
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return None

            try:
                result = collection.find_one_and_update(
                    {"session_id": session_id},
                    {"$set": {"session_data.session_name": session_name, "updated_at": int(time.time())}},
                    return_document=ReturnDocument.AFTER,
                    upsert=False,
                )
            except OperationFailure:
                # If the update fails because session_data doesn't contain a session_name yet, we initialize session_data
                result = collection.find_one_and_update(
                    {"session_id": session_id},
                    {"$set": {"session_data": {"session_name": session_name}, "updated_at": int(time.time())}},
                    return_document=ReturnDocument.AFTER,
                    upsert=False,
                )
            if not result:
                return None

            deserialized_session = deserialize_session_json_fields(result)

            if not deserialize:
                return deserialized_session

            if session_type == SessionType.AGENT.value:
                return AgentSession.from_dict(deserialized_session)
            elif session_type == SessionType.TEAM.value:
                return TeamSession.from_dict(deserialized_session)
            else:
                return WorkflowSession.from_dict(deserialized_session)

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            return None

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
            collection = self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            if collection is None:
                return None

            serialized_session_dict = serialize_session_json_fields(session.to_dict())

            if isinstance(session, AgentSession):
                record = {
                    "session_id": serialized_session_dict.get("session_id"),
                    "session_type": SessionType.AGENT.value,
                    "agent_id": serialized_session_dict.get("agent_id"),
                    "user_id": serialized_session_dict.get("user_id"),
                    "runs": serialized_session_dict.get("runs"),
                    "agent_data": serialized_session_dict.get("agent_data"),
                    "session_data": serialized_session_dict.get("session_data"),
                    "summary": serialized_session_dict.get("summary"),
                    "metadata": serialized_session_dict.get("metadata"),
                    "created_at": serialized_session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

                result = collection.find_one_and_replace(
                    filter={"session_id": serialized_session_dict.get("session_id")},
                    replacement=record,
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                if not result:
                    return None

                session = deserialize_session_json_fields(result)  # type: ignore

                log_debug("Upserted session'")

                if not deserialize:
                    return session

                return AgentSession.from_dict(session)  # type: ignore

            elif isinstance(session, TeamSession):
                record = {
                    "session_id": serialized_session_dict.get("session_id"),
                    "session_type": SessionType.TEAM.value,
                    "team_id": serialized_session_dict.get("team_id"),
                    "user_id": serialized_session_dict.get("user_id"),
                    "runs": serialized_session_dict.get("runs"),
                    "team_data": serialized_session_dict.get("team_data"),
                    "session_data": serialized_session_dict.get("session_data"),
                    "summary": serialized_session_dict.get("summary"),
                    "metadata": serialized_session_dict.get("metadata"),
                    "created_at": serialized_session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

                result = collection.find_one_and_replace(
                    filter={"session_id": serialized_session_dict.get("session_id")},
                    replacement=record,
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                if not result:
                    return None

                session = deserialize_session_json_fields(result)  # type: ignore

                log_debug(f"Upserted session with id '{session.session_id}'")

                if not deserialize:
                    return session

                return TeamSession.from_dict(session)  # type: ignore

            else:
                record = {
                    "session_id": serialized_session_dict.get("session_id"),
                    "session_type": SessionType.WORKFLOW.value,
                    "workflow_id": serialized_session_dict.get("workflow_id"),
                    "user_id": serialized_session_dict.get("user_id"),
                    "runs": serialized_session_dict.get("runs"),
                    "workflow_data": serialized_session_dict.get("workflow_data"),
                    "session_data": serialized_session_dict.get("session_data"),
                    "summary": serialized_session_dict.get("summary"),
                    "metadata": serialized_session_dict.get("metadata"),
                    "created_at": serialized_session_dict.get("created_at"),
                    "updated_at": int(time.time()),
                }

                result = collection.find_one_and_replace(
                    filter={"session_id": serialized_session_dict.get("session_id")},
                    replacement=record,
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                if not result:
                    return None

                session = deserialize_session_json_fields(result)  # type: ignore

                log_debug(f"Upserted session with id '{session.session_id}'")

                if not deserialize:
                    return session

                return WorkflowSession.from_dict(session)  # type: ignore

        except Exception as e:
            log_error(f"Exception upserting session: {e}")
            return None

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.

        Returns:
            bool: True if the memory was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the memory.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            result = collection.delete_one({"memory_id": memory_id})

            success = result.deleted_count > 0
            if success:
                log_debug(f"Successfully deleted memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.

        Raises:
            Exception: If there is an error deleting the memories.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            result = collection.delete_many({"memory_id": {"$in": memory_ids}})

            if result.deleted_count == 0:
                log_debug(f"No memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: The topics.

        Raises:
            Exception: If there is an error getting the topics.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return []

            topics = collection.distinct("topics")
            return [topic for topic in topics if topic]

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
            return []

    def get_user_memory(self, memory_id: str, deserialize: Optional[bool] = True) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Optional[UserMemory]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error getting the memory.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return None

            result = collection.find_one({"memory_id": memory_id})
            if result is None or not deserialize:
                return result

            return UserMemory.from_dict(result)

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
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
            create_table_if_not_found: Whether to create the collection if it doesn't exist.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories and the total count.

        Raises:
            Exception: If there is an error getting the memories.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return [] if deserialize else ([], 0)

            query: Dict[str, Any] = {}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if topics is not None:
                query["topics"] = {"$in": topics}
            if search_content is not None:
                query["memory"] = {"$regex": search_content, "$options": "i"}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if not deserialize:
                return records, total_count

            return [UserMemory.from_dict(record) for record in records]

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
            return []

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
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
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return [], 0

            pipeline = [
                {"$match": {"user_id": {"$ne": None}}},
                {
                    "$group": {
                        "_id": "$user_id",
                        "total_memories": {"$sum": 1},
                        "last_memory_updated_at": {"$max": "$updated_at"},
                    }
                },
                {"$sort": {"last_memory_updated_at": -1}},
            ]

            # Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = list(collection.aggregate(count_pipeline))  # type: ignore
            total_count = count_result[0]["total"] if count_result else 0

            # Apply pagination
            if limit is not None:
                if page is not None:
                    pipeline.append({"$skip": (page - 1) * limit})
                pipeline.append({"$limit": limit})

            results = list(collection.aggregate(pipeline))  # type: ignore

            formatted_results = [
                {
                    "user_id": result["_id"],
                    "total_memories": result["total_memories"],
                    "last_memory_updated_at": result["last_memory_updated_at"],
                }
                for result in results
            ]

            return formatted_results, total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {e}")
            return [], 0

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
            collection = self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            update_doc = {
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "topics": memory.topics,
                "updated_at": int(time.time()),
            }

            result = collection.replace_one({"memory_id": memory.memory_id}, update_doc, upsert=True)

            if result.upserted_id:
                update_doc["_id"] = result.upserted_id

            if not deserialize:
                return update_doc

            return UserMemory.from_dict(update_doc)

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            return None

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = self._get_collection(table_type="memories")
            if collection is None:
                return

            collection.delete_many({})

        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {e}")

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions of all types for metrics calculation."""
        try:
            collection = self._get_collection(table_type="sessions")
            if collection is None:
                return []

            query = {}
            if start_timestamp is not None:
                query["created_at"] = {"$gte": start_timestamp}
            if end_timestamp is not None:
                if "created_at" in query:
                    query["created_at"]["$lte"] = end_timestamp
                else:
                    query["created_at"] = {"$lte": end_timestamp}

            projection = {
                "user_id": 1,
                "session_data": 1,
                "runs": 1,
                "created_at": 1,
                "session_type": 1,
            }

            results = list(collection.find(query, projection))
            return results

        except Exception as e:
            log_error(f"Exception reading from sessions collection: {e}")
            return []

    def _get_metrics_calculation_starting_date(self, collection: Collection) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        try:
            result = collection.find_one({}, sort=[("date", -1)], limit=1)

            if result is not None:
                result_date = datetime.strptime(result["date"], "%Y-%m-%d").date()
                if result.get("completed"):
                    return result_date + timedelta(days=1)
                else:
                    return result_date

            # No metrics records. Return the date of the first recorded session.
            first_session_result = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
            first_session_date = first_session_result[0][0]["created_at"] if first_session_result[0] else None  # type: ignore

            if first_session_date is None:
                return None

            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        except Exception as e:
            log_error(f"Exception getting metrics calculation starting date: {e}")
            return None

    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            collection = self._get_collection(table_type="metrics", create_collection_if_not_found=True)
            if collection is None:
                return None

            starting_date = self._get_metrics_calculation_starting_date(collection)
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = int(
                datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
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
                results = bulk_upsert_metrics(collection, metrics_records)

            return results

        except Exception as e:
            log_error(f"Error calculating metrics: {e}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range."""
        try:
            collection = self._get_collection(table_type="metrics")
            if collection is None:
                return [], None

            query = {}
            if starting_date:
                query["date"] = {"$gte": starting_date.isoformat()}
            if ending_date:
                if "date" in query:
                    query["date"]["$lte"] = ending_date.isoformat()
                else:
                    query["date"] = {"$lte": ending_date.isoformat()}

            records = list(collection.find(query))
            if not records:
                return [], None

            # Get the latest updated_at
            latest_updated_at = max(record.get("updated_at", 0) for record in records)

            return records, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {e}")
            return [], None

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return

            collection.delete_one({"id": id})

            log_debug(f"Deleted knowledge content with id '{id}'")

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise

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
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return None

            result = collection.find_one({"id": id})
            if result is None:
                return None

            return KnowledgeRow.model_validate(result)

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            return None

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            create_table_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection = self._get_collection(table_type="knowledge")
            if collection is None:
                return [], 0

            query: Dict[str, Any] = {}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply sorting
            sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            knowledge_rows = [KnowledgeRow.model_validate(record) for record in records]

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            return [], 0

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection = self._get_collection(table_type="knowledge", create_collection_if_not_found=True)
            if collection is None:
                return None

            update_doc = knowledge_row.model_dump()
            collection.replace_one({"id": knowledge_row.id}, update_doc, upsert=True)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {e}")
            return None

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            collection = self._get_collection(table_type="evals", create_collection_if_not_found=True)
            if collection is None:
                return None

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            collection.insert_one(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            return None

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return

            result = collection.delete_one({"run_id": eval_run_id})

            if result.deleted_count == 0:
                log_debug(f"No eval run found with ID: {eval_run_id}")
            else:
                log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return

            result = collection.delete_many({"run_id": {"$in": eval_run_ids}})

            if result.deleted_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {result.deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise

    def get_eval_run_raw(self, eval_run_id: str) -> Optional[Dict[str, Any]]:
        """Get an eval run from the database as a raw dictionary."""
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            result = collection.find_one({"run_id": eval_run_id})
            return result

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
            return None

    def get_eval_run(self, eval_run_id: str, deserialize: Optional[bool] = True) -> Optional[EvalRunRecord]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.

        Returns:
            Optional[EvalRunRecord]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If there is an error getting the eval run.
        """
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            eval_run_raw = collection.find_one({"run_id": eval_run_id})

            if not eval_run_raw:
                return None

            if not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
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
            create_table_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        try:
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return [] if deserialize else ([], 0)

            query: Dict[str, Any] = {}
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if workflow_id is not None:
                query["workflow_id"] = workflow_id
            if model_id is not None:
                query["model_id"] = model_id
            if eval_type is not None and len(eval_type) > 0:
                query["eval_type"] = {"$in": eval_type}
            if filter_type is not None:
                if filter_type == EvalFilterType.AGENT:
                    query["agent_id"] = {"$ne": None}
                elif filter_type == EvalFilterType.TEAM:
                    query["team_id"] = {"$ne": None}
                elif filter_type == EvalFilterType.WORKFLOW:
                    query["workflow_id"] = {"$ne": None}

            # Get total count
            total_count = collection.count_documents(query)

            # Apply default sorting by created_at desc if no sort parameters provided
            if sort_by is None:
                sort_criteria = [("created_at", -1)]
            else:
                sort_criteria = apply_sorting({}, sort_by, sort_order)

            # Apply pagination
            query_args = apply_pagination({}, limit, page)

            cursor = collection.find(query)
            if sort_criteria:
                cursor = cursor.sort(sort_criteria)
            if query_args.get("skip"):
                cursor = cursor.skip(query_args["skip"])
            if query_args.get("limit"):
                cursor = cursor.limit(query_args["limit"])

            records = list(cursor)
            if not records:
                return [] if deserialize else ([], 0)

            if not deserialize:
                return records, total_count

            return [EvalRunRecord.model_validate(row) for row in records]

        except Exception as e:
            log_debug(f"Exception getting eval runs: {e}")
            return [] if deserialize else ([], 0)

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
            collection = self._get_collection(table_type="evals")
            if collection is None:
                return None

            result = collection.find_one_and_update(
                {"run_id": eval_run_id}, {"$set": {"name": name, "updated_at": int(time.time())}}
            )

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not result or not deserialize:
                return result

            return EvalRunRecord.model_validate(result)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {e}")
            raise
