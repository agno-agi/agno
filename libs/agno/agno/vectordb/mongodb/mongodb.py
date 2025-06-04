import asyncio
import time
from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info, log_warning, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

try:
    from hashlib import md5

except ImportError:
    raise ImportError("`hashlib` not installed. Please install using `pip install hashlib`")
try:
    from pymongo import AsyncMongoClient, MongoClient, errors
    from pymongo.collection import Collection
    from pymongo.operations import SearchIndexModel

except ImportError:
    raise ImportError("`pymongo` not installed. Please install using `pip install pymongo`")


class MongoDb(VectorDb):
    """
    MongoDB Vector Database implementation with elegant handling of Atlas Search index creation.
    """

    def __init__(
        self,
        collection_name: str,
        db_url: Optional[str] = "mongodb://localhost:27017/",
        database: str = "agno",
        embedder: Optional[Embedder] = None,
        distance_metric: str = Distance.cosine,
        overwrite: bool = False,
        wait_until_index_ready_in_seconds: Optional[float] = 3,
        wait_after_insert_in_seconds: Optional[float] = 3,
        max_pool_size: int = 100,
        retry_writes: bool = True,
        client: Optional[MongoClient] = None,
        search_index_name: Optional[str] = "vector_index_1",
        cosmos_compatibility: Optional[bool] = False,
        search_type: SearchType = SearchType.vector,
        hybrid_vector_weight: float = 0.5,
        hybrid_keyword_weight: float = 0.5,
        hybrid_rank_constant: int = 60,
        **kwargs,
    ):
        """
        Initialize the MongoDb with MongoDB collection details.

        Args:
            collection_name (str): Name of the MongoDB collection.
            db_url (Optional[str]): MongoDB connection string.
            database (str): Database name.
            embedder (Embedder): Embedder instance for generating embeddings.
            distance_metric (str): Distance metric for similarity.
            overwrite (bool): Overwrite existing collection and index if True.
            wait_until_index_ready_in_seconds (float): Time in seconds to wait until the index is ready.
            wait_after_insert_in_seconds (float): Time in seconds to wait after inserting documents.
            max_pool_size (int): Maximum number of connections in the connection pool
            retry_writes (bool): Whether to retry write operations
            client (Optional[MongoClient]): An existing MongoClient instance.
            search_index_name (str): Name of the search index (default: "vector_index_1")
            cosmos_compatibility (bool): Whether to use Azure Cosmos DB Mongovcore compatibility mode.
            search_type: The search type to use when searching for documents.
            hybrid_vector_weight (float): Default weight for vector search results in hybrid search.
            hybrid_keyword_weight (float): Default weight for keyword search results in hybrid search.
            hybrid_rank_constant (int): Default rank constant (k) for Reciprocal Rank Fusion in hybrid search. This constant is added to the rank before taking the reciprocal, helping to smooth scores. A common value is 60.
            **kwargs: Additional arguments for MongoClient.
        """
        if not collection_name:
            raise ValueError("Collection name must not be empty.")
        if not database:
            raise ValueError("Database name must not be empty.")
        self.collection_name = collection_name
        self.database = database
        self.search_index_name = search_index_name
        self.cosmos_compatibility = cosmos_compatibility
        self.search_type = search_type
        self.hybrid_vector_weight = hybrid_vector_weight
        self.hybrid_keyword_weight = hybrid_keyword_weight
        self.hybrid_rank_constant = hybrid_rank_constant

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder = embedder

        self.distance_metric = distance_metric
        self.connection_string = db_url
        self.overwrite = overwrite
        self.wait_until_index_ready_in_seconds = wait_until_index_ready_in_seconds
        self.wait_after_insert_in_seconds = wait_after_insert_in_seconds
        self.kwargs = kwargs
        self.kwargs.update(
            {
                "maxPoolSize": max_pool_size,
                "retryWrites": retry_writes,
                "serverSelectionTimeoutMS": 5000,  # 5 second timeout
            }
        )

        self._client = client
        self._db = None
        self._collection: Optional[Collection] = None

        self._async_client: Optional[AsyncMongoClient] = None
        self._async_db = None
        self._async_collection: Optional[Collection] = None

    def _get_client(self) -> MongoClient:
        """Create or retrieve the MongoDB client."""
        if self._client is None:
            if self.cosmos_compatibility:
                try:
                    log_debug("Creating MongoDB Client for Azure Cosmos DB")
                    # Cosmos DB specific settings
                    cosmos_kwargs = {
                        "retryWrites": False,
                        "ssl": True,
                        "tlsAllowInvalidCertificates": True,
                        "maxPoolSize": 100,
                        "maxIdleTimeMS": 30000,
                    }

                    # Suppress UserWarning about CosmosDB
                    import warnings

                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore", category=UserWarning, message=".*connected to a CosmosDB cluster.*"
                        )
                        self._client = MongoClient(self.connection_string, **cosmos_kwargs)  # type: ignore

                        self._client.admin.command("ping")

                    log_info("Connected to Azure Cosmos DB successfully.")
                    self._db = self._client.get_database(self.database)  # type: ignore
                    log_info(f"Using database: {self.database}")

                except errors.ConnectionFailure as e:
                    raise ConnectionError(f"Failed to connect to Azure Cosmos DB: {e}")
                except Exception as e:
                    logger.error(f"An error occurred while connecting to Azure Cosmos DB: {e}")
                    raise
            else:
                try:
                    log_debug("Creating MongoDB Client")
                    self._client = MongoClient(self.connection_string, **self.kwargs)
                    # Trigger a connection to verify the client
                    self._client.admin.command("ping")
                    log_info("Connected to MongoDB successfully.")
                    self._db = self._client[self.database]  # type: ignore
                except errors.ConnectionFailure as e:
                    logger.error(f"Failed to connect to MongoDB: {e}")
                    raise ConnectionError(f"Failed to connect to MongoDB: {e}")
                except Exception as e:
                    logger.error(f"An error occurred while connecting to MongoDB: {e}")
                    raise
        return self._client

    async def _get_async_client(self) -> AsyncMongoClient:
        """Create or retrieve the async MongoDB client."""
        if self._async_client is None:
            log_debug("Creating Async MongoDB Client")
            self._async_client = AsyncMongoClient(
                self.connection_string,
                maxPoolSize=self.kwargs.get("maxPoolSize", 100),
                retryWrites=self.kwargs.get("retryWrites", True),
                serverSelectionTimeoutMS=5000,
            )
            # Verify connection
            try:
                await self._async_client.admin.command("ping")
                log_info("Connected to MongoDB asynchronously.")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB asynchronously: {e}")
                raise
        return self._async_client

    def _get_or_create_collection(self) -> Collection:
        """Get or create the MongoDB collection, handling Atlas Search index creation."""
        self._collection = self._db[self.collection_name]  # type: ignore

        if not self.collection_exists():
            log_info(f"Creating collection '{self.collection_name}'.")
            self._db.create_collection(self.collection_name)  # type: ignore
            self._create_search_index()
        else:
            log_info(f"Using existing collection '{self.collection_name}'.")
            # check if index exists
            log_info(f"Checking if search index '{self.collection_name}' exists.")
            if not self._search_index_exists():
                log_info(f"Search index '{self.collection_name}' does not exist. Creating it.")
                self._create_search_index()
                if self.wait_until_index_ready_in_seconds and not self.cosmos_compatibility:
                    self._wait_for_index_ready()
            else:
                log_info("Using existing vector search index.")
        return self._collection  # type: ignore

    def _get_collection(self) -> Collection:
        """Get or create the MongoDB collection."""
        if self._collection is None:
            if self._client is None:
                self._get_client()
            self._collection = self._db[self.collection_name]  # type: ignore
            log_info(f"Using collection: {self.collection_name}")
        return self._collection

    async def _get_async_collection(self):
        """Get or create the async MongoDB collection."""
        if self._async_collection is None:
            client = await self._get_async_client()
            self._async_db = client[self.database]  # type: ignore
            self._async_collection = self._async_db[self.collection_name]  # type: ignore
        return self._async_collection

    def _create_search_index(self, overwrite: bool = True) -> None:
        """Create or overwrite the Atlas Search index with proper error handling."""
        index_name = self.search_index_name or "vector_index_1"
        max_retries = 3
        retry_delay = 5

        if self.cosmos_compatibility:
            try:
                collection = self._get_collection()

                # Handle overwrite if requested
                if overwrite and index_name in collection.index_information():
                    log_info(f"Dropping existing index '{index_name}'")
                    collection.drop_index(index_name)

                embedding_dim = getattr(self.embedder, "dimensions", 1536)
                log_info(f"Creating vector search index '{index_name}'")

                # Create vector search index using Cosmos DB IVF format
                collection.create_index(
                    [("embedding", "cosmosSearch")],
                    name=index_name,
                    cosmosSearchOptions={
                        "kind": "vector-ivf",
                        "numLists": 1,
                        "dimensions": embedding_dim,
                        "similarity": self._get_cosmos_similarity_metric(),
                    },
                )

                log_info(f"Created vector search index '{index_name}' successfully")

            except Exception as e:
                logger.error(f"Error creating vector search index: {e}")
                raise
        else:
            for attempt in range(max_retries):
                try:
                    if overwrite and self._search_index_exists():
                        log_info(f"Dropping existing search index '{index_name}'.")
                        try:
                            collection = self._get_collection()
                            collection.drop_search_index(index_name)
                            # Wait longer after index deletion
                            time.sleep(retry_delay * 2)
                        except errors.OperationFailure as e:
                            if "Index already requested to be deleted" in str(e):
                                log_info("Index is already being deleted, waiting...")
                                time.sleep(retry_delay * 2)  # Wait longer for deletion to complete
                            else:
                                raise

                    # Verify index is gone before creating new one
                    retries = 3
                    while retries > 0 and self._search_index_exists():
                        log_info("Waiting for index deletion to complete...")
                        time.sleep(retry_delay)
                        retries -= 1

                    log_info(f"Creating search index '{index_name}'.")

                    # Get embedding dimension from embedder
                    embedding_dim = getattr(self.embedder, "dimensions", 1536)

                    search_index_model = SearchIndexModel(
                        definition={
                            "fields": [
                                {
                                    "type": "vector",
                                    "numDimensions": embedding_dim,
                                    "path": "embedding",
                                    "similarity": self.distance_metric,
                                },
                            ]
                        },
                        name=index_name,
                        type="vectorSearch",
                    )

                    collection = self._get_collection()
                    collection.create_search_index(model=search_index_model)

                    if self.wait_until_index_ready_in_seconds:
                        self._wait_for_index_ready()

                    log_info(f"Search index '{index_name}' created successfully.")
                    return

                except errors.OperationFailure as e:
                    if "Duplicate Index" in str(e) and attempt < max_retries - 1:
                        logger.warning(f"Index already exists, retrying... (attempt {attempt + 1})")
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    logger.error(f"Failed to create search index: {e}")
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error creating search index: {e}")
                    raise

    async def _create_search_index_async(self) -> None:
        """Create the Atlas Search index asynchronously."""
        index_name = self.search_index_name
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                collection = await self._get_async_collection()

                # Get embedding dimension from embedder
                embedding_dim = getattr(self.embedder, "dimensions", 1536)

                search_index_model = SearchIndexModel(
                    definition={
                        "fields": [
                            {
                                "type": "vector",
                                "numDimensions": embedding_dim,
                                "path": "embedding",
                                "similarity": self.distance_metric,
                            },
                        ]
                    },
                    name=index_name,
                    type="vectorSearch",
                )

                await collection.create_search_index(model=search_index_model)
                log_info(f"Search index '{index_name}' created successfully.")
                return

            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                logger.error(f"Failed to create search index: {e}")
                raise

    def _search_index_exists(self) -> bool:
        """Check if the search index exists."""
        index_name = self.search_index_name
        if self.cosmos_compatibility:
            index_name = self.search_index_name or "vector_index_1"
            try:
                collection = self._get_collection()
                indexes = collection.index_information()

                for idx_name, idx_info in indexes.items():
                    if idx_name == index_name:
                        key_info = idx_info.get("key", [])
                        for key, value in key_info:
                            if key == "embedding" and value == "cosmosSearch":
                                log_debug(f"Found existing vector search index: {index_name}")
                                return True

                log_debug(f"Vector search index '{index_name}' not found")
                return False
            except Exception as e:
                logger.error(f"Error checking search index existence: {e}")
                return False
        else:
            try:
                collection = self._get_collection()
                indexes = list(collection.list_search_indexes())  # type: ignore
                exists = any(index["name"] == index_name for index in indexes)  # type: ignore
                return exists
            except Exception as e:
                logger.error(f"Error checking search index existence: {e}")
                return False

    def _wait_for_index_ready(self) -> None:
        """Wait until the Atlas Search index is ready."""
        index_name = self.search_index_name
        while True:
            try:
                if self._search_index_exists():
                    log_info(f"Search index '{index_name}' is ready.")
                    break
            except Exception as e:
                logger.error(f"Error checking index status: {e}")
                raise TimeoutError("Timeout waiting for search index to become ready.")
            time.sleep(1)

    async def _wait_for_index_ready_async(self) -> None:
        """Wait until the Atlas Search index is ready asynchronously."""
        start_time = time.time()
        index_name = self.search_index_name
        while True:
            try:
                collection = await self._get_async_collection()
                indexes = await collection.list_search_indexes()
                if any(index["name"] == index_name for index in indexes):
                    log_info(f"Search index '{index_name}' is ready.")
                    break
            except Exception as e:
                logger.error(f"Error checking index status asynchronously: {e}")
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}")

            if time.time() - start_time > self.wait_until_index_ready_in_seconds:  # type: ignore
                raise TimeoutError("Timeout waiting for search index to become ready.")
            await asyncio.sleep(1)

    def collection_exists(self) -> bool:
        """Check if the collection exists in the database."""
        if self._db is None:
            self._get_client()
        return self.collection_name in self._db.list_collection_names()  # type: ignore

    def create(self) -> None:
        """Create the MongoDB collection and indexes if they do not exist."""
        self._get_or_create_collection()

    async def async_create(self) -> None:
        """Create the MongoDB collection and indexes asynchronously."""
        await self._get_async_collection()

        if not await self.async_exists():
            log_info(f"Creating collection '{self.collection_name}' asynchronously.")
            await self._async_db.create_collection(self.collection_name)  # type: ignore
            await self._create_search_index_async()
            if self.wait_until_index_ready_in_seconds:
                await self._wait_for_index_ready_async()

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the MongoDB collection based on its content."""
        try:
            collection = self._get_collection()
            # Use content hash as document ID
            doc_id = md5(document.content.encode("utf-8")).hexdigest()
            result = collection.find_one({"_id": doc_id})
            exists = result is not None
            log_debug(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection."""
        try:
            collection = self._get_collection()
            exists = collection.find_one({"name": name}) is not None
            log_debug(f"Document with name '{name}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with a given ID exists in the collection."""
        try:
            collection = self._get_collection()
            exists = collection.find_one({"_id": id}) is not None
            log_debug(f"Document with ID '{id}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document ID existence: {e}")
            return False

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the MongoDB collection."""
        log_debug(f"Inserting {len(documents)} documents")
        collection = self._get_collection()

        prepared_docs = []
        for document in documents:
            try:
                doc_data = self.prepare_doc(document, filters)
                prepared_docs.append(doc_data)
            except ValueError as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if prepared_docs:
            try:
                collection.insert_many(prepared_docs, ordered=False)
                log_info(f"Inserted {len(prepared_docs)} documents successfully.")
                if self.wait_after_insert_in_seconds and self.wait_after_insert_in_seconds > 0:
                    time.sleep(self.wait_after_insert_in_seconds)
            except errors.BulkWriteError as e:
                logger.warning(f"Bulk write error while inserting documents: {e.details}")
            except Exception as e:
                logger.error(f"Error inserting documents: {e}")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the MongoDB collection."""
        log_info(f"Upserting {len(documents)} documents")
        collection = self._get_collection()

        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                collection.update_one(
                    {"_id": doc_data["_id"]},
                    {"$set": doc_data},
                    upsert=True,
                )
                log_info(f"Upserted document: {doc_data['_id']}")
            except Exception as e:
                logger.error(f"Error upserting document '{document.name}': {e}")

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    def search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None, min_score: float = 0.0
    ) -> List[Document]:
        """Search for documents using vector similarity."""
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit=limit)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        if self.cosmos_compatibility:
            # Azure Cosmos DB Mongo Vcore compatibility mode
            try:
                collection = self._get_collection()

                # Construct the search pipeline
                search_stage = {
                    "$search": {
                        "cosmosSearch": {"vector": query_embedding, "path": "embedding", "k": limit, "nProbes": 2},
                        "returnStoredSource": True,
                    }
                }

                pipeline = [
                    search_stage,
                    {
                        "$project": {
                            "similarityScore": {"$meta": "searchScore"},
                            "_id": 1,
                            "name": 1,
                            "content": 1,
                            "meta_data": 1,
                        }
                    },
                ]

                results = list(collection.aggregate(pipeline))
                docs = [
                    Document(
                        id=str(doc["_id"]),
                        name=doc.get("name"),
                        content=doc["content"],
                        meta_data={**doc.get("meta_data", {}), "score": doc.get("similarityScore", 0.0)},
                    )
                    for doc in results
                ]

                log_info(f"Search completed. Found {len(docs)} documents.")
                return docs

            except Exception as e:
                logger.error(f"Error during vector search: {e}")
                return []
        else:
            # MongoDB Atlas Search
            try:
                collection = self._get_collection()
                pipeline = [
                    {
                        "$vectorSearch": {
                            "index": self.search_index_name,
                            "limit": limit,
                            "numCandidates": min(limit * 4, 100),
                            "queryVector": query_embedding,
                            "path": "embedding",
                        }
                    },
                    {"$set": {"score": {"$meta": "vectorSearchScore"}}},
                ]

                match_filters = {}
                if min_score > 0:
                    match_filters["score"] = {"$gte": min_score}

                # Handle filters if provided
                if filters:
                    # MongoDB uses dot notation for nested fields, so we need to prepend meta_data. if needed
                    mongo_filters = {}
                    for key, value in filters.items():
                        # If the key doesn't already include a dot notation for meta_data
                        if not key.startswith("meta_data.") and "." not in key:
                            mongo_filters[f"meta_data.{key}"] = value
                        else:
                            mongo_filters[key] = value

                    match_filters.update(mongo_filters)

                if match_filters:
                    pipeline.append({"$match": match_filters})  # type: ignore

                pipeline.append({"$project": {"embedding": 0}})

                results = list(collection.aggregate(pipeline))  # type: ignore

                docs = [
                    Document(
                        id=str(doc["_id"]),
                        name=doc.get("name"),
                        content=doc["content"],
                        meta_data={**doc.get("meta_data", {}), "score": doc.get("score", 0.0)},
                    )
                    for doc in results
                ]

                log_info(f"Search completed. Found {len(docs)} documents.")
                return docs

            except Exception as e:
                logger.error(f"Error during search: {e}")
                raise

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a vector-based search."""
        log_debug("Performing vector search.")
        return self.search(query, limit=limit)

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a keyword-based search."""
        try:
            collection = self._get_collection()
            cursor = collection.find(
                {"content": {"$regex": query, "$options": "i"}},
                {"_id": 1, "name": 1, "content": 1, "meta_data": 1},
            ).limit(limit)
            results = [
                Document(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    content=doc["content"],
                    meta_data=doc.get("meta_data", {}),
                )
                for doc in cursor
            ]
            log_debug(f"Keyword search completed. Found {len(results)} documents.")
            return results
        except Exception as e:
            logger.error(f"Error during keyword search: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Document]:
        """
        Perform a hybrid search combining vector and keyword-based searches using Reciprocal Rank Fusion.

        Weights for vector and keyword search are configured at the instance level (hybrid_vector_weight, hybrid_keyword_weight).
        The rank constant k is used in the RRF formula `1 / (rank + k)` to smooth scores.

        Reference: https://www.mongodb.com/docs/atlas/atlas-vector-search/tutorials/reciprocal-rank-fusion
        """

        if self.cosmos_compatibility:
            log_warning("Hybrid search is not implemented for Cosmos DB compatibility mode. Returning empty list.")
            return []

        log_debug(f"Performing hybrid search for query: '{query}' with limit: {limit}")

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        collection = self._get_collection()

        k = self.hybrid_rank_constant

        pipeline = [
            # Vector Search Branch
            {
                "$vectorSearch": {
                    "index": self.search_index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": min(limit * 10, 200),
                    "limit": limit * 2,
                }
            },
            {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
            {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
            {
                "$addFields": {
                    "_id": "$docs._id",
                    "name": "$docs.name",
                    "content": "$docs.content",
                    "meta_data": "$docs.meta_data",
                    "vs_score": {
                        "$divide": [
                            self.hybrid_vector_weight,
                            {"$add": ["$rank", k, 1]},
                        ]
                    },
                    "fts_score": 0.0,  # Ensure fts_score exists with a default value
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "name": 1,
                    "content": 1,
                    "meta_data": 1,
                    "vs_score": 1,
                    # Now fts_score is included with its value (0.0 here)
                    "fts_score": 1,
                }
            },
            # Union with Keyword Search Branch
            {
                "$unionWith": {
                    "coll": self.collection_name,
                    "pipeline": [
                        {
                            "$search": {
                                "index": "default",
                                "text": {"query": query, "path": "content"},
                            }
                        },
                        {"$limit": limit * 2},
                        {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
                        {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
                        {
                            "$addFields": {
                                "_id": "$docs._id",
                                "name": "$docs.name",
                                "content": "$docs.content",
                                "meta_data": "$docs.meta_data",
                                "vs_score": 0.0,
                                "fts_score": {
                                    "$divide": [
                                        self.hybrid_keyword_weight,
                                        {"$add": ["$rank", k, 1]},
                                    ]
                                },
                            }
                        },
                        {
                            "$project": {
                                "_id": 1,
                                "name": 1,
                                "content": 1,
                                "meta_data": 1,
                                "vs_score": 1,
                                "fts_score": 1,
                            }
                        },
                    ],
                }
            },
            # Combine and Rank
            {
                "$group": {
                    "_id": "$_id",
                    "name": {"$first": "$name"},
                    "content": {"$first": "$content"},
                    "meta_data": {"$first": "$meta_data"},
                    "vs_score": {"$sum": "$vs_score"},
                    "fts_score": {"$sum": "$fts_score"},
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "name": 1,
                    "content": 1,
                    "meta_data": 1,
                    "score": {"$add": ["$vs_score", "$fts_score"]},
                }
            },
            {"$sort": {"score": -1}},
            {"$limit": limit},
        ]

        try:
            results = list(collection.aggregate(pipeline))
            docs = [
                Document(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    content=doc["content"],
                    meta_data={**doc.get("meta_data", {}), "score": doc.get("score", 0.0)},
                )
                for doc in results
            ]
            log_info(f"Hybrid search completed. Found {len(docs)} documents.")
            return docs
        except errors.OperationFailure as e:
            logger.error(
                f"Error during hybrid search, potentially due to missing or misconfigured Atlas Search index for text search: {e}"
            )
            logger.error(f"Details: {e.details}")
            return []
        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def drop(self) -> None:
        """Drop the collection and clean up indexes."""
        collection = self._get_collection()
        index_name = self.search_index_name or "vector_index_1"

        if self.exists():
            if self.cosmos_compatibility:
                # Cosmos DB specific handling
                try:
                    # Drop the index if it exists
                    if self._search_index_exists():
                        log_info(f"Dropping index '{index_name}'")
                        try:
                            collection.drop_index(index_name)
                        except Exception as e:
                            logger.error(f"Error dropping index: {e}")

                except Exception as e:
                    logger.error(f"Error dropping collection: {e}")
                    raise
            else:
                # MongoDB Atlas specific handling
                try:
                    if self._search_index_exists():
                        collection.drop_search_index(index_name)
                        time.sleep(2)

                except Exception as e:
                    logger.error(f"Error dropping collection: {e}")
                    raise

        # Drop the collection
        collection.drop()
        time.sleep(2)

        log_info(f"Collection '{self.collection_name}' dropped successfully")

    def exists(self) -> bool:
        """Check if the MongoDB collection exists."""
        exists = self.collection_exists()
        log_debug(f"Collection '{self.collection_name}' existence: {exists}")
        return exists

    def optimize(self) -> None:
        """TODO: not implemented"""
        pass

    def delete(self) -> bool:
        """Delete all documents from the collection."""
        if self.exists():
            try:
                collection = self._get_collection()
                result = collection.delete_many({})
                # Consider any deletion (even 0) as success
                success = result.deleted_count >= 0
                log_info(f"Deleted {result.deleted_count} documents from collection.")
                return success
            except Exception as e:
                logger.error(f"Error deleting documents: {e}")
                return False
        # Return True if collection doesn't exist (nothing to delete)
        return True

    def prepare_doc(self, document: Document, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prepare a document for insertion or upsertion into MongoDB."""
        document.embed(embedder=self.embedder)
        if document.embedding is None:
            raise ValueError(f"Failed to generate embedding for document: {document.id}")

        # Add filters to document metadata if provided
        if filters:
            meta_data = document.meta_data.copy() if document.meta_data else {}
            meta_data.update(filters)
            document.meta_data = meta_data

        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode("utf-8")).hexdigest()
        doc_data = {
            "_id": doc_id,
            "name": document.name,
            "content": cleaned_content,
            "meta_data": document.meta_data,
            "embedding": document.embedding,
        }
        log_debug(f"Prepared document: {doc_data['_id']}")
        return doc_data

    def get_count(self) -> int:
        """Get the count of documents in the MongoDB collection."""
        try:
            collection = self._get_collection()
            count = collection.count_documents({})
            log_debug(f"Collection '{self.collection_name}' has {count} documents.")
            return count
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists asynchronously."""
        try:
            collection = await self._get_async_collection()
            doc_id = md5(document.content.encode("utf-8")).hexdigest()
            result = await collection.find_one({"_id": doc_id})
            exists = result is not None
            log_debug(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document existence asynchronously: {e}")
            return False

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously."""
        log_debug(f"Inserting {len(documents)} documents asynchronously")
        collection = await self._get_async_collection()

        prepared_docs = []
        for document in documents:
            try:
                doc_data = self.prepare_doc(document, filters)
                prepared_docs.append(doc_data)
            except ValueError as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if prepared_docs:
            try:
                await collection.insert_many(prepared_docs, ordered=False)
                log_info(f"Inserted {len(prepared_docs)} documents successfully.")
                if self.wait_after_insert_in_seconds and self.wait_after_insert_in_seconds > 0:
                    await asyncio.sleep(self.wait_after_insert_in_seconds)
            except errors.BulkWriteError as e:
                logger.warning(f"Bulk write error while inserting documents: {e.details}")
            except Exception as e:
                logger.error(f"Error inserting documents asynchronously: {e}")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously."""
        log_info(f"Upserting {len(documents)} documents asynchronously")
        collection = await self._get_async_collection()

        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                await collection.update_one(
                    {"_id": doc_data["_id"]},
                    {"$set": doc_data},
                    upsert=True,
                )
                log_info(f"Upserted document: {doc_data['_id']}")
            except Exception as e:
                logger.error(f"Error upserting document '{document.name}' asynchronously: {e}")

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for documents asynchronously."""
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        try:
            collection = await self._get_async_collection()
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": self.search_index_name,
                        "limit": limit,
                        "numCandidates": min(limit * 4, 100),
                        "queryVector": query_embedding,
                        "path": "embedding",
                    }
                },
                {"$set": {"score": {"$meta": "vectorSearchScore"}}},
            ]

            # Handle filters if provided
            if filters:
                # MongoDB uses dot notation for nested fields, so we need to prepend meta_data. if needed
                mongo_filters = {}
                for key, value in filters.items():
                    # If the key doesn't already include a dot notation for meta_data
                    if not key.startswith("meta_data.") and "." not in key:
                        mongo_filters[f"meta_data.{key}"] = value
                    else:
                        mongo_filters[key] = value

                pipeline.append({"$match": mongo_filters})

            pipeline.append({"$project": {"embedding": 0}})

            # With AsyncMongoClient, aggregate() returns a coroutine that resolves to a cursor
            # We need to await it first to get the cursor
            cursor = await collection.aggregate(pipeline)

            # Now we can iterate over the cursor to get results
            results = []
            async for doc in cursor:
                results.append(doc)
                if len(results) >= limit:
                    break

            docs = [
                Document(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    content=doc["content"],
                    meta_data={**doc.get("meta_data", {}), "score": doc.get("score", 0.0)},
                )
                for doc in results
            ]

            log_info(f"Async search completed. Found {len(docs)} documents.")
            return docs

        except Exception as e:
            logger.error(f"Error during async search: {e}")
            # Include traceback for better debugging
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def async_drop(self) -> None:
        """Drop the collection asynchronously."""
        if await self.async_exists():
            try:
                collection = await self._get_async_collection()
                await collection.drop()
                log_info(f"Collection '{self.collection_name}' dropped asynchronously")
            except Exception as e:
                logger.error(f"Error dropping collection asynchronously: {e}")
                raise

    async def async_exists(self) -> bool:
        """Check if the collection exists asynchronously."""
        try:
            client = await self._get_async_client()
            collection_names = await client[self.database].list_collection_names()
            exists = self.collection_name in collection_names
            log_debug(f"Collection '{self.collection_name}' existence (async): {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking collection existence asynchronously: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists asynchronously."""
        try:
            collection = await self._get_async_collection()
            exists = await collection.find_one({"name": name}) is not None
            log_debug(f"Document with name '{name}' {'exists' if exists else 'does not exist'} (async)")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence asynchronously: {e}")
            return False

    def _get_cosmos_similarity_metric(self) -> str:
        """Convert MongoDB distance metric to Cosmos DB format."""
        # Cosmos DB supports: COS (cosine), L2 (Euclidean), IP (inner product)
        metric_mapping = {"cosine": "COS", "euclidean": "L2", "dotProduct": "IP"}
        return metric_mapping.get(self.distance_metric, "COS")
