import asyncio
from typing import Any, Dict, List, Optional, Union

try:
    from redis import Redis
    from redisvl.index import SearchIndex
    from redisvl.query import HybridQuery, TextQuery, VectorQuery
    from redisvl.redis.utils import array_to_buffer, buffer_to_array, convert_bytes
    from redisvl.schema import IndexSchema
except ImportError:
    raise ImportError(
        "`redis` and `redisvl` not installed. Please install using `pip install redis redisvl`"
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.utils.string import safe_content_hash
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
            self.redis_client = Redis.from_url(redis_url, **redis_kwargs)
        else:
            self.redis_client = redis_client

        # Index settings
        self.index_name: str = index_name

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Search type and distance metric
        self.search_type: SearchType = search_type
        self.distance: Distance = distance
        self.vector_score_weight: float = vector_score_weight

        # # Reranker instance
        # self.reranker: Optional[Reranker] = reranker

        # Create index schema
        self.schema = self._get_schema()
        self.index = self._create_index()
        self.meta_data_fields = set()

        log_debug(f"Initialized Redis with index '{self.index_name}'")

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

    def _create_index(self) -> IndexSchema:
        """Create the RedisVL index schema."""
        # Map distance metrics to RedisVL distance types

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
            logger.error(f"Error creating Redis index: {e}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        pass

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the index."""
        # try:
        #     doc_id = document.id or safe_content_hash(document.content)
        #     return self.redis_client.hexists(f"{self.index_name}:{doc_id}", "id")
        # except Exception as e:
        #     logger.error(f"Error checking if document exists: {e}")
        #     return False
        pass

    async def async_doc_exists(self, document: Document) -> bool:
        """Async version of doc_exists method."""
        # return await asyncio.to_thread(self.doc_exists, document)
        pass

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        # try:
        #     # Search for documents with the given name
        #     query = VectorQuery(
        #         vector=[0.0] * self.dimensions,  # Dummy vector
        #         vector_field="embedding",
        #         return_fields=["id"],
        #         filter_expression="@name:{" + name + "}",
        #         num_results=1,
        #     )
        #     results = self.redisvl.search(query, self.index_name)
        #     return len(results) > 0
        # except Exception as e:
        #     logger.error(f"Error checking if name exists: {e}")
        #     return False
        pass

    def async_name_exists(self, name: str) -> bool:
        """Async version of name_exists method."""
        # return self.name_exists(name)  # Redis operations are already fast
        pass

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        # try:
        #     return self.redis_client.hexists(f"{self.index_name}:{id}", "id")
        # except Exception as e:
        #     logger.error(f"Error checking if ID exists: {e}")
        #     return False
        pass

    def _parse_redis_hash(self, doc: Document):
        """
        Create object serializable into Redis HASH structure
        """
        doc_dict = doc.to_dict()
        if not doc.embedding:
            doc.embed(self.embedder)

        # TODO: determine how we want to handle dtypes
        doc_dict["embedding"] = array_to_buffer(doc.embedding, "float32")
        if "meta_data" in doc_dict:
            meta_data = doc_dict.pop("meta_data", {})
            for md in meta_data:
                self.meta_data_fields.add(md)
            doc_dict.update(meta_data)

        return doc_dict

    def insert(
        self, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents into the Redis index."""

        # TODO: figure out how/if we support custom index definitions
        try:
            # Question: do we want to check successful here?
            # num_docs_before + documents = index.info()["num_docs"]
            documents = [self._parse_redis_hash(doc) for doc in documents]
            self.index.load(documents)
        except Exception as e:
            logger.error(f"Error inserting documents: {e}")
            raise

    async def async_insert(
        self, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async version of insert method."""
        # await asyncio.to_thread(self.insert, documents, filters)
        pass

    def upsert_available(self) -> bool:
        """Check if upsert is available (always True for Redis)."""
        # TODO: update when upsert implemented
        return False

    def upsert(
        self, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents into the Redis index."""
        pass

    async def async_upsert(
        self, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async version of upsert method."""
        pass

    def search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for documents using the specified search type."""
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
            logger.error(f"Error in search: {e}")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Async version of search method."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform vector similarity search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(
                self.embedder.get_embedding(query), "float32"
            )

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

            return documents
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
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

            return documents
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform hybrid search combining vector and keyword search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(
                self.embedder.get_embedding(query), "float32"
            )

            # Create vector query
            vector_query = HybridQuery(
                vector=query_embedding,
                vector_field_name="embedding",
                text=query,
                text_field_name="content",
                alpha=self.vector_score_weight,
                return_fields=["id", "name", "content"],
                num_results=limit,
            )

            # Execute search
            results = self.index.query(vector_query)
            parsed = convert_bytes(results)

            # Convert results to documents
            documents = [Document.from_dict(p) for p in parsed]

            return documents
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            return []

    def drop(self) -> None:
        """Drop the Redis index."""
        try:
            self.index.drop()
            log_debug(f"Dropped Redis index: {self.index_name}")
        except Exception as e:
            logger.error(f"Error dropping Redis index: {e}")
            raise

    async def async_drop(self) -> None:
        """Async version of drop method."""
        pass

    def exists(self) -> bool:
        """Check if the Redis index exists."""
        try:
            return True if self.index.info() else False
        except Exception as e:
            logger.error(f"Error checking if index exists: {e}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        return await asyncio.to_thread(self.exists)

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
            logger.error(f"Error deleting Redis index: {e}")
            return False
