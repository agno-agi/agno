import asyncio
import json
import time
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    from redis import Redis
    from redis.commands.search.field import TagField, TextField, VectorField
    from redis.commands.search.index_definition import IndexDefinition, IndexType
    from redis.commands.search.query import Query
except ImportError:
    raise ImportError("`redis` not installed. Please install using `pip install redis`")

try:
    import numpy as np
except ImportError:
    raise ImportError("`numpy` not installed. Please install using `pip install numpy`")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.redis.index import HNSW, Ivfflat
from agno.vectordb.search import SearchType


class RedisVector(VectorDb):
    """
    RedisVector class for managing vector operations with Redis and RediSearch.

    This class provides methods for creating, inserting, searching, and managing
    vector data in a Redis database using the RediSearch module with vector similarity search.
    """

    def __init__(
        self,
        index_name: str,
        prefix: str = "doc:",
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        ssl: Optional[bool] = False,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        vector_index: Union[Ivfflat, HNSW] = HNSW(),
        distance: Distance = Distance.cosine,
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        reranker: Optional[Reranker] = None,
        expire: Optional[int] = None,
    ):
        """
        Initialize the RedisVector instance.

        Args:
            index_name (str): Name of the vector index.
            prefix (str): Key prefix for documents in Redis.
            host (str): Redis host address.
            port (int): Redis port number.
            db (int): Redis database number.
            password (Optional[str]): Redis password if authentication is required.
            ssl (Optional[bool]): Whether to use SSL for Redis connection.
            embedder (Optional[Embedder]): Embedder instance for creating embeddings.
            search_type (SearchType): Type of search to perform.
            vector_index (Union[Ivfflat, HNSW]): Vector index configuration.
            distance (Distance): Distance metric for vector comparisons.
            schema_version (int): Version of the index schema.
            auto_upgrade_schema (bool): Automatically upgrade schema if True.
            reranker (Optional[Reranker]): Reranker instance for post-processing results.
            expire (Optional[int]): TTL (time to live) in seconds for Redis keys.
        """
        if not index_name:
            raise ValueError("Index name must be provided.")

        # Redis settings
        self.index_name: str = index_name
        self.prefix: str = prefix
        self.expire: Optional[int] = expire
        self.redis_client: Redis = Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            ssl=ssl,
        )

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Search type
        self.search_type: SearchType = search_type
        # Distance metric
        self.distance: Distance = distance
        # Index configuration
        self.vector_index: Union[Ivfflat, HNSW] = vector_index
        # Schema version
        self.schema_version: int = schema_version
        # Automatically upgrade schema if True
        self.auto_upgrade_schema: bool = auto_upgrade_schema
        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        log_debug(f"Initialized RedisVector with index '{self.index_name}' and prefix '{self.prefix}'")

    def _get_key(self, doc_id: str) -> str:
        """Generate Redis key for a document."""
        return f"{self.prefix}{doc_id}"

    def _get_distance_metric(self) -> str:
        """Get Redis distance metric string."""
        distance_map = {
            Distance.cosine: "COSINE",
            Distance.l2: "L2",
            Distance.max_inner_product: "IP",
        }
        return distance_map.get(self.distance, "COSINE")

    def _get_vector_algorithm(self) -> str:
        """Get Redis vector algorithm string."""
        if isinstance(self.vector_index, HNSW):
            return "HNSW"
        elif isinstance(self.vector_index, Ivfflat):
            return "FLAT"
        else:
            return "FLAT"

    def index_exists(self) -> bool:
        """
        Check if the vector index exists in Redis.

        Returns:
            bool: True if the index exists, False otherwise.
        """
        try:
            self.redis_client.ft(self.index_name).info()
            return True
        except Exception:
            return False

    def create(self) -> None:
        """
        Create the vector index if it does not exist.
        """
        if not self.index_exists():
            log_debug(f"Creating vector index: {self.index_name}")
            try:
                # Define the schema
                schema = [
                    TextField("name"),
                    TextField("content"),
                    TagField("content_hash"),
                    VectorField(
                        "vector",
                        self._get_vector_algorithm(),
                        {
                            "TYPE": "FLOAT32",
                            "DIM": self.dimensions,
                            "DISTANCE_METRIC": self._get_distance_metric(),
                        }
                        | (
                            {"M": self.vector_index.m, "EF_CONSTRUCTION": self.vector_index.ef_construction}
                            if isinstance(self.vector_index, HNSW)
                            else {}
                        ),
                    ),
                ]

                # Index definition
                definition = IndexDefinition(prefix=[self.prefix], index_type=IndexType.HASH)

                # Create index
                self.redis_client.ft(self.index_name).create_index(fields=schema, definition=definition)
                log_info(f"Created vector index: {self.index_name}")
            except Exception as e:
                logger.error(f"Error creating index: {e}")
                raise
        else:
            log_debug(f"Index '{self.index_name}' already exists")

    async def async_create(self) -> None:
        """Create the index asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def _clean_content(self, content: str) -> str:
        """
        Clean the content by replacing problematic characters.

        Args:
            content (str): The content to clean.

        Returns:
            str: The cleaned content.
        """
        return content.replace("\x00", "\ufffd")

    def doc_exists(self, document: Document) -> bool:
        """
        Check if a document with the same content hash exists.

        Args:
            document (Document): The document to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        cleaned_content = self._clean_content(document.content)
        content_hash = md5(cleaned_content.encode()).hexdigest()
        return self.content_hash_exists(content_hash)

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if document exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.doc_exists, document)

    def content_hash_exists(self, content_hash: str) -> bool:
        """
        Check if a document with the given content hash exists.

        Args:
            content_hash (str): The content hash to check.

        Returns:
            bool: True if a document with the hash exists, False otherwise.
        """
        try:
            query = Query(f"@content_hash:{{{content_hash}}}").no_content()
            results = self.redis_client.ft(self.index_name).search(query)
            return results.total > 0
        except Exception as e:
            logger.error(f"Error checking content hash existence: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists.

        Args:
            name (str): The name to check.

        Returns:
            bool: True if a document with the name exists, False otherwise.
        """
        try:
            # Escape the name for Redis search
            escaped_name = name.replace("-", "\\-").replace(":", "\\:")
            query = Query(f"@name:{escaped_name}").no_content()
            results = self.redis_client.ft(self.index_name).search(query)
            return results.total > 0
        except Exception as e:
            logger.error(f"Error checking name existence: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if name exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, doc_id: str) -> bool:
        """
        Check if a document with the given ID exists.

        Args:
            doc_id (str): The ID to check.

        Returns:
            bool: True if a document with the ID exists, False otherwise.
        """
        try:
            key = self._get_key(doc_id)
            return self.redis_client.exists(key) > 0
        except Exception as e:
            logger.error(f"Error checking ID existence: {e}")
            return False

    def insert(
        self,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        """
        Insert documents into Redis.

        Args:
            documents (List[Document]): List of documents to insert.
            filters (Optional[Dict[str, Any]]): Additional metadata filters.
            batch_size (int): Number of documents to insert in each batch.
        """
        try:
            # Use pipeline for batch operations
            pipe = self.redis_client.pipeline()

            for i, doc in enumerate(documents):
                try:
                    # Generate embedding if not present
                    doc.embed(embedder=self.embedder)

                    # Clean content and generate hash
                    cleaned_content = self._clean_content(doc.content)
                    content_hash = md5(cleaned_content.encode()).hexdigest()
                    doc_id = doc.id or content_hash

                    # Prepare document data
                    doc_data = {
                        "name": doc.name or "",
                        "content": cleaned_content,
                        "content_hash": content_hash,
                        "vector": np.array(doc.embedding, dtype=np.float32).tobytes(),
                        "meta_data": json.dumps(doc.meta_data or {}),
                        "usage": json.dumps(doc.usage or {}),
                        "created_at": int(time.time()),
                    }

                    if filters:
                        doc_data["filters"] = json.dumps(filters)

                    # Add to pipeline
                    key = self._get_key(doc_id)
                    pipe.hset(key, mapping=doc_data)

                    if self.expire:
                        pipe.expire(key, self.expire)

                    # Execute batch
                    if (i + 1) % batch_size == 0:
                        pipe.execute()
                        pipe = self.redis_client.pipeline()
                        log_debug(f"Inserted batch ending at index {i}")

                except Exception as e:
                    logger.error(f"Error processing document '{doc.name}': {e}")

            # Execute remaining documents
            if len(pipe.command_stack) > 0:
                pipe.execute()

            log_info(f"Inserted {len(documents)} documents")

        except Exception as e:
            logger.error(f"Error inserting documents: {e}")
            raise

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.insert, documents, filters)

    def upsert_available(self) -> bool:
        """
        Check if upsert operation is available.

        Returns:
            bool: Always returns True for RedisVector.
        """
        return True

    def upsert(
        self,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        """
        Upsert (insert or update) documents in Redis.

        Args:
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Additional metadata filters.
            batch_size (int): Number of documents to upsert in each batch.
        """
        # For Redis, upsert is the same as insert since HSET overwrites existing keys
        self.insert(documents, filters, batch_size)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.upsert, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform a search based on the configured search type.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """
        if self.search_type == SearchType.vector:
            return self.vector_search(query=query, limit=limit, filters=filters)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query=query, limit=limit, filters=filters)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query=query, limit=limit, filters=filters)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform a vector similarity search.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            # Get the embedding for the query string
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for Query: {query}")
                return []

            # Convert embedding to bytes
            query_vector = np.array(query_embedding, dtype=np.float32).tobytes()

            # Build the query
            base_query = f"*=>[KNN {limit} @vector $query_vector AS vector_score]"

            # Add filters if provided
            if filters:
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        filter_parts.append(f"@{key}:{{{value}}}")
                    else:
                        filter_parts.append(f"@{key}:{value}")

                if filter_parts:
                    filter_query = " ".join(filter_parts)
                    base_query = f"({filter_query})=>[KNN {limit} @vector $query_vector AS vector_score]"

            redis_query = (
                Query(base_query)
                .sort_by("vector_score")
                .return_fields("vector_score", "name", "content", "meta_data", "usage")
                .paging(0, limit)
                .dialect(2)
            )

            # Execute the search
            try:
                results = self.redis_client.ft(self.index_name).search(redis_query, {"query_vector": query_vector})
            except Exception as e:
                logger.error(f"Error performing vector search: {e}")
                logger.error("Index might not exist, creating for future use")
                self.create()
                return []

            # Convert results to Document objects
            search_results: List[Document] = []
            for doc in results.docs:
                try:
                    meta_data = json.loads(getattr(doc, "meta_data", "{}"))
                    usage = json.loads(getattr(doc, "usage", "{}"))

                    document = Document(
                        id=doc.id.replace(self.prefix, ""),  # Remove prefix from ID
                        name=getattr(doc, "name", ""),
                        content=getattr(doc, "content", ""),
                        meta_data=meta_data,
                        usage=usage,
                        embedder=self.embedder,
                    )
                    search_results.append(document)
                except Exception as e:
                    logger.error(f"Error processing search result: {e}")

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during vector search: {e}")
            return []

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform a keyword search on the content field.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            # Escape special characters in query
            escaped_query = query.replace("-", "\\-").replace(":", "\\:")

            # Build the query
            base_query = f"@content:({escaped_query})"

            # Add filters if provided
            if filters:
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        filter_parts.append(f"@{key}:{{{value}}}")
                    else:
                        filter_parts.append(f"@{key}:{value}")

                if filter_parts:
                    filter_query = " ".join(filter_parts)
                    base_query = f"({base_query}) ({filter_query})"

            redis_query = Query(base_query).return_fields("name", "content", "meta_data", "usage").paging(0, limit)

            # Execute the search
            try:
                results = self.redis_client.ft(self.index_name).search(redis_query)
            except Exception as e:
                logger.error(f"Error performing keyword search: {e}")
                logger.error("Index might not exist, creating for future use")
                self.create()
                return []

            # Convert results to Document objects
            search_results: List[Document] = []
            for doc in results.docs:
                try:
                    meta_data = json.loads(getattr(doc, "meta_data", "{}"))
                    usage = json.loads(getattr(doc, "usage", "{}"))

                    document = Document(
                        id=doc.id.replace(self.prefix, ""),
                        name=getattr(doc, "name", ""),
                        content=getattr(doc, "content", ""),
                        meta_data=meta_data,
                        usage=usage,
                        embedder=self.embedder,
                    )
                    search_results.append(document)
                except Exception as e:
                    logger.error(f"Error processing search result: {e}")

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during keyword search: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Perform a hybrid search combining vector similarity and keyword search.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            # Get results from both search types
            vector_results = self.vector_search(query, limit * 2, filters)
            keyword_results = self.keyword_search(query, limit * 2, filters)

            # Combine and deduplicate results
            seen_ids = set()
            combined_results = []

            # Add vector results first (they have similarity scores)
            for doc in vector_results:
                if doc.id not in seen_ids:
                    seen_ids.add(doc.id)
                    combined_results.append(doc)

            # Add keyword results that weren't in vector results
            for doc in keyword_results:
                if doc.id not in seen_ids:
                    seen_ids.add(doc.id)
                    combined_results.append(doc)

            # Limit the results
            combined_results = combined_results[:limit]

            if self.reranker:
                combined_results = self.reranker.rerank(query=query, documents=combined_results)

            log_info(f"Found {len(combined_results)} documents in hybrid search")
            return combined_results

        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            return []

    def drop(self) -> None:
        """
        Drop the vector index and all associated documents.
        """
        try:
            if self.index_exists():
                # Drop the index (this also removes the data)
                self.redis_client.ft(self.index_name).dropindex(delete_documents=True)
                log_info(f"Dropped index '{self.index_name}' and all documents")
            else:
                log_info(f"Index '{self.index_name}' does not exist")
        except Exception as e:
            logger.error(f"Error dropping index: {e}")
            raise

    async def async_drop(self) -> None:
        """Drop the index asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """
        Check if the vector index exists.

        Returns:
            bool: True if the index exists, False otherwise.
        """
        return self.index_exists()

    async def async_exists(self) -> bool:
        """Check if index exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        """
        Get the number of documents in the index.

        Returns:
            int: The number of documents in the index.
        """
        try:
            if not self.index_exists():
                return 0

            # Use a wildcard search to count all documents
            results = self.redis_client.ft(self.index_name).search(Query("*").no_content())
            return results.total
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    def optimize(self, force_recreate: bool = False) -> None:
        """
        Optimize the vector database.
        For Redis, this doesn't require special optimization as indexes are maintained automatically.

        Args:
            force_recreate (bool): If True, recreate the index.
        """
        log_debug("==== Optimizing Vector DB ====")

        if force_recreate and self.index_exists():
            log_info("Force recreating index")
            self.drop()
            self.create()
        elif not self.index_exists():
            log_info("Creating index as it doesn't exist")
            self.create()
        else:
            log_info("Index already exists and optimization not needed for Redis")

        log_debug("==== Optimized Vector DB ====")

    def delete(self) -> bool:
        """
        Delete all documents from the index without dropping the index structure.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            if not self.index_exists():
                log_info("Index does not exist, nothing to delete")
                return True

            # Get all document keys
            pattern = f"{self.prefix}*"
            keys = list(self.redis_client.scan_iter(match=pattern))

            if keys:
                # Delete all matching keys
                self.redis_client.delete(*keys)
                log_info(f"Deleted {len(keys)} documents")
            else:
                log_info("No documents found to delete")

            return True

        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            return False

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the RedisVector instance.

        Args:
            memo (dict): A dictionary of objects already copied during the current copying pass.

        Returns:
            RedisVector: A deep-copied instance of RedisVector.
        """
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            # Reuse redis_client and embedder without copying
            if k in {"redis_client", "embedder"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        return copied_obj
