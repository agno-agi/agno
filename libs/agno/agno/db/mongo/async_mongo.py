import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

try:
    from pymongo.errors import DuplicateKeyError
except ImportError:
    DuplicateKeyError = Exception  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.mongo.utils import (
    apply_pagination,
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_collection_indexes_async,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    serialize_cultural_knowledge_for_db,
)
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import deserialize_session_json_fields
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

try:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase  # type: ignore

    MOTOR_AVAILABLE = True
except ImportError:
    MOTOR_AVAILABLE = False
    AsyncIOMotorClient = None  # type: ignore
    AsyncIOMotorCollection = None  # type: ignore
    AsyncIOMotorDatabase = None  # type: ignore

try:
    from pymongo import AsyncMongoClient  # type: ignore
    from pymongo.collection import AsyncCollection  # type: ignore
    from pymongo.database import AsyncDatabase  # type: ignore

    PYMONGO_ASYNC_AVAILABLE = True
except ImportError:
    PYMONGO_ASYNC_AVAILABLE = False
    AsyncMongoClient = None  # type: ignore
    AsyncDatabase = None  # type: ignore
    AsyncCollection = None  # type: ignore

try:
    from pymongo import ReturnDocument
    from pymongo.errors import OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install -U pymongo`")

# Ensure at least one async library is available
if not MOTOR_AVAILABLE and not PYMONGO_ASYNC_AVAILABLE:
    raise ImportError(
        "Neither `motor` nor PyMongo async is installed. "
        "Please install one of them using:\n"
        "  - `pip install -U 'pymongo>=4.9'` (recommended)"
        "  - `pip install -U motor` (legacy, deprecated)\n"
    )

# Create union types for client, database, and collection
if TYPE_CHECKING:
    if MOTOR_AVAILABLE and PYMONGO_ASYNC_AVAILABLE:
        AsyncMongoClientType = Union[AsyncIOMotorClient, AsyncMongoClient]  # type: ignore
        AsyncMongoDatabaseType = Union[AsyncIOMotorDatabase, AsyncDatabase]  # type: ignore
        AsyncMongoCollectionType = Union[AsyncIOMotorCollection, AsyncCollection]  # type: ignore
    elif MOTOR_AVAILABLE:
        AsyncMongoClientType = AsyncIOMotorClient  # type: ignore
        AsyncMongoDatabaseType = AsyncIOMotorDatabase  # type: ignore
        AsyncMongoCollectionType = AsyncIOMotorCollection  # type: ignore
    else:
        AsyncMongoClientType = AsyncMongoClient  # type: ignore
        AsyncMongoDatabaseType = AsyncDatabase  # type: ignore
        AsyncMongoCollectionType = AsyncCollection  # type: ignore
else:
    # Runtime type - use Any to avoid import issues
    AsyncMongoClientType = Any
    AsyncMongoDatabaseType = Any
    AsyncMongoCollectionType = Any


# Client type constants (defined before class to allow use in _detect_client_type)
_CLIENT_TYPE_MOTOR = "motor"
_CLIENT_TYPE_PYMONGO_ASYNC = "pymongo_async"
_CLIENT_TYPE_UNKNOWN = "unknown"


def _detect_client_type(client: Any) -> str:
    """Detect whether a client is Motor or PyMongo async."""
    if client is None:
        return _CLIENT_TYPE_UNKNOWN

    # Check PyMongo async
    if PYMONGO_ASYNC_AVAILABLE and AsyncMongoClient is not None:
        try:
            if isinstance(client, AsyncMongoClient):
                return _CLIENT_TYPE_PYMONGO_ASYNC
        except (TypeError, AttributeError):
            pass  # Fall through to next check

    if MOTOR_AVAILABLE and AsyncIOMotorClient is not None:
        try:
            if isinstance(client, AsyncIOMotorClient):
                return _CLIENT_TYPE_MOTOR
        except (TypeError, AttributeError):
            pass  # Fall through to fallback

    # Fallback to string matching only if isinstance fails
    # (should rarely happen, but useful for edge cases)
    client_type_name = type(client).__name__
    if "Motor" in client_type_name or "AsyncIOMotor" in client_type_name:
        return _CLIENT_TYPE_MOTOR
    elif "AsyncMongo" in client_type_name:
        return _CLIENT_TYPE_PYMONGO_ASYNC

    # Last resort: check module name
    module_name = type(client).__module__
    if "motor" in module_name:
        return _CLIENT_TYPE_MOTOR
    elif "pymongo" in module_name:
        return _CLIENT_TYPE_PYMONGO_ASYNC

    return _CLIENT_TYPE_UNKNOWN


class AsyncMongoDb(AsyncBaseDb):
    # Client type constants (class-level access to module constants)
    CLIENT_TYPE_MOTOR = _CLIENT_TYPE_MOTOR
    CLIENT_TYPE_PYMONGO_ASYNC = _CLIENT_TYPE_PYMONGO_ASYNC
    CLIENT_TYPE_UNKNOWN = _CLIENT_TYPE_UNKNOWN

    def __init__(
        self,
        db_client: Optional[Union["AsyncIOMotorClient", "AsyncMongoClient"]] = None,
        db_name: Optional[str] = None,
        db_url: Optional[str] = None,
        session_collection: Optional[str] = None,
        memory_collection: Optional[str] = None,
        metrics_collection: Optional[str] = None,
        eval_collection: Optional[str] = None,
        knowledge_collection: Optional[str] = None,
        culture_collection: Optional[str] = None,
        traces_collection: Optional[str] = None,
        spans_collection: Optional[str] = None,
        learnings_collection: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Async interface for interacting with a MongoDB database.

        Supports both Motor (legacy) and PyMongo async (recommended) clients.
        When both libraries are available, PyMongo async is preferred.

        Args:
            db_client (Optional[Union[AsyncIOMotorClient, AsyncMongoClient]]):
                The MongoDB async client to use. Can be either Motor's AsyncIOMotorClient
                or PyMongo's AsyncMongoClient. If not provided, a client will be created
                from db_url using the preferred available library.
            db_name (Optional[str]): The name of the database to use.
            db_url (Optional[str]): The database URL to connect to.
            session_collection (Optional[str]): Name of the collection to store sessions.
            memory_collection (Optional[str]): Name of the collection to store memories.
            metrics_collection (Optional[str]): Name of the collection to store metrics.
            eval_collection (Optional[str]): Name of the collection to store evaluation runs.
            knowledge_collection (Optional[str]): Name of the collection to store knowledge documents.
            culture_collection (Optional[str]): Name of the collection to store cultural knowledge.
            traces_collection (Optional[str]): Name of the collection to store traces.
            spans_collection (Optional[str]): Name of the collection to store spans.
            learnings_collection (Optional[str]): Name of the collection to store learnings.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If neither db_url nor db_client is provided, or if db_client type is unsupported.
            ImportError: If neither motor nor pymongo async is installed.
        """
        if id is None:
            base_seed = db_url or str(db_client)
            db_name_suffix = db_name if db_name is not None else "agno"
            seed = f"{base_seed}#{db_name_suffix}"
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
            learnings_table=learnings_collection,
        )

        # Detect client type if provided
        if db_client is not None:
            self._client_type = _detect_client_type(db_client)
            if self._client_type == self.CLIENT_TYPE_UNKNOWN:
                raise ValueError(
                    f"Unsupported MongoDB client type: {type(db_client).__name__}. "
                    "Only Motor (AsyncIOMotorClient) or PyMongo async (AsyncMongoClient) are supported."
                )
        else:
            # Auto-select preferred library when creating from URL
            # Prefer PyMongo async if available, fallback to Motor
            self._client_type = self.CLIENT_TYPE_PYMONGO_ASYNC if PYMONGO_ASYNC_AVAILABLE else self.CLIENT_TYPE_MOTOR

        # Store configuration for lazy initialization
        self._provided_client: Optional[AsyncMongoClientType] = db_client
        self.db_url: Optional[str] = db_url
        self.db_name: str = db_name if db_name is not None else "agno"

        if self._provided_client is None and self.db_url is None:
            raise ValueError("One of db_url or db_client must be provided")

        # Client and database will be lazily initialized per event loop
        self._client: Optional[AsyncMongoClientType] = None
        self._database: Optional[AsyncMongoDatabaseType] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def table_exists(self, table_name: str) -> bool:
        """Check if a collection with the given name exists in the MongoDB database.

        Args:
            table_name: Name of the collection to check

        Returns:
            bool: True if the collection exists in the database, False otherwise
        """
        collection_names = await self.database.list_collection_names()
        return table_name in collection_names

    async def _create_all_tables(self):
        """Create all configured MongoDB collections if they don't exist."""
        collections_to_create = [
            ("sessions", self.session_table_name),
            ("memories", self.memory_table_name),
            ("metrics", self.metrics_table_name),
            ("evals", self.eval_table_name),
            ("knowledge", self.knowledge_table_name),
            ("culture", self.culture_table_name),
        ]

        for collection_type, collection_name in collections_to_create:
            if collection_name and not await self.table_exists(collection_name):
                await self._get_collection(collection_type, create_collection_if_not_found=True)

    async def close(self) -> None:
        """Close the MongoDB client connection.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None

    def _ensure_client(self) -> AsyncMongoClientType:
        """
        Ensure the MongoDB async client is valid for the current event loop.

        Both Motor's AsyncIOMotorClient and PyMongo's AsyncMongoClient are tied to
        the event loop they were created in. If we detect a new event loop, we need
        to refresh the client.

        Returns:
            Union[AsyncIOMotorClient, AsyncMongoClient]: A valid client for the current event loop.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, return existing client or create new one
            if self._client is None:
                if self._provided_client is not None:
                    self._client = self._provided_client
                elif self.db_url is not None:
                    # Create client based on detected type
                    if self._client_type == self.CLIENT_TYPE_PYMONGO_ASYNC and PYMONGO_ASYNC_AVAILABLE:
                        self._client = AsyncMongoClient(self.db_url)  # type: ignore
                    elif self._client_type == self.CLIENT_TYPE_MOTOR and MOTOR_AVAILABLE:
                        self._client = AsyncIOMotorClient(self.db_url)  # type: ignore
                    else:
                        raise RuntimeError(f"Client type '{self._client_type}' not available")
            return self._client  # type: ignore

        # Check if we're in a different event loop
        if self._event_loop is None or self._event_loop is not current_loop:
            # New event loop detected, create new client
            if self._provided_client is not None:
                # User provided a client, use it but warn them
                client_type_name = (
                    "AsyncMongoClient" if self._client_type == self.CLIENT_TYPE_PYMONGO_ASYNC else "AsyncIOMotorClient"
                )
                log_debug(
                    f"New event loop detected. Using provided {client_type_name}, "
                    "which may cause issues if it was created in a different event loop."
                )
                self._client = self._provided_client
            elif self.db_url is not None:
                if self._client_type == self.CLIENT_TYPE_PYMONGO_ASYNC and PYMONGO_ASYNC_AVAILABLE:
                    self._client = AsyncMongoClient(self.db_url)  # type: ignore
                elif self._client_type == self.CLIENT_TYPE_MOTOR and MOTOR_AVAILABLE:
                    self._client = AsyncIOMotorClient(self.db_url)  # type: ignore
                else:
                    raise RuntimeError(f"Client type '{self._client_type}' not available")

            self._event_loop = current_loop
            self._database = None  # Reset database reference
            # Clear collection caches and initialization flags when switching event loops
            for attr in list(vars(self).keys()):
                if attr.endswith("_collection") or attr.endswith("_initialized"):
                    delattr(self, attr)

        return self._client  # type: ignore

    @property
    def db_client(self) -> AsyncMongoClientType:
        """Get the MongoDB client, ensuring it's valid for the current event loop."""
        return self._ensure_client()

    @property
    def database(self) -> AsyncMongoDatabaseType:
        """Get the MongoDB database, ensuring it's valid for the current event loop."""
        try:
            current_loop = asyncio.get_running_loop()
            if self._database is None or self._event_loop != current_loop:
                self._database = self.db_client[self.db_name]  # type: ignore
        except RuntimeError:
            # No running loop - fallback to existing database or create new one
            if self._database is None:
                self._database = self.db_client[self.db_name]  # type: ignore
        return self._database

    # -- DB methods --

    def _should_reset_collection_cache(self) -> bool:
        """Check if collection cache should be reset due to event loop change."""
        try:
            current_loop = asyncio.get_running_loop()
            return self._event_loop is not current_loop
        except RuntimeError:
            return False

    async def _get_collection(
        self, table_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[AsyncMongoCollectionType]:
        """Get or create a collection based on table type.

        Args:
            table_type (str): The type of table to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[AsyncIOMotorCollection, AsyncCollection]: The collection object.
        """
        # Ensure client is valid for current event loop before accessing collections
        _ = self.db_client  # This triggers _ensure_client()

        # Check if collections need to be reset due to event loop change
        reset_cache = self._should_reset_collection_cache()

        if table_type == "sessions":
            if reset_cache or not hasattr(self, "session_collection"):
                if self.session_table_name is None:
                    raise ValueError("Session collection was not provided on initialization")
                self.session_collection = await self._get_or_create_collection(
                    collection_name=self.session_table_name,
                    collection_type="sessions",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.session_collection

        if table_type == "memories":
            if reset_cache or not hasattr(self, "memory_collection"):
                if self.memory_table_name is None:
                    raise ValueError("Memory collection was not provided on initialization")
                self.memory_collection = await self._get_or_create_collection(
                    collection_name=self.memory_table_name,
                    collection_type="memories",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.memory_collection

        if table_type == "metrics":
            if reset_cache or not hasattr(self, "metrics_collection"):
                if self.metrics_table_name is None:
                    raise ValueError("Metrics collection was not provided on initialization")
                self.metrics_collection = await self._get_or_create_collection(
                    collection_name=self.metrics_table_name,
                    collection_type="metrics",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.metrics_collection

        if table_type == "evals":
            if reset_cache or not hasattr(self, "eval_collection"):
                if self.eval_table_name is None:
                    raise ValueError("Eval collection was not provided on initialization")
                self.eval_collection = await self._get_or_create_collection(
                    collection_name=self.eval_table_name,
                    collection_type="evals",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.eval_collection

        if table_type == "knowledge":
            if reset_cache or not hasattr(self, "knowledge_collection"):
                if self.knowledge_table_name is None:
                    raise ValueError("Knowledge collection was not provided on initialization")
                self.knowledge_collection = await self._get_or_create_collection(
                    collection_name=self.knowledge_table_name,
                    collection_type="knowledge",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.knowledge_collection

        if table_type == "culture":
            if reset_cache or not hasattr(self, "culture_collection"):
                if self.culture_table_name is None:
                    raise ValueError("Culture collection was not provided on initialization")
                self.culture_collection = await self._get_or_create_collection(
                    collection_name=self.culture_table_name,
                    collection_type="culture",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.culture_collection

        if table_type == "traces":
            if reset_cache or not hasattr(self, "traces_collection"):
                if self.trace_table_name is None:
                    raise ValueError("Traces collection was not provided on initialization")
                self.traces_collection = await self._get_or_create_collection(
                    collection_name=self.trace_table_name,
                    collection_type="traces",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.traces_collection

        if table_type == "spans":
            if reset_cache or not hasattr(self, "spans_collection"):
                if self.span_table_name is None:
                    raise ValueError("Spans collection was not provided on initialization")
                self.spans_collection = await self._get_or_create_collection(
                    collection_name=self.span_table_name,
                    collection_type="spans",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.spans_collection

        if table_type == "learnings":
            if reset_cache or not hasattr(self, "learnings_collection"):
                if self.learnings_table_name is None:
                    raise ValueError("Learnings collection was not provided on initialization")
                self.learnings_collection = await self._get_or_create_collection(
                    collection_name=self.learnings_table_name,
                    collection_type="learnings",
                    create_collection_if_not_found=create_collection_if_not_found,
                )
            return self.learnings_collection

        raise ValueError(f"Unknown table type: {table_type}")

    async def _get_or_create_collection(
        self, collection_name: str, collection_type: str, create_collection_if_not_found: Optional[bool] = True
    ) -> Optional[AsyncMongoCollectionType]:
        """Get or create a collection with proper indexes.

        Args:
            collection_name (str): The name of the collection to get or create.
            collection_type (str): The type of collection to get or create.
            create_collection_if_not_found (Optional[bool]): Whether to create the collection if it doesn't exist.

        Returns:
            Union[AsyncIOMotorCollection, AsyncCollection]: The collection object.
        """
        try:
            collection = self.database[collection_name]

            if not hasattr(self, f"_{collection_name}_initialized"):
                if not create_collection_if_not_found:
                    return None
                # Create indexes asynchronously for async MongoDB collections
                await create_collection_indexes_async(collection, collection_type)
                setattr(self, f"_{collection_name}_initialized", True)
                log_debug(f"Initialized collection '{collection_name}'")
            else:
                log_debug(f"Collection '{collection_name}' already initialized")

            return collection

        except Exception as e:
            log_error(f"Error getting collection {collection_name}: {e}")
            raise

    def get_latest_schema_version(self):
        """Get the latest version of the database schema."""
        pass

    def upsert_schema_version(self, version: str) -> None:
        """Upsert the schema version into the database."""
        pass

    # -- Session methods --

    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
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
            collection = await self._get_collection(table_type="sessions")
            if collection is None:
                return False

            query: Dict[str, Any] = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            result = await collection.delete_one(query)
            if result.deleted_count == 0:
                log_debug(f"No session found to delete with session_id: {session_id}")
                return False
            else:
                log_debug(f"Successfully deleted session with session_id: {session_id}")
                return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

    async def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple sessions from the database.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
        """
        try:
            collection = await self._get_collection(table_type="sessions")
            if collection is None:
                return

            query: Dict[str, Any] = {"session_id": {"$in": session_ids}}
            if user_id is not None:
                query["user_id"] = user_id
            result = await collection.delete_many(query)
            log_debug(f"Successfully deleted {result.deleted_count} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")
            raise e

    async def get_session(
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
            collection = await self._get_collection(table_type="sessions")
            if collection is None:
                return None

            query = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            if session_type is not None:
                query["session_type"] = session_type

            result = await collection.find_one(query)
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

    async def get_sessions(
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
            collection = await self._get_collection(table_type="sessions")
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
            total_count = await collection.count_documents(query)

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

            records = await cursor.to_list(length=None)
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
            raise e

    async def rename_session(
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
            collection = await self._get_collection(table_type="sessions")
            if collection is None:
                return None

            query: Dict[str, Any] = {"session_id": session_id}
            if user_id is not None:
                query["user_id"] = user_id
            try:
                result = await collection.find_one_and_update(
                    query,
                    {"$set": {"session_data.session_name": session_name, "updated_at": int(time.time())}},
                    return_document=ReturnDocument.AFTER,
                    upsert=False,
                )
            except OperationFailure:
                # If the update fails because session_data doesn't contain a session_name yet, we initialize session_data
                result = await collection.find_one_and_update(
                    query,
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
            raise e

    async def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update a session in the database.

        Args:
            session (Session): The session to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]: The upserted session.

        Raises:
            Exception: If there is an error upserting the session.
        """
        try:
            collection = await self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            if collection is None:
                return None

            session_dict = session.to_dict()

            existing = await collection.find_one({"session_id": session_dict.get("session_id")}, {"user_id": 1})
            if existing:
                existing_uid = existing.get("user_id")
                if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                    return None

            incoming_uid = session_dict.get("user_id")
            upsert_filter: Dict[str, Any] = {"session_id": session_dict.get("session_id")}
            if incoming_uid is not None:
                upsert_filter["$or"] = [{"user_id": incoming_uid}, {"user_id": None}, {"user_id": {"$exists": False}}]
            else:
                upsert_filter["$or"] = [{"user_id": None}, {"user_id": {"$exists": False}}]

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

                try:
                    result = await collection.find_one_and_replace(
                        filter=upsert_filter,
                        replacement=record,
                        upsert=True,
                        return_document=ReturnDocument.AFTER,
                    )
                except DuplicateKeyError:
                    return None
                if not result:
                    return None

                session = result  # type: ignore

                if not deserialize:
                    return session

                return AgentSession.from_dict(session)  # type: ignore

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

                try:
                    result = await collection.find_one_and_replace(
                        filter=upsert_filter,
                        replacement=record,
                        upsert=True,
                        return_document=ReturnDocument.AFTER,
                    )
                except DuplicateKeyError:
                    return None
                if not result:
                    return None

                # MongoDB stores native objects, no deserialization needed for document fields
                session = result  # type: ignore

                if not deserialize:
                    return session

                return TeamSession.from_dict(session)  # type: ignore

            else:
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

                try:
                    result = await collection.find_one_and_replace(
                        filter=upsert_filter,
                        replacement=record,
                        upsert=True,
                        return_document=ReturnDocument.AFTER,
                    )
                except DuplicateKeyError:
                    return None
                if not result:
                    return None

                session = result  # type: ignore

                if not deserialize:
                    return session

                return WorkflowSession.from_dict(session)  # type: ignore

        except Exception as e:
            log_error(f"Exception upserting session: {e}")
            raise e

    async def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions for improved performance on large datasets.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the session object.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            collection = await self._get_collection(table_type="sessions", create_collection_if_not_found=True)
            if collection is None:
                log_info("Sessions collection not available, falling back to individual upserts")
                return [
                    result
                    for session in sessions
                    if session is not None
                    for result in [await self.upsert_session(session, deserialize=deserialize)]
                    if result is not None
                ]

            from pymongo import ReplaceOne

            operations = []
            results: List[Union[Session, Dict[str, Any]]] = []

            for session in sessions:
                if session is None:
                    continue

                session_dict = session.to_dict()

                # Use preserved updated_at if flag is set and value exists, otherwise use current time
                updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())

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
                        "updated_at": updated_at,
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
                        "updated_at": updated_at,
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
                        "updated_at": updated_at,
                    }
                else:
                    continue

                operations.append(
                    ReplaceOne(filter={"session_id": record["session_id"]}, replacement=record, upsert=True)
                )

            if operations:
                # Execute bulk write
                await collection.bulk_write(operations)

                # Fetch the results
                session_ids = [session.session_id for session in sessions if session and session.session_id]
                cursor = collection.find({"session_id": {"$in": session_ids}})

                async for doc in cursor:
                    session_dict = doc

                    if deserialize:
                        session_type = doc.get("session_type")
                        if session_type == SessionType.AGENT.value:
                            deserialized_agent_session = AgentSession.from_dict(session_dict)
                            if deserialized_agent_session is None:
                                continue
                            results.append(deserialized_agent_session)

                        elif session_type == SessionType.TEAM.value:
                            deserialized_team_session = TeamSession.from_dict(session_dict)
                            if deserialized_team_session is None:
                                continue
                            results.append(deserialized_team_session)

                        elif session_type == SessionType.WORKFLOW.value:
                            deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                            if deserialized_workflow_session is None:
                                continue
                            results.append(deserialized_workflow_session)
                    else:
                        results.append(session_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert, falling back to individual upserts: {e}")

            # Fallback to individual upserts
            return [
                result
                for session in sessions
                if session is not None
                for result in [await self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only delete if the memory belongs to this user.

        Returns:
            bool: True if the memory was deleted, False otherwise.

        Raises:
            Exception: If there is an error deleting the memory.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return

            query = {"memory_id": memory_id}
            if user_id is not None:
                query["user_id"] = user_id

            result = await collection.delete_one(query)

            success = result.deleted_count > 0
            if success:
                log_debug(f"Successfully deleted memory id: {memory_id}")
            else:
                log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")
            raise e

    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only delete memories that belong to this user.

        Raises:
            Exception: If there is an error deleting the memories.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return

            query: Dict[str, Any] = {"memory_id": {"$in": memory_ids}}
            if user_id is not None:
                query["user_id"] = user_id

            result = await collection.delete_many(query)

            if result.deleted_count == 0:
                log_debug(f"No memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")
            raise e

    async def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Returns:
            List[str]: The topics.

        Raises:
            Exception: If there is an error getting the topics.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return []

            query = {}
            if user_id is not None:
                query["user_id"] = user_id

            topics = await collection.distinct("topics", query)
            return [topic for topic in topics if topic]

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
            raise e

    async def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user to verify ownership. If provided, only return the memory if it belongs to this user.

        Returns:
            Optional[UserMemory]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If there is an error getting the memory.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return None

            query = {"memory_id": memory_id}
            if user_id is not None:
                query["user_id"] = user_id

            result = await collection.find_one(query)
            if result is None or not deserialize:
                return result

            # Remove MongoDB's _id field before creating UserMemory object
            result_filtered = {k: v for k, v in result.items() if k != "_id"}
            return UserMemory.from_dict(result_filtered)

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
            raise e

    async def get_user_memories(
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

        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If there is an error getting the memories.
        """
        try:
            collection = await self._get_collection(table_type="memories")
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
            total_count = await collection.count_documents(query)

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

            records = await cursor.to_list(length=None)
            if not deserialize:
                return records, total_count

            # Remove MongoDB's _id field before creating UserMemory objects
            return [UserMemory.from_dict({k: v for k, v in record.items() if k != "_id"}) for record in records]

        except Exception as e:
            log_error(f"Exception reading from collection: {e}")
            raise e

    async def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The limit of the memories to get.
            page (Optional[int]): The page number to get.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A tuple containing the memories stats and the total count.

        Raises:
            Exception: If there is an error getting the memories stats.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return [], 0

            match_stage: Dict[str, Any] = {"user_id": {"$ne": None}}
            if user_id is not None:
                match_stage["user_id"] = user_id

            pipeline = [
                {"$match": match_stage},
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
            count_result = await collection.aggregate(count_pipeline).to_list(length=1)
            total_count = count_result[0]["total"] if count_result else 0

            # Apply pagination
            if limit is not None:
                if page is not None:
                    pipeline.append({"$skip": (page - 1) * limit})  # type: ignore
                pipeline.append({"$limit": limit})  # type: ignore

            results = await collection.aggregate(pipeline).to_list(length=None)

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
            raise e

    async def upsert_user_memory(
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
            collection = await self._get_collection(table_type="memories", create_collection_if_not_found=True)
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

            result = await collection.replace_one({"memory_id": memory.memory_id}, update_doc, upsert=True)

            if result.upserted_id:
                update_doc["_id"] = result.upserted_id

            if not deserialize:
                return update_doc

            # Remove MongoDB's _id field before creating UserMemory object
            update_doc_filtered = {k: v for k, v in update_doc.items() if k != "_id"}
            return UserMemory.from_dict(update_doc_filtered)

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            raise e

    async def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories for improved performance on large datasets.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the memory object.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            collection = await self._get_collection(table_type="memories", create_collection_if_not_found=True)
            if collection is None:
                log_info("Memories collection not available, falling back to individual upserts")
                return [
                    result
                    for memory in memories
                    if memory is not None
                    for result in [await self.upsert_user_memory(memory, deserialize=deserialize)]
                    if result is not None
                ]

            from pymongo import ReplaceOne

            operations = []
            results: List[Union[UserMemory, Dict[str, Any]]] = []

            current_time = int(time.time())
            for memory in memories:
                if memory is None:
                    continue

                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                # Use preserved updated_at if flag is set and value exists, otherwise use current time
                updated_at = memory.updated_at if preserve_updated_at else current_time

                record = {
                    "user_id": memory.user_id,
                    "agent_id": memory.agent_id,
                    "team_id": memory.team_id,
                    "memory_id": memory.memory_id,
                    "memory": memory.memory,
                    "topics": memory.topics,
                    "input": memory.input,
                    "feedback": memory.feedback,
                    "created_at": memory.created_at,
                    "updated_at": updated_at,
                }

                operations.append(ReplaceOne(filter={"memory_id": memory.memory_id}, replacement=record, upsert=True))

            if operations:
                # Execute bulk write
                await collection.bulk_write(operations)

                # Fetch the results
                memory_ids = [memory.memory_id for memory in memories if memory and memory.memory_id]
                cursor = collection.find({"memory_id": {"$in": memory_ids}})

                async for doc in cursor:
                    if deserialize:
                        # Remove MongoDB's _id field before creating UserMemory object
                        doc_filtered = {k: v for k, v in doc.items() if k != "_id"}
                        results.append(UserMemory.from_dict(doc_filtered))
                    else:
                        results.append(doc)

            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert, falling back to individual upserts: {e}")

            # Fallback to individual upserts
            return [
                result
                for memory in memories
                if memory is not None
                for result in [await self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

    async def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = await self._get_collection(table_type="memories")
            if collection is None:
                return

            await collection.delete_many({})

        except Exception as e:
            log_error(f"Exception deleting all memories: {e}")
            raise e

    # -- Cultural Knowledge methods --
    async def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = await self._get_collection(table_type="culture")
            if collection is None:
                return

            await collection.delete_many({})

        except Exception as e:
            log_error(f"Exception deleting all cultural knowledge: {e}")
            raise e

    async def delete_cultural_knowledge(self, id: str) -> None:
        """Delete cultural knowledge by ID.

        Args:
            id (str): The ID of the cultural knowledge to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = await self._get_collection(table_type="culture")
            if collection is None:
                return

            await collection.delete_one({"id": id})
            log_debug(f"Deleted cultural knowledge with ID: {id}")

        except Exception as e:
            log_error(f"Error deleting cultural knowledge: {e}")
            raise e

    async def get_cultural_knowledge(
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
            collection = await self._get_collection(table_type="culture")
            if collection is None:
                return None

            result = await collection.find_one({"id": id})
            if result is None:
                return None

            # Remove MongoDB's _id field
            result_filtered = {k: v for k, v in result.items() if k != "_id"}

            if not deserialize:
                return result_filtered

            return deserialize_cultural_knowledge_from_db(result_filtered)

        except Exception as e:
            log_error(f"Error getting cultural knowledge: {e}")
            raise e

    async def get_all_cultural_knowledge(
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
            collection = await self._get_collection(table_type="culture")
            if collection is None:
                if not deserialize:
                    return [], 0
                return []

            # Build query
            query: Dict[str, Any] = {}
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if name is not None:
                query["name"] = {"$regex": name, "$options": "i"}

            # Get total count for pagination
            total_count = await collection.count_documents(query)

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

            # Remove MongoDB's _id field from all results
            results_filtered = [{k: v for k, v in item.items() if k != "_id"} async for item in cursor]

            if not deserialize:
                return results_filtered, total_count

            return [deserialize_cultural_knowledge_from_db(item) for item in results_filtered]

        except Exception as e:
            log_error(f"Error getting all cultural knowledge: {e}")
            raise e

    async def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert cultural knowledge in MongoDB.

        Args:
            cultural_knowledge (CulturalKnowledge): The cultural knowledge to upsert.
            deserialize (Optional[bool]): Whether to deserialize the result. Defaults to True.

        Returns:
            Optional[Union[CulturalKnowledge, Dict[str, Any]]]: The upserted cultural knowledge.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection = await self._get_collection(table_type="culture", create_collection_if_not_found=True)
            if collection is None:
                return None

            # Serialize content, categories, and notes into a dict for DB storage
            content_dict = serialize_cultural_knowledge_for_db(cultural_knowledge)

            # Create the document with serialized content
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

            result = await collection.replace_one({"id": cultural_knowledge.id}, update_doc, upsert=True)

            if result.upserted_id:
                update_doc["_id"] = result.upserted_id

            # Remove MongoDB's _id field
            doc_filtered = {k: v for k, v in update_doc.items() if k != "_id"}

            if not deserialize:
                return doc_filtered

            return deserialize_cultural_knowledge_from_db(doc_filtered)

        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

    # -- Metrics methods --

    async def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions of all types for metrics calculation."""
        try:
            collection = await self._get_collection(table_type="sessions")
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

            results = await collection.find(query, projection).to_list(length=None)
            return results

        except Exception as e:
            log_error(f"Exception reading from sessions collection: {e}")
            return []

    async def _get_metrics_calculation_starting_date(self, collection: AsyncMongoCollectionType) -> Optional[date]:
        """Get the first date for which metrics calculation is needed."""
        try:
            result = await collection.find_one({}, sort=[("date", -1)], limit=1)

            if result is not None:
                result_date = datetime.strptime(result["date"], "%Y-%m-%d").date()
                if result.get("completed"):
                    return result_date + timedelta(days=1)
                else:
                    return result_date

            # No metrics records. Return the date of the first recorded session.
            first_session_result = await self.get_sessions(
                sort_by="created_at", sort_order="asc", limit=1, deserialize=False
            )
            first_session_date = first_session_result[0][0]["created_at"] if first_session_result[0] else None  # type: ignore

            if first_session_date is None:
                return None

            return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

        except Exception as e:
            log_error(f"Exception getting metrics calculation starting date: {e}")
            return None

    async def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics."""
        try:
            collection = await self._get_collection(table_type="metrics", create_collection_if_not_found=True)
            if collection is None:
                return None

            starting_date = await self._get_metrics_calculation_starting_date(collection)
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

            sessions = await self._get_all_sessions_for_metrics_calculation(
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
                results = bulk_upsert_metrics(collection, metrics_records)  # type: ignore

            return results

        except Exception as e:
            log_error(f"Error calculating metrics: {e}")
            raise e

    async def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range."""
        try:
            collection = await self._get_collection(table_type="metrics")
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

            records = await collection.find(query).to_list(length=None)
            if not records:
                return [], None

            # Get the latest updated_at
            latest_updated_at = max(record.get("updated_at", 0) for record in records)

            return records, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {e}")
            raise e

    # -- Knowledge methods --

    async def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            collection = await self._get_collection(table_type="knowledge")
            if collection is None:
                return

            await collection.delete_one({"id": id})

            log_debug(f"Deleted knowledge content with id '{id}'")

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    async def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            collection = await self._get_collection(table_type="knowledge")
            if collection is None:
                return None

            result = await collection.find_one({"id": id})
            if result is None:
                return None

            return KnowledgeRow.model_validate(result)

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            raise e

    async def get_knowledge_contents(
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
            collection = await self._get_collection(table_type="knowledge")
            if collection is None:
                return [], 0

            query: Dict[str, Any] = {}

            # Apply linked_to filter if provided
            if linked_to is not None:
                query["linked_to"] = linked_to

            # Get total count
            total_count = await collection.count_documents(query)

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

            records = await cursor.to_list(length=None)
            knowledge_rows = [KnowledgeRow.model_validate(record) for record in records]

            return knowledge_rows, total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            raise e

    async def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            collection = await self._get_collection(table_type="knowledge", create_collection_if_not_found=True)
            if collection is None:
                return None

            update_doc = knowledge_row.model_dump()
            await collection.replace_one({"id": knowledge_row.id}, update_doc, upsert=True)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {e}")
            raise e

    # -- Eval methods --

    async def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            collection = await self._get_collection(table_type="evals", create_collection_if_not_found=True)
            if collection is None:
                return None

            current_time = int(time.time())
            eval_dict = eval_run.model_dump()
            eval_dict["created_at"] = current_time
            eval_dict["updated_at"] = current_time

            await collection.insert_one(eval_dict)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

    async def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database."""
        try:
            collection = await self._get_collection(table_type="evals")
            if collection is None:
                return

            result = await collection.delete_one({"run_id": eval_run_id})

            if result.deleted_count == 0:
                log_debug(f"No eval run found with ID: {eval_run_id}")
            else:
                log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise e

    async def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database."""
        try:
            collection = await self._get_collection(table_type="evals")
            if collection is None:
                return

            result = await collection.delete_many({"run_id": {"$in": eval_run_ids}})

            if result.deleted_count == 0:
                log_debug(f"No eval runs found with IDs: {eval_run_ids}")
            else:
                log_debug(f"Deleted {result.deleted_count} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise e

    async def get_eval_run_raw(self, eval_run_id: str) -> Optional[Dict[str, Any]]:
        """Get an eval run from the database as a raw dictionary."""
        try:
            collection = await self._get_collection(table_type="evals")
            if collection is None:
                return None

            result = await collection.find_one({"run_id": eval_run_id})
            return result

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
            raise e

    async def get_eval_run(
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
            collection = await self._get_collection(table_type="evals")
            if collection is None:
                return None

            eval_run_raw = await collection.find_one({"run_id": eval_run_id})

            if not eval_run_raw:
                return None

            if not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
            raise e

    async def get_eval_runs(
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

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of eval run dictionaries and the total count

        Raises:
            Exception: If there is an error getting the eval runs.
        """
        try:
            collection = await self._get_collection(table_type="evals")
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
            total_count = await collection.count_documents(query)

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

            records = await cursor.to_list(length=None)
            if not records:
                return [] if deserialize else ([], 0)

            if not deserialize:
                return records, total_count

            return [EvalRunRecord.model_validate(row) for row in records]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            raise e

    async def rename_eval_run(
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
            collection = await self._get_collection(table_type="evals")
            if collection is None:
                return None

            result = await collection.find_one_and_update(
                {"run_id": eval_run_id}, {"$set": {"name": name, "updated_at": int(time.time())}}
            )

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not result or not deserialize:
                return result

            return EvalRunRecord.model_validate(result)

        except Exception as e:
            log_error(f"Error updating eval run name {eval_run_id}: {e}")
            raise e

    # --- Traces ---
    def _get_component_level(
        self, workflow_id: Optional[str], team_id: Optional[str], agent_id: Optional[str], name: str
    ) -> int:
        """Get the component level for a trace based on its context.

        Component levels (higher = more important):
            - 3: Workflow root (.run or .arun with workflow_id)
            - 2: Team root (.run or .arun with team_id)
            - 1: Agent root (.run or .arun with agent_id)
            - 0: Child span (not a root)

        Args:
            workflow_id: The workflow ID of the trace.
            team_id: The team ID of the trace.
            agent_id: The agent ID of the trace.
            name: The name of the trace.

        Returns:
            int: The component level (0-3).
        """
        # Check if name indicates a root span
        is_root_name = ".run" in name or ".arun" in name

        if not is_root_name:
            return 0  # Child span (not a root)
        elif workflow_id:
            return 3  # Workflow root
        elif team_id:
            return 2  # Team root
        elif agent_id:
            return 1  # Agent root
        else:
            return 0  # Unknown

    async def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses MongoDB's update_one with upsert=True and aggregation pipeline
        to handle concurrent inserts atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            collection = await self._get_collection(table_type="traces", create_collection_if_not_found=True)
            if collection is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)

            # Calculate the component level for the new trace
            new_level = self._get_component_level(trace.workflow_id, trace.team_id, trace.agent_id, trace.name)

            # Use MongoDB aggregation pipeline update for atomic upsert
            # This allows conditional logic within a single atomic operation
            pipeline: List[Dict[str, Any]] = [
                {
                    "$set": {
                        # Always update these fields
                        "status": trace.status,
                        "created_at": {"$ifNull": ["$created_at", trace_dict.get("created_at")]},
                        # Use $min for start_time (keep earliest)
                        "start_time": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$start_time"}, "missing"]},
                                "then": trace_dict.get("start_time"),
                                "else": {"$min": ["$start_time", trace_dict.get("start_time")]},
                            }
                        },
                        # Use $max for end_time (keep latest)
                        "end_time": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$end_time"}, "missing"]},
                                "then": trace_dict.get("end_time"),
                                "else": {"$max": ["$end_time", trace_dict.get("end_time")]},
                            }
                        },
                        # Preserve existing non-null context values using $ifNull
                        "run_id": {"$ifNull": [trace.run_id, "$run_id"]},
                        "session_id": {"$ifNull": [trace.session_id, "$session_id"]},
                        "user_id": {"$ifNull": [trace.user_id, "$user_id"]},
                        "agent_id": {"$ifNull": [trace.agent_id, "$agent_id"]},
                        "team_id": {"$ifNull": [trace.team_id, "$team_id"]},
                        "workflow_id": {"$ifNull": [trace.workflow_id, "$workflow_id"]},
                    }
                },
                {
                    "$set": {
                        # Calculate duration_ms from the (potentially updated) start_time and end_time
                        # MongoDB stores dates as strings in ISO format, so we need to parse them
                        "duration_ms": {
                            "$cond": {
                                "if": {
                                    "$and": [
                                        {"$ne": [{"$type": "$start_time"}, "missing"]},
                                        {"$ne": [{"$type": "$end_time"}, "missing"]},
                                    ]
                                },
                                "then": {
                                    "$subtract": [
                                        {"$toLong": {"$toDate": "$end_time"}},
                                        {"$toLong": {"$toDate": "$start_time"}},
                                    ]
                                },
                                "else": trace_dict.get("duration_ms", 0),
                            }
                        },
                        # Update name based on component level priority
                        # Only update if new trace is from a higher-level component
                        "name": {
                            "$cond": {
                                "if": {"$eq": [{"$type": "$name"}, "missing"]},
                                "then": trace.name,
                                "else": {
                                    "$cond": {
                                        "if": {
                                            "$gt": [
                                                new_level,
                                                {
                                                    "$switch": {
                                                        "branches": [
                                                            # Check if existing name is a root span
                                                            {
                                                                "case": {
                                                                    "$not": {
                                                                        "$or": [
                                                                            {
                                                                                "$regexMatch": {
                                                                                    "input": {"$ifNull": ["$name", ""]},
                                                                                    "regex": "\\.run",
                                                                                }
                                                                            },
                                                                            {
                                                                                "$regexMatch": {
                                                                                    "input": {"$ifNull": ["$name", ""]},
                                                                                    "regex": "\\.arun",
                                                                                }
                                                                            },
                                                                        ]
                                                                    }
                                                                },
                                                                "then": 0,
                                                            },
                                                            # Workflow root (level 3)
                                                            {
                                                                "case": {"$ne": ["$workflow_id", None]},
                                                                "then": 3,
                                                            },
                                                            # Team root (level 2)
                                                            {
                                                                "case": {"$ne": ["$team_id", None]},
                                                                "then": 2,
                                                            },
                                                            # Agent root (level 1)
                                                            {
                                                                "case": {"$ne": ["$agent_id", None]},
                                                                "then": 1,
                                                            },
                                                        ],
                                                        "default": 0,
                                                    }
                                                },
                                            ]
                                        },
                                        "then": trace.name,
                                        "else": "$name",
                                    }
                                },
                            }
                        },
                    }
                },
            ]

            # Perform atomic upsert using aggregation pipeline
            await collection.update_one(
                {"trace_id": trace.trace_id},
                pipeline,
                upsert=True,
            )

        except Exception as e:
            log_error(f"Error creating trace: {e}")
            # Don't raise - tracing should not break the main application flow

    async def get_trace(
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
            from agno.tracing.schemas import Trace as TraceSchema

            collection = await self._get_collection(table_type="traces")
            if collection is None:
                return None

            # Get spans collection for aggregation
            spans_collection = await self._get_collection(table_type="spans")

            query: Dict[str, Any] = {}
            if trace_id:
                query["trace_id"] = trace_id
            elif run_id:
                query["run_id"] = run_id
            else:
                log_debug("get_trace called without any filter parameters")
                return None

            # Find trace with sorting by most recent
            result = await collection.find_one(query, sort=[("start_time", -1)])

            if result:
                # Calculate total_spans and error_count from spans collection
                total_spans = 0
                error_count = 0
                if spans_collection is not None:
                    total_spans = await spans_collection.count_documents({"trace_id": result["trace_id"]})
                    error_count = await spans_collection.count_documents(
                        {"trace_id": result["trace_id"], "status_code": "ERROR"}
                    )

                result["total_spans"] = total_spans
                result["error_count"] = error_count
                # Remove MongoDB's _id field
                result.pop("_id", None)
                return TraceSchema.from_dict(result)
            return None

        except Exception as e:
            log_error(f"Error getting trace: {e}")
            return None

    async def get_traces(
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
        """Get traces matching the provided filters with pagination.

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
            from agno.tracing.schemas import Trace as TraceSchema

            collection = await self._get_collection(table_type="traces")
            if collection is None:
                log_debug("Traces collection not found")
                return [], 0

            # Get spans collection for aggregation
            spans_collection = await self._get_collection(table_type="spans")

            # Build query
            query: Dict[str, Any] = {}
            if run_id:
                query["run_id"] = run_id
            if session_id:
                query["session_id"] = session_id
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id:
                query["agent_id"] = agent_id
            if team_id:
                query["team_id"] = team_id
            if workflow_id:
                query["workflow_id"] = workflow_id
            if status:
                query["status"] = status
            if start_time:
                query["start_time"] = {"$gte": start_time.isoformat()}
            if end_time:
                if "end_time" in query:
                    query["end_time"]["$lte"] = end_time.isoformat()
                else:
                    query["end_time"] = {"$lte": end_time.isoformat()}

            # Get total count
            total_count = await collection.count_documents(query)

            # Apply pagination
            skip = ((page or 1) - 1) * (limit or 20)
            cursor = collection.find(query).sort("start_time", -1).skip(skip).limit(limit or 20)

            results = await cursor.to_list(length=None)

            traces = []
            for row in results:
                # Calculate total_spans and error_count from spans collection
                total_spans = 0
                error_count = 0
                if spans_collection is not None:
                    total_spans = await spans_collection.count_documents({"trace_id": row["trace_id"]})
                    error_count = await spans_collection.count_documents(
                        {"trace_id": row["trace_id"], "status_code": "ERROR"}
                    )

                row["total_spans"] = total_spans
                row["error_count"] = error_count
                # Remove MongoDB's _id field
                row.pop("_id", None)
                traces.append(TraceSchema.from_dict(row))

            return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {e}")
            return [], 0

    async def get_trace_stats(
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
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                workflow_id, first_trace_at, last_trace_at.
        """
        try:
            collection = await self._get_collection(table_type="traces")
            if collection is None:
                log_debug("Traces collection not found")
                return [], 0

            # Build match stage
            match_stage: Dict[str, Any] = {"session_id": {"$ne": None}}
            if user_id is not None:
                match_stage["user_id"] = user_id
            if agent_id:
                match_stage["agent_id"] = agent_id
            if team_id:
                match_stage["team_id"] = team_id
            if workflow_id:
                match_stage["workflow_id"] = workflow_id
            if start_time:
                match_stage["created_at"] = {"$gte": start_time.isoformat()}
            if end_time:
                if "created_at" in match_stage:
                    match_stage["created_at"]["$lte"] = end_time.isoformat()
                else:
                    match_stage["created_at"] = {"$lte": end_time.isoformat()}

            # Build aggregation pipeline
            pipeline: List[Dict[str, Any]] = [
                {"$match": match_stage},
                {
                    "$group": {
                        "_id": "$session_id",
                        "user_id": {"$first": "$user_id"},
                        "agent_id": {"$first": "$agent_id"},
                        "team_id": {"$first": "$team_id"},
                        "workflow_id": {"$first": "$workflow_id"},
                        "total_traces": {"$sum": 1},
                        "first_trace_at": {"$min": "$created_at"},
                        "last_trace_at": {"$max": "$created_at"},
                    }
                },
                {"$sort": {"last_trace_at": -1}},
            ]

            # Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = await collection.aggregate(count_pipeline).to_list(length=1)
            total_count = count_result[0]["total"] if count_result else 0

            # Apply pagination
            skip = ((page or 1) - 1) * (limit or 20)
            pipeline.append({"$skip": skip})
            pipeline.append({"$limit": limit or 20})

            results = await collection.aggregate(pipeline).to_list(length=None)

            # Convert to list of dicts with datetime objects
            stats_list = []
            for row in results:
                # Convert ISO strings to datetime objects
                first_trace_at_str = row["first_trace_at"]
                last_trace_at_str = row["last_trace_at"]

                # Parse ISO format strings to datetime objects
                first_trace_at = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                last_trace_at = datetime.fromisoformat(last_trace_at_str.replace("Z", "+00:00"))

                stats_list.append(
                    {
                        "session_id": row["_id"],
                        "user_id": row["user_id"],
                        "agent_id": row["agent_id"],
                        "team_id": row["team_id"],
                        "workflow_id": row["workflow_id"],
                        "total_traces": row["total_traces"],
                        "first_trace_at": first_trace_at,
                        "last_trace_at": last_trace_at,
                    }
                )

            return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {e}")
            return [], 0

    # --- Spans ---
    async def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            collection = await self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection is None:
                return

            await collection.insert_one(span.to_dict())

        except Exception as e:
            log_error(f"Error creating span: {e}")

    async def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            collection = await self._get_collection(table_type="spans", create_collection_if_not_found=True)
            if collection is None:
                return

            span_dicts = [span.to_dict() for span in spans]
            await collection.insert_many(span_dicts)

        except Exception as e:
            log_error(f"Error creating spans batch: {e}")

    async def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span as SpanSchema

            collection = await self._get_collection(table_type="spans")
            if collection is None:
                return None

            result = await collection.find_one({"span_id": span_id})
            if result:
                # Remove MongoDB's _id field
                result.pop("_id", None)
                return SpanSchema.from_dict(result)
            return None

        except Exception as e:
            log_error(f"Error getting span: {e}")
            return None

    async def get_spans(
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
            from agno.tracing.schemas import Span as SpanSchema

            collection = await self._get_collection(table_type="spans")
            if collection is None:
                return []

            # Build query
            query: Dict[str, Any] = {}
            if trace_id:
                query["trace_id"] = trace_id
            if parent_span_id:
                query["parent_span_id"] = parent_span_id

            cursor = collection.find(query).limit(limit or 1000)
            results = await cursor.to_list(length=None)

            spans = []
            for row in results:
                # Remove MongoDB's _id field
                row.pop("_id", None)
                spans.append(SpanSchema.from_dict(row))

            return spans

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

    # -- Learning methods --
    async def get_learning(
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
        """Retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        try:
            collection = await self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return None

            # Build query
            query: Dict[str, Any] = {"learning_type": learning_type}
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if session_id is not None:
                query["session_id"] = session_id
            if namespace is not None:
                query["namespace"] = namespace
            if entity_id is not None:
                query["entity_id"] = entity_id
            if entity_type is not None:
                query["entity_type"] = entity_type

            result = await collection.find_one(query)
            if result is None:
                return None

            # Remove MongoDB's _id field
            result.pop("_id", None)
            return {"content": result.get("content")}

        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

    async def upsert_learning(
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
        """Insert or update a learning record.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        try:
            collection = await self._get_collection(table_type="learnings", create_collection_if_not_found=True)
            if collection is None:
                return

            current_time = int(time.time())

            document = {
                "learning_id": id,
                "learning_type": learning_type,
                "namespace": namespace,
                "user_id": user_id,
                "agent_id": agent_id,
                "team_id": team_id,
                "session_id": session_id,
                "entity_id": entity_id,
                "entity_type": entity_type,
                "content": content,
                "metadata": metadata,
                "updated_at": current_time,
            }

            # Use upsert to insert or update
            await collection.update_one(
                {"learning_id": id},
                {"$set": document, "$setOnInsert": {"created_at": current_time}},
                upsert=True,
            )

            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    async def delete_learning(self, id: str) -> bool:
        """Delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            collection = await self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return False

            result = await collection.delete_one({"learning_id": id})
            return result.deleted_count > 0

        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    async def get_learnings(
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
        """Get multiple learning records.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        try:
            collection = await self._get_collection(table_type="learnings", create_collection_if_not_found=False)
            if collection is None:
                return []

            # Build query
            query: Dict[str, Any] = {}
            if learning_type is not None:
                query["learning_type"] = learning_type
            if user_id is not None:
                query["user_id"] = user_id
            if agent_id is not None:
                query["agent_id"] = agent_id
            if team_id is not None:
                query["team_id"] = team_id
            if session_id is not None:
                query["session_id"] = session_id
            if namespace is not None:
                query["namespace"] = namespace
            if entity_id is not None:
                query["entity_id"] = entity_id
            if entity_type is not None:
                query["entity_type"] = entity_type

            cursor = collection.find(query)
            if limit is not None:
                cursor = cursor.limit(limit)

            results = await cursor.to_list(length=None)

            learnings = []
            for row in results:
                # Remove MongoDB's _id field
                row.pop("_id", None)
                learnings.append(row)

            return learnings

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []
