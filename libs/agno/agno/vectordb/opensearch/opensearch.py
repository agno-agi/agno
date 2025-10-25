from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    from opensearchpy import AsyncOpenSearch, OpenSearch, RequestsHttpConnection
    from opensearchpy import exceptions as opensearch_exceptions
except ImportError:
    raise ImportError("`opensearch-py` not installed. Please install using `pip install opensearch-py`")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType
from agno.vectordb.opensearch.index import Engine, SpaceType


class OpensearchDb(VectorDb):
    """
    OpenSearch vector database implementation with comprehensive search capabilities.

    This class provides a complete vector database solution using OpenSearch as the backend,
    supporting vector similarity search, keyword search, and hybrid search with configurable
    engines and distance metrics.

    Features:
        - Multiple KNN engines (nmslib, faiss, lucene)
        - Various distance metrics (cosine, l2, max_inner_product)
        - Synchronous and asynchronous operations
        - Bulk document operations (insert, upsert, delete)
        - Advanced filtering capabilities
        - Optional reranking support
        - Comprehensive error handling and logging

    Attributes:
        index_name (str): Name of the OpenSearch index
        dimension (int): Dimensionality of the vector embeddings
        engine (Engine): KNN engine to use for vector operations
        distance (Distance): Distance metric for similarity calculations
        search_type (SearchType): Default search type (vector, keyword, or hybrid)
        embedder (Embedder): Embedder instance for generating vector embeddings
        reranker (Optional[Reranker]): Optional reranker for improving search results
    """

    def __init__(
        self,
        index_name: str,
        dimension: int,
        hosts: List[Dict[str, Any]],
        embedder: Optional[Embedder] = None,
        engine: Engine = Engine.nmslib,
        distance: Distance = Distance.cosine,
        search_type: SearchType = SearchType.vector,
        parameters: Optional[Dict[str, Any]] = None,
        http_auth: Optional[tuple] = None,
        use_ssl: bool = False,
        verify_certs: bool = False,
        connection_class: Any = RequestsHttpConnection,
        timeout: int = 30,
        max_retries: int = 10,
        retry_on_timeout: bool = True,
        reranker: Optional[Reranker] = None,
    ):
        """
        Initialize OpenSearch vector database.

        Args:
            index_name: Name of the OpenSearch index
            dimension: Dimensionality of the vector embeddings
            hosts: List of OpenSearch host configurations
            embedder: Embedder instance for generating vector embeddings
            engine: KNN engine to use (nmslib, faiss, or lucene)
            distance: Distance metric for similarity calculations
            search_type: Default search type (vector, keyword, or hybrid)
            parameters: Custom engine parameters (will be merged with defaults)
            http_auth: HTTP authentication tuple (username, password)
            use_ssl: Whether to use SSL/TLS for connections
            verify_certs: Whether to verify SSL certificates
            connection_class: Connection class for OpenSearch client
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_on_timeout: Whether to retry on timeout errors
            reranker: Optional reranker for improving search results

        Raises:
            ValueError: If unsupported engine is specified
            ImportError: If opensearch-py is not installed
        """
        # Core configuration
        self.index_name = index_name
        self.dimension = dimension
        self.engine = engine
        self.distance = distance
        self.search_type = search_type

        # Connection configuration
        self.hosts = hosts
        self.http_auth = http_auth
        self.use_ssl = use_ssl
        self.verify_certs = verify_certs
        self.connection_class = connection_class
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_on_timeout = retry_on_timeout

        # Engine parameters
        self.parameters = self._get_default_parameters()
        if parameters:
            self.parameters.update(parameters)
            log_debug(f"Updated engine parameters: {self.parameters}")

        # Clients (lazy initialized)
        self._client: Optional[OpenSearch] = None
        self._async_client: Optional[AsyncOpenSearch] = None

        # Index mapping
        self.mapping = self._create_mapping()

        # Initialize embedder and reranker
        self.embedder = self._initialize_embedder(embedder)
        self.reranker = reranker

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

    def _get_default_parameters(self) -> Dict[str, Any]:
        """
        Get default parameters for the specified KNN engine.

        Returns:
            Dict[str, Any]: Default parameters for the engine

        Raises:
            ValueError: If unsupported engine is specified
        """
        defaults = {
            Engine.nmslib: {"ef_construction": 512, "m": 16},
            Engine.faiss: {"ef_construction": 512, "m": 16},
            Engine.lucene: {"m": 16, "ef_construction": 512},
        }

        if self.engine not in defaults:
            raise ValueError(f"Unsupported engine: {self.engine}")

        params = defaults[self.engine]
        log_debug(f"Default parameters for {self.engine}: {params}")
        return params

    @property
    def space_type(self) -> str:
        """
        Get OpenSearch space type from distance metric.

        Returns:
            str: OpenSearch-compatible space type string

        Note:
            Maps Distance enum values to OpenSearch space types:
            - cosine -> cosinesimil
            - l2 -> l2
            - max_inner_product -> innerproduct
        """
        distance_mapping = {
            Distance.cosine: SpaceType.cosinesimil,
            Distance.l2: SpaceType.l2,
            Distance.max_inner_product: SpaceType.innerproduct,
        }
        return distance_mapping.get(self.distance, SpaceType.cosinesimil)

    def _create_mapping(self) -> Dict[str, Any]:
        """
        Create index mapping configuration for OpenSearch.

        Returns:
            Dict[str, Any]: Complete index mapping configuration

        Note:
            Creates mapping with:
            - KNN vector field for embeddings
            - Text fields for content and name
            - Object field for metadata with dynamic mapping
            - Additional fields for usage and reranking scores
        """
        log_debug(f"Creating mapping for engine: {self.engine}, space_type: {self.space_type}")

        knn_method = {
            "name": "hnsw",
            "space_type": self.space_type,
            "engine": self.engine,
            "parameters": self.parameters,
        }

        return {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": self.parameters.get("ef_search", 512),
                }
            },
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self.dimension,
                        "method": knn_method,
                    },
                    "content": {"type": "text", "analyzer": "standard"},
                    "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                    "meta_data": {
                        "type": "object",
                        "dynamic": True,
                        "properties": {
                            "*": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}}
                        },
                    },
                    "usage": {"type": "object", "enabled": True},
                    "reranking_score": {"type": "float"},
                    "content_id": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                }
            },
        }

    @property
    def client(self) -> OpenSearch:
        """
        Get or create synchronous OpenSearch client.

        Returns:
            OpenSearch: Configured synchronous client instance

        Note:
            Client is lazily initialized and cached for reuse
        """
        if self._client is None:
            self._client = self._create_sync_client()
        return self._client

    @property
    def async_client(self) -> AsyncOpenSearch:
        """
        Get or create asynchronous OpenSearch client.

        Returns:
            AsyncOpenSearch: Configured asynchronous client instance

        Note:
            Client is lazily initialized and cached for reuse
        """
        if self._async_client is None:
            self._async_client = self._create_async_client()
        return self._async_client

    def _create_sync_client(self) -> OpenSearch:
        """
        Create synchronous OpenSearch client with connection testing.

        Returns:
            OpenSearch: Configured and tested synchronous client

        Raises:
            Exception: If client creation or connection test fails
        """
        log_debug("Creating OpenSearch client")
        try:
            connection_config = {
                "hosts": self.hosts,
                "http_auth": self.http_auth,
                "use_ssl": self.use_ssl,
                "verify_certs": self.verify_certs,
                "connection_class": self.connection_class,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "retry_on_timeout": self.retry_on_timeout,
            }

            client = OpenSearch(**connection_config)
            ping_result = client.ping()
            log_info(f"Successfully connected to OpenSearch (ping: {ping_result})")
            return client
        except Exception as e:
            logger.error(f"Failed to create OpenSearch client: {e}")
            raise

    def _create_async_client(self) -> AsyncOpenSearch:
        """
        Create asynchronous OpenSearch client.

        Returns:
            AsyncOpenSearch: Configured asynchronous client

        Raises:
            Exception: If client creation fails

        Note:
            Async client doesn't perform connection test during creation
        """
        log_debug("Creating async OpenSearch client")
        try:
            connection_config = {
                "hosts": self.hosts,
                "http_auth": self.http_auth,
                "use_ssl": self.use_ssl,
                "verify_certs": self.verify_certs,
            }

            client = AsyncOpenSearch(**connection_config)
            log_info("Successfully created async OpenSearch client")
            return client
        except Exception as e:
            logger.error(f"Failed to create async OpenSearch client: {e}")
            raise

    def create(self) -> None:
        """
        Create the index if it does not exist.

        Note:
            This is a synchronous operation that will create the index
            with the configured mapping if it doesn't already exist.
        """
        self._execute_with_timing("create", self._create_index_impl)

    async def async_create(self) -> None:
        """
        Create the index asynchronously if it does not exist.

        Note:
            Asynchronous version of create() method.
        """
        await self._async_execute_with_timing("async_create", self._async_create_index_impl)

    def _create_index_impl(self) -> None:
        """
        Implementation for synchronous index creation.

        Creates the index with the configured mapping if it doesn't exist.
        """
        if not self.exists():
            log_debug(f"Creating index: {self.index_name}")
            self.client.indices.create(index=self.index_name, body=self.mapping)
            log_info(f"Successfully created index: {self.index_name}")
        else:
            log_debug(f"Index {self.index_name} already exists")

    async def _async_create_index_impl(self) -> None:
        """
        Implementation for asynchronous index creation.

        Creates the index with the configured mapping if it doesn't exist.
        """
        if not await self.async_exists():
            log_debug(f"Creating index (async): {self.index_name}")
            await self.async_client.indices.create(index=self.index_name, body=self.mapping)
            log_info(f"Successfully created index (async): {self.index_name}")
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
            exists = self.client.indices.exists(index=self.index_name)
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
            exists = await self.async_client.indices.exists(index=self.index_name)
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
        """
        if self.exists():
            log_debug(f"Optimizing index: {self.index_name}")
            self.client.indices.forcemerge(index=self.index_name, max_num_segments=1)
            log_info(f"Successfully optimized index: {self.index_name}")
        else:
            logger.warning(f"Index {self.index_name} does not exist, cannot optimize")

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
            exists = self.client.exists(index=self.index_name, id=document.id)
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
            exists = await self.async_client.exists(index=self.index_name, id=document.id)
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
            exists = self.client.exists(index=self.index_name, id=id)
            log_debug(f"Document ID '{id}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if ID exists: {e}")
            return False

    def _check_field_exists(self, field: str, value: str) -> bool:
        """
        Check if a document with a specific field value exists.

        Args:
            field: Field name to search in
            value: Value to search for

        Returns:
            bool: True if document with field value exists, False otherwise
        """
        try:
            log_debug(f"Checking if field {field} exists with value: {value}")
            if not self.exists():
                log_debug("Index does not exist, returning False")
                return False

            search_query = {"query": {"term": {field: value}}, "size": 1}
            response = self.client.search(index=self.index_name, body=search_query)
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

            search_query = {"query": {"term": {field: value}}, "size": 1}
            response = await self.async_client.search(index=self.index_name, body=search_query)
            exists = response["hits"]["total"]["value"] > 0
            log_debug(f"Field {field} with value '{value}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if field exists: {e}")
            return False

    def _prepare_document_for_indexing(self, doc: Document) -> Dict[str, Any]:
        """
        Prepare a document for indexing by ensuring proper structure and embeddings.

        Args:
            doc: Document to prepare

        Returns:
            Dict[str, Any]: Document structure ready for indexing

        Raises:
            ValueError: If document cannot be prepared for indexing

        Note:
            Generates ID if missing, ensures embedding exists, validates dimensions,
            and builds the final index document structure.
        """
        log_debug(f"Preparing document for indexing: {doc.id}")

        # Generate ID if not present
        if doc.id is None:
            doc.id = str(uuid.uuid4())
            log_debug(f"Generated new document ID: {doc.id}")

        # Ensure document has embedding
        self._ensure_document_embedding(doc)

        # Validate embedding dimensions
        self._validate_embedding_dimensions(doc)

        # Build index document
        index_doc = self._build_index_document(doc)

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
            ValueError: If embedding dimensions don't match expected dimension
        """
        if len(doc.embedding) != self.dimension:
            error_msg = f"Embedding dimension mismatch for document {doc.id}: expected {self.dimension}, got {len(doc.embedding)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        log_debug(f"Document {doc.id} embedding dimension check passed: {len(doc.embedding)}")

    def _build_index_document(self, doc: Document) -> Dict[str, Any]:
        """
        Build the document structure for indexing.

        Args:
            doc: Document to build index structure for

        Returns:
            Dict[str, Any]: Document structure ready for OpenSearch indexing

        Note:
            Includes core fields (embedding, content, meta_data) and optional fields
            (name, usage, reranking_score) if they exist.
        """
        index_doc = {
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

        return index_doc

    def _create_document_from_hit(self, hit: Dict[str, Any]) -> Document:
        """
        Create a Document object from an OpenSearch search hit.

        Args:
            hit: OpenSearch search hit containing document data

        Returns:
            Document: Constructed document with search metadata

        Note:
            Adds search score to document metadata for reference.
        """
        doc_data = hit["_source"]

        # Store the search score in meta_data
        meta_data = doc_data.get("meta_data", {}).copy()
        meta_data["search_score"] = hit["_score"]

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

        log_debug(f"Created document from search hit: {doc.id} (score: {hit['_score']:.4f})")
        return doc

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Insert documents into the index.

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to insert
            filters: Optional filters (unused for insert operation)

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
        """
        # Store content_hash in each document's metadata for tracking
        for doc in documents:
            if doc.meta_data is None:
                doc.meta_data = {}
            doc.meta_data["content_hash"] = content_hash
        self._execute_bulk_operation("insert", documents, self._prepare_bulk_insert_data)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Insert documents into the index asynchronously.

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to insert
            filters: Optional filters (unused for insert operation)

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
            Uses batch embedding for improved performance.
        """
        # Store content_hash in each document's metadata for tracking
        for doc in documents:
            if doc.meta_data is None:
                doc.meta_data = {}
            doc.meta_data["content_hash"] = content_hash
        await self._async_execute_bulk_operation("insert", documents, self._prepare_bulk_insert_data, use_batch_embed=True)

    def upsert_available(self) -> bool:
        """
        Check if upsert operations are supported.

        Returns:
            bool: Always True for OpenSearch

        Note:
            OpenSearch supports upsert operations through update with doc_as_upsert.
        """
        log_debug("Upsert operations are supported for OpenSearch")
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents in the index (insert if new, update if exists).

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to upsert
            filters: Optional filters (unused for upsert operation)

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
        """
        # Store content_hash in each document's metadata for tracking
        for doc in documents:
            if doc.meta_data is None:
                doc.meta_data = {}
            doc.meta_data["content_hash"] = content_hash
        self._execute_bulk_operation("upsert", documents, self._prepare_bulk_upsert_data)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Upsert documents in the index asynchronously (insert if new, update if exists).

        Args:
            content_hash: Content hash for the documents
            documents: List of documents to upsert
            filters: Optional filters (unused for upsert operation)

        Note:
            Creates index if it doesn't exist. Skips documents that fail preparation.
            Uses batch embedding for improved performance.
        """
        # Store content_hash in each document's metadata for tracking
        for doc in documents:
            if doc.meta_data is None:
                doc.meta_data = {}
            doc.meta_data["content_hash"] = content_hash
        await self._async_execute_bulk_operation("upsert", documents, self._prepare_bulk_upsert_data, use_batch_embed=True)

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
                hit = {
                    "_id": document_id,
                    "_source": response["_source"],
                    "_score": 1.0,
                }
                doc = self._create_document_from_hit(hit)
                log_debug(f"Successfully retrieved document: {document_id}")
                return doc
            else:
                log_debug(f"Document {document_id} not found")
                return None
        except opensearch_exceptions.NotFoundError:
            log_info(f"Document {document_id} not found in index {self.index_name}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving document {document_id}: {e}")
            return None

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
                    index=self.index_name, body={"query": {"match_all": {}}}, refresh=True
                )
                deleted_count = response.get("deleted", 0)
                log_info(f"Successfully deleted {deleted_count} documents from index: {self.index_name}")
                return True
            else:
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
            bulk_data = [{"delete": {"_index": self.index_name, "_id": doc_id}} for doc_id in document_ids]

            if bulk_data:
                log_debug(f"Executing bulk delete operation for {len(document_ids)} documents")
                response = self.client.bulk(body=bulk_data, refresh=True)

                if response.get("errors"):
                    error_count = 0
                    for item in response.get("items", []):
                        if "delete" in item and "error" in item["delete"]:
                            logger.error(f"Bulk delete error: {item['delete']['error']}")
                            error_count += 1
                    logger.warning(f"Bulk delete completed with {error_count} errors")
                else:
                    log_info(f"Successfully deleted {len(document_ids)} documents from index {self.index_name}")

        except Exception as e:
            logger.error(f"Error executing bulk delete operation: {e}")
            raise

    def _execute_bulk_operation(self, operation: str, documents: List[Document], prepare_func) -> None:
        """
        Execute bulk operation with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process
            prepare_func: Function to prepare bulk data

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

        try:
            bulk_data, prepared_count = prepare_func(documents)
            if bulk_data:
                self._execute_bulk_request(bulk_data, operation, prepared_count)
        except Exception as e:
            logger.error(f"Error executing bulk {operation} operation: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"Bulk {operation} operation took {end_time - start_time:.2f} seconds")

    async def _async_execute_bulk_operation(
        self, operation: str, documents: List[Document], prepare_func, use_batch_embed: bool = False
    ) -> None:
        """
        Execute bulk operation asynchronously with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process
            prepare_func: Function to prepare bulk data
            use_batch_embed: Whether to use batch embedding (default: False)

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

        try:
            # Embed documents in batch if requested
            if use_batch_embed:
                await self._async_embed_documents(documents)

            bulk_data, prepared_count = prepare_func(documents)
            if bulk_data:
                await self._async_execute_bulk_request(bulk_data, operation, prepared_count)
        except Exception as e:
            logger.error(f"Error executing async bulk {operation} operation: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"Async bulk {operation} operation took {end_time - start_time:.2f} seconds")

    def _prepare_bulk_insert_data(self, documents: List[Document]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Prepare bulk insert data for OpenSearch.

        Args:
            documents: List of documents to prepare

        Returns:
            Tuple[List[Dict[str, Any]], int]: Bulk data and count of prepared documents

        Note:
            Skips documents that fail preparation and logs errors.
        """
        bulk_data = []
        prepared_count = 0

        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc)
                bulk_data.extend([{"index": {"_index": self.index_name, "_id": doc.id}}, index_doc])
                prepared_count += 1
            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for indexing: {e}")
                continue

        log_debug(f"Prepared {prepared_count}/{len(documents)} documents for bulk insert")
        return bulk_data, prepared_count

    def _prepare_bulk_upsert_data(self, documents: List[Document]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Prepare bulk upsert data for OpenSearch.

        Args:
            documents: List of documents to prepare

        Returns:
            Tuple[List[Dict[str, Any]], int]: Bulk data and count of prepared documents

        Note:
            Skips documents that fail preparation and logs errors.
        """
        bulk_data = []
        prepared_count = 0

        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc)
                bulk_data.extend(
                    [{"update": {"_index": self.index_name, "_id": doc.id}}, {"doc": index_doc, "doc_as_upsert": True}]
                )
                prepared_count += 1
            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for upsert: {e}")
                continue

        log_debug(f"Prepared {prepared_count}/{len(documents)} documents for bulk upsert")
        return bulk_data, prepared_count

    def _execute_bulk_request(self, bulk_data: List[Dict[str, Any]], operation: str, prepared_count: int) -> None:
        """
        Execute bulk request and handle response.

        Args:
            bulk_data: Prepared bulk data for OpenSearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared

        Note:
            Handles bulk response errors and provides detailed logging.
        """
        log_debug(f"Executing bulk {operation} operation with {len(bulk_data) // 2} documents")
        response = self.client.bulk(body=bulk_data, refresh=True)
        self._handle_bulk_response(response, operation, prepared_count)

    async def _async_execute_bulk_request(
        self, bulk_data: List[Dict[str, Any]], operation: str, prepared_count: int
    ) -> None:
        """
        Execute async bulk request and handle response.

        Args:
            bulk_data: Prepared bulk data for OpenSearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared

        Note:
            Handles bulk response errors and provides detailed logging.
        """
        log_debug(f"Executing async bulk {operation} operation with {len(bulk_data) // 2} documents")
        response = await self.async_client.bulk(body=bulk_data, refresh=True)
        self._handle_bulk_response(response, operation, prepared_count)

    def _handle_bulk_response(self, response: Dict[str, Any], operation: str, prepared_count: int) -> None:
        """
        Handle bulk operation response and log results.

        Args:
            response: Bulk operation response from OpenSearch
            operation: Operation name for logging
            prepared_count: Number of documents prepared

        Note:
            Counts and logs individual errors if any occur.
        """
        if response.get("errors"):
            error_count = self._count_bulk_errors(response, operation)
            logger.warning(f"Bulk {operation} completed with {error_count} errors")
        else:
            log_info(f"Successfully {operation}ed {prepared_count} documents in index {self.index_name}")

    def _count_bulk_errors(self, response: Dict[str, Any], operation: str) -> int:
        """
        Count and log bulk operation errors.

        Args:
            response: Bulk operation response from OpenSearch
            operation: Operation name for logging

        Returns:
            int: Number of errors encountered

        Note:
            Logs individual error details for debugging.
        """
        error_count = 0
        for item in response.get("items", []):
            item_key = "update" if operation == "upsert" else "index"
            if item_key in item and "error" in item[item_key]:
                logger.error(f"Bulk {operation} error: {item[item_key]['error']}")
                error_count += 1
        return error_count

    async def _async_embed_documents(self, documents: List[Document]) -> None:
        """
        Embed a batch of documents using either batch embedding or individual embedding.

        Args:
            documents: List of documents to embed

        Note:
            - Uses batch embedding when embedder.enable_batch is True and supports async_get_embeddings_batch_and_usage
            - Falls back to individual embedding if batch fails (except for rate limit errors)
            - Skips documents that already have embeddings unless they need to be regenerated
        """
        if self.embedder is None:
            logger.warning("No embedder configured, skipping embedding generation")
            return

        # Check if embedder supports batch embedding
        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            try:
                # Extract content from documents that need embedding
                docs_to_embed = [doc for doc in documents if doc.embedding is None]

                if not docs_to_embed:
                    log_debug("All documents already have embeddings")
                    return

                # Get batch embeddings and usage
                doc_contents = [doc.content for doc in docs_to_embed]
                log_debug(f"Generating batch embeddings for {len(doc_contents)} documents")
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                # Assign embeddings to documents
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
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    logger.error(f"Rate limit detected during batch embedding: {e}")
                    raise e
                else:
                    logger.warning(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents if doc.embedding is None]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            log_debug("Using individual embedding (batch embedding not available)")
            embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents if doc.embedding is None]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents based on configured search type.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of matching documents

        Note:
            Uses the search type configured during initialization (vector, keyword, or hybrid).
        """
        search_methods = {
            SearchType.vector: self.vector_search,
            SearchType.keyword: self.keyword_search,
            SearchType.hybrid: self.hybrid_search,
        }

        search_method = search_methods.get(self.search_type)
        if search_method is None:
            logger.error(f"Invalid search type '{self.search_type}'")
            return []

        return search_method(query, limit, filters)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Search for documents asynchronously based on configured search type.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of matching documents

        Note:
            Runs the synchronous search in a thread to avoid blocking the event loop.
        """
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform vector similarity search using embeddings.

        Args:
            query: Search query string (will be embedded)
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of documents ordered by similarity score

        Note:
            Generates query embedding and performs KNN search.
        """
        return self._execute_search_with_timing("vector", query, limit, self._build_vector_query, filters)

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform keyword-based text search.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List[Document]: List of documents ordered by text relevance score

        Note:
            Uses multi-match query on content and name fields.
        """
        return self._execute_search_with_timing("keyword", query, limit, self._build_keyword_query, filters)

    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform hybrid search combining vector and keyword search.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List[Document]: List of documents ordered by combined similarity and relevance scores

        Note:
            Combines vector similarity (70% weight) and keyword relevance (30% weight).
        """
        return self._execute_search_with_timing("hybrid", query, limit, self._build_hybrid_query, filters)

    def _execute_search_with_timing(
        self, search_type: str, query: str, limit: int, query_builder, filters: Optional[Dict[str, Any]]
    ) -> List[Document]:
        """
        Execute search with timing and comprehensive error handling.

        Args:
            search_type: Type of search for logging
            query: Search query string
            limit: Maximum number of results
            query_builder: Function to build search query
            filters: Optional filters to apply

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
            search_query = query_builder(query, limit, filters)
            log_debug(f"Executing {search_type} search query")
            response = self.client.search(index=self.index_name, body=search_query)

            documents = [self._create_document_from_hit(hit) for hit in response["hits"]["hits"]]
            log_debug(f"Retrieved {len(documents)} documents from {search_type} search")

            # Apply reranking if configured
            if self.reranker and documents:
                documents = self._apply_reranking(query, documents)

            log_info(f"{search_type.capitalize()} search returned {len(documents)} documents for query: '{query}'")
            return documents

        except Exception as e:
            logger.error(f"Error during {search_type} search: {e}")
            return []
        finally:
            end_time = time.time()
            log_debug(f"Total {search_type} search operation took {end_time - start_time:.2f} seconds")

    def _build_vector_query(self, query: str, limit: int, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build vector search query for OpenSearch.

        Args:
            query: Search query string (will be embedded)
            limit: Maximum number of results
            filters: Optional filters to apply

        Returns:
            Dict[str, Any]: OpenSearch KNN query structure

        Note:
            Generates query embedding and optionally applies filters.
        """
        query_embedding, usage = self._get_query_embedding(query)

        search_query = {"size": limit, "query": {"knn": {"embedding": {"vector": query_embedding, "k": limit}}}}

        if filters:
            filter_conditions = self._build_filter_conditions(filters)
            if filter_conditions:
                search_query = {
                    "size": limit,
                    "query": {
                        "bool": {
                            "must": [{"knn": {"embedding": {"vector": query_embedding, "k": limit}}}],
                            "filter": filter_conditions,
                        }
                    },
                }

        return search_query

    def _build_keyword_query(self, query: str, limit: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Build keyword search query for OpenSearch.

        Args:
            query: Search query string.
            limit: Maximum number of results.
            filters: Optional filters to apply.

        Returns:
            Dict[str, Any]: OpenSearch multi-match query structure.

        Note:
            Searches across 'content' and 'name' fields with 'best_fields' scoring.
        """
        base_query = {"multi_match": {"query": query, "fields": ["content", "name"], "type": "best_fields"}}

        search_query: Dict[str, Any] = {"size": limit, "query": base_query}

        if filters:
            filter_conditions = self._build_filter_conditions(filters)
            if filter_conditions:
                search_query["query"] = {"bool": {"must": [base_query], "filter": filter_conditions}}

        return search_query

    def _build_hybrid_query(self, query: str, limit: int, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build hybrid search query combining vector and keyword search.

        Args:
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply

        Returns:
            Dict[str, Any]: OpenSearch boolean query with vector and keyword components

        Note:
            Combines KNN search (70% boost) with multi-match search (30% boost).
        """
        query_embedding, usage = self._get_query_embedding(query)

        search_query = {
            "size": limit,
            "query": {
                "bool": {
                    "should": [
                        {"knn": {"embedding": {"vector": query_embedding, "k": limit, "boost": 0.7}}},
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["content", "name"],
                                "type": "best_fields",
                                "boost": 0.3,
                            }
                        },
                    ]
                }
            },
        }

        if filters:
            filter_conditions = self._build_filter_conditions(filters)
            if filter_conditions:
                search_query["query"]["bool"]["filter"] = filter_conditions

        return search_query

    def _get_query_embedding(self, query: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Generate embedding for search query.

        Args:
            query: Search query string

        Returns:
            Tuple[List[float], Optional[Dict[str, Any]]]: Query embedding and usage statistics

        Raises:
            ValueError: If no embedder is configured

        Note:
            Uses the configured embedder to generate query embedding.
        """
        if self.embedder is None:
            raise ValueError("No embedder configured for search")

        log_debug("Generating query embedding")
        query_embedding, usage = self.embedder.get_embedding_and_usage(query)
        log_debug(f"Generated query embedding (dimension: {len(query_embedding)})")

        if usage:
            log_debug(f"Embedding generation usage: {usage}")

        return query_embedding, usage

    def _build_filter_conditions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build filter conditions for OpenSearch query.

        Args:
            filters: Dictionary of filter conditions

        Returns:
            List[Dict[str, Any]]: List of OpenSearch filter conditions

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
        Build a single filter condition for OpenSearch.

        Args:
            key: Field name to filter on
            value: Filter value (can be scalar, list, or dict with operators)

        Returns:
            Optional[Dict[str, Any]]: OpenSearch filter condition or None if invalid

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
            log_debug(f"Added terms filter for {key}: {value}")
            return {"terms": {f"meta_data.{key}": value}}
        else:
            log_debug(f"Added term filter for {key}: {value}")
            return {"term": {f"meta_data.{key}.keyword": value}}

    def _build_dict_filter_condition(self, key: str, value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Build filter condition for dictionary filter values.

        Args:
            key: Field name to filter on
            value: Dictionary containing filter operators and values

        Returns:
            Optional[Dict[str, Any]]: OpenSearch filter condition or None if invalid

        Note:
            Supports:
            - $in/in operators for multiple values
            - Range operators: gt, lt, gte, lte
        """
        # Handle $in and in operators
        if "$in" in value or "in" in value:
            in_value = value.get("$in") or value.get("in")
            if isinstance(in_value, list):
                log_debug(f"Added terms filter for {key}: {in_value}")
                return {"terms": {f"meta_data.{key}": in_value}}
            else:
                logger.warning(f"Invalid value for $in/in operator for key {key}: {in_value}")
                return None

        # Handle range queries
        range_ops = ["gt", "lt", "gte", "lte"]
        if any(op in value for op in range_ops):
            range_conditions = {op: val for op, val in value.items() if op in range_ops}
            log_debug(f"Added range filter for {key}: {range_conditions}")
            return {"range": {f"meta_data.{key}": range_conditions}}

        logger.warning(f"Unsupported filter operator for key {key}: {value}")
        return None

    def _apply_reranking(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Apply reranking to search results if reranker is configured.

        Args:
            query: Original search query
            documents: List of documents to rerank

        Returns:
            List[Document]: Reranked list of documents

        Note:
            Uses the configured reranker to improve search result ordering.
        """
        log_debug(f"Applying reranking with {type(self.reranker).__name__}")
        rerank_start = time.time()
        reranked_docs = self.reranker.rerank(query, documents)
        rerank_end = time.time()
        log_debug(f"Reranking took {rerank_end - rerank_start:.2f} seconds")
        return reranked_docs

    def _execute_with_timing(self, operation: str, func, return_result: bool = False):
        """
        Execute function with timing and error handling.

        Args:
            operation: Operation name for logging
            func: Function to execute
            return_result: Whether to return function result

        Returns:
            Any: Function result if return_result is True, otherwise None

        Note:
            Provides comprehensive timing and error logging for all operations.
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

        Note:
            Provides comprehensive timing and error logging for async operations.
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

    def content_hash_exists(self, content_hash: str) -> bool:
        """
        Check if a document with the given content hash exists.

        Args:
            content_hash: Content hash to check

        Returns:
            bool: True if document exists, False otherwise
        """
        return self._check_field_exists("content_hash", content_hash)

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

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name: Document name to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.exists():
                log_info(f"Index '{self.index_name}' does not exist")
                return False

            # Search for documents with this name
            query = {"query": {"term": {"name.keyword": name}}, "size": 1000}
            response = self.client.search(index=self.index_name, body=query)

            doc_ids = [hit["_id"] for hit in response.get("hits", {}).get("hits", [])]
            if doc_ids:
                self.delete_documents(doc_ids)
                log_info(f"Deleted {len(doc_ids)} documents with name '{name}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.

        Args:
            metadata: Metadata dictionary to match

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.exists():
                log_info(f"Index '{self.index_name}' does not exist")
                return False

            # Build filter conditions
            filter_conditions = self._build_filter_conditions(metadata)
            query = {"query": {"bool": {"filter": filter_conditions}}, "size": 1000}
            response = self.client.search(index=self.index_name, body=query)

            doc_ids = [hit["_id"] for hit in response.get("hits", {}).get("hits", [])]
            if doc_ids:
                self.delete_documents(doc_ids)
                log_info(f"Deleted {len(doc_ids)} documents with metadata {metadata}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id: Content ID to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.exists():
                log_info(f"Index '{self.index_name}' does not exist")
                return False

            # Search for documents with this content_id
            query = {"query": {"term": {"content_id.keyword": content_id}}, "size": 1000}
            response = self.client.search(index=self.index_name, body=query)

            doc_ids = [hit["_id"] for hit in response.get("hits", {}).get("hits", [])]
            if doc_ids:
                self.delete_documents(doc_ids)
                log_info(f"Deleted {len(doc_ids)} documents with content_id '{content_id}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_id {content_id}: {e}")
            return False

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

            # Search for documents with this content_id
            query = {"query": {"term": {"content_id.keyword": content_id}}, "size": 1000}
            response = self.client.search(index=self.index_name, body=query)

            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                log_info(f"No documents found with content_id '{content_id}'")
                return

            # Update each document
            for hit in hits:
                doc_id = hit["_id"]
                current_metadata = hit["_source"].get("meta_data", {})
                updated_metadata = {**current_metadata, **metadata}

                self.client.update(index=self.index_name, id=doc_id, body={"doc": {"meta_data": updated_metadata}})

            log_info(f"Updated metadata for {len(hits)} documents with content_id '{content_id}'")
        except Exception as e:
            logger.error(f"Error updating metadata for content_id {content_id}: {e}")
            raise
