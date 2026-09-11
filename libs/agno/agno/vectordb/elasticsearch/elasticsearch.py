from __future__ import annotations

import asyncio
import time
from hashlib import md5
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from elasticsearch import AsyncElasticsearch as AsyncElasticsearchClient
    from elasticsearch import Elasticsearch as ElasticsearchClient
    from elasticsearch import exceptions as elasticsearch_exceptions
except ImportError:
    raise ImportError("`elasticsearch` not installed. Please install using `pip install elasticsearch`")

from agno.filters import MAX_FILTER_DEPTH, FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, log_warning, logger
from agno.vectordb.base import (
    VectorDb,
    aembed_before_replace,
    embed_before_replace,
    is_rate_limit_error,
    raise_embedding_failures,
)
from agno.vectordb.distance import Distance
from agno.vectordb.elasticsearch.index import HybridStrategy, Similarity
from agno.vectordb.search import SearchType

# Owner of each chunk, for per-user isolation. The field is absent for user_id=None,
# which is the shared bucket every caller can read but none can delete out of.
USER_ID_FIELD = "user_id"

# Neighbors each shard examines before the top k are picked.
DEFAULT_NUM_CANDIDATES_MULTIPLIER = 10
MIN_NUM_CANDIDATES = 50
# The cluster's own ceiling: num_candidates above this is rejected outright.
MAX_NUM_CANDIDATES = 10000

# rrf rank_window_size defaults to 10 and must be >= the requested size.
RRF_MIN_RANK_WINDOW_SIZE = 10


