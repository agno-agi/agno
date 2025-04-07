import time
from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance

try:
    from hashlib import md5

except ImportError:
    raise ImportError("`hashlib` not installed. Please install using `pip install hashlib`")
try:
    from pymongo import MongoClient, errors
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
        wait_until_index_ready: Optional[float] = None,
        wait_after_insert: Optional[float] = None,
        max_pool_size: int = 100,
        retry_writes: bool = True,
        client: Optional[MongoClient] = None,
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
            wait_until_index_ready (float): Time in seconds to wait until the index is ready.
            wait_after_insert (float): Time in seconds to wait after inserting documents.
            max_pool_size (int): Maximum number of connections in the connection pool
            retry_writes (bool): Whether to retry write operations
            client (Optional[MongoClient]): An existing MongoClient instance.
            **kwargs: Additional arguments for MongoClient.
        """
        if not collection_name:
            raise ValueError("Collection name must not be empty.")
        if not database:
            raise ValueError("Database name must not be empty.")
        self.collection_name = collection_name
        self.database = database

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder = embedder

        self.distance_metric = distance_metric
        self.connection_string = db_url
        self.overwrite = overwrite
        self.wait_until_index_ready = wait_until_index_ready
        self.wait_after_insert = wait_after_insert
        self.kwargs = kwargs
        self.kwargs.update(
            {
                "maxPoolSize": max_pool_size,
                "retryWrites": retry_writes,
                "serverSelectionTimeoutMS": 5000,  # 5 second timeout
            }
        )

        if client:
            self._client = client
            log_info("Using provided MongoDB client.")
        else:
            self._client = self._get_client()
        self._db = self._client[self.database]
        self._collection = self._db[self.collection_name]

    def _get_client(self) -> MongoClient:
        """Create or retrieve the MongoDB client."""
        try:
            log_debug("Creating MongoDB Client")
            client: MongoClient = MongoClient(self.connection_string, **self.kwargs)
            # Trigger a connection to verify the client
            client.admin.command("ping")
            log_info("Connected to MongoDB successfully.")
            return client
        except errors.ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise ConnectionError(f"Failed to connect to MongoDB: {e}")
        except Exception as e:
            logger.error(f"An error occurred while connecting to MongoDB: {e}")
            raise

    def _get_or_create_collection(self) -> Collection:
        """Get or create the MongoDB collection, handling Atlas Search index creation."""

        self._collection = self._db[self.collection_name]

        if not self.collection_exists():
            log_info(f"Creating collection '{self.collection_name}'.")
            self._db.create_collection(self.collection_name)
            self._create_search_index()
        else:
            log_info(f"Using existing collection '{self.collection_name}'.")
            # check if index exists
            log_info(f"Checking if search index '{self.collection_name}' exists.")
            if not self._search_index_exists():
                log_info(f"Search index '{self.collection_name}' does not exist. Creating it.")
                self._create_search_index()
                if self.wait_until_index_ready:
                    self._wait_for_index_ready()
        return self._collection

    def _create_search_index(self, overwrite: bool = True) -> None:
        """Create or overwrite the Atlas Search index with proper error handling."""
        index_name = "vector_index_1"
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                if overwrite and self._search_index_exists():
                    log_info(f"Dropping existing search index '{index_name}'.")
                    try:
                        self._collection.drop_search_index(index_name)
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
                embedding_dim = getattr(self.embedder, "embedding_dim", 1536)

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

                self._collection.create_search_index(model=search_index_model)

                if self.wait_until_index_ready:
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

    def _search_index_exists(self) -> bool:
        """Check if the search index exists."""
        index_name = "vector_index_1"
        try:
            indexes = list(self._collection.list_search_indexes())
            exists = any(index["name"] == index_name for index in indexes)
            return exists
        except Exception as e:
            logger.error(f"Error checking search index existence: {e}")
            return False

    def _wait_for_index_ready(self) -> None:
        """Wait until the Atlas Search index is ready."""
        start_time = time.time()
        index_name = "vector_index_1"
        while True:
            try:
                if self._search_index_exists():
                    log_info(f"Search index '{index_name}' is ready.")
                    break
            except Exception as e:
                logger.error(f"Error checking index status: {e}")
            if time.time() - start_time > self.wait_until_index_ready:  # type: ignore
                raise TimeoutError("Timeout waiting for search index to become ready.")
            time.sleep(1)

    def collection_exists(self) -> bool:
        """Check if the collection exists in the database."""
        return self.collection_name in self._db.list_collection_names()

    def create(self) -> None:
        """Create the MongoDB collection and indexes if they do not exist."""
        self._get_or_create_collection()

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the MongoDB collection based on its content."""
        try:
            # Use content hash as document ID
            doc_id = md5(document.content.encode("utf-8")).hexdigest()
            result = self._collection.find_one({"_id": doc_id})
            exists = result is not None
            log_debug(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection."""
        try:
            exists = self._collection.find_one({"name": name}) is not None
            log_debug(f"Document with name '{name}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with a given ID exists in the collection."""
        try:
            exists = self._collection.find_one({"_id": id}) is not None
            log_debug(f"Document with ID '{id}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document ID existence: {e}")
            return False

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the MongoDB collection."""
        log_info(f"Inserting {len(documents)} documents")

        prepared_docs = []
        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                prepared_docs.append(doc_data)
            except ValueError as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if prepared_docs:
            try:
                self._collection.insert_many(prepared_docs, ordered=False)
                log_info(f"Inserted {len(prepared_docs)} documents successfully.")
                if self.wait_after_insert and self.wait_after_insert > 0:
                    time.sleep(self.wait_after_insert)
            except errors.BulkWriteError as e:
                logger.warning(f"Bulk write error while inserting documents: {e.details}")
            except Exception as e:
                logger.error(f"Error inserting documents: {e}")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the MongoDB collection."""
        log_info(f"Upserting {len(documents)} documents")

        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                self._collection.update_one(
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
        """
        Search for documents using vector similarity.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: MongoDB query filters to apply
            min_score: Minimum similarity score (0-1) for results
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index_1",
                        "limit": limit,
                        "numCandidates": min(limit * 4, 100),  # Scale candidates with limit
                        "queryVector": query_embedding,
                        "path": "embedding",
                    }
                },
                {"$set": {"score": {"$meta": "vectorSearchScore"}}},
            ]

            # Add score filter if specified
            if min_score > 0:
                pipeline.append({"$match": {"score": {"$gte": min_score}}})

            # Add custom filters if provided
            if filters:
                pipeline.append({"$match": filters})

            # Exclude embedding from results
            pipeline.append({"$project": {"embedding": 0}})

            results = list(self._collection.aggregate(pipeline))  # type: ignore

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
            cursor = self._collection.find(
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

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a hybrid search combining vector and keyword-based searches."""
        log_debug("Performing hybrid search is not yet implemented.")
        return []

    def drop(self) -> None:
        """Drop the collection and clean up indexes."""
        if self.exists():
            try:
                # First drop all indexes
                index_name = "vector_index_1"
                if self._search_index_exists():
                    self._collection.drop_search_index(index_name)
                    time.sleep(2)  # Wait for index deletion

                # Then drop the collection
                self._collection.drop()
                log_info(f"Collection '{self.collection_name}' dropped successfully")

                # Wait to ensure cleanup
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error dropping collection: {e}")
                raise

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
                result = self._collection.delete_many({})
                success = result.deleted_count >= 0  # Consider any deletion (even 0) as success
                log_info(f"Deleted {result.deleted_count} documents from collection.")
                return success
            except Exception as e:
                logger.error(f"Error deleting documents: {e}")
                return False
        return True  # Return True if collection doesn't exist (nothing to delete)

    def prepare_doc(self, document: Document) -> Dict[str, Any]:
        """Prepare a document for insertion or upsertion into MongoDB."""
        document.embed(embedder=self.embedder)
        if document.embedding is None:
            raise ValueError(f"Failed to generate embedding for document: {document.id}")

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
            count = self._collection.count_documents({})
            log_debug(f"Collection '{self.collection_name}' has {count} documents.")
            return count
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    async def async_create(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_doc_exists(self, document: Document) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_drop(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_exists(self) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
