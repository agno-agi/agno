import asyncio
from typing import Any, Dict, List, Optional, Union

try:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis
    from redisvl.index import AsyncSearchIndex, SearchIndex
    from redisvl.query import FilterQuery, HybridQuery, TextQuery, VectorQuery
    from redisvl.query.filter import Tag
    from redisvl.redis.utils import array_to_buffer, convert_bytes
    from redisvl.schema import IndexSchema
except ImportError:
    raise ImportError("`redis` and `redisvl` not installed. Please install using `pip install redis redisvl`")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import hash_string_sha256
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType


class RedisDB(VectorDb):
    """
    Redis class for managing vector operations with Redis and RedisVL.

    This class provides methods for creating, inserting, searching, and managing
    vector data in a Redis database using the RedisVL library.
    """

    def __init__(
        self,
        index_name: str,
        redis_url: Optional[str] = None,
        redis_client: Optional[Redis] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        vector_score_weight: float = 0.7,
        reranker: Optional[Reranker] = None,
        **redis_kwargs,
    ):
        """
        Initialize the Redis instance.

        Args:
            index_name (str): Name of the Redis index to store vector data.
            redis_url (Optional[str]): Redis connection URL.
            redis_client (Optional[redis.Redis]): Redis client instance.
            embedder (Optional[Embedder]): Embedder instance for creating embeddings.
            search_type (SearchType): Type of search to perform.
            distance (Distance): Distance metric for vector comparisons.
            vector_score_weight (float): Weight for vector similarity in hybrid search.
            reranker (Optional[Reranker]): Reranker instance.
            **redis_kwargs: Additional Redis connection parameters.
        """
        if not index_name:
            raise ValueError("Index name must be provided.")

        if redis_client is None and redis_url is None:
            raise ValueError("Either 'redis_url' or 'redis_client' must be provided.")

        self.redis_url = redis_url

        # Initialize Redis client
        if redis_client is None:
            assert redis_url is not None
            self.redis_client = Redis.from_url(redis_url, **redis_kwargs)
        else:
            self.redis_client = redis_client

        # Index settings
        self.index_name: str = index_name

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Search type and distance metric
        self.search_type: SearchType = search_type
        self.distance: Distance = distance
        self.vector_score_weight: float = vector_score_weight

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Create index schema
        self.schema = self._get_schema()
        self.index = self._create_index()
        self.meta_data_fields: set[str] = set()

        # Async components - created lazily when needed
        self._async_redis_client: Optional[AsyncRedis] = None
        self._async_index: Optional[AsyncSearchIndex] = None

        log_debug(f"Initialized Redis with index '{self.index_name}'")

    async def _get_async_index(self) -> AsyncSearchIndex:
        """Get or create the async index and client."""
        if self._async_index is None:
            if self.redis_url is None:
                raise ValueError("redis_url must be provided for async operations")
            url: str = self.redis_url
            self._async_redis_client = AsyncRedis.from_url(url)
            self._async_index = AsyncSearchIndex(schema=self.schema, redis_client=self._async_redis_client)
        return self._async_index

    def _get_schema(self):
        """Get default redis schema"""
        distance_mapping = {
            Distance.cosine: "cosine",
            Distance.l2: "l2",
            Distance.max_inner_product: "ip",
        }

        return IndexSchema.from_dict(
            {
                "index": {
                    "name": self.index_name,
                    "prefix": f"{self.index_name}:",
                    "storage_type": "hash",
                },
                "fields": [
                    {"name": "id", "type": "tag"},
                    {"name": "name", "type": "tag"},
                    {"name": "content", "type": "text"},
                    {"name": "content_hash", "type": "tag"},
                    {"name": "content_id", "type": "tag"},
                    # Common metadata fields used in operations/tests
                    {"name": "status", "type": "tag"},
                    {"name": "category", "type": "tag"},
                    {"name": "tag", "type": "tag"},
                    {"name": "source", "type": "tag"},
                    {"name": "mode", "type": "tag"},
                    {
                        "name": "embedding",
                        "type": "vector",
                        "attrs": {
                            "dims": self.dimensions,
                            "distance_metric": distance_mapping[self.distance],
                            "algorithm": "flat",
                        },
                    },
                ],
            }
        )

    def _create_index(self) -> SearchIndex:
        """Create the RedisVL index object for this schema."""
        return SearchIndex(self.schema, redis_url=self.redis_url)

    def create(self) -> None:
        """Create the Redis index if it does not exist."""
        try:
            if not self.exists():
                self.index.create()
                log_debug(f"Created Redis index: {self.index_name}")
            else:
                log_debug(f"Redis index already exists: {self.index_name}")
        except Exception as e:
            log_error(f"Error creating Redis index: {e}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        try:
            async_index = await self._get_async_index()
            await async_index.create(overwrite=False, drop=False)
            log_debug(f"Created Redis index: {self.index_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                log_debug(f"Redis index already exists: {self.index_name}")
            else:
                log_error(f"Error creating Redis index: {e}")
                raise

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        try:
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if name exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:  # type: ignore[override]
        """Async version of name_exists method."""
        try:
            async_index = await self._get_async_index()
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = await async_index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if name exists: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        try:
            id_filter = Tag("id") == id
            query = FilterQuery(
                filter_expression=id_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if ID exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document with the given content hash exists."""
        try:
            content_hash_filter = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=content_hash_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if content hash exists: {e}")
            return False

    def _parse_redis_hash(self, doc: Document):
        """
        Create object serializable into Redis HASH structure
        """
        doc_dict = doc.to_dict()
        # Ensure an ID is present; derive a deterministic one from content when missing
        doc_id = doc.id or hash_string_sha256(doc.content)
        doc_dict["id"] = doc_id
        if not doc.embedding:
            doc.embed(self.embedder)

        # TODO: determine how we want to handle dtypes
        doc_dict["embedding"] = array_to_buffer(doc.embedding, "float32")

        # Add content_id if available
        if hasattr(doc, "content_id") and doc.content_id:
            doc_dict["content_id"] = doc.content_id

        if "meta_data" in doc_dict:
            meta_data = doc_dict.pop("meta_data", {})
            for md in meta_data:
                self.meta_data_fields.add(md)
            doc_dict.update(meta_data)

        return doc_dict

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert documents into the Redis index."""
        try:
            # Store content hash for tracking
            parsed_documents = []
            for doc in documents:
                parsed_doc = self._parse_redis_hash(doc)
                parsed_doc["content_hash"] = content_hash
                parsed_documents.append(parsed_doc)

            self.index.load(parsed_documents, id_field="id")
            log_debug(f"Inserted {len(documents)} documents with content_hash: {content_hash}")
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async version of insert method."""
        try:
            async_index = await self._get_async_index()
            parsed_documents = []
            for doc in documents:
                parsed_doc = self._parse_redis_hash(doc)
                parsed_doc["content_hash"] = content_hash
                parsed_documents.append(parsed_doc)
            await async_index.load(parsed_documents, id_field="id")
            log_debug(f"Inserted {len(documents)} documents with content_hash: {content_hash}")
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    def upsert_available(self) -> bool:
        """Check if upsert is available (always True for Redis)."""
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upsert documents into the Redis index.
        Strategy: delete existing docs with the same content_hash, then insert new docs.
        """
        try:
            # Find existing docs for this content_hash and delete them
            ch_filter = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=ch_filter,
                return_fields=["id"],
                num_results=1000,
            )
            existing = self.index.query(query)
            parsed = convert_bytes(existing)
            for r in parsed:
                key = r.get("id")
                if key:
                    self.index.drop_keys(key)

            # Insert new docs
            self.insert(content_hash, documents, filters)
        except Exception as e:
            log_error(f"Error upserting documents: {e}")
            raise

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async version of upsert method.
        Strategy: delete existing docs with the same content_hash, then insert new docs.
        """
        try:
            async_index = await self._get_async_index()

            # Find existing docs for this content_hash and delete them
            ch_filter = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=ch_filter,
                return_fields=["id"],
                num_results=1000,
            )
            existing = await async_index.query(query)
            parsed = convert_bytes(existing)
            for r in parsed:
                key = r.get("id")
                if key:
                    await async_index.drop_keys(key)

            # Insert new docs
            await self.async_insert(content_hash, documents, filters)
        except Exception as e:
            log_error(f"Error upserting documents: {e}")
            raise

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Search for documents using the specified search type."""

        if filters and isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Redis. No filters will be applied.")
            filters = None
        try:
            if self.search_type == SearchType.vector:
                return self.vector_search(query, limit)
            elif self.search_type == SearchType.keyword:
                return self.keyword_search(query, limit)
            elif self.search_type == SearchType.hybrid:
                return self.hybrid_search(query, limit)
            else:
                raise ValueError(f"Unsupported search type: {self.search_type}")
        except Exception as e:
            log_error(f"Error in search: {e}")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Async version of search method."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform vector similarity search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(self.embedder.get_embedding(query), "float32")

            # TODO: do we want to pass back the embedding?
            # Create vector query
            vector_query = VectorQuery(
                vector=query_embedding,
                vector_field_name="embedding",
                return_fields=["id", "name", "content"],
                return_score=False,
                num_results=limit,
            )

            # Execute search
            results = self.index.query(vector_query)

            # Convert results to documents
            documents = [Document.from_dict(r) for r in results]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in vector search: {e}")
            return []

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform keyword search using Redis text search."""
        try:
            # Create text query
            text_query = TextQuery(
                text=query,
                text_field_name="content",
            )

            # Execute search
            results = self.index.query(text_query)

            # Convert results to documents
            parsed = convert_bytes(results)

            # Convert results to documents
            documents = [Document.from_dict(p) for p in parsed]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in keyword search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform hybrid search combining vector and keyword search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(self.embedder.get_embedding(query), "float32")

            # Create vector query
            vector_query = HybridQuery(
                vector=query_embedding,
                vector_field_name="embedding",
                text=query,
                text_field_name="content",
                linear_alpha=self.vector_score_weight,
                return_fields=["id", "name", "content"],
                num_results=limit,
            )

            # Execute search
            results = self.index.query(vector_query)
            parsed = convert_bytes(results)

            # Convert results to documents
            documents = [Document.from_dict(p) for p in parsed]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in hybrid search: {e}")
            return []

    def drop(self) -> bool:  # type: ignore[override]
        """Drop the Redis index."""
        try:
            self.index.delete(drop=True)
            log_debug(f"Deleted Redis index: {self.index_name}")
            return True
        except Exception as e:
            log_error(f"Error dropping Redis index: {e}")
            return False

    async def async_drop(self) -> None:
        """Async version of drop method."""
        try:
            async_index = await self._get_async_index()
            await async_index.delete(drop=True)
            log_debug(f"Deleted Redis index: {self.index_name}")
        except Exception as e:
            log_error(f"Error dropping Redis index: {e}")
            raise

    def exists(self) -> bool:
        """Check if the Redis index exists."""
        try:
            return self.index.exists()
        except Exception as e:
            log_error(f"Error checking if index exists: {e}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        try:
            async_index = await self._get_async_index()
            return await async_index.exists()
        except Exception as e:
            log_error(f"Error checking if index exists: {e}")
            return False

    def optimize(self) -> None:
        """Optimize the Redis index (no-op for Redis)."""
        log_debug("Redis optimization not required")
        pass

    def delete(self) -> bool:
        """Delete the Redis index (same as drop)."""
        try:
            self.index.clear()
            return True
        except Exception as e:
            log_error(f"Error deleting Redis index: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete documents by ID."""
        try:
            # Use RedisVL to drop documents by document ID
            result = self.index.drop_documents(id)
            log_debug(f"Deleted document with id '{id}' from Redis index")
            return result > 0
        except Exception as e:
            log_error(f"Error deleting document by ID: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name."""
        try:
            # First find documents with the given name
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with name '{name}'")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by name: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        try:
            # Build filter expression for metadata using Tag filters
            filters = []
            for key, value in metadata.items():
                filters.append(Tag(key) == str(value))

            # Combine filters with AND logic
            if len(filters) == 1:
                combined_filter = filters[0]
            else:
                combined_filter = filters[0]
                for f in filters[1:]:
                    combined_filter = combined_filter & f

            # Find documents with the given metadata
            query = FilterQuery(
                filter_expression=combined_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with metadata {metadata}")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by metadata: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID."""
        try:
            # Find documents with the given content_id
            content_id_filter = Tag("content_id") == content_id
            query = FilterQuery(
                filter_expression=content_id_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with content_id '{content_id}'")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by content_id: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Update metadata for documents with the given content ID."""
        try:
            # Find documents with the given content_id
            content_id_filter = Tag("content_id") == content_id
            query = FilterQuery(
                filter_expression=content_id_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)

            # Update metadata for each found document
            for result in results:
                doc_id = result.get("id")
                if doc_id:
                    # result['id'] is the Redis key
                    key = result.get("id")
                    # Update the hash with new metadata
                    if key:
                        self.redis_client.hset(key, mapping=metadata)

            log_debug(f"Updated metadata for documents with content_id '{content_id}'")
        except Exception as e:
            log_error(f"Error updating metadata: {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get list of supported search types."""
        return ["vector", "keyword", "hybrid"]