class Elasticsearch(VectorDb):
    """
    Elasticsearch vector database implementation with comprehensive search capabilities.

    This class provides a complete vector database solution using Elasticsearch as the
    backend, supporting vector similarity search, keyword search, and hybrid search.

    The installed client's major version must match the cluster's: an 8.x cluster
    rejects a 9.x client outright ("Accept version must be either version 8 or 7"),
    so pin `elasticsearch` to the major your cluster runs.

    Async strategy: everything that can be awaited is. Reads and writes both use the
    native async client, and the query embedding is awaited through the embedder's
    async_get_embedding_and_usage. What cannot be awaited is offloaded to a worker
    thread rather than left to block the event loop: Reranker.rerank has no async
    variant on the base class, and neither do the two synchronous helpers an async
    write needs - the owner-mapping gate and the upsert's replace prelude.

    Features:
        - Native dense_vector kNN search with pre-filtering
        - Various similarity functions (cosine, l2_norm, dot_product, max_inner_product)
        - Synchronous and asynchronous operations
        - Bulk document operations (insert, upsert, delete)
        - Advanced filtering capabilities
        - Optional reranking support
        - Per-user isolation through a top-level user_id keyword field

    Attributes:
        index_name (str): Name of the Elasticsearch index
        dimension (int): Dimensionality of the vector embeddings
        similarity (Similarity): Similarity function for the dense_vector field
        search_type (SearchType): Default search type (vector, keyword, or hybrid)
        embedder (Embedder): Embedder instance for generating vector embeddings
        reranker (Optional[Reranker]): Optional reranker for improving search results
    """

    def __init__(
        self,
        index_name: str,
        url: Union[str, List[str]] = "http://localhost:9200",
        dimension: Optional[int] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        similarity: Optional[Similarity] = None,
        search_type: SearchType = SearchType.vector,
        hybrid_strategy: HybridStrategy = HybridStrategy.boost,
        api_key: Optional[str] = None,
        cloud_id: Optional[str] = None,
        basic_auth: Optional[tuple] = None,
        verify_certs: bool = True,
        ca_certs: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 10,
        retry_on_timeout: bool = True,
        num_candidates: Optional[int] = None,
        index_settings: Optional[Dict[str, Any]] = None,
        reranker: Optional[Reranker] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Initialize Elasticsearch vector database.

        Args:
            index_name: Name of the Elasticsearch index
            url: Elasticsearch URL, e.g. "https://user:password@my-cluster:9243". The scheme
                selects TLS and any credentials embedded in the URL are applied, so
                basic_auth is only needed to keep the password out of the URL. Pass a list
                of URLs to spread requests across the nodes of a cluster. Ignored when
                cloud_id is given.
            dimension: Dimensionality of the vector embeddings. Defaults to the embedder's
                dimensions.
            embedder: Embedder instance for generating vector embeddings
            distance: Distance metric, mapped to the matching Elasticsearch similarity.
                Ignored when similarity is passed explicitly.
            similarity: Elasticsearch similarity function for the dense_vector field. Takes
                precedence over distance, and reaches l2_norm, which distance cannot name.
            search_type: Default search type (vector, keyword, or hybrid)
            hybrid_strategy: How a hybrid search combines its two halves. Defaults to
                boost, which every distribution supports; rrf needs a platinum/enterprise
                licence or a trial.
            api_key: Elasticsearch API key for authentication
            cloud_id: Elastic Cloud ID. Takes precedence over url when set.
            basic_auth: HTTP basic authentication tuple (username, password)
            verify_certs: Whether to verify SSL certificates. Defaults to True, unlike the
                client's own default of True only for https, so a misconfigured TLS
                endpoint fails loudly rather than silently dropping verification.
            ca_certs: Path to a CA bundle used to verify the cluster's certificate
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_on_timeout: Whether to retry on timeout errors
            num_candidates: Neighbours each shard considers before the top k are picked.
                Defaults to 10x the requested limit, floored at 50 and capped at the
                cluster's limit of 10000. Higher is more accurate and slower.
            index_settings: Settings sent when the index is created, e.g.
                {"index": {"number_of_shards": 3, "number_of_replicas": 1}}. Defaults to
                no replica, which keeps a single-node cluster green; pass a replica count
                on a multi-node cluster to make the index redundant. A serverless project
                rejects shard settings, and the index is then created without them.
            reranker: Optional reranker for improving search results
            id: Optional custom ID. Derived from the url and index name if not provided.
            name: Optional name for the vector database
            description: Optional description for the vector database
            **kwargs: Additional keyword arguments passed to the underlying
                `elasticsearch.Elasticsearch` and `elasticsearch.AsyncElasticsearch` clients.

        Raises:
            ValueError: If no host can be resolved, or if the embedding dimension cannot
                be resolved
            ImportError: If elasticsearch is not installed
        """
        self.cloud_id = cloud_id
        self.hosts: List[str] = [url] if isinstance(url, str) else list(url)
        if not self.hosts and cloud_id is None:
            raise ValueError("At least one Elasticsearch url must be provided, or a cloud_id.")

        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            origin = cloud_id if cloud_id is not None else self.hosts[0]
            id = generate_id(f"{origin}#{index_name}")

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        # Core configuration
        self.index_name = index_name
        self.distance = distance
        self.similarity = similarity if similarity is not None else self._similarity_for_distance(distance)
        self.search_type = search_type
        self.hybrid_strategy = hybrid_strategy
        self.num_candidates = num_candidates
        self.index_settings = index_settings
        # Whether the live index can honour a user_id scope filter; resolved lazily on first use.
        self._owner_field_exact: Optional[bool] = None

        # Connection configuration
        self.api_key = api_key
        self.basic_auth = basic_auth
        self.verify_certs = verify_certs
        self.ca_certs = ca_certs
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_on_timeout = retry_on_timeout
        self.client_kwargs = kwargs

        # Clients (lazy initialized)
        self._client: Optional[ElasticsearchClient] = None
        self._async_client: Optional[AsyncElasticsearchClient] = None

        # Initialize embedder and reranker
        self.embedder = self._initialize_embedder(embedder)
        self.reranker = reranker

        # Fall back to the embedder's dimensions, as the other vector dbs do
        resolved_dimension = dimension if dimension is not None else self.embedder.dimensions
        if resolved_dimension is None:
            raise ValueError(
                "Could not determine the embedding dimension. Pass dimension=... explicitly "
                f"or use an embedder that declares its dimensions ({type(self.embedder).__name__} does not)."
            )
        self.dimension: int = resolved_dimension

        # Index mapping (depends on dimension and similarity)
        self.mappings = self._create_mappings()
        self.settings = self._create_settings()

        if self.reranker:
            log_debug(f"Reranker configured: {type(self.reranker).__name__}")

    # ========== Initialization and Configuration ==========

    def _initialize_embedder(self, embedder: Optional[Embedder]) -> Embedder:
        """
        Initialize embedder with fallback to default.

        Args:
            embedder: Optional embedder instance

        Returns:
            Embedder: Configured embedder instance

        Note:
            If no embedder is provided, defaults to OpenAIEmbedder
        """
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        else:
            log_info(f"Using provided embedder: {type(embedder).__name__}")
        return embedder

    @staticmethod
    def _similarity_for_distance(distance: Distance) -> Similarity:
        """
        Map a Distance to the matching Elasticsearch similarity function.

        Args:
            distance: Distance metric to map

        Returns:
            Similarity: Elasticsearch similarity function

        Note:
            Distance.l2 maps to l2_norm and max_inner_product to max_inner_product;
            anything else falls back to cosine.
        """
        mapping = {
            Distance.cosine: Similarity.cosine,
            Distance.l2: Similarity.l2_norm,
            Distance.max_inner_product: Similarity.max_inner_product,
        }
        return mapping.get(distance, Similarity.cosine)

    def _create_settings(self) -> Optional[Dict[str, Any]]:
        """
        Create index settings.

        Returns:
            Optional[Dict[str, Any]]: Index settings sent when the index is created

        Note:
            Defaults to no replica, which is what keeps a single-node cluster green:
            the cluster-wide default of one replica cannot be assigned when there is
            only one node, leaving the index yellow with an unassigned shard.

            A serverless project manages its own shards and rejects this setting, so
            ``_create_index_impl`` retries without settings when it is refused rather
            than failing construction. Shard count is deliberately not set: it has no
            equivalent single-node problem, and leaving it out lets the cluster size
            the index.
        """
        if self.index_settings is not None:
            return self.index_settings
        return {"index": {"number_of_replicas": 0}}

    def _create_mappings(self) -> Dict[str, Any]:
        """
        Create index mappings for Elasticsearch.

        Returns:
            Dict[str, Any]: Complete index mappings

        Note:
            Creates mappings with:
            - dense_vector field for embeddings, indexed for kNN search
            - Text fields for content and name
            - Object field for metadata with dynamic mapping
            - Additional fields for usage and reranking scores
        """
        log_debug(f"Creating mappings with similarity: {self.similarity}")

        return {
            # Off so a date-shaped string stays text. Date detection would map
            # meta_data.published_on="2024-01-15" as a date field, which has no .keyword
            # subfield for an equality filter to match, and the filter would silently
            # select nothing.
            "date_detection": False,
            "dynamic_templates": [
                {
                    "meta_data_strings": {
                        "path_match": "meta_data.*",
                        "match_mapping_type": "string",
                        "mapping": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        },
                    }
                }
            ],
            "properties": {
                "embedding": {
                    "type": "dense_vector",
                    "dims": self.dimension,
                    "index": True,
                    "similarity": self.similarity,
                },
                "content": {"type": "text", "analyzer": "standard"},
                "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                "meta_data": {"type": "object", "dynamic": True},
                # Disabled rather than indexed: usage is an opaque bag of counters that
                # nothing queries, and indexing it would map every provider's keys.
                "usage": {"type": "object", "enabled": False},
                "reranking_score": {"type": "float"},
                "content_id": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                # Fixed-length hash: indexed as an exact-match keyword with no length
                # cap, since ignore_above would silently drop it from the index.
                "content_hash": {"type": "keyword"},
                # Owner of the chunk. Keyword rather than text so the scope filter
                # matches the id exactly instead of its analyzed tokens.
                USER_ID_FIELD: {"type": "keyword"},
            },
        }

    @property
    def client(self) -> ElasticsearchClient:
        """
        Get or create synchronous Elasticsearch client.

        Returns:
            ElasticsearchClient: Configured synchronous client instance

        Note:
            Client is lazily initialized and cached for reuse
        """
        if self._client is None:
            self._client = self._create_sync_client()
        return self._client

    @property
    def async_client(self) -> AsyncElasticsearchClient:
        """
        Get or create asynchronous Elasticsearch client.

        Returns:
            AsyncElasticsearchClient: Configured asynchronous client instance

        Note:
            Client is lazily initialized and cached for reuse
        """
        if self._async_client is None:
            self._async_client = self._create_async_client()
        return self._async_client

    def _connection_config(self) -> Dict[str, Any]:
        """
        Build the keyword arguments shared by both clients.

        Returns:
            Dict[str, Any]: Client connection configuration

        Note:
            cloud_id and hosts are mutually exclusive in the Elasticsearch client, so only
            one of them is ever passed. Optional auth arguments are omitted rather than
            passed as None, which the client rejects for api_key.
        """
        config: Dict[str, Any] = {
            "request_timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_on_timeout": self.retry_on_timeout,
            "verify_certs": self.verify_certs,
        }

        if self.cloud_id is not None:
            config["cloud_id"] = self.cloud_id
        else:
            config["hosts"] = self.hosts

        if self.api_key is not None:
            config["api_key"] = self.api_key
        if self.basic_auth is not None:
            config["basic_auth"] = self.basic_auth
        if self.ca_certs is not None:
            config["ca_certs"] = self.ca_certs

        config.update(self.client_kwargs)
        return config

    def _create_sync_client(self) -> ElasticsearchClient:
        """
        Create synchronous Elasticsearch client with connection testing.

        Returns:
            ElasticsearchClient: Configured and tested synchronous client

        Raises:
            Exception: If client creation or connection test fails
        """
        log_debug("Creating Elasticsearch client")
        try:
            client = ElasticsearchClient(**self._connection_config())
            ping_result = client.ping()
            log_info(f"Successfully connected to Elasticsearch (ping: {ping_result})")
            return client
        except Exception as e:
            logger.error(f"Failed to create Elasticsearch client: {e}")
            raise

    def _create_async_client(self) -> AsyncElasticsearchClient:
        """
        Create asynchronous Elasticsearch client.

        Returns:
            AsyncElasticsearchClient: Configured asynchronous client

        Raises:
            Exception: If client creation fails

        Note:
            Async client doesn't perform a connection test during creation, since that
            would need an await.
        """
        log_debug("Creating async Elasticsearch client")
        try:
            client = AsyncElasticsearchClient(**self._connection_config())
            log_info("Successfully created async Elasticsearch client")
            return client
        except Exception as e:
            logger.error(f"Failed to create async Elasticsearch client: {e}")
            raise

    # ========== Index Lifecycle ==========

    def create(self) -> None:
        """
        Create the index if it does not exist.

        Note:
            This is a synchronous operation that will create the index
            with the configured mappings if it doesn't already exist.
        """
        self._execute_with_timing("create", self._create_index_impl)

    async def async_create(self) -> None:
        """
        Create the index asynchronously if it does not exist.

        Note:
            Asynchronous version of create() method.
        """
        await self._async_execute_with_timing("async_create", self._async_create_index_impl)

    def _create_kwargs(self) -> Dict[str, Any]:
        """Extra arguments for an index creation.

        ``settings`` is omitted entirely when there are none: passing ``settings=None``
        still sends the key, which a serverless project rejects.
        """
        return {"settings": self.settings} if self.settings else {}

    @staticmethod
    def _is_unsupported_settings_error(error: Exception) -> bool:
        """Whether the cluster refused the settings themselves rather than the index.

        A serverless project answers an index creation carrying shard or replica
        settings with "not available when running in serverless mode". The index is
        creatable, just not on those terms, so the caller retries without them.
        """
        message = str(error)
        return "not available when running in serverless" in message or (
            "unknown setting" in message and "number_of_replicas" in message
        )

    def _create_index_impl(self) -> None:
        """
        Implementation for synchronous index creation.

        Creates the index with the configured mappings if it doesn't exist.
        """
        if not self.exists():
            log_debug(f"Creating index: {self.index_name}")
            try:
                self.client.indices.create(index=self.index_name, mappings=self.mappings, **self._create_kwargs())
            except Exception as e:
                if not self._is_unsupported_settings_error(e):
                    raise
                log_info(f"Cluster manages its own shards; creating index {self.index_name} without settings")
                self.client.indices.create(index=self.index_name, mappings=self.mappings)
            log_info(f"Successfully created index: {self.index_name}")
            self._owner_field_exact = True
        else:
            log_debug(f"Index {self.index_name} already exists")

    async def _async_create_index_impl(self) -> None:
        """
        Implementation for asynchronous index creation.

        Creates the index with the configured mappings if it doesn't exist.
        """
        if not await self.async_exists():
            log_debug(f"Creating index (async): {self.index_name}")
            try:
                await self.async_client.indices.create(
                    index=self.index_name, mappings=self.mappings, **self._create_kwargs()
                )
            except Exception as e:
                if not self._is_unsupported_settings_error(e):
                    raise
                log_info(f"Cluster manages its own shards; creating index {self.index_name} without settings")
                await self.async_client.indices.create(index=self.index_name, mappings=self.mappings)
            log_info(f"Successfully created index (async): {self.index_name}")
            self._owner_field_exact = True
        else:
            log_info(f"Index {self.index_name} already exists")

    def exists(self) -> bool:
        """
        Check if the index exists.

        Returns:
            bool: True if index exists, False otherwise

        Note:
            Returns False if an error occurs during the check
        """
        try:
            log_debug(f"Checking if index exists: {self.index_name}")
            exists = bool(self.client.indices.exists(index=self.index_name))
            log_debug(f"Index {self.index_name} exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if index exists: {e}")
            return False

    async def async_exists(self) -> bool:
        """
        Check if the index exists asynchronously.

        Returns:
            bool: True if index exists, False otherwise

        Note:
            Returns False if an error occurs during the check
        """
        try:
            log_debug(f"Checking if index exists (async): {self.index_name}")
            exists = bool(await self.async_client.indices.exists(index=self.index_name))
            log_debug(f"Index {self.index_name} exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if index exists: {e}")
            return False

    def drop(self) -> None:
        """
        Delete the index if it exists.

        Warning:
            This operation permanently deletes the index and all its data.
        """
        self._execute_with_timing("drop", self._drop_index_impl)

    async def async_drop(self) -> None:
        """
        Delete the index asynchronously if it exists.

        Warning:
            This operation permanently deletes the index and all its data.
        """
        await self._async_execute_with_timing("async_drop", self._async_drop_index_impl)

    def _drop_index_impl(self) -> None:
        """
        Implementation for synchronous index deletion.

        Deletes the index if it exists.
        """
        if self.exists():
            log_debug(f"Deleting index: {self.index_name}")
            self.client.indices.delete(index=self.index_name)
            log_info(f"Successfully deleted index: {self.index_name}")
            # The next index under this name is created with the mapping — re-resolve lazily
            self._owner_field_exact = None
        else:
            log_info(f"Index {self.index_name} does not exist, nothing to delete")

    async def _async_drop_index_impl(self) -> None:
        """
        Implementation for asynchronous index deletion.

        Deletes the index if it exists.
        """
        if await self.async_exists():
            log_debug(f"Deleting index (async): {self.index_name}")
            await self.async_client.indices.delete(index=self.index_name)
            log_info(f"Successfully deleted index (async): {self.index_name}")
            self._owner_field_exact = None
        else:
            log_info(f"Index {self.index_name} does not exist, nothing to delete")

    def optimize(self) -> None:
        """
        Optimize the index for better performance.

        Note:
            Forces merge of index segments to improve search performance.
            Should be used sparingly as it's a resource-intensive operation.
        """
        self._execute_with_timing("optimize", self._optimize_index_impl)

    def _optimize_index_impl(self) -> None:
        """
        Implementation for index optimization.

        Forces merge of all segments into a single segment for better performance.

        Note:
            A serverless project manages its own segments and answers _forcemerge with
            api_not_available_exception. Optimising is a performance hint rather than a
            correctness step, so that answer is logged and swallowed instead of raised.
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist, cannot optimize")
            return

        log_debug(f"Optimizing index: {self.index_name}")
        try:
            self.client.indices.forcemerge(index=self.index_name, max_num_segments=1)
        except elasticsearch_exceptions.ApiError as e:
            if getattr(e, "status_code", None) == 410 or "not available when running in serverless" in str(e):
                log_info(f"Skipping optimize for index {self.index_name}: the cluster manages its own segments")
                return
            raise
        log_info(f"Successfully optimized index: {self.index_name}")

    def count(self) -> int:
        """
        Get the number of documents in the index.

        Returns:
            int: Number of documents in the index, 0 if index doesn't exist or on error
        """
        log_debug(f"Counting documents in index: {self.index_name}")

        if not self.exists():
            log_debug("Index does not exist, returning count 0")
            return 0

        try:
            response = self.client.count(index=self.index_name)
            count = response["count"]
            log_debug(f"Index {self.index_name} contains {count} documents")
            return count
        except Exception as e:
            logger.error(f"Error counting documents: {e}")
            return 0

    # ========== Existence Checks ==========

    def doc_exists(self, document: Document) -> bool:
        """
        Check if a document exists in the index by its ID.

        Args:
            document: Document to check for existence

        Returns:
            bool: True if document exists, False otherwise

        Note:
            Returns False if document ID is None or on error
        """
        if document.id is None:
            logger.warning("Document ID is None, cannot check existence")
            return False

        try:
            log_debug(f"Checking if document exists: {document.id}")
            exists = bool(self.client.exists(index=self.index_name, id=document.id))
            log_debug(f"Document {document.id} exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if document exists: {e}")
            return False

    async def async_doc_exists(self, document: Document) -> bool:
        """
        Check if a document exists in the index asynchronously by its ID.

        Args:
            document: Document to check for existence

        Returns:
            bool: True if document exists, False otherwise

        Note:
            Returns False if document ID is None or on error
        """
        if document.id is None:
            logger.warning("Document ID is None, cannot check existence")
            return False

        try:
            log_debug(f"Checking if document exists (async): {document.id}")
            exists = bool(await self.async_client.exists(index=self.index_name, id=document.id))
            log_debug(f"Document {document.id} exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if document exists: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists.

        Args:
            name: Name to search for

        Returns:
            bool: True if document with name exists, False otherwise
        """
        return self._check_field_exists("name.keyword", name)

    async def async_name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists asynchronously.

        Args:
            name: Name to search for

        Returns:
            bool: True if document with name exists, False otherwise
        """
        return await self._async_check_field_exists("name.keyword", name)

    def id_exists(self, id: str) -> bool:
        """
        Check if a document with the given ID exists.

        Args:
            id: Document ID to check

        Returns:
            bool: True if document with ID exists, False otherwise
        """
        try:
            log_debug(f"Checking if document ID exists: {id}")
            exists = bool(self.client.exists(index=self.index_name, id=id))
            log_debug(f"Document ID '{id}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if ID exists: {e}")
            return False

    def _check_field_exists(self, field: str, value: str, scope: Optional[Dict[str, Any]] = None) -> bool:
        """
        Check if a document with a specific field value exists.

        Args:
            field: Field name to search in
            value: Value to search for
            scope: Optional per-user clause to AND with the field match

        Returns:
            bool: True if document with field value exists, False otherwise
        """
        try:
            log_debug(f"Checking if field {field} exists with value: {value}")
            if not self.exists():
                log_debug("Index does not exist, returning False")
                return False

            term: Dict[str, Any] = {"term": {field: value}}
            query: Dict[str, Any] = term if scope is None else {"bool": {"filter": [term, scope]}}
            response = self.client.search(index=self.index_name, query=query, size=1)
            exists = response["hits"]["total"]["value"] > 0
            log_debug(f"Field {field} with value '{value}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if field exists: {e}")
            return False

    async def _async_check_field_exists(self, field: str, value: str) -> bool:
        """
        Check if a document with a specific field value exists asynchronously.

        Args:
            field: Field name to search in
            value: Value to search for

        Returns:
            bool: True if document with field value exists, False otherwise
        """
        try:
            log_debug(f"Checking if field {field} exists with value (async): {value}")
            if not await self.async_exists():
                log_debug("Index does not exist, returning False")
                return False

            response = await self.async_client.search(index=self.index_name, query={"term": {field: value}}, size=1)
            exists = response["hits"]["total"]["value"] > 0
            log_debug(f"Field {field} with value '{value}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if field exists: {e}")
            return False

    # ========== Document Preparation ==========

    def _build_doc_id(self, doc: Document, user_id: Optional[str] = None) -> str:
        """
        Build a deterministic Elasticsearch _id for a document.

        Args:
            doc: Document to build an ID for
            user_id: Owner of the document, or None for the shared bucket

        Returns:
            str: Stable document ID

        Note:
            Derived from the document's explicit id (or a hash of its content) combined
            with the content_hash, so re-indexing the same document upserts in place.
            The owner is hashed in on top of that, so two users ingesting the same bytes
            get distinct _ids; user_id=None keeps the pre-isolation _id.
        """
        cleaned_content = (doc.content or "").replace("\x00", "�")
        base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
        content_hash = (doc.meta_data or {}).get("content_hash", "")
        doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
        if user_id is None:
            return doc_id
        return md5(f"{doc_id}_{user_id}".encode()).hexdigest()

    def _prepare_document_for_indexing(self, doc: Document, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Prepare a document for indexing by ensuring proper structure and embeddings.

        Args:
            doc: Document to prepare
            user_id: Owner stamped onto the indexed document, or None for the shared bucket

        Returns:
            Dict[str, Any]: Document structure ready for indexing

        Raises:
            ValueError: If document cannot be prepared for indexing
        """
        log_debug(f"Preparing document for indexing: {doc.id}")

        self._ensure_document_embedding(doc)
        self._validate_embedding_dimensions(doc)
        index_doc = self._build_index_document(doc, user_id)

        log_debug(f"Document {doc.id} prepared for indexing with {len(index_doc)} fields")
        return index_doc

    def _ensure_document_embedding(self, doc: Document) -> None:
        """
        Ensure document has an embedding, generating one if necessary.

        Args:
            doc: Document to ensure has embedding

        Raises:
            ValueError: If no embedder is available or embedding generation fails
        """
        if doc.embedding is None:
            try:
                log_debug(f"Generating embedding for document: {doc.id}")
                embedder_to_use = doc.embedder or self.embedder
                if embedder_to_use is None:
                    raise ValueError(f"No embedder available for document {doc.id}")

                doc.embed(embedder_to_use)
                log_debug(f"Successfully generated embedding for document: {doc.id}")
            except Exception as e:
                logger.error(f"Error generating embedding for document {doc.id}: {e}")
                raise

        if doc.embedding is None:
            raise ValueError(f"Document {doc.id} has no embedding and no embedder is configured")

    def _validate_embedding_dimensions(self, doc: Document) -> None:
        """
        Validate that document embedding dimensions match expected dimension.

        Args:
            doc: Document with embedding to validate

        Raises:
            ValueError: If the embedding is missing or its dimensions don't match
        """
        embedding = doc.embedding
        if embedding is None:
            raise ValueError(f"Document {doc.id} has no embedding to validate")

        if len(embedding) != self.dimension:
            error_msg = (
                f"Embedding dimension mismatch for document {doc.id}: expected {self.dimension}, got {len(embedding)}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        log_debug(f"Document {doc.id} embedding dimension check passed: {len(embedding)}")

    def _build_index_document(self, doc: Document, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Build the document structure for indexing.

        Args:
            doc: Document to build index structure for
            user_id: Owner stamped onto the indexed document, or None for the shared bucket

        Returns:
            Dict[str, Any]: Document structure ready for Elasticsearch indexing

        Note:
            Includes core fields (embedding, content, meta_data) and optional fields
            (name, usage, reranking_score) if they exist. The content_hash is also
            promoted to a top-level field so it can be matched exactly by
            content_hash_exists().
        """
        index_doc: Dict[str, Any] = {
            "embedding": doc.embedding,
            "content": doc.content,
            "meta_data": doc.meta_data,
        }

        # Add optional fields if they exist
        optional_fields = ["name", "usage", "reranking_score", "content_id"]
        for field in optional_fields:
            value = getattr(doc, field, None)
            if value is not None:
                index_doc[field] = value

        # Promote content_hash out of meta_data so it is indexed as a top-level keyword
        content_hash = (doc.meta_data or {}).get("content_hash")
        if content_hash is not None:
            index_doc["content_hash"] = content_hash

        # Leaving the field off for user_id=None is what puts the document in the shared bucket
        if user_id is not None:
            index_doc[USER_ID_FIELD] = user_id

        return index_doc

    def _create_document_from_hit(self, hit: Dict[str, Any]) -> Document:
        """
        Create a Document object from an Elasticsearch search hit.

        Args:
            hit: Elasticsearch search hit containing document data

        Returns:
            Document: Constructed document with search metadata

        Note:
            Adds search score to document metadata for reference. A hit from an rrf
            retriever carries a null _score, so it is stored as-is rather than formatted.
        """
        doc_data = hit["_source"]

        meta_data = (doc_data.get("meta_data") or {}).copy()
        meta_data["search_score"] = hit.get("_score")

        doc = Document(
            id=hit["_id"],
            content=doc_data["content"],
            name=doc_data.get("name"),
            meta_data=meta_data,
            embedding=doc_data.get("embedding"),
            usage=doc_data.get("usage"),
            reranking_score=doc_data.get("reranking_score"),
            content_id=doc_data.get("content_id"),
        )

        log_debug(f"Created document from search hit: {doc.id} (score: {hit.get('_score')})")
        return doc

    def _apply_content_hash_and_filters(
        self, documents: List[Document], content_hash: str, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Attach the content hash and any filters to each document's metadata.

        Args:
            documents: Documents to annotate (modified in place)
            content_hash: Content hash for the documents
            filters: Optional filters to merge into each document's metadata

        Note:
            Filters are stored in meta_data so they can be matched by filtered searches,
            matching the behaviour of the other vector database implementations.
        """
        for doc in documents:
            if doc.meta_data is None:
                doc.meta_data = {}
            if filters:
                doc.meta_data.update(filters)
            doc.meta_data["content_hash"] = content_hash

    # ========== Insert and Upsert ==========

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Insert documents into the index.

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to insert
            filters: Optional filters merged into each document's metadata
            user_id: Owner of these chunks. None writes to the shared bucket.

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        self._apply_content_hash_and_filters(documents, content_hash, filters)
        self._execute_bulk_operation("insert", documents, self._prepare_bulk_insert_data, user_id=user_id)

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Insert documents into the index asynchronously.

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to insert
            filters: Optional filters merged into each document's metadata
            user_id: Owner of these chunks. None writes to the shared bucket.

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
            Uses batch embedding for improved performance.
        """
        self._validate_user_id(user_id)
        # The gate inspects the live mapping over the network, so keep it off the event loop.
        await asyncio.to_thread(self._require_owner_field, user_id)
        self._apply_content_hash_and_filters(documents, content_hash, filters)
        await self._async_execute_bulk_operation(
            "insert", documents, self._prepare_bulk_insert_data, use_batch_embed=True, user_id=user_id
        )

    def upsert_available(self) -> bool:
        """
        Check if upsert operations are supported.

        Returns:
            bool: Always True for Elasticsearch

        Note:
            Elasticsearch supports upsert operations through update with doc_as_upsert.
        """
        log_debug("Upsert operations are supported for Elasticsearch")
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents in the index (insert if new, update if exists).

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to upsert
            filters: Optional filters merged into each document's metadata
            user_id: Owner of these chunks. The owner is part of the _id, so an upsert
                only ever updates that owner's copy.

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
            Clears the owner's existing chunks for this hash first, so a re-upsert that
            splits into fewer chunks leaves no surplus behind.
        """
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        embed_before_replace(documents, self.embedder)
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)
        self._apply_content_hash_and_filters(documents, content_hash, filters)
        self._execute_bulk_operation("upsert", documents, self._prepare_bulk_upsert_data, user_id=user_id)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents in the index asynchronously (insert if new, update if exists).

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to upsert
            filters: Optional filters merged into each document's metadata
            user_id: Owner of these chunks. The owner is part of the _id, so an upsert
                only ever updates that owner's copy.

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
            Uses batch embedding for improved performance. Clears the owner's existing
            chunks for this hash first.
        """
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        await aembed_before_replace(documents, self.embedder)
        self._validate_user_id(user_id)
        # The gate, the existence check and the delete are all synchronous round trips.
        # Run them on a worker thread so the event loop is not blocked for the duration.
        await asyncio.to_thread(self._replace_prelude, content_hash, user_id)
        self._apply_content_hash_and_filters(documents, content_hash, filters)
        await self._async_execute_bulk_operation(
            "upsert", documents, self._prepare_bulk_upsert_data, use_batch_embed=True, user_id=user_id
        )

    def _replace_prelude(self, content_hash: str, user_id: Optional[str]) -> None:
        """Gate the owner and clear the chunks an upsert is about to replace.

        Grouped into one callable so the async path can offload the whole blocking
        sequence in a single hop rather than three.
        """
        self._require_owner_field(user_id)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)

    def get_document_by_id(self, document_id: str) -> Optional[Document]:
        """
        Retrieve a document by its ID.

        Args:
            document_id: ID of the document to retrieve

        Returns:
            Optional[Document]: Document if found, None otherwise

        Note:
            Returns None if index doesn't exist, document not found, or on error.
        """
        log_debug(f"Retrieving document by ID: {document_id}")

        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return None

        try:
            response = self.client.get(index=self.index_name, id=document_id)
            if response["found"]:
                hit = {"_id": document_id, "_source": response["_source"], "_score": 1.0}
                doc = self._create_document_from_hit(hit)
                log_debug(f"Successfully retrieved document: {document_id}")
                return doc
            log_debug(f"Document {document_id} not found")
            return None
        except elasticsearch_exceptions.NotFoundError:
            log_info(f"Document {document_id} not found in index {self.index_name}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving document {document_id}: {e}")
            return None

    # ========== Bulk Operations ==========

    def delete(self) -> bool:
        """
        Delete all documents from the index.

        Returns:
            bool: True if deletion was successful, False otherwise

        Warning:
            This operation deletes all documents but preserves the index structure.
        """
        return self._execute_with_timing("delete_all", self._delete_all_impl, return_result=True)

    def _delete_all_impl(self) -> bool:
        """
        Implementation for deleting all documents from the index.

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        log_info(f"Deleting all documents from index: {self.index_name}")

        try:
            if self.exists():
                response = self.client.delete_by_query(
                    index=self.index_name, query={"match_all": {}}, refresh=True, conflicts="proceed"
                )
                deleted_count = response.get("deleted", 0)
                log_info(f"Successfully deleted {deleted_count} documents from index: {self.index_name}")
                return True
            logger.warning(f"Index {self.index_name} does not exist")
            return False
        except Exception as e:
            logger.error(f"Error deleting documents from index {self.index_name}: {e}")
            return False

    def delete_documents(self, document_ids: List[str]) -> None:
        """
        Delete specific documents from the index by their IDs.

        Args:
            document_ids: List of document IDs to delete

        Raises:
            Exception: If bulk delete operation fails

        Note:
            Logs individual errors but continues processing remaining documents.
        """
        self._execute_with_timing("delete_documents", lambda: self._delete_documents_impl(document_ids))

    def _delete_documents_impl(self, document_ids: List[str]) -> None:
        """
        Implementation for deleting specific documents by ID.

        Args:
            document_ids: List of document IDs to delete

        Raises:
            Exception: If bulk delete operation fails
        """
        log_info(f"Deleting {len(document_ids)} documents from index {self.index_name}")

        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return

        if not document_ids:
            logger.warning("No document IDs provided for deletion")
            return

        try:
            operations = [{"delete": {"_index": self.index_name, "_id": doc_id}} for doc_id in document_ids]

            log_debug(f"Executing bulk delete operation for {len(document_ids)} documents")
            response = self.client.bulk(operations=operations, refresh=True)

            if response.get("errors"):
                # delete_by_id turns this into a False return, so a caller is told the
                # documents are still there rather than reading silence as success.
                error_count, samples = self._count_bulk_errors(response, "delete")
                raise RuntimeError(
                    f"Bulk delete failed for {error_count} of {len(document_ids)} documents "
                    f"in index {self.index_name}: {'; '.join(samples)}"
                )
            log_info(f"Successfully deleted {len(document_ids)} documents from index {self.index_name}")
        except Exception as e:
            logger.error(f"Error executing bulk delete operation: {e}")
            raise

    def _execute_bulk_operation(
        self, operation: str, documents: List[Document], prepare_func, user_id: Optional[str] = None
    ) -> None:
        """
        Execute bulk operation with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process
            prepare_func: Function to prepare bulk data
            user_id: Owner stamped onto every document in the batch

        Note:
            Creates index if it doesn't exist and handles errors gracefully.
        """
        start_time = time.time()
        log_info(f"Starting bulk {operation} of {len(documents)} documents to index {self.index_name}")

        if not documents:
            logger.warning(f"No documents provided for {operation}")
            return

        if not self.exists():
            log_info(f"Index {self.index_name} does not exist, creating it")
            self.create()

        # Claim the owner field's type before any value can imply it
        self._ensure_owner_field_mapped(user_id)

        try:
            operations, prepared_count = prepare_func(documents, user_id)
            self._require_preparable(operation, prepared_count, len(documents))
            if operations:
                self._execute_bulk_request(operations, operation, prepared_count)
        except Exception as e:
            logger.error(f"Error executing bulk {operation} operation: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"Bulk {operation} operation took {end_time - start_time:.2f} seconds")

    async def _async_execute_bulk_operation(
        self,
        operation: str,
        documents: List[Document],
        prepare_func,
        use_batch_embed: bool = False,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Execute bulk operation asynchronously with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process
            prepare_func: Function to prepare bulk data
            use_batch_embed: Whether to use batch embedding (default: False)
            user_id: Owner stamped onto every document in the batch

        Note:
            Creates index if it doesn't exist and handles errors gracefully.
            When use_batch_embed is True, documents are embedded in batches for better performance.
        """
        start_time = time.time()
        log_info(f"Starting async bulk {operation} of {len(documents)} documents to index {self.index_name}")

        if not documents:
            logger.warning(f"No documents provided for {operation}")
            return

        if not await self.async_exists():
            log_info(f"Index {self.index_name} does not exist, creating it")
            await self.async_create()

        # Claim the owner field's type before any value can imply it
        await asyncio.to_thread(self._ensure_owner_field_mapped, user_id)

        try:
            if use_batch_embed:
                await self._async_embed_documents(documents)

            operations, prepared_count = prepare_func(documents, user_id)
            self._require_preparable(operation, prepared_count, len(documents))
            if operations:
                await self._async_execute_bulk_request(operations, operation, prepared_count)
        except Exception as e:
            logger.error(f"Error executing async bulk {operation} operation: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"Async bulk {operation} operation took {end_time - start_time:.2f} seconds")

    def _prepare_bulk_insert_data(
        self, documents: List[Document], user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Prepare bulk insert operations for Elasticsearch.

        Args:
            documents: List of documents to prepare
            user_id: Owner stamped onto every document in the batch

        Returns:
            Tuple[List[Dict[str, Any]], int]: Bulk operations and count of prepared documents

        Note:
            Skips documents that fail preparation and logs errors.
        """
        operations: List[Dict[str, Any]] = []
        prepared_count = 0

        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc, user_id)
                operations.extend(
                    [{"index": {"_index": self.index_name, "_id": self._build_doc_id(doc, user_id)}}, index_doc]
                )
                prepared_count += 1
            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for indexing: {e}")
                self._mark_unretrievable(doc)
                continue

        log_debug(f"Prepared {prepared_count}/{len(documents)} documents for bulk insert")
        return operations, prepared_count

    def _prepare_bulk_upsert_data(
        self, documents: List[Document], user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Prepare bulk upsert operations for Elasticsearch.

        Args:
            documents: List of documents to prepare
            user_id: Owner stamped onto every document in the batch

        Returns:
            Tuple[List[Dict[str, Any]], int]: Bulk operations and count of prepared documents

        Note:
            Skips documents that fail preparation and logs errors.
        """
        operations: List[Dict[str, Any]] = []
        prepared_count = 0

        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc, user_id)
                operations.extend(
                    [
                        {"update": {"_index": self.index_name, "_id": self._build_doc_id(doc, user_id)}},
                        {"doc": index_doc, "doc_as_upsert": True},
                    ]
                )
                prepared_count += 1
            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for upsert: {e}")
                self._mark_unretrievable(doc)
                continue

        log_debug(f"Prepared {prepared_count}/{len(documents)} documents for bulk upsert")
        return operations, prepared_count

    def _execute_bulk_request(self, operations: List[Dict[str, Any]], operation: str, prepared_count: int) -> None:
        """
        Execute bulk request and handle response.

        Args:
            operations: Prepared bulk operations for Elasticsearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared
        """
        log_debug(f"Executing bulk {operation} operation with {len(operations) // 2} documents")
        response = self.client.bulk(operations=operations, refresh=True)
        self._handle_bulk_response(response, operation, prepared_count)

    async def _async_execute_bulk_request(
        self, operations: List[Dict[str, Any]], operation: str, prepared_count: int
    ) -> None:
        """
        Execute async bulk request and handle response.

        Args:
            operations: Prepared bulk operations for Elasticsearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared
        """
        log_debug(f"Executing async bulk {operation} operation with {len(operations) // 2} documents")
        response = await self.async_client.bulk(operations=operations, refresh=True)
        self._handle_bulk_response(response, operation, prepared_count)

    @staticmethod
    def _mark_unretrievable(doc: Document) -> None:
        """Clear the embedding of a chunk that was dropped before the write.

        Ingestion decides COMPLETED versus PARTIAL by counting documents that carry an
        embedding. A chunk dropped here never reached the cluster, so leaving a
        usable-looking vector on it would report the content fully indexed - a
        wrong-width vector is exactly that case, since it is present but unusable.
        Clearing it lets the existing shortfall count see the loss.
        """
        doc.embedding = None

    def _require_preparable(self, operation: str, prepared_count: int, total: int) -> None:
        """Refuse a batch that lost every document before it reached the cluster.

        Args:
            operation: Operation name for the message
            prepared_count: How many documents survived preparation
            total: How many were handed in

        Raises:
            RuntimeError: If documents were supplied but none could be prepared

        Note:
            A document rejected here is never written, yet ingestion reads a quiet return
            as success, so a total loss is raised. A partial shortfall stays a warning:
            the chunks that did land are retrievable, and ingestion reports PARTIAL from
            its own embedding count - which sees the dropped chunks because
            ``_mark_unretrievable`` clears their embeddings first.
        """
        if total and prepared_count == 0:
            raise RuntimeError(
                f"Bulk {operation} prepared none of {total} documents in index "
                f"{self.index_name}; nothing was written. See the logged errors for the cause."
            )
        if prepared_count < total:
            logger.warning(
                f"Bulk {operation} prepared {prepared_count} of {total} documents in index "
                f"{self.index_name}; the rest were dropped and are not retrievable."
            )

    def _handle_bulk_response(self, response: Any, operation: str, prepared_count: int) -> None:
        """
        Handle bulk operation response and log results.

        Args:
            response: Bulk operation response from Elasticsearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared

        Raises:
            RuntimeError: If the cluster rejected any document in the batch

        Note:
            A rejected chunk is unretrievable, and ingestion decides COMPLETED versus
            FAILED on whether this call raises. Logging alone would commit the rest of
            the batch and report success, leaving content marked indexed with no vectors
            behind it, so the failure is raised for ingestion to record and retry.
        """
        if not response.get("errors"):
            log_info(f"Successfully {operation}ed {prepared_count} documents in index {self.index_name}")
            return

        error_count, samples = self._count_bulk_errors(response, operation)
        detail = "; ".join(samples)
        raise RuntimeError(
            f"Bulk {operation} rejected {error_count} of {prepared_count} documents "
            f"in index {self.index_name}: {detail}"
        )

    def _count_bulk_errors(self, response: Any, operation: str, max_samples: int = 3) -> Tuple[int, List[str]]:
        """
        Count and log bulk operation errors.

        Args:
            response: Bulk operation response from Elasticsearch
            operation: Operation name for logging
            max_samples: How many representative errors to carry back to the caller

        Returns:
            Tuple[int, List[str]]: Number of errors, and a few of them rendered for the
            exception message. The full set is logged rather than raised, so one bad
            mapping cannot produce a megabyte-long error.
        """
        error_count = 0
        samples: List[str] = []
        for item in response.get("items", []):
            # A bulk response echoes the action it is answering, so read whichever the
            # batch actually sent rather than assuming the happy path.
            action = next((k for k in ("index", "update", "create", "delete") if k in item), None)
            if action is None:
                continue
            error = item[action].get("error")
            if error is None:
                continue
            logger.error(f"Bulk {operation} error: {error}")
            if len(samples) < max_samples:
                reason = error.get("reason", error) if isinstance(error, dict) else error
                samples.append(str(reason))
            error_count += 1
        if error_count > len(samples):
            samples.append(f"... and {error_count - len(samples)} more")
        return error_count, samples

    async def _async_embed_documents(self, documents: List[Document]) -> None:
        """
        Embed a batch of documents using either batch embedding or individual embedding.

        Args:
            documents: List of documents to embed

        Note:
            - Uses batch embedding when embedder.enable_batch is True and supports
              async_get_embeddings_batch_and_usage
            - Falls back to individual embedding if batch fails (except for rate limit errors)
            - Skips documents that already have embeddings
        """
        if self.embedder is None:
            logger.warning("No embedder configured, skipping embedding generation")
            return

        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            try:
                docs_to_embed = [doc for doc in documents if doc.embedding is None]

                if not docs_to_embed:
                    log_debug("All documents already have embeddings")
                    return

                doc_contents = [doc.content for doc in docs_to_embed]
                log_debug(f"Generating batch embeddings for {len(doc_contents)} documents")
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                for j, doc in enumerate(docs_to_embed):
                    try:
                        if j < len(embeddings):
                            doc.embedding = embeddings[j]
                            doc.usage = usages[j] if j < len(usages) else None
                            log_debug(f"Assigned batch embedding to document {doc.id}")
                    except Exception as e:
                        logger.error(f"Error assigning batch embedding to document '{doc.name}': {e}")

                log_info(f"Successfully generated {len(embeddings)} batch embeddings")

            except Exception as e:
                # A throttle must not fall back to per-item calls, which would throttle harder.
                if is_rate_limit_error(e):
                    logger.error(f"Rate limit detected during batch embedding: {e}")
                    raise e

                logger.warning(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents if doc.embedding is None]
                results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                raise_embedding_failures(results)
        else:
            log_debug("Using individual embedding (batch embedding not available)")
            embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents if doc.embedding is None]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

    # ========== Search ==========

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Search for documents based on configured search type.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search
            user_id: Restrict results to this owner's chunks plus the shared bucket. None applies no scope.

        Returns:
            List[Document]: List of matching documents

        Note:
            Uses the search type configured during initialization (vector, keyword, or hybrid).
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        search_methods = {
            SearchType.vector: self.vector_search,
            SearchType.keyword: self.keyword_search,
            SearchType.hybrid: self.hybrid_search,
        }

        search_method = search_methods.get(self.search_type)
        if search_method is None:
            logger.error(f"Invalid search type '{self.search_type}'")
            return []

        return search_method(query, limit, filters, user_id)

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Search for documents asynchronously based on configured search type.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search
            user_id: Restrict results to this owner's chunks plus the shared bucket. None applies no scope.

        Returns:
            List[Document]: List of matching documents

        Note:
            Embedding the query and the round trip are both awaited natively. Reranking
            is not: ``Reranker.rerank`` has no async variant on the base class, so it is
            offloaded to a worker thread rather than left to block the event loop.
        """
        self._validate_user_id(user_id)
        await asyncio.to_thread(self._require_owner_field, user_id)

        query_builders = {
            SearchType.vector: self._build_vector_query,
            SearchType.keyword: self._build_keyword_query,
            SearchType.hybrid: self._build_hybrid_query,
        }
        query_builder = query_builders.get(self.search_type)
        if query_builder is None:
            logger.error(f"Invalid search type '{self.search_type}'")
            return []

        # .value, not str(): str(SearchType.vector) renders the enum name, and the sync
        # path logs the bare word.
        label = getattr(self.search_type, "value", str(self.search_type))
        return await self._async_execute_search(label, query, limit, query_builder, filters, user_id)

    async def _async_execute_search(
        self,
        search_type: str,
        query: str,
        limit: int,
        query_builder,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]],
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Asynchronous twin of ``_execute_search_with_timing``.

        Args:
            search_type: Type of search for logging
            query: Search query string
            limit: Maximum number of results
            query_builder: Function building the search body
            filters: Optional filters to apply
            user_id: Owner scope applied to the built query

        Returns:
            List[Document]: Search results with optional reranking applied

        Note:
            Only the reranker is offloaded; everything else is awaited. A keyword search
            embeds nothing, so the embedding is computed only when a builder needs it.
        """
        start_time = time.time()
        log_info(f"Performing {search_type} search for: '{query}' (limit: {limit})")

        if not await self.async_exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            query_embedding = None
            if self.search_type != SearchType.keyword:
                query_embedding = await self._async_get_query_embedding(query)

            search_body = query_builder(query, limit, filters, user_id, query_embedding)
            log_debug(f"Executing {search_type} search query (async)")
            response = await self.async_client.search(index=self.index_name, **search_body)

            documents = [self._create_document_from_hit(hit) for hit in response["hits"]["hits"]]
            log_debug(f"Retrieved {len(documents)} documents from {search_type} search")

            if self.reranker and documents:
                # rerank() is sync-only on the base Reranker, and it is usually a network
                # call, so it goes to a worker thread instead of blocking the event loop.
                documents = await asyncio.to_thread(self._apply_reranking, query, documents)

            log_info(f"{search_type.capitalize()} search returned {len(documents)} documents for query: '{query}'")
            return documents

        except Exception as e:
            if self._is_unlicensed_rrf_error(e):
                log_warning(
                    "This cluster's licence does not cover rrf; falling back to the boost "
                    "hybrid strategy for the rest of this session. Set hybrid_strategy="
                    "HybridStrategy.boost to silence this, or use a licensed cluster."
                )
                self.hybrid_strategy = HybridStrategy.boost
                return await self._async_execute_search(search_type, query, limit, query_builder, filters, user_id)
            logger.error(f"Error during {search_type} search: {e}")
            return []
        finally:
            end_time = time.time()
            log_debug(f"Total {search_type} search operation took {end_time - start_time:.2f} seconds")

    async def _async_get_query_embedding(self, query: str) -> List[float]:
        """Embed the query without blocking the event loop.

        Args:
            query: Search query string

        Returns:
            List[float]: The query embedding

        Raises:
            ValueError: If no embedder is configured
        """
        if self.embedder is None:
            raise ValueError("No embedder configured for search")

        log_debug("Generating query embedding (async)")
        query_embedding, usage = await self.embedder.async_get_embedding_and_usage(query)
        if usage:
            log_debug(f"Embedding generation usage: {usage}")
        return query_embedding

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform vector similarity search using embeddings.

        Args:
            query: Search query string (will be embedded)
            limit: Maximum number of results to return
            filters: Optional filters to apply to search
            user_id: Restrict results to this owner's chunks plus the shared bucket

        Returns:
            List[Document]: List of documents ordered by similarity score
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        return self._execute_search_with_timing("vector", query, limit, self._build_vector_query, filters, user_id)

    def keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform keyword-based text search.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search
            user_id: Restrict results to this owner's chunks plus the shared bucket

        Returns:
            List[Document]: List of documents ordered by text relevance score

        Note:
            Uses multi-match query on content and name fields.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        return self._execute_search_with_timing("keyword", query, limit, self._build_keyword_query, filters, user_id)

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform hybrid search combining vector and keyword search.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search
            user_id: Restrict results to this owner's chunks plus the shared bucket

        Returns:
            List[Document]: List of documents ordered by combined similarity and relevance scores

        Note:
            Combines vector similarity (70% weight) and keyword relevance (30% weight), or
            fuses the two rankings with rrf when hybrid_strategy is rrf.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        return self._execute_search_with_timing("hybrid", query, limit, self._build_hybrid_query, filters, user_id)

    def _execute_search_with_timing(
        self,
        search_type: str,
        query: str,
        limit: int,
        query_builder,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]],
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Execute search with timing and comprehensive error handling.

        Args:
            search_type: Type of search for logging
            query: Search query string
            limit: Maximum number of results
            query_builder: Function to build the search body
            filters: Optional filters to apply
            user_id: Owner scope applied to the built query

        Returns:
            List[Document]: Search results with optional reranking applied

        Note:
            Applies reranking if configured and handles all search errors gracefully.
        """
        start_time = time.time()
        log_info(f"Performing {search_type} search for: '{query}' (limit: {limit})")

        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            search_body = query_builder(query, limit, filters, user_id)
            log_debug(f"Executing {search_type} search query")
            response = self.client.search(index=self.index_name, **search_body)

            documents = [self._create_document_from_hit(hit) for hit in response["hits"]["hits"]]
            log_debug(f"Retrieved {len(documents)} documents from {search_type} search")

            if self.reranker and documents:
                documents = self._apply_reranking(query, documents)

            log_info(f"{search_type.capitalize()} search returned {len(documents)} documents for query: '{query}'")
            return documents

        except Exception as e:
            if self._is_unlicensed_rrf_error(e):
                # Falling back beats returning nothing: the caller opted into a ranking
                # strategy, not into an empty knowledge base. Downgrading is announced
                # once and then sticks, so the next search does not retry the refusal.
                log_warning(
                    "This cluster's licence does not cover rrf; falling back to the boost "
                    "hybrid strategy for the rest of this session. Set hybrid_strategy="
                    "HybridStrategy.boost to silence this, or use a licensed cluster."
                )
                self.hybrid_strategy = HybridStrategy.boost
                return self._execute_search_with_timing(search_type, query, limit, query_builder, filters, user_id)
            logger.error(f"Error during {search_type} search: {e}")
            return []
        finally:
            end_time = time.time()
            log_debug(f"Total {search_type} search operation took {end_time - start_time:.2f} seconds")

    def _is_unlicensed_rrf_error(self, error: Exception) -> bool:
        """Whether the cluster refused an rrf search for want of a licence.

        rrf needs a platinum/enterprise licence; a basic-licence cluster answers with a
        403 security_exception. Ingestion succeeds either way, so without this the agent
        just sees an empty knowledge base.
        """
        if self.hybrid_strategy != HybridStrategy.rrf:
            return False
        message = str(error).lower()
        return "license" in message and "rrf" in message.replace("reciprocal rank fusion", "rrf")

    def _resolve_num_candidates(self, limit: int) -> int:
        """
        Resolve how many neighbours each shard considers before the top k are picked.

        Args:
            limit: Number of results requested

        Returns:
            int: num_candidates for the knn clause

        Note:
            A num_candidates below k is rejected outright, so the floor is never applied
            below the requested limit, and the ceiling cannot pull it under one either:
            the cluster caps k at 10000 too, so a limit that would need more candidates
            than the ceiling allows is already refused for its own size.
        """
        if self.num_candidates is not None:
            resolved = max(self.num_candidates, limit)
        else:
            resolved = max(limit * DEFAULT_NUM_CANDIDATES_MULTIPLIER, MIN_NUM_CANDIDATES, limit)
        # The cluster rejects a value above its own ceiling, and the search path turns
        # that rejection into an empty result set rather than an error.
        return min(resolved, MAX_NUM_CANDIDATES)

    def _build_knn_clause(
        self, query_embedding: List[float], limit: int, filter_conditions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build the knn clause for a vector search.

        Args:
            query_embedding: Embedded query vector
            limit: Number of results requested
            filter_conditions: Conditions restricting which documents are searched

        Returns:
            Dict[str, Any]: Elasticsearch knn clause

        Note:
            The filter goes inside the knn clause, which pre-filters: post-filtering
            returns nothing when the k nearest neighbours all belong to another owner.
        """
        knn: Dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": limit,
            "num_candidates": self._resolve_num_candidates(limit),
        }
        if filter_conditions:
            knn["filter"] = filter_conditions
        return knn

    def _build_vector_query(
        self,
        query: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]],
        user_id: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Build vector search body for Elasticsearch.

        Args:
            query: Search query string (will be embedded)
            limit: Maximum number of results
            filters: Optional filters to apply
            user_id: Owner scope to apply alongside the filters

        Returns:
            Dict[str, Any]: Keyword arguments for the search call
        """
        if query_embedding is None:
            query_embedding, _ = self._get_query_embedding(query)
        filter_conditions = self._scoped_filter_conditions(filters, user_id)
        return {"size": limit, "knn": self._build_knn_clause(query_embedding, limit, filter_conditions)}

    def _build_keyword_query(
        self,
        query: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Build keyword search body for Elasticsearch.

        Args:
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply
            user_id: Owner scope to apply alongside the filters

        Returns:
            Dict[str, Any]: Keyword arguments for the search call

        Note:
            Searches across 'content' and 'name' fields with 'best_fields' scoring.
        """
        base_query: Dict[str, Any] = {
            "multi_match": {"query": query, "fields": ["content", "name"], "type": "best_fields"}
        }

        filter_conditions = self._scoped_filter_conditions(filters, user_id)
        if filter_conditions:
            return {"size": limit, "query": {"bool": {"must": [base_query], "filter": filter_conditions}}}

        return {"size": limit, "query": base_query}

    def _build_hybrid_query(
        self,
        query: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]],
        user_id: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Build hybrid search body combining vector and keyword search.

        Args:
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply
            user_id: Owner scope to apply alongside the filters

        Returns:
            Dict[str, Any]: Keyword arguments for the search call

        Note:
            With the boost strategy the knn and multi_match scores are summed with 0.7/0.3
            weights. With rrf the two rankings are fused instead, which needs no score
            normalisation but requires a licensed cluster.
        """
        if query_embedding is None:
            query_embedding, _ = self._get_query_embedding(query)
        filter_conditions = self._scoped_filter_conditions(filters, user_id)

        keyword_query: Dict[str, Any] = {
            "multi_match": {"query": query, "fields": ["content", "name"], "type": "best_fields"}
        }
        if filter_conditions:
            keyword_query = {"bool": {"must": [keyword_query], "filter": filter_conditions}}

        knn_clause = self._build_knn_clause(query_embedding, limit, filter_conditions)

        if self.hybrid_strategy == HybridStrategy.rrf:
            return {
                "size": limit,
                "retriever": {
                    "rrf": {
                        # Defaults to 10, and the cluster rejects a size larger than it,
                        # so a page past the first 10 hits would come back empty.
                        "rank_window_size": max(limit, RRF_MIN_RANK_WINDOW_SIZE),
                        "retrievers": [
                            {"standard": {"query": keyword_query}},
                            {"knn": knn_clause},
                        ],
                    }
                },
            }

        # A top-level knn and a query are scored independently and summed, so the boosts
        # are what weight the two halves against each other.
        knn_clause["boost"] = 0.7
        boosted_keyword = dict(keyword_query)
        if "multi_match" in boosted_keyword:
            boosted_keyword["multi_match"] = {**boosted_keyword["multi_match"], "boost": 0.3}
        else:
            boosted_keyword = {"bool": {**boosted_keyword["bool"], "boost": 0.3}}

        return {"size": limit, "knn": knn_clause, "query": boosted_keyword}

    def _get_query_embedding(self, query: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Generate embedding for search query.

        Args:
            query: Search query string

        Returns:
            Tuple[List[float], Optional[Dict[str, Any]]]: Query embedding and usage statistics

        Raises:
            ValueError: If no embedder is configured
        """
        if self.embedder is None:
            raise ValueError("No embedder configured for search")

        log_debug("Generating query embedding")
        query_embedding, usage = self.embedder.get_embedding_and_usage(query)
        log_debug(f"Generated query embedding (dimension: {len(query_embedding)})")

        if usage:
            log_debug(f"Embedding generation usage: {usage}")

        return query_embedding, usage

    def _apply_reranking(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Apply reranking to search results if reranker is configured.

        Args:
            query: Original search query
            documents: List of documents to rerank

        Returns:
            List[Document]: Reranked list of documents, unchanged when no reranker is configured
        """
        if self.reranker is None:
            return documents

        log_debug(f"Applying reranking with {type(self.reranker).__name__}")
        rerank_start = time.time()
        reranked_docs = self.reranker.rerank(query, documents)
        rerank_end = time.time()
        log_debug(f"Reranking took {rerank_end - rerank_start:.2f} seconds")
        return reranked_docs

    # ========== Filters ==========

    def _build_filter_conditions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build filter conditions for an Elasticsearch query.

        Args:
            filters: Dictionary of filter conditions

        Returns:
            List[Dict[str, Any]]: List of Elasticsearch filter conditions

        Note:
            Supports term, terms, range, and special operators like $in.
        """
        log_debug(f"Building filter conditions from: {filters}")
        filter_conditions = []

        for key, value in filters.items():
            condition = self._build_single_filter_condition(key, value)
            if condition:
                filter_conditions.append(condition)

        log_debug(f"Built {len(filter_conditions)} filter conditions")
        return filter_conditions

    def _build_single_filter_condition(self, key: str, value: Any) -> Optional[Dict[str, Any]]:
        """
        Build a single filter condition for Elasticsearch.

        Args:
            key: Field name to filter on
            value: Filter value (can be scalar, list, or dict with operators)

        Returns:
            Optional[Dict[str, Any]]: Elasticsearch filter condition or None if invalid

        Note:
            Supports various filter types:
            - Scalar values: term filter
            - Lists: terms filter
            - Dict with $in/in: terms filter
            - Dict with range operators: range filter
        """
        if isinstance(value, dict):
            return self._build_dict_filter_condition(key, value)
        elif isinstance(value, list):
            field = self._match_field(key, value[0] if value else None)
            log_debug(f"Added terms filter for {key}: {value}")
            return {"terms": {field: value}}
        else:
            log_debug(f"Added term filter for {key}: {value}")
            return {"term": {self._match_field(key, value): value}}

    @staticmethod
    def _match_field(key: str, value: Any) -> str:
        """Name the metadata subfield an exact-match filter has to target.

        Only a string is dynamic-mapped as analyzed ``text`` with a ``.keyword`` subfield;
        a number or a bool is mapped as ``long``/``float``/``boolean``, which has no such
        subfield. Asking for one anyway matches nothing at all, so a filter like
        ``{"index": 1}`` would silently return no results rather than fail.
        """
        # bool is a subclass of int, so it needs no separate arm here.
        if isinstance(value, str):
            return f"meta_data.{key}.keyword"
        return f"meta_data.{key}"

    def _build_dict_filter_condition(self, key: str, value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Build filter condition for dictionary filter values.

        Args:
            key: Field name to filter on
            value: Dictionary containing filter operators and values

        Returns:
            Optional[Dict[str, Any]]: Elasticsearch filter condition or None if invalid

        Note:
            Supports:
            - $in/in operators for multiple values
            - Range operators: gt, lt, gte, lte
        """
        if "$in" in value or "in" in value:
            # Read by key presence, not truthiness: `or` would send an empty $in list on
            # to the absent "in" key, drop the condition, and run the search unfiltered -
            # so a filter selecting nothing would return everything.
            in_value = value["$in"] if "$in" in value else value["in"]
            if isinstance(in_value, list):
                field = self._match_field(key, in_value[0] if in_value else None)
                log_debug(f"Added terms filter for {key}: {in_value}")
                return {"terms": {field: in_value}}
            logger.warning(f"Invalid value for $in/in operator for key {key}: {in_value}")
            return None

        range_ops = ["gt", "lt", "gte", "lte"]
        if any(op in value for op in range_ops):
            range_conditions = {op: val for op, val in value.items() if op in range_ops}
            # A string bound ranges over the keyword subfield: with date detection off an
            # ISO date is text, and a range on the analyzed parent compares its tokens.
            # A numeric bound keeps the bare field, which is where numbers are mapped.
            bound = next(iter(range_conditions.values()))
            field = self._match_field(key, bound)
            log_debug(f"Added range filter for {key}: {range_conditions}")
            return {"range": {field: range_conditions}}

        logger.warning(f"Unsupported filter operator for key {key}: {value}")
        return None

    # ========== Per-User Isolation ==========

    def _owner_field_is_exact(self) -> bool:
        """Whether the live index maps ``user_id`` in a way the scope filter can honour.

        An absent field is fine: the docs carry no owner and read as the shared bucket, which
        is what an index predating isolation is documented to do. A field mapped as anything
        but keyword is not: it is analyzed, so the filter matches tokens rather than the id
        and user_id="dave" also matches "Dave" and "dave smith".
        """
        if self._owner_field_exact is None:
            try:
                mappings = self.client.indices.get_mapping(index=self.index_name)
                # Keyed by concrete index, never by the name asked for, so an alias or a
                # wildcard resolves to several real indexes and each one has to be exact.
                types = [
                    index_mapping.get("mappings", {}).get("properties", {}).get(USER_ID_FIELD, {}).get("type")
                    for index_mapping in mappings.values()
                ]
                answer = all(t in (None, "keyword") for t in types)
                if set(mappings) != {self.index_name}:
                    # An alias or a wildcard: it can be repointed while this process lives,
                    # so the answer is about whatever it resolved to just now, not the name.
                    return answer
                self._owner_field_exact = answer
            except elasticsearch_exceptions.NotFoundError:
                # No live index yet, and the one that appears under this name may not be ours
                return True
            except Exception:
                # Assume mapped, uncached: caching a failed inspection would mask a bad mapping
                logger.warning(
                    f"Could not inspect index '{self.index_name}' for the user_id mapping; "
                    "proceeding as mapped for this operation."
                )
                return True
        return self._owner_field_exact

    def _ensure_owner_field_mapped(self, user_id: Optional[str]) -> None:
        """Declare ``user_id`` as a keyword before the first owner-stamped write.

        An index created before the field existed has no mapping for it, so the first
        scoped write lets Elasticsearch dynamic-map the value — and its default for a string
        is an analyzed ``text`` with a ``keyword`` subfield. The scope filter then matches
        tokens rather than the owner (``user_id="123"`` also matches ``"team-123"``), and
        because a field type is fixed for the life of the index, that write permanently
        bricks scoped access.

        Adding a field to an existing mapping is allowed; only *changing* one is not. So
        the type is claimed here, before any value can imply it. A failure is logged and
        swallowed: the write still has to be gated, and ``_require_owner_field`` is what
        refuses it.
        """
        if user_id is None:
            return
        try:
            # A cached True only means "safe to filter" — on a legacy index that is the
            # absent-field case, which is exactly the one that still needs declaring.
            mappings = self.client.indices.get_mapping(index=self.index_name)
            if any(
                USER_ID_FIELD in index_mapping.get("mappings", {}).get("properties", {})
                for index_mapping in mappings.values()
            ):
                return
            self.client.indices.put_mapping(
                index=self.index_name,
                properties={USER_ID_FIELD: {"type": "keyword"}},
            )
            self._owner_field_exact = True
            log_debug(f"Declared '{USER_ID_FIELD}' as keyword on index '{self.index_name}'")
        except Exception as e:
            logger.warning(
                f"Could not declare '{USER_ID_FIELD}' as a keyword on index '{self.index_name}': {e}. "
                "A scoped write may dynamic-map it as analyzed text, which cannot be undone."
            )

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """
        Reject a user_id the field-absence contract cannot express.

        Args:
            user_id: Owner to validate, or None for the shared bucket

        Raises:
            ValueError: If the owner is empty or whitespace-only

        Note:
            The shared bucket is the absence of the field, not a value, so an empty owner
            would be a third bucket no one can read or clear. Use None for shared access.
        """
        if user_id is not None and user_id.strip() == "":
            raise ValueError("user_id must not be empty or whitespace-only")

    def _require_owner_field(self, user_id: Optional[str]) -> bool:
        """Gate every owner-field reference on the live index mapping.

        True when the mapping can honour a scope filter, False when it cannot and the
        operation is unscoped. A scoped operation on an index that maps the field as
        analyzed text raises rather than matching another owner's tokens.
        """
        if self._owner_field_is_exact():
            return True
        if user_id is None:
            return False
        # The cached answer may predate a reindex — re-inspect once before refusing
        self._owner_field_exact = None
        if self._owner_field_is_exact():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but index '{self.index_name}' does not support "
            f"per-user isolation: it maps '{USER_ID_FIELD}' as analyzed text, so the scope "
            "filter matches its tokens rather than the owner. A field type can only be set "
            "when the index is created, so recreate the index and re-ingest — reindexing "
            "into the same mapping is not sufficient."
        )

    def _owner_filter(self, user_id: str) -> Dict[str, Any]:
        """
        Build the exact-owner scope for a delete.

        Args:
            user_id: Owner to scope to

        Returns:
            Dict[str, Any]: Elasticsearch clause matching only the owner's chunks

        Note:
            No must_not exists arm here: a caller may read the shared bucket but may not
            delete out of it.
        """
        return {"term": {USER_ID_FIELD: user_id}}

    def _shared_bucket_filter(self) -> Dict[str, Any]:
        """
        Build the shared-bucket scope.

        Returns:
            Dict[str, Any]: Elasticsearch clause matching only chunks that have no owner

        Note:
            The shared bucket is the absence of the field, so this also covers every
            document written before the field existed.
        """
        return {"bool": {"must_not": {"exists": {"field": USER_ID_FIELD}}}}

    def _exact_owner_scope(self, user_id: Optional[str]) -> Dict[str, Any]:
        """
        Build the scope the dedup pair shares.

        Args:
            user_id: Owner to scope to, or None for the shared bucket

        Returns:
            Dict[str, Any]: Elasticsearch clause matching exactly one bucket

        Note:
            Unlike the read scope this never widens to a second bucket and has no
            unscoped branch: None resolves to the shared bucket, not to every owner.
        """
        return self._owner_filter(user_id) if user_id is not None else self._shared_bucket_filter()

    def _user_scope_filter(self, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Build the per-user read scope for a search.

        Args:
            user_id: Owner to scope to, or None for no scope

        Returns:
            Optional[Dict[str, Any]]: Elasticsearch clause matching the owner's chunks plus
            the shared bucket, or None when no scope applies

        Note:
            must_not exists is what keeps unowned content - including every document
            written before the field existed - discoverable by every caller.
        """
        if user_id is None:
            return None

        return {
            "bool": {
                "should": [
                    {"term": {USER_ID_FIELD: user_id}},
                    self._shared_bucket_filter(),
                ],
                "minimum_should_match": 1,
            }
        }

    def _translate_filter_expressions(self, expressions: List[Any]) -> List[Dict[str, Any]]:
        """Translate the ``FilterExpr`` DSL into Elasticsearch clauses.

        Args:
            expressions: The filter expressions to translate, ANDed together

        Returns:
            List[Dict[str, Any]]: Clauses to AND into the query's filter

        Raises:
            ValueError: If an expression cannot be translated

        Note:
            Dropping an untranslatable filter is not an option here. ``Knowledge`` puts
            its ``linked_to`` instance scope into this same list when
            isolate_vector_search is on, so discarding the list would discard that
            scope - and a filter meant to narrow the search would widen it across
            knowledge bases instead.
        """
        return [self._translate_filter_node(e.to_dict() if hasattr(e, "to_dict") else e) for e in expressions]

    def _translate_filter_node(self, node: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        """Translate one DSL node, recursing through the logical operators.

        Args:
            node: The node's ``to_dict()`` form
            depth: Current recursion depth, bounded by the DSL's own limit

        Returns:
            Dict[str, Any]: The equivalent Elasticsearch clause

        Raises:
            ValueError: If the operator is unknown or the nesting is too deep
        """
        if depth > MAX_FILTER_DEPTH:
            raise ValueError(f"Filter expression nests deeper than {MAX_FILTER_DEPTH} levels")

        op = node.get("op")
        if op is None:
            raise ValueError(f"Filter expression node has no operator: {node}")

        # Logical operators recurse; the rest name a field.
        if op == "AND":
            return {"bool": {"filter": [self._translate_filter_node(c, depth + 1) for c in node["conditions"]]}}
        if op == "OR":
            return {
                "bool": {
                    "should": [self._translate_filter_node(c, depth + 1) for c in node["conditions"]],
                    "minimum_should_match": 1,
                }
            }
        if op == "NOT":
            return {"bool": {"must_not": [self._translate_filter_node(node["condition"], depth + 1)]}}

        key = node["key"]
        if op == "IN":
            values = node["values"]
            return {"terms": {self._match_field(key, values[0] if values else None): values}}

        value = node["value"]
        if op == "EQ":
            return {"term": {self._match_field(key, value): value}}
        if op == "NEQ":
            return {"bool": {"must_not": [{"term": {self._match_field(key, value): value}}]}}
        if op in ("GT", "GTE", "LT", "LTE"):
            return {"range": {self._match_field(key, value): {op.lower(): value}}}
        # Substring and prefix matching need the unanalyzed value, so both take .keyword.
        if op == "CONTAINS":
            return {"wildcard": {f"meta_data.{key}.keyword": f"*{value}*"}}
        if op == "STARTSWITH":
            return {"prefix": {f"meta_data.{key}.keyword": value}}

        raise ValueError(f"Unsupported filter operator '{op}' for Elasticsearch")

    def _scoped_filter_conditions(
        self, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]], user_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Combine the caller's metadata filters with the per-user scope.

        Args:
            filters: Dictionary of filter conditions, or None
            user_id: Owner to scope to, or None for no scope

        Returns:
            List[Dict[str, Any]]: Filter conditions to AND together

        Note:
            The scope is a nested bool rather than a term, being an OR of two buckets.
        """
        if isinstance(filters, list):
            conditions = self._translate_filter_expressions(filters)
        else:
            conditions = self._build_filter_conditions(filters) if filters else []

        scope = self._user_scope_filter(user_id)
        if scope is not None:
            conditions.append(scope)

        return conditions

    # ========== Deletes and Metadata ==========

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Check if a document with the given content hash exists.

        Args:
            content_hash: Content hash to check
            user_id: Restrict the check to this owner's chunks. None checks the shared bucket alone.

        Returns:
            bool: True if document exists, False otherwise

        Note:
            Scoped to the exact owner, not the own-or-shared scope reads use: it has to
            match exactly the chunks _delete_by_content_hash clears for the same user_id.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        return self._check_field_exists("content_hash", content_hash, self._exact_owner_scope(user_id))

    def delete_by_id(self, id: str) -> bool:
        """
        Delete document by ID.

        Args:
            id: Document ID to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.delete_documents([id])
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID {id}: {e}")
            return False

    def _delete_by_query(self, query: Dict[str, Any], description: str) -> bool:
        """
        Delete every document matching a query.

        Args:
            query: Elasticsearch query selecting the documents to delete
            description: Human readable description of the selection, for logging

        Returns:
            bool: True if successful, False otherwise

        Note:
            Uses the delete_by_query API so all matches are removed.
        """
        try:
            if not self.exists():
                log_info(f"Index '{self.index_name}' does not exist")
                return False

            response = self.client.delete_by_query(
                index=self.index_name, query=query, refresh=True, conflicts="proceed"
            )

            deleted = response.get("deleted", 0)
            failures = response.get("failures") or []
            if failures:
                logger.error(f"delete_by_query reported {len(failures)} failure(s) for {description}")
                return False

            log_info(f"Deleted {deleted} documents with {description}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by {description}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name: Document name to delete

        Returns:
            bool: True if successful, False otherwise
        """
        return self._delete_by_query({"term": {"name.keyword": name}}, f"name '{name}'")

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.

        Args:
            metadata: Metadata dictionary to match

        Returns:
            bool: True if successful, False otherwise
        """
        filter_conditions = self._build_filter_conditions(metadata)
        return self._delete_by_query({"bool": {"filter": filter_conditions}}, f"metadata {metadata}")

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id: Content ID to delete
            user_id: Restrict the delete to this owner's chunks. None deletes across all owners.

        Returns:
            bool: True if successful, False otherwise

        Note:
            Scoped to the exact owner: a caller can view shared content but cannot delete
            it, so removing shared chunks takes an unscoped call.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        content_id_term = {"term": {"content_id.keyword": content_id}}

        if user_id is None:
            return self._delete_by_query(content_id_term, f"content_id '{content_id}'")

        return self._delete_by_query(
            {"bool": {"filter": [content_id_term, self._owner_filter(user_id)]}},
            f"content_id '{content_id}' (user_id={user_id})",
        )

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Delete the owner's chunks carrying the given content hash.

        Args:
            content_hash: Content hash to delete
            user_id: Owner to scope the delete to. None scopes to the shared bucket.

        Returns:
            bool: True if successful, False otherwise

        Note:
            doc_as_upsert alone is not enough: the _id folds in each chunk's own id, so a
            re-upsert that splits the same content into fewer chunks leaves the surplus behind.
        """
        return self._delete_by_query(
            self._content_hash_query(content_hash, user_id),
            f"content_hash '{content_hash}' (user_id={user_id})",
        )

    def _content_hash_query(self, content_hash: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Build the query the dedup pair shares.

        Args:
            content_hash: Content hash to match
            user_id: Owner to scope to, or None for the shared bucket

        Returns:
            Dict[str, Any]: Elasticsearch query matching one owner's chunks for this hash
        """
        return {
            "bool": {
                "filter": [
                    {"term": {"content_hash": content_hash}},
                    self._exact_owner_scope(user_id),
                ]
            }
        }

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update metadata for documents with the given content ID.

        Args:
            content_id: Content ID to update
            metadata: Metadata to merge/update

        Raises:
            Exception: If update fails
        """
        try:
            if not self.exists():
                logger.error(f"Index '{self.index_name}' does not exist")
                raise ValueError(f"Index '{self.index_name}' does not exist")

            # Merge server-side via update_by_query so every matching document is updated,
            # however many chunks the content was split into.
            response = self.client.update_by_query(
                index=self.index_name,
                query={"term": {"content_id.keyword": content_id}},
                script={
                    "source": (
                        "if (ctx._source.meta_data == null) { ctx._source.meta_data = [:] } "
                        "for (entry in params.metadata.entrySet()) { "
                        "ctx._source.meta_data[entry.getKey()] = entry.getValue() }"
                    ),
                    "lang": "painless",
                    "params": {"metadata": metadata},
                },
                refresh=True,
                conflicts="proceed",
            )

            failures = response.get("failures") or []
            if failures:
                raise RuntimeError(f"update_by_query reported {len(failures)} failure(s): {failures[:3]}")

            updated = response.get("updated", 0)
            if not updated:
                log_info(f"No documents found with content_id '{content_id}'")
                return

            log_info(f"Updated metadata for {updated} documents with content_id '{content_id}'")
        except Exception as e:
            logger.error(f"Error updating metadata for content_id {content_id}: {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]

    # ========== Timing Helpers and Teardown ==========

    def _execute_with_timing(self, operation: str, func, return_result: bool = False):
        """
        Execute function with timing and error handling.

        Args:
            operation: Operation name for logging
            func: Function to execute
            return_result: Whether to return function result

        Returns:
            Any: Function result if return_result is True, otherwise None
        """
        start_time = time.time()
        try:
            result = func()
            if return_result:
                return result
        except Exception as e:
            logger.error(f"Error during {operation}: {e}")
            if return_result:
                return False
            raise
        finally:
            end_time = time.time()
            log_debug(f"{operation} operation took {end_time - start_time:.2f} seconds")

    async def _async_execute_with_timing(self, operation: str, func):
        """
        Execute async function with timing and error handling.

        Args:
            operation: Operation name for logging
            func: Async function to execute
        """
        start_time = time.time()
        try:
            await func()
        except Exception as e:
            logger.error(f"Error during {operation}: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"{operation} operation took {end_time - start_time:.2f} seconds")

    def close(self) -> None:
        """Close the synchronous Elasticsearch client connection."""
        if self._client is not None:
            try:
                self._client.close()
                log_debug("Elasticsearch client closed successfully")
            except Exception as e:
                log_debug(f"Error closing Elasticsearch client: {e}")
            finally:
                self._client = None

    async def async_close(self) -> None:
        """
        Close both Elasticsearch client connections.

        Note:
            The async client holds an aiohttp session that must be closed explicitly,
            otherwise aiohttp reports an unclosed client session on interpreter exit.

            The synchronous client is closed here too. An async-only caller still builds
            one - the owner gate inspects the live mapping synchronously and async_search
            runs the sync client on a worker thread - so closing only the async half
            would leave that transport open for anyone following the documented
            ``await vector_db.async_close()``.
        """
        if self._async_client is not None:
            try:
                await self._async_client.close()
                log_debug("Async Elasticsearch client closed successfully")
            except Exception as e:
                log_debug(f"Error closing async Elasticsearch client: {e}")
            finally:
                self._async_client = None

        # close() is a blocking network teardown, so it does not belong on the event loop.
        if self._client is not None:
            await asyncio.to_thread(self.close)
