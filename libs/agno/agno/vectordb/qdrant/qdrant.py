from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    from qdrant_client import AsyncQdrantClient, QdrantClient  # noqa: F401
    from qdrant_client.http import models
except ImportError:
    raise ImportError(
        "The `qdrant-client` package is not installed. Please install it via `pip install qdrant-client`."
    )

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

DEFAULT_DENSE_VECTOR_NAME = "dense"
DEFAULT_SPARSE_VECTOR_NAME = "sparse"
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"


class Qdrant(VectorDb):
    """Vector DB implementation powered by Qdrant - https://qdrant.tech/"""

    def __init__(
        self,
        collection: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        location: Optional[str] = None,
        url: Optional[str] = None,
        port: Optional[int] = 6333,
        grpc_port: int = 6334,
        prefer_grpc: bool = False,
        https: Optional[bool] = None,
        api_key: Optional[str] = None,
        prefix: Optional[str] = None,
        timeout: Optional[float] = None,
        host: Optional[str] = None,
        path: Optional[str] = None,
        reranker: Optional[Reranker] = None,
        search_type: SearchType = SearchType.vector,
        dense_vector_name: str = DEFAULT_DENSE_VECTOR_NAME,
        sparse_vector_name: str = DEFAULT_SPARSE_VECTOR_NAME,
        hybrid_fusion_strategy: models.Fusion = models.Fusion.RRF,
        fastembed_kwargs: Optional[dict] = None,
        **kwargs,
    ):
        """
        Args:
            collection (str): Name of the Qdrant collection.
            name (Optional[str]): Name of the vector database.
            description (Optional[str]): Description of the vector database.
            embedder (Optional[Embedder]): Optional embedder for automatic vector generation.
            distance (Distance): Distance metric to use (default: cosine).
            location (Optional[str]): `":memory:"` for in-memory, or str used as `url`. If `None`, use default host/port.
            url (Optional[str]): Full URL (scheme, host, port, prefix). Overrides host/port if provided.
            port (Optional[int]): REST API port (default: 6333).
            grpc_port (int): gRPC interface port (default: 6334).
            prefer_grpc (bool): Prefer gRPC over REST if True.
            https (Optional[bool]): Use HTTPS if True.
            api_key (Optional[str]): API key for Qdrant Cloud authentication.
            prefix (Optional[str]): URL path prefix (e.g., "service/v1").
            timeout (Optional[float]): Request timeout (REST: default 5s, gRPC: unlimited).
            host (Optional[str]): Qdrant host (default: "localhost" if not specified).
            path (Optional[str]): Path for local persistence (QdrantLocal).
            reranker (Optional[Reranker]): Optional reranker for result refinement.
            search_type (SearchType): Whether to use vector, keyword or hybrid search.
            dense_vector_name (str): Dense vector name.
            sparse_vector_name (str): Sparse vector name.
            hybrid_fusion_strategy (models.Fusion): Strategy for hybrid fusion.
            fastembed_kwargs (Optional[dict]): Keyword args for `fastembed.SparseTextEmbedding.__init__()`.
            **kwargs: Keyword args for `qdrant_client.QdrantClient.__init__()`.
        """
        # Validate required parameters
        if not collection:
            raise ValueError("Collection name must be provided.")

        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            host_identifier = host or location or url or "localhost"
            seed = f"{host_identifier}#{collection}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        # Collection attributes
        self.collection: str = collection

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        # Distance metric
        self.distance: Distance = distance

        # Qdrant client instance
        self._client: Optional[QdrantClient] = None

        # Qdrant async client instance
        self._async_client: Optional[AsyncQdrantClient] = None

        # Qdrant client arguments
        self.location: Optional[str] = location
        self.url: Optional[str] = url
        self.port: Optional[int] = port
        self.grpc_port: int = grpc_port
        self.prefer_grpc: bool = prefer_grpc
        self.https: Optional[bool] = https
        self.api_key: Optional[str] = api_key
        self.prefix: Optional[str] = prefix
        self.timeout: Optional[float] = timeout
        self.host: Optional[str] = host
        self.path: Optional[str] = path

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Qdrant client kwargs
        self.kwargs = kwargs

        self.search_type = search_type
        self.dense_vector_name = dense_vector_name
        self.sparse_vector_name = sparse_vector_name
        self.hybrid_fusion_strategy = hybrid_fusion_strategy

        # TODO(v2.0.0): Remove backward compatibility for unnamed vectors
        # TODO(v2.0.0): Make named vectors mandatory and simplify the codebase
        self.use_named_vectors = search_type in [SearchType.hybrid]

        if self.search_type in [SearchType.keyword, SearchType.hybrid]:
            try:
                from fastembed import SparseTextEmbedding  # type: ignore

                default_kwargs = {"model_name": DEFAULT_SPARSE_MODEL}
                if fastembed_kwargs:
                    default_kwargs.update(fastembed_kwargs)

                # Type ignore for mypy as SparseTextEmbedding constructor accepts flexible kwargs
                self.sparse_encoder = SparseTextEmbedding(**default_kwargs)  # type: ignore

            except ImportError as e:
                raise ImportError(
                    "To use keyword/hybrid search, install the `fastembed` extra with `pip install fastembed`."
                ) from e

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            log_debug("Creating Qdrant Client")
            self._client = QdrantClient(
                location=self.location,
                url=self.url,
                port=self.port,
                grpc_port=self.grpc_port,
                prefer_grpc=self.prefer_grpc,
                https=self.https,
                api_key=self.api_key,
                prefix=self.prefix,
                timeout=int(self.timeout) if self.timeout is not None else None,
                host=self.host,
                path=self.path,
                **self.kwargs,
            )
        return self._client

    @property
    def async_client(self) -> AsyncQdrantClient:
        """Get or create the async Qdrant client."""
        if self._async_client is None:
            log_debug("Creating Async Qdrant Client")
            self._async_client = AsyncQdrantClient(
                location=self.location,
                url=self.url,
                port=self.port,
                grpc_port=self.grpc_port,
                prefer_grpc=self.prefer_grpc,
                https=self.https,
                api_key=self.api_key,
                prefix=self.prefix,
                timeout=int(self.timeout) if self.timeout is not None else None,
                host=self.host,
                path=self.path,
                **self.kwargs,
            )
        return self._async_client

    def create(self) -> None:
        _distance = models.Distance.COSINE
        if self.distance == Distance.l2:
            _distance = models.Distance.EUCLID
        elif self.distance == Distance.max_inner_product:
            _distance = models.Distance.DOT

        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")

            # Configure vectors based on search type
            if self.search_type == SearchType.vector:
                # Maintain backward compatibility with unnamed vectors
                vectors_config = models.VectorParams(size=self.dimensions or 1536, distance=_distance)
            else:
                # Use named vectors for hybrid search
                vectors_config = {
                    self.dense_vector_name: models.VectorParams(size=self.dimensions or 1536, distance=_distance)
                }  # type: ignore

            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vectors_config,
                sparse_vectors_config={self.sparse_vector_name: models.SparseVectorParams()}
                if self.search_type in [SearchType.keyword, SearchType.hybrid]
                else None,
            )

    async def async_create(self) -> None:
        """Create the collection asynchronously."""
        # Collection distance
        _distance = models.Distance.COSINE
        if self.distance == Distance.l2:
            _distance = models.Distance.EUCLID
        elif self.distance == Distance.max_inner_product:
            _distance = models.Distance.DOT

        if not await self.async_exists():
            log_debug(f"Creating collection asynchronously: {self.collection}")

            # Configure vectors based on search type
            if self.search_type == SearchType.vector:
                # Maintain backward compatibility with unnamed vectors
                vectors_config = models.VectorParams(size=self.dimensions or 1536, distance=_distance)
            else:
                # Use named vectors for hybrid search
                vectors_config = {
                    self.dense_vector_name: models.VectorParams(size=self.dimensions or 1536, distance=_distance)
                }  # type: ignore

            await self.async_client.create_collection(
                collection_name=self.collection,
                vectors_config=vectors_config,
                sparse_vectors_config={self.sparse_vector_name: models.SparseVectorParams()}
                if self.search_type in [SearchType.keyword, SearchType.hybrid]
                else None,
            )

    def name_exists(self, name: str) -> bool:
        """
        Validates if a document with the given name exists in the collection.

        Args:
            name (str): The name of the document to check.

        Returns:
            bool: True if a document with the given name exists, False otherwise.
        """
        if self.client:
            scroll_result = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="name", match=models.MatchValue(value=name))]
                ),
                limit=1,
            )
            return len(scroll_result[0]) > 0
        return False

    async def async_name_exists(self, name: str) -> bool:  # type: ignore[override]
        """
        Asynchronously validates if a document with the given name exists in the collection.

        Args:
            name (str): The name of the document to check.

        Returns:
            bool: True if a document with the given name exists, False otherwise.
        """
        if self.async_client:
            scroll_result = await self.async_client.scroll(
                collection_name=self.collection,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="name", match=models.MatchValue(value=name))]
                ),
                limit=1,
            )
            return len(scroll_result[0]) > 0
        return False

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 10,
    ) -> None:
        """
        Insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
            batch_size (int): Batch size for inserting documents
        """
        log_debug(f"Inserting {len(documents)} documents")
        points = []
        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # TODO(v2.0.0): Remove conditional vector naming logic
            if self.use_named_vectors:
                vector = {self.dense_vector_name: document.embedding}
            else:
                vector = document.embedding  # type: ignore

            if self.search_type == SearchType.vector:
                # For vector search, maintain backward compatibility with unnamed vectors
                document.embed(embedder=self.embedder)
                vector = document.embedding  # type: ignore
            else:
                # For other search types, use named vectors
                vector = {}
                if self.search_type in [SearchType.hybrid]:
                    document.embed(embedder=self.embedder)
                    vector[self.dense_vector_name] = document.embedding

                if self.search_type in [SearchType.keyword, SearchType.hybrid]:
                    vector[self.sparse_vector_name] = next(
                        iter(self.sparse_encoder.embed([document.content]))
                    ).as_object()  # type: ignore

            # Create payload with document properties
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
                "content_id": document.content_id,
                "content_hash": content_hash,
            }

            # Add filters as metadata if provided
            if filters:
                # Merge filters with existing metadata
                if "meta_data" not in payload:
                    payload["meta_data"] = {}
                payload["meta_data"].update(filters)  # type: ignore

            points.append(
                models.PointStruct(
                    id=doc_id,
                    vector=vector,  # type: ignore
                    payload=payload,
                )
            )
            log_debug(f"Inserted document: {document.name} ({document.meta_data})")
        if len(points) > 0:
            self.client.upsert(collection_name=self.collection, wait=False, points=points)
        log_debug(f"Upsert {len(points)} documents")

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Insert documents asynchronously.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
        """
        log_debug(f"Inserting {len(documents)} documents asynchronously")

        # Apply batch embedding when needed for vector or hybrid search
        if self.search_type in [SearchType.vector, SearchType.hybrid]:
            if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
                # Use batch embedding when enabled and supported
                try:
                    # Extract content from all documents
                    doc_contents = [doc.content for doc in documents]

                    # Get batch embeddings and usage
                    embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                    # Process documents with pre-computed embeddings
                    for j, doc in enumerate(documents):
                        try:
                            if j < len(embeddings):
                                doc.embedding = embeddings[j]
                                doc.usage = usages[j] if j < len(usages) else None
                        except Exception as e:
                            log_error(f"Error assigning batch embedding to document '{doc.name}': {e}")

                except Exception as e:
                    # Check if this is a rate limit error - don't fall back as it would make things worse
                    error_str = str(e).lower()
                    is_rate_limit = any(
                        phrase in error_str
                        for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                    )

                    if is_rate_limit:
                        log_error(f"Rate limit detected during batch embedding. {e}")
                        raise e
                    else:
                        log_warning(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                        # Fall back to individual embedding
                        for doc in documents:
                            if self.search_type in [SearchType.vector, SearchType.hybrid]:
                                await doc.async_embed(embedder=self.embedder)
            else:
                # Use individual embedding
                for doc in documents:
                    if self.search_type in [SearchType.vector, SearchType.hybrid]:
                        await doc.async_embed(embedder=self.embedder)

        async def process_document(document):
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            if self.search_type == SearchType.vector:
                # For vector search, maintain backward compatibility with unnamed vectors
                vector = document.embedding  # Already embedded above
            else:
                # For other search types, use named vectors
                vector = {}
                if self.search_type in [SearchType.hybrid]:
                    vector[self.dense_vector_name] = document.embedding  # Already embedded above

                if self.search_type in [SearchType.keyword, SearchType.hybrid]:
                    vector[self.sparse_vector_name] = next(
                        iter(self.sparse_encoder.embed([document.content]))
                    ).as_object()  # type: ignore

            if self.search_type in [SearchType.keyword, SearchType.hybrid]:
                vector[self.sparse_vector_name] = next(iter(self.sparse_encoder.embed([document.content]))).as_object()

            # Create payload with document properties
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
                "content_id": document.content_id,
                "content_hash": content_hash,
            }

            # Add filters as metadata if provided
            if filters:
                # Merge filters with existing metadata
                if "meta_data" not in payload:
                    payload["meta_data"] = {}
                payload["meta_data"].update(filters)

            log_debug(f"Inserted document asynchronously: {document.name} ({document.meta_data})")
            return models.PointStruct(  # type: ignore
                id=doc_id,
                vector=vector,  # type: ignore
                payload=payload,
            )

        import asyncio

        # Process all documents in parallel
        points = await asyncio.gather(*[process_document(doc) for doc in documents])

        if len(points) > 0:
            await self.async_client.upsert(collection_name=self.collection, wait=False, points=points)
        log_debug(f"Upserted {len(points)} documents asynchronously")

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_debug("Redirecting the request to insert")
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self.insert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents asynchronously."""
        log_debug("Redirecting the async request to async_insert")
        await self.async_insert(content_hash=content_hash, documents=documents, filters=filters)

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """
        Search for documents in the collection.

        Args:
            query (str): Query to search for
            limit (int): Number of search results to return
            filters (Optional[Dict[str, Any]]): Filters to apply while searching
        """

        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Qdrant. No filters will be applied.")
            filters = None

        formatted_filters = self._format_filters(filters or {})  # type: ignore
        if self.search_type == SearchType.vector:
            results = self._run_vector_search_sync(query, limit, formatted_filters=formatted_filters)  # type: ignore
        elif self.search_type == SearchType.keyword:
            results = self._run_keyword_search_sync(query, limit, formatted_filters=formatted_filters)  # type: ignore
        elif self.search_type == SearchType.hybrid:
            results = self._run_hybrid_search_sync(query, limit, formatted_filters=formatted_filters)  # type: ignore
        else:
            raise ValueError(f"Unsupported search type: {self.search_type}")

        return self._build_search_results(results, query)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Qdrant. No filters will be applied.")
            filters = None

        formatted_filters = self._format_filters(filters or {})  # type: ignore
        if self.search_type == SearchType.vector:
            results = await self._run_vector_search_async(query, limit, formatted_filters=formatted_filters)  # type: ignore
        elif self.search_type == SearchType.keyword:
            results = await self._run_keyword_search_async(query, limit, formatted_filters=formatted_filters)  # type: ignore
        elif self.search_type == SearchType.hybrid:
            results = await self._run_hybrid_search_async(query, limit, formatted_filters=formatted_filters)  # type: ignore
        else:
            raise ValueError(f"Unsupported search type: {self.search_type}")

        return self._build_search_results(results, query)

    def _run_hybrid_search_sync(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        dense_embedding = self.embedder.get_embedding(query)
        sparse_embedding = next(iter(self.sparse_encoder.embed([query]))).as_object()
        call = self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(
                    query=models.SparseVector(**sparse_embedding),  # type: ignore  # type: ignore
                    limit=limit,
                    using=self.sparse_vector_name,
                ),
                models.Prefetch(query=dense_embedding, limit=limit, using=self.dense_vector_name),
            ],
            query=models.FusionQuery(fusion=self.hybrid_fusion_strategy),
            with_vectors=True,
            with_payload=True,
            limit=limit,
            query_filter=formatted_filters,
        )
        return call.points

    def _run_vector_search_sync(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        dense_embedding = self.embedder.get_embedding(query)

        # TODO(v2.0.0): Remove this conditional and always use named vectors
        if self.use_named_vectors:
            call = self.client.query_points(
                collection_name=self.collection,
                query=dense_embedding,
                with_vectors=True,
                with_payload=True,
                limit=limit,
                query_filter=formatted_filters,
                using=self.dense_vector_name,
            )
        else:
            # Backward compatibility mode - use unnamed vector
            call = self.client.query_points(
                collection_name=self.collection,
                query=dense_embedding,
                with_vectors=True,
                with_payload=True,
                limit=limit,
                query_filter=formatted_filters,
            )
        return call.points

    def _run_keyword_search_sync(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        sparse_embedding = next(iter(self.sparse_encoder.embed([query]))).as_object()
        call = self.client.query_points(
            collection_name=self.collection,
            query=models.SparseVector(**sparse_embedding),  # type: ignore
            with_vectors=True,
            with_payload=True,
            limit=limit,
            using=self.sparse_vector_name,
            query_filter=formatted_filters,
        )
        return call.points

    async def _run_vector_search_async(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        dense_embedding = await self.embedder.async_get_embedding(query)

        # TODO(v2.0.0): Remove this conditional and always use named vectors
        if self.use_named_vectors:
            call = await self.async_client.query_points(
                collection_name=self.collection,
                query=dense_embedding,
                with_vectors=True,
                with_payload=True,
                limit=limit,
                query_filter=formatted_filters,
                using=self.dense_vector_name,
            )
        else:
            # Backward compatibility mode - use unnamed vector
            call = await self.async_client.query_points(
                collection_name=self.collection,
                query=dense_embedding,
                with_vectors=True,
                with_payload=True,
                limit=limit,
                query_filter=formatted_filters,
            )
        return call.points

    async def _run_keyword_search_async(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        sparse_embedding = next(iter(self.sparse_encoder.embed([query]))).as_object()
        call = await self.async_client.query_points(
            collection_name=self.collection,
            query=models.SparseVector(**sparse_embedding),  # type: ignore
            with_vectors=True,
            with_payload=True,
            limit=limit,
            using=self.sparse_vector_name,
            query_filter=formatted_filters,
        )
        return call.points

    async def _run_hybrid_search_async(
        self,
        query: str,
        limit: int,
        formatted_filters: Optional[models.Filter],
    ) -> List[models.ScoredPoint]:
        dense_embedding = await self.embedder.async_get_embedding(query)
        sparse_embedding = next(iter(self.sparse_encoder.embed([query]))).as_object()
        call = await self.async_client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(
                    query=models.SparseVector(**sparse_embedding),  # type: ignore  # type: ignore
                    limit=limit,
                    using=self.sparse_vector_name,
                ),
                models.Prefetch(query=dense_embedding, limit=limit, using=self.dense_vector_name),
            ],
            query=models.FusionQuery(fusion=self.hybrid_fusion_strategy),
            with_vectors=True,
            with_payload=True,
            limit=limit,
            query_filter=formatted_filters,
        )
        return call.points

    def _build_search_results(self, results, query: str) -> List[Document]:
        search_results: List[Document] = []

        for result in results:
            if result.payload is None:
                continue
            search_results.append(
                Document(
                    name=result.payload["name"],
                    meta_data=result.payload["meta_data"],
                    content=result.payload["content"],
                    embedder=self.embedder,
                    embedding=result.vector,  # type: ignore
                    usage=result.payload.get("usage"),
                    content_id=result.payload.get("content_id"),
                )
            )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def _format_filters(self, filters: Optional[Dict[str, Any]]) -> Optional[models.Filter]:
        if filters:
            filter_conditions = []
            for key, value in filters.items():
                # If key contains a dot already, assume it's in the correct format
                # Otherwise, assume it's a metadata field and add the prefix
                if "." not in key and not key.startswith("meta_data."):
                    # This is a simple field name, assume it's metadata
                    key = f"meta_data.{key}"

                if isinstance(value, dict):
                    # Handle nested dictionaries
                    for sub_key, sub_value in value.items():
                        filter_conditions.append(
                            models.FieldCondition(key=f"{key}.{sub_key}", match=models.MatchValue(value=sub_value))
                        )
                else:
                    # Handle direct key-value pairs
                    filter_conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))

            if filter_conditions:
                return models.Filter(must=filter_conditions)  # type: ignore

        return None

    def optimize(self) -> None:
        pass

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.collection}")
            self.client.delete_collection(self.collection)

    async def async_drop(self) -> None:
        """Drop the collection asynchronously."""
        if await self.async_exists():
            log_debug(f"Deleting collection asynchronously: {self.collection}")
            await self.async_client.delete_collection(self.collection)

    def exists(self) -> bool:
        """Check if the collection exists."""
        return self.client.collection_exists(collection_name=self.collection)

    async def async_exists(self) -> bool:
        """Check if the collection exists asynchronously."""
        return await self.async_client.collection_exists(collection_name=self.collection)

    def get_count(self) -> int:
        count_result: models.CountResult = self.client.count(collection_name=self.collection, exact=True)
        return count_result.count

    def point_exists(self, id: str) -> bool:
        """Check if a point with the given ID exists in the collection."""
        try:
            log_info(f"Checking if point with ID '{id}' (type: {type(id)}) exists in collection '{self.collection}'")
            points = self.client.retrieve(
                collection_name=self.collection, ids=[id], with_payload=False, with_vectors=False
            )
            log_info(f"Retrieved {len(points)} points for ID '{id}'")
            if len(points) > 0:
                log_info(f"Found point with ID: {points[0].id} (type: {type(points[0].id)})")
            return len(points) > 0
        except Exception as e:
            log_info(f"Error checking if point {id} exists: {e}")
            return False

    def delete(self) -> bool:
        return self.client.delete_collection(collection_name=self.collection)

    def delete_by_id(self, id: str) -> bool:
        try:
            # Check if point exists before deletion
            if not self.point_exists(id):
                log_warning(f"Point with ID {id} does not exist")
                return True

            self.client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=[id]),
                wait=True,  # Wait for the operation to complete
            )
            return True

        except Exception as e:
            log_info(f"Error deleting point with ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete all points that have the specified name in their payload (precise match)."""
        try:
            log_info(f"Attempting to delete all points with name: {name}")

            # Create a filter to find all points with the specified name (precise match)
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="name", match=models.MatchValue(value=name))]
            )

            # First, count how many points will be deleted
            count_result = self.client.count(collection_name=self.collection, count_filter=filter_condition, exact=True)

            if count_result.count == 0:
                log_warning(f"No points found with name: {name}")
                return True

            log_info(f"Found {count_result.count} points to delete with name: {name}")

            # Delete all points matching the filter
            result = self.client.delete(
                collection_name=self.collection,
                points_selector=filter_condition,
                wait=True,  # Wait for the operation to complete
            )

            # Check if the deletion was successful
            if result.status == models.UpdateStatus.COMPLETED:
                log_info(f"Successfully deleted {count_result.count} points with name: {name}")
                return True
            else:
                log_warning(f"Deletion failed for name {name}. Status: {result.status}")
                return False

        except Exception as e:
            log_warning(f"Error deleting points with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete all points where the given metadata is contained in the meta_data payload field."""
        try:
            log_info(f"Attempting to delete all points with metadata: {metadata}")

            # Create filter conditions for each metadata key-value pair
            filter_conditions = []
            for key, value in metadata.items():
                # Use the meta_data prefix since that's how metadata is stored in the payload
                filter_conditions.append(
                    models.FieldCondition(key=f"meta_data.{key}", match=models.MatchValue(value=value))
                )

            # Create a filter that requires ALL metadata conditions to match
            filter_condition = models.Filter(must=filter_conditions)  # type: ignore

            # First, count how many points will be deleted
            count_result = self.client.count(collection_name=self.collection, count_filter=filter_condition, exact=True)

            if count_result.count == 0:
                log_warning(f"No points found with metadata: {metadata}")
                return True

            log_info(f"Found {count_result.count} points to delete with metadata: {metadata}")

            # Delete all points matching the filter
            result = self.client.delete(
                collection_name=self.collection,
                points_selector=filter_condition,
                wait=True,  # Wait for the operation to complete
            )

            # Check if the deletion was successful
            if result.status == models.UpdateStatus.COMPLETED:
                log_info(f"Successfully deleted {count_result.count} points with metadata: {metadata}")
                return True
            else:
                log_warning(f"Deletion failed for metadata {metadata}. Status: {result.status}")
                return False

        except Exception as e:
            log_warning(f"Error deleting points with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete all points that have the specified content_id in their payload."""
        try:
            log_info(f"Attempting to delete all points with content_id: {content_id}")

            # Create a filter to find all points with the specified content_id
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="content_id", match=models.MatchValue(value=content_id))]
            )

            # First, count how many points will be deleted
            count_result = self.client.count(collection_name=self.collection, count_filter=filter_condition, exact=True)

            if count_result.count == 0:
                log_warning(f"No points found with content_id: {content_id}")
                return True

            log_info(f"Found {count_result.count} points to delete with content_id: {content_id}")

            # Delete all points matching the filter
            result = self.client.delete(
                collection_name=self.collection,
                points_selector=filter_condition,
                wait=True,  # Wait for the operation to complete
            )

            # Check if the deletion was successful
            if result.status == models.UpdateStatus.COMPLETED:
                log_info(f"Successfully deleted {count_result.count} points with content_id: {content_id}")
                return True
            else:
                log_warning(f"Deletion failed for content_id {content_id}. Status: {result.status}")
                return False

        except Exception as e:
            log_warning(f"Error deleting points with content_id {content_id}: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a point with the given ID exists in the collection.

        Args:
            id (str): The ID to check.

        Returns:
            bool: True if the point exists, False otherwise.
        """
        try:
            points = self.client.retrieve(
                collection_name=self.collection, ids=[id], with_payload=False, with_vectors=False
            )
            return len(points) > 0
        except Exception as e:
            log_info(f"Error checking if point {id} exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if any points with the given content hash exist in the collection.

        Args:
            content_hash (str): The content hash to check.

        Returns:
            bool: True if points with the content hash exist, False otherwise.
        """
        try:
            # Create a filter to find points with the specified content_hash
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="content_hash", match=models.MatchValue(value=content_hash))]
            )

            # Count how many points match the filter
            count_result = self.client.count(collection_name=self.collection, count_filter=filter_condition, exact=True)
            return count_result.count > 0
        except Exception as e:
            log_info(f"Error checking if content_hash {content_hash} exists: {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete all points that have the specified content_hash in their payload.

        Args:
            content_hash (str): The content hash to delete.

        Returns:
            bool: True if points were deleted successfully, False otherwise.
        """
        try:
            log_info(f"Attempting to delete all points with content_hash: {content_hash}")

            # Create a filter to find all points with the specified content_hash
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="content_hash", match=models.MatchValue(value=content_hash))]
            )

            # First, count how many points will be deleted
            count_result = self.client.count(collection_name=self.collection, count_filter=filter_condition, exact=True)

            if count_result.count == 0:
                log_warning(f"No points found with content_hash: {content_hash}")
                return True

            log_info(f"Found {count_result.count} points to delete with content_hash: {content_hash}")

            # Delete all points matching the filter
            result = self.client.delete(
                collection_name=self.collection,
                points_selector=filter_condition,
                wait=True,  # Wait for the operation to complete
            )

            # Check if the deletion was successful
            if result.status == models.UpdateStatus.COMPLETED:
                log_info(f"Successfully deleted {count_result.count} points with content_hash: {content_hash}")
                return True
            else:
                log_warning(f"Deletion failed for content_hash {content_hash}. Status: {result.status}")
                return False

        except Exception as e:
            log_warning(f"Error deleting points with content_hash {content_hash}: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            if not self.client:
                log_error("Client not initialized")
                return

            # Create filter for content_id
            filter_condition = models.Filter(
                must=[models.FieldCondition(key="content_id", match=models.MatchValue(value=content_id))]
            )

            # Search for points with the given content_id
            search_result = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=filter_condition,
                limit=10000,  # Get all matching points
                with_payload=True,
                with_vectors=False,
            )

            if not search_result[0]:  # search_result is a tuple (points, next_page_offset)
                log_error(f"No documents found with content_id: {content_id}")
                return

            points = search_result[0]
            update_operations = []

            # Prepare update operations for each point
            for point in points:
                point_id = point.id
                current_payload = point.payload or {}

                # Merge existing metadata with new metadata
                updated_payload = current_payload.copy()
                updated_payload.update(metadata)

                if "filters" not in updated_payload:
                    updated_payload["filters"] = {}
                if isinstance(updated_payload["filters"], dict):
                    updated_payload["filters"].update(metadata)
                else:
                    updated_payload["filters"] = metadata

                # Create set payload operation
                update_operations.append(models.SetPayload(payload=updated_payload, points=[point_id]))

            # Execute all updates
            for operation in update_operations:
                self.client.set_payload(
                    collection_name=self.collection, payload=operation.payload, points=operation.points
                )

            log_debug(f"Updated metadata for {len(update_operations)} documents with content_id: {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def close(self) -> None:
        """Close the Qdrant client connections."""
        if self._client is not None:
            try:
                self._client.close()
                log_debug("Qdrant client closed successfully")
            except Exception as e:
                log_debug(f"Error closing Qdrant client: {e}")
            finally:
                self._client = None

    async def async_close(self) -> None:
        """Close the Qdrant client connections asynchronously."""
        if self._async_client is not None:
            try:
                await self._async_client.close()
                log_debug("Async Qdrant client closed successfully")
            except Exception as e:
                log_debug(f"Error closing async Qdrant client: {e}")
            finally:
                self._async_client = None

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]
