from hashlib import md5
from typing import Any, Dict, List, Optional
import time
import os
import json
import numpy as np
import asyncio

try:
    import redisvl
    from redisvl.query.filter import Text
    from redisvl.index import SearchIndex, AsyncSearchIndex
    from redisvl.query import VectorQuery, HybridQuery, TextQuery, RangeQuery

except ImportError:
    raise ImportError(
        "The `redisvl` package is not installed. Please install it via `pip install -U redisvl`."
    )

try:
    import redis
    from redis.asyncio import Redis as aioredis  # for async redis
    from redis.exceptions import ConnectionError, TimeoutError
    
except ImportError:
    raise ImportError(
        "The `redis` package is not installed. Please install it via `pip install redis`."
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class RedisVL(VectorDb):
    """
    RedisVL Vector Database implementation with RedisVL Search Index creation.
    """

    def __init__(
        self,
        db_url: str,
        client: Optional[redis.Redis] = None,
        host: Optional[str]= None,
        port: Optional[str] = None,
        database: str = "agno",
        embedding_name: Optional[str] = "embedding",
        embedder: Optional[Embedder]= None,
        openai_api_key: str = os.getenv("OPENAI_API_KEY"),
        distance_metric: str = Distance.cosine,
        field_names: Optional[List[str]] = [],
        search_index_name: Optional[str] = "vector_index_1",
        wait_until_index_ready: Optional[float] = None,
        wait_after_insert: Optional[float] = None,
        max_pool_size: int = 100,
        retry_writes: bool = True,
        filter_expression: Optional[Text] = None,
        return_fields: Optional[List[str]] = [],
        distance_threshold: Optional[float] = 0.0,
        **kwargs,
    ):
        """
        Initialize RedisVL with Redis collection details.

        Args:
            db_url (Optional[str]): Redis connection string.
            client (Optional[redis.Redis]): An existing Redis instance.
            host (Optional[str]): Redis host.
            port (Optional[str]): Redis port.
            database (str): Database name.
            embedding_name (str): Name of the embedding (default: "embedding").
            embedder (Embedder): Embedder instance for generating embeddings.
            openai_api_key (str): OpenAI API key.
            distance_metric (str): Distance metric for similarity.
            field_names (Optional[List[str]]): List of field names to be indexed.
            search_index_name (str): Name of the search index (default: "vector_index_1").
            wait_until_index_ready (float): Time in seconds to wait until the index is ready.
            wait_after_insert (float): Time in seconds to wait after inserting documents.
            max_pool_size (int): Maximum number of connections in the connection pool.
            retry_writes (bool): Whether to retry write operations.
            filter_expression (Optional[Text]): Expression on which the filters can be made for index search.
            return_fields (Optional[List[str]]): Name of the fields to be returned after index search.
            distance_threshold (Optional[float]): Distance threshold to perform redisvl RangeQuery.      
            **kwargs: Additional arguments for Redis Instance.
        """
        if not database:
            raise ValueError("Database name must not be empty.")
       
        self.database = database
        self.search_index_name = search_index_name
        self.embedding_name = embedding_name
        self.open_ai_api_key = openai_api_key
        self.field_names = field_names
        self.return_fields = return_fields
        self.db_url =  db_url
        self.host = host
        self.port = port
        self.filter_expression = filter_expression
        self.distance_threshold = distance_threshold

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder = embedder

        self.distance_metric = distance_metric
        self.connection_string = db_url
        self.wait_until_index_ready = wait_until_index_ready
        self.wait_after_insert = wait_after_insert
        self.kwargs = kwargs
        self.kwargs.update(
            {
                "maxPoolSize": max_pool_size,
                "retryWrites": retry_writes,
                "connectTimeout": 5000,  # 5 second timeout
            }
        )

        self._client = client
        self._db = None

        self._async_client: Optional[aioredis] = None
        self._async_db = None

    def _get_client(self) -> redis.Redis:
        """Create or retrieve the Redis instance."""
        if self._client is None:
            try:
                log_debug("Creating Redis Instance")
                if self.host and self.port and self.database:
                    self._client = redis.Redis(host=self.host, port=self.port, db=self.database, **self.kwargs)
                else:
                    self._client = redis.Redis.from_url(self.db_url)
                # Trigger a connection to verify the client
                self._client.ping()
                log_info("Connected to Redis successfully.")
                self._db = self._client  # type: ignore
            except ConnectionError as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise ConnectionError(f"Failed to connect to Redis: {e}")
            except Exception as e:
                logger.error(f"An error occurred while connecting to Redis: {e}")
                raise
        return self._client

    async def _get_async_client(self) -> redis.Redis:
        """Async Create or retrieve the async Redis client."""
        if self._async_client is None:
            log_debug("Creating Async Redis Client")
            if self.host and self.port and self.database:
                self._async_client = await aioredis.create_redis_pool(
                (self.host, self.port),
                db=self.database,
                minsize=1,
                maxsize=10,
                timeout=5,
                retry_attempts=5,
                retry_delay=0.5,
            )
            else:
                self._async_client = await aioredis.from_url(self.db_url)
            # Verify connection
            try:
                response = self._async_client.ping()
                if response:
                    log_info("Connected to Redis asynchronously.")
            except ConnectionError as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise ConnectionError(f"Failed to connect to Redis: {e}")
            except TimeoutError as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise TimeoutError(f"Failed waiting to connect to redis: {e}")
            except Exception as e:
                logger.error(f"An error occurred while connecting to Redis asynchronously: {e}")
                raise
        return self._async_client
    
    def _search_index_exists(self) -> bool:
        """Check if the search index exists."""
        index_name = self.search_index_name
        try:
            if self._client is None:
                self._get_client()
            search_index = SearchIndex.from_existing(name=index_name, redis_url=self.db_url)
            search_index_exists = SearchIndex.exists(search_index)
            if search_index_exists:
                return True
        except Exception as e:
            logger.error(f"Error checking search index existence: {e}")
            return False
        
    async def _async_search_index_exists(self) -> bool:
        """Async Check if the search index exists."""
        index_name = self.search_index_name
        try:
            if self._client is None:
                self._get_client()
            search_index_exists = await AsyncSearchIndex.exists(index_name)
            return search_index_exists
        except Exception as e:
            logger.error(f"Error checking search index existence: {e}")
            return False
        
    def _drop_search_index(self):
        """Drop the search index."""
        if self._search_index_exists():
            try:
                index_name = self.search_index_name or "vector_index_1"
                if self._search_index_exists():
                    index = SearchIndex.from_existing(index_name, redis_url=self.db_url)
                    index.delete(index_name)
                    time.sleep(2)

                log_info(f"Index '{index_name}' dropped successfully")

                time.sleep(2)

            except Exception as e:
                logger.error(f"Error dropping index: {e}")
                raise

    async def _async_drop_search_index(self):
        """Async Drop the search index."""
        if await self._async_search_index_exists():
            try:
                index_name = self.search_index_name or "vector_index_1"
                if await self._async_search_index_exists():
                    AsyncSearchIndex.delete(index_name)
                    time.sleep(2)

                log_info(f"Index '{index_name}' dropped successfully")

                time.sleep(2)

            except Exception as e:
                logger.error(f"Error dropping index: {e}")
                raise
    
    def _wait_for_index_ready(self) -> None:
        """Wait until the Redis Search index is ready."""
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

    def _create_search_index(self) -> None:
        """Create or overwrite the Redis Search index with proper error handling."""
        index_name = self.search_index_name or "vector_index_1"
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                if self._search_index_exists():
                    log_info(f"Dropping existing search index '{index_name}'.")
                    try:
                        self._drop_search_index(index_name)
                        # Wait longer after index deletion
                        time.sleep(retry_delay * 2)
                    except Exception as e:
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

                field_name_list = []
                field_name_list.append({"name": "_id", "type": "tag"})
                
                for field_name in self.field_names:
                    field_name_list.append({"name": field_name, "type": "text"})

                """field_name_list.append(RedisVectorField(name=self.embedding_name, algorithm="flat", attributes={
                    "dims": embedding_dim, "distance_metric": self.distance_metric, "datatype": "float32"}))"""
                
                    #dims=embedding_dim, distance_metric=self.distance_metric,  datatype="float32")

                field_name_list.append({
                                        "name": self.embedding_name,
                                        "type": "vector",
                                        "attrs": {
                                            "dims": embedding_dim,
                                            "distance_metric": self.distance_metric,
                                            "algorithm": "flat",
                                            "datatype": "float32"
                                        }

                                    })

                search_index = SearchIndex.from_dict(
                    schema_dict={
                                "index": {
                                    "name": self.search_index_name,
                                    "prefix": "rvl",
                                    "storage_type": "hash", # default setting -- HASH
                                },
                                "fields": field_name_list
                            },
                        redis_url = self.db_url
                            
                    )
                
                search_index.create(overwrite=True)

                if self.wait_until_index_ready:
                    self._wait_for_index_ready()

                log_info(f"Search index '{index_name}' created successfully.")
                return

            except Exception as e:
                logger.error(f"Unexpected error creating search index: {e}")
                raise

    async def _async_create_search_index(self) -> None:
        """Async Create or overwrite the Redis Search index with proper error handling."""
        index_name = self.search_index_name or "vector_index_1"
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                if await self._async_search_index_exists():
                    log_info(f"Dropping existing search index '{index_name}'.")
                    try:
                        await self._async_drop_search_index(index_name)
                        # Wait longer after index deletion
                        time.sleep(retry_delay * 2)
                    except Exception as e:
                        if "Index already requested to be deleted" in str(e):
                            log_info("Index is already being deleted, waiting...")
                            time.sleep(retry_delay * 2)  # Wait longer for deletion to complete
                        else:
                            raise

                # Verify index is gone before creating new one
                retries = 3
                while retries > 0 and await self._async_search_index_exists():
                    log_info("Waiting for index deletion to complete...")
                    time.sleep(retry_delay)
                    retries -= 1

                log_info(f"Creating search index '{index_name}'.")

                # Get embedding dimension from embedder
                embedding_dim = getattr(self.embedder, "embedding_dim", 1536)

                search_index = AsyncSearchIndex.from_dict(
                    schema_dict={
                                "index": {
                                    "name": self.search_index_name,
                                    "prefix": "rvl",
                                    "storage_type": "hash", # default setting -- HASH
                                },
                                "fields": [
                                    {"name": "_id", "type": "tag"},
                                    {
                                        "name": self.embedding_name,
                                        "type": "vector",
                                        "attrs": {
                                            "dims": embedding_dim,
                                            "distance_metric": self.distance_metric,
                                            "algorithm": "flat",
                                            "datatype": "float32"
                                        }

                                    }

                                ]
                            }
                    )
                
                await search_index.create(overwrite=True)

                if self.wait_until_index_ready:
                    self._wait_for_index_ready()

                log_info(f"Search index '{index_name}' created successfully.")
                return

            except Exception as e:
                logger.error(f"Unexpected error creating search index: {e}")
                raise

    def create(self) -> None:
        """Create the Redis index if they do not exist."""
        self._create_search_index()
    
    async def async_create(self):
        """Async Create the Redis index if they do not exist."""
        await self._async_create_search_index()

    def exists(self) -> bool:
        """Check if Redis Search Index exists."""
        exists = self._search_index_exists()
        if exists:
            return True
        return False
    
    async def async_exists(self) -> bool:
        """Async Check if Redis Search Index exists."""
        exists = await self._async_search_index_exists()
        if exists:
            return True
        return False

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the Redis index based on its content."""
        try:
            index = self.get_index()
            # Use content hash as document ID
            doc_id = md5(document.content.encode("utf-8")).hexdigest()
            result = index.fetch(id = doc_id)
            exists = result is not None
            log_info(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists

        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False
    
    async def async_doc_exists(self, document: Document) -> bool:
        """Async Check if a document exists in the Redis index based on its content."""
        doc_id = document.id
        log_info(f"Checking if the document {document} exists")
        try:
            index = self.get_index()
            # Use content hash as document ID
            doc_id = md5(document.content.encode("utf-8")).hexdigest()
            result = await index.fetch(id=doc_id)
            exists = result is not None
            log_debug(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False
    
    def name_exists(self, index_name: str) -> bool:
        """Check if a document with a given name exists in the database."""
        try:
            exists = self._search_index_exists()
            log_debug(f"Document with name '{index_name}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False
        
    async def async_name_exists(self, index_name: str) -> bool:
        """Async Check if a document with a given name exists in the database."""
        try:
            exists = await self._async_search_index_exists()
            log_debug(f"Document with name '{index_name}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False
    
    def id_exists(self, id: str) -> bool:
        """TODO: not implemented"""
        pass

    def get_index(self):
        """Get the existing search index"""
        try:
            if self._search_index_exists():
                index = SearchIndex.from_existing(self.search_index_name, redis_url=self.db_url)
            return index
        except Exception as e:
            logger.error(f"Error getting existing index: {e}")

    def prepare_doc(self, document: Document, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prepare a document for insertion or upsertion into Redis index."""
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
        embedding_bytes = np.array(document.embedding, dtype=np.float32).tobytes()
        doc_data = {
            "_id": doc_id,
            "name": document.name,
            "content": cleaned_content,
            "meta_data": json.dumps(document.meta_data),
            "embedding": embedding_bytes,
        }
        log_debug(f"Prepared document: {doc_data['_id']}")
        return doc_data
    
    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the Redis index."""
        log_info(f"Inserting {len(documents)} documents")
        index = self.get_index()

        all_documents = []
        try:
            for document in documents:
                doc_data = self.prepare_doc(document, filters)
                log_info(f"Prepared document: {doc_data["_id"]}")
                all_documents.append(doc_data)

            log_info(f"All docs list: {all_documents[-1]}")    
            loaded_data = index.load(
                    data = all_documents
            )
            log_info(f"Inserted document: {loaded_data}")
        except Exception as e:
                logger.error(f"Error inserting document '{document.name}': {e}")


    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Async Insert documents into the Redis index."""
        """Index inserting in Redis is already async."""
        pass

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the Redis index."""
        log_info(f"Upserting {len(documents)} documents")
        index = self.get_index()

        all_documents = []
        try:
            for document in documents:
                doc_data = self.prepare_doc(document, filters)
                log_info(f"Prepared document: {doc_data["_id"]}")
                all_documents.append(doc_data)

            log_info(f"All docs list: {all_documents[-1]}")    
            loaded_data = index.load(
                    data = all_documents
            )
            log_info(f"Upserted document: {loaded_data}")
        except Exception as e:
                logger.error(f"Error upserting document '{document.name}': {e}")

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Async Upsert documents into the Redis index."""
        """Index upserting in Redis is already async."""
        pass

    def optimize(self) -> None:
        """TODO: not implemented"""
        pass

    def delete(self, index_name) -> bool:
        """Delete the Redis index"""
        if self._search_index_exists():
            log_info(f"Deleting the index {index_name}")
            try:
                self._drop_search_index(index_name)
                log_info(f"Deleted {index_name} index successfully.")
            except Exception as e:
                logger.error(f"Error deleting index: {e}")
        
        return True  # Return True if index doesn't exist (nothing to delete)

    async def async_delete(self, index_name):
        """Async Delete the Redis index"""
        log_info(f"Deleting the index {index_name}")
        try:
            await self._async_drop_search_index(index_name)
            log_info(f"Deleted {index_name} index successfully.")
        except Exception as e:
            logger.error(f"Error deleting index: {e}")
    
    def drop(self) -> None:
        """Drop the index and clean up indexes."""
        try:
            index_name = self.search_index_name or "vector_index_1"
            if self._search_index_exists():
                index = SearchIndex.from_existing(index_name, redis_url=self.db_url)
                index.delete(drop=True)
                time.sleep(2)

            log_info(f"Index '{index_name}' dropped successfully")

            time.sleep(2)

        except redisvl.exceptions.RedisSearchError as e:
            if "Index already requested to be deleted" in str(e):
                log_info("Index is already being deleted, waiting...")
                time.sleep(2)
        except Exception as e:
            logger.error(f"Error dropping index: {e}")
            raise

    async def async_drop(self) -> None:
        """Async Drop the index and clean up indexes."""
        try:
            index_name = self.search_index_name or "vector_index_1"
            if await self._async_search_index_exists():
                index = await AsyncSearchIndex.from_existing(index_name, redis_url=self.db_url)
                await index.delete(drop=True)
                time.sleep(2)

            log_info(f"Index '{index_name}' dropped successfully")

            time.sleep(2)

        except Exception as e:
            logger.error(f"Error dropping index: {e}")
            raise

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Perform search."""
        log_debug("Performing search.")

        query_embedding = self.embedder.get_embedding(query)
        
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []
        
        query_embedding_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        try:
            index_name = self.search_index_name
            index = None
            if self._search_index_exists():
                index = SearchIndex.from_existing(index_name,redis_url=self.db_url)
            else:
                log_info("Search index does not exist.")
                raise

            if self.distance_threshold:
                query_to_be_run = RangeQuery(
                    vector=query_embedding_bytes,
                    vector_field_name=self.embedding_name,
                    return_fields=self.return_fields,
                    distance_threshold=self.distance_threshold,
                    num_results=limit
                )
            else:
                query_to_be_run = VectorQuery(
                    vector=query_embedding_bytes,
                    vector_field_name=self.embedding_name,
                    return_fields=self.return_fields,
                    num_results=limit
                )

            results = index.query(query_to_be_run)
            log_info(f"Redis search results: {results}")
            return results
        except Exception as e:
            import traceback
            logger.error(f"Error during search: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    def vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None, min_score: float = 0.0
    ) -> List[Document]:
        """Perform a vector-based search."""
        log_debug("Performing vector search.")
        return self.search(query, limit=limit)

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a keyword-based search."""
        log_debug("Performing keyword based search.")
        try:
            index_name = self.search_index_name
            if self._search_index_exists():
                index = SearchIndex.from_existing(index_name, redis_url=self.db_url)

            query_to_be_run = TextQuery(
                text=query,
                text_field_name="text_field",
                text_scorer="BM25STD",
                filter_expression=self.filter_expression,
                num_results=limit,
                return_fields=self.return_fields,
                stopwords="english",
                dialect=2,
            )

            results = index.query(query_to_be_run)
            return results
        except Exception as e:
            logger.error(f"Error during key word based search: {e}")

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform hybrid search."""
        log_debug("Performing hybrid search.")
        try:
            index_name = self.search_index_name
            if self._search_index_exists():
                index = SearchIndex.from_existing(index_name, redis_url=self.db_url)

            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Failed to generate embedding for query: {query}")
                return []
            
            query_embedding_bytes = np.array(query_embedding, dtype=np.float32).tobytes()

            query_to_be_run = HybridQuery(
                    text=query_embedding_bytes,
                    text_field_name="text_field",
                    vector=query_embedding,
                    vector_field_name="vector_field",
                    text_scorer="BM25STD",
                    filter_expression=self.filter_expression,
                    alpha=0.7,
                    dtype="float32",
                    num_results=limit,
                    return_fields=self.return_fields,
                    stopwords="english",
                    dialect=2,
                )

            results = index.query(query_to_be_run)
            return results
        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Async Search against the query"""
        log_info(f"Searching against the query {query} asynchronously.")
        log_debug("Performing async search.")
        if self._async_client is None:
            self._async_client = await self._get_async_client()

        query_embedding = await self.embedder.get_embedding(query)
        
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []
        
        query_embedding_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        try:
            index_name = self.search_index_name
            index = None
            if await self._async_search_index_exists():
                index = await AsyncSearchIndex.from_existing(index_name,redis_url=self.db_url)
            else:
                log_info("Search index does not exist.")
                raise

            if self.distance_threshold:
                query_to_be_run = RangeQuery(
                    vector=query_embedding_bytes,
                    vector_field_name=self.embedding_name,
                    return_fields=self.return_fields,
                    distance_threshold=self.distance_threshold,
                    num_results=limit
                )
            else:
                query_to_be_run = VectorQuery(
                    vector=query_embedding_bytes,
                    vector_field_name=self.embedding_name,
                    return_fields=self.return_fields,
                    num_results=limit
                )

            results = await index.query(query_to_be_run)
            log_info(f"Redis search results: {results}")
            return results
        except Exception as e:
            import traceback
            logger.error(f"Error during search: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

