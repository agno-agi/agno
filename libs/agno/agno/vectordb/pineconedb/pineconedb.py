import asyncio
from typing import Any, Dict, List, Optional, Union

try:
    from packaging import version
    from pinecone import __version__

    if version.parse(__version__).major >= 6:
        import warnings

        warnings.warn(
            "We do not yet support Pinecone v6.x.x. We are actively working to achieve compatibility. "
            "In the meantime, we recommend using Pinecone v5.4.2 for the best experience. Please run `pip install pinecone==5.4.2`",
            UserWarning,
        )
        raise RuntimeError("Incompatible Pinecone version detected. Execution halted.")

    from pinecone import Pinecone, PodSpec, ServerlessSpec
    from pinecone.config import Config

except ImportError:
    raise ImportError("The `pinecone` package is not installed, please install using `pip install pinecone`.")


from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_warning, logger
from agno.vectordb.base import VectorDb


class PineconeDb(VectorDb):
    """A class representing a Pinecone database.

    Args:
        name (str): The name of the index.
        dimension (int): The dimension of the embeddings.
        spec (Union[Dict, ServerlessSpec, PodSpec]): The index spec.
        metric (Optional[str], optional): The metric used for similarity search. Defaults to "cosine".
        additional_headers (Optional[Dict[str, str]], optional): Additional headers to pass to the Pinecone client. Defaults to {}.
        pool_threads (Optional[int], optional): The number of threads to use for the Pinecone client. Defaults to 1.
        namespace: (Optional[str], optional): The namespace partition within the index that will be used. Defaults to None.
        timeout (Optional[int], optional): The timeout for Pinecone operations. Defaults to None.
        index_api (Optional[Any], optional): The Index API object. Defaults to None.
        api_key (Optional[str], optional): The Pinecone API key. Defaults to None.
        host (Optional[str], optional): The Pinecone host. Defaults to None.
        config (Optional[Config], optional): The Pinecone config. Defaults to None.
        **kwargs: Additional keyword arguments.

    Attributes:
        client (Pinecone): The Pinecone client.
        index: The Pinecone index.
        api_key (Optional[str]): The Pinecone API key.
        host (Optional[str]): The Pinecone host.
        config (Optional[Config]): The Pinecone config.
        additional_headers (Optional[Dict[str, str]]): Additional headers to pass to the Pinecone client.
        pool_threads (Optional[int]): The number of threads to use for the Pinecone client.
        index_api (Optional[Any]): The Index API object.
        name (str): The name of the index.
        dimension (int): The dimension of the embeddings.
        spec (Union[Dict, ServerlessSpec, PodSpec]): The index spec.
        metric (Optional[str]): The metric used for similarity search.
        timeout (Optional[int]): The timeout for Pinecone operations.
        kwargs (Optional[Dict[str, str]]): Additional keyword arguments.
    """

    def __init__(
        self,
        dimension: int,
        spec: Union[Dict, ServerlessSpec, PodSpec],
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        metric: Optional[str] = "cosine",
        additional_headers: Optional[Dict[str, str]] = None,
        pool_threads: Optional[int] = 1,
        namespace: Optional[str] = None,
        timeout: Optional[int] = None,
        index_api: Optional[Any] = None,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        config: Optional[Config] = None,
        use_hybrid_search: bool = False,
        hybrid_alpha: float = 0.5,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        # Validate required parameters
        if dimension is None or dimension <= 0:
            raise ValueError("Dimension must be provided and greater than 0.")
        if spec is None:
            raise ValueError("Spec must be provided for Pinecone index.")

        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            index_name = name or "default_index"
            seed = f"{host or 'pinecone'}#{index_name}#{dimension}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        self._client = None
        self._index = None
        self.api_key: Optional[str] = api_key
        self.host: Optional[str] = host
        self.config: Optional[Config] = config
        self.additional_headers: Dict[str, str] = additional_headers or {}
        self.pool_threads: Optional[int] = pool_threads
        self.namespace: Optional[str] = namespace
        self.index_api: Optional[Any] = index_api
        self.dimension: Optional[int] = dimension
        self.spec: Union[Dict, ServerlessSpec, PodSpec] = spec
        self.metric: Optional[str] = metric
        self.timeout: Optional[int] = timeout
        self.kwargs: Optional[Dict[str, str]] = kwargs
        self.use_hybrid_search: bool = use_hybrid_search
        self.hybrid_alpha: float = hybrid_alpha
        if self.use_hybrid_search:
            try:
                from pinecone_text.sparse import BM25Encoder
            except ImportError:
                raise ImportError(
                    "The `pinecone_text` package is not installed, please install using `pip install pinecone-text`."
                )

            self.sparse_encoder = BM25Encoder().default()

        # Embedder for embedding the document contents
        _embedder = embedder
        if _embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            _embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = _embedder
        self.reranker: Optional[Reranker] = reranker

    @property
    def client(self) -> Pinecone:
        """The Pinecone client.

        Returns:
            Pinecone: The Pinecone client.

        """
        if self._client is None:
            log_debug("Creating Pinecone Client")
            self._client = Pinecone(
                api_key=self.api_key,
                host=self.host,
                config=self.config,
                additional_headers=self.additional_headers,
                pool_threads=self.pool_threads,
                index_api=self.index_api,
                **self.kwargs,
            )
        return self._client

    @property
    def index(self):
        """The Pinecone index.

        Returns:
            Pinecone.Index: The Pinecone index.

        """
        if self._index is None:
            log_debug(f"Connecting to Pinecone Index: {self.name}")
            self._index = self.client.Index(self.name)
        return self._index

    def exists(self) -> bool:
        """Check if the index exists.

        Returns:
            bool: True if the index exists, False otherwise.

        """
        list_indexes = self.client.list_indexes()
        return self.name in list_indexes.names()

    async def async_exists(self) -> bool:
        """Check if the index exists asynchronously."""
        return await asyncio.to_thread(self.exists)

    def create(self) -> None:
        """Create the index if it does not exist."""
        if not self.exists():
            log_debug(f"Creating index: {self.name}")

            if self.use_hybrid_search:
                self.metric = "dotproduct"

            if self.dimension is None:
                raise ValueError("Dimension is not set for this Pinecone index")

            self.client.create_index(
                name=self.name,
                dimension=self.dimension,
                spec=self.spec,
                metric=self.metric if self.metric is not None else "cosine",
                timeout=self.timeout,
            )

    async def async_create(self) -> None:
        """Create the index asynchronously if it does not exist."""
        await asyncio.to_thread(self.create)

    def drop(self) -> None:
        """Delete the index if it exists."""
        if self.exists():
            log_debug(f"Deleting index: {self.name}")
            self.client.delete_index(name=self.name, timeout=self.timeout)

    def name_exists(self, name: str) -> bool:
        """Check if an index with the given name exists.

        Args:
            name (str): The name of the index.

        Returns:
            bool: True if the index exists, False otherwise.

        """
        try:
            self.client.describe_index(name)
            return True
        except Exception:
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if an index with the given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self._upsert(content_hash=content_hash, documents=documents, filters=filters)

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
        batch_size: Optional[int] = None,
        show_progress: bool = False,
    ) -> None:
        """insert documents into the index.

        Args:
            documents (List[Document]): The documents to upsert.
            filters (Optional[Dict[str, Any]], optional): The filters for the upsert. Defaults to None.
            namespace (Optional[str], optional): The namespace for the documents. Defaults to None.
            batch_size (Optional[int], optional): The batch size for upsert. Defaults to None.
            show_progress (bool, optional): Whether to show progress during upsert. Defaults to False.

        """

        vectors = []
        for document in documents:
            document.embed(embedder=self.embedder)
            document.meta_data["text"] = document.content
            # Include name and content_id in metadata
            metadata = document.meta_data.copy()
            if filters:
                metadata.update(filters)

            if document.name:
                metadata["name"] = document.name
            if document.content_id:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            data_to_upsert = {
                "id": document.id,
                "values": document.embedding,
                "metadata": metadata,
            }
            if self.use_hybrid_search:
                data_to_upsert["sparse_values"] = self.sparse_encoder.encode_documents(document.content)
            vectors.append(data_to_upsert)

        self.index.upsert(
            vectors=vectors,
            namespace=namespace or self.namespace,
            batch_size=batch_size,
            show_progress=show_progress,
        )

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
        batch_size: Optional[int] = None,
        show_progress: bool = False,
    ) -> None:
        """Upsert documents into the index asynchronously with batching."""
        if self.content_hash_exists(content_hash):
            await asyncio.to_thread(self._delete_by_content_hash, content_hash)
        if not documents:
            return

        # Pinecone has its own batching mechanism, but we'll add an additional layer
        # to process document embedding in parallel
        _batch_size = batch_size or 100

        # Split documents into batches
        batches = [documents[i : i + _batch_size] for i in range(0, len(documents), _batch_size)]
        log_debug(f"Processing {len(documents)} documents in {len(batches)} batches for upsert")

        # Process each batch in parallel
        async def process_batch(batch_docs):
            return await self._prepare_vectors(batch_docs, content_hash, filters)

        # Run all batches in parallel
        batch_vectors = await asyncio.gather(*[process_batch(batch) for batch in batches])

        # Flatten vectors
        all_vectors = [vector for batch in batch_vectors for vector in batch]

        # Upsert all vectors
        await asyncio.to_thread(
            self._upsert_vectors, all_vectors, namespace or self.namespace, batch_size, show_progress
        )

        log_debug(f"Finished async upsert of {len(documents)} documents")

    async def _prepare_vectors(
        self, documents: List[Document], content_hash: str, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Prepare vectors for upsert."""
        vectors = []

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
                        logger.error(f"Error assigning batch embedding to document '{doc.name}': {e}")

            except Exception as e:
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    logger.error(f"Rate limit detected during batch embedding. {e}")
                    raise e
                else:
                    logger.warning(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

        for doc in documents:
            doc.meta_data["text"] = doc.content
            # Include name and content_id in metadata
            metadata = doc.meta_data.copy()
            if filters:
                metadata.update(filters)

            if doc.name:
                metadata["name"] = doc.name
            if doc.content_id:
                metadata["content_id"] = doc.content_id

            metadata["content_hash"] = content_hash

            data_to_upsert = {
                "id": doc.id,
                "values": doc.embedding,
                "metadata": metadata,
            }
            if self.use_hybrid_search:
                data_to_upsert["sparse_values"] = self.sparse_encoder.encode_documents(doc.content)
            vectors.append(data_to_upsert)
        return vectors

    def _upsert_vectors(self, vectors, namespace, batch_size, show_progress):
        """Upsert vectors to the index."""
        self.index.upsert(
            vectors=vectors,
            namespace=namespace,
            batch_size=batch_size,
            show_progress=show_progress,
        )

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        log_warning("Pinecone does not support insert operations. Redirecting to async_upsert instead.")
        await self.async_upsert(content_hash=content_hash, documents=documents, filters=filters)

    def upsert_available(self) -> bool:
        """Check if upsert operation is available.

        Returns:
            bool: True if upsert is available, False otherwise.

        """
        return True

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_warning("Pinecone does not support insert operations. Redirecting to upsert instead.")
        self.upsert(content_hash=content_hash, documents=documents, filters=filters)

    def _hybrid_scale(self, dense: List[float], sparse: Dict[str, Any], alpha: float):
        """Hybrid vector scaling using a convex combination
        1 is pure semantic search, 0 is pure keyword search
        alpha * dense + (1 - alpha) * sparse

        Args:
            dense: Array of floats representing
            sparse: a dict of `indices` and `values`
            alpha: float between 0 and 1 where 0 == sparse only
                and 1 == dense only
        """
        if alpha < 0 or alpha > 1:
            raise ValueError("Alpha must be between 0 and 1")
        # scale sparse and dense vectors to create hybrid search vecs
        hsparse = {"indices": sparse["indices"], "values": [v * (1 - alpha) for v in sparse["values"]]}
        hdense = [v * alpha for v in dense]
        return hdense, hsparse

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        namespace: Optional[str] = None,
        include_values: Optional[bool] = None,
    ) -> List[Document]:
        """Search for similar documents in the index.

        Args:
            query (str): The query to search for.
            limit (int, optional): The maximum number of results to return. Defaults to 5.
            filters (Optional[Dict[str, Union[str, float, int, bool, List, dict]]], optional): The filter for the search. Defaults to None.
            namespace (Optional[str], optional): The namespace to search in. Defaults to None.
            include_values (Optional[bool], optional): Whether to include values in the search results. Defaults to None.
            include_metadata (Optional[bool], optional): Whether to include metadata in the search results. Defaults to None.

        Returns:
            List[Document]: The list of matching documents.

        """
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in PineconeDB. No filters will be applied.")
            filters = None
        dense_embedding = self.embedder.get_embedding(query)

        if self.use_hybrid_search:
            sparse_embedding = self.sparse_encoder.encode_queries(query)

        if dense_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if self.use_hybrid_search:
            hdense, hsparse = self._hybrid_scale(dense_embedding, sparse_embedding, alpha=self.hybrid_alpha)
            response = self.index.query(
                vector=hdense,
                sparse_vector=hsparse,
                top_k=limit,
                namespace=namespace or self.namespace,
                filter=filters,
                include_values=include_values,
                include_metadata=True,
            )
        else:
            response = self.index.query(
                vector=dense_embedding,
                top_k=limit,
                namespace=namespace or self.namespace,
                filter=filters,
                include_values=include_values,
                include_metadata=True,
            )

        search_results = [
            Document(
                content=(result.metadata.get("text", "") if result.metadata is not None else ""),
                id=result.id,
                embedding=result.values,
                meta_data=result.metadata,
            )
            for result in response.matches
        ]

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)
        return search_results

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        namespace: Optional[str] = None,
        include_values: Optional[bool] = None,
    ) -> List[Document]:
        """Search for similar documents in the index asynchronously."""
        return await asyncio.to_thread(self.search, query, limit, filters, namespace, include_values)

    def optimize(self) -> None:
        """Optimize the index.

        This method can be left empty as Pinecone automatically optimizes indexes.

        """
        pass

    def delete(self, namespace: Optional[str] = None) -> bool:
        """Clear the index.

        Args:
            namespace (Optional[str], optional): The namespace to clear. Defaults to None.

        """
        try:
            self.index.delete(delete_all=True, namespace=namespace)
            return True
        except Exception:
            return False

    async def async_drop(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    def delete_by_id(self, id: str) -> bool:
        """Delete a document by ID."""
        try:
            self.index.delete(ids=[id])
            return True
        except Exception as e:
            log_warning(f"Error deleting document with ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name (stored in metadata)."""
        try:
            # Delete all documents where metadata.name equals the given name
            self.index.delete(filter={"name": {"$eq": name}})
            return True
        except Exception as e:
            log_warning(f"Error deleting documents with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        try:
            # Build filter for metadata matching
            filter_conditions = {}
            for key, value in metadata.items():
                filter_conditions[key] = {"$eq": value}

            self.index.delete(filter=filter_conditions)
            return True
        except Exception as e:
            log_warning(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID (stored in metadata)."""
        try:
            # Delete all documents where metadata.content_id equals the given content_id
            self.index.delete(filter={"content_id": {"$eq": content_id}})
            return True
        except Exception as e:
            log_warning(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    def get_count(self) -> int:
        """Get the count of documents in the index."""
        try:
            # Pinecone doesn't have a direct count method, so we use describe_index_stats
            stats = self.index.describe_index_stats()
            # The stats include total_vector_count which gives us the count
            return stats.total_vector_count
        except Exception as e:
            log_warning(f"Error getting document count: {e}")
            return 0

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the index.

        Args:
            id (str): The ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        try:
            response = self.index.fetch(ids=[id], namespace=self.namespace)
            return len(response.vectors) > 0
        except Exception as e:
            log_warning(f"Error checking if ID {id} exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if documents with the given content hash exist in the index.

        Args:
            content_hash (str): The content hash to check.

        Returns:
            bool: True if documents with the content hash exist, False otherwise.
        """
        try:
            # Use a dummy vector to perform a minimal query with filter
            # We only need to check if any results exist
            if self.dimension is None:
                raise ValueError("Dimension is not set for this Pinecone index")
            dummy_vector = [0.0] * self.dimension
            response = self.index.query(
                vector=dummy_vector,
                top_k=1,
                namespace=self.namespace,
                filter={"content_hash": {"$eq": content_hash}},
                include_metadata=False,
                include_values=False,
            )
            return len(response.matches) > 0
        except Exception as e:
            log_warning(f"Error checking if content_hash {content_hash} exists: {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete documents by content hash (stored in metadata).

        Args:
            content_hash (str): The content hash to delete.

        Returns:
            bool: True if documents were deleted, False otherwise.
        """
        try:
            # Delete all documents where metadata.content_hash equals the given content_hash
            self.index.delete(filter={"content_hash": {"$eq": content_hash}}, namespace=self.namespace)
            return True
        except Exception as e:
            log_warning(f"Error deleting documents with content_hash {content_hash}: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            # Query for vectors with the given content_id
            query_response = self.index.query(
                filter={"content_id": {"$eq": content_id}},
                top_k=10000,  # Get all matching vectors
                include_metadata=True,
                namespace=self.namespace,
            )

            if not query_response.matches:
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Prepare updates for each matching vector
            update_data = []
            for match in query_response.matches:
                vector_id = match.id
                current_metadata = match.metadata or {}

                # Merge existing metadata with new metadata
                updated_metadata = current_metadata.copy()
                updated_metadata.update(metadata)

                if "filters" not in updated_metadata:
                    updated_metadata["filters"] = {}
                if isinstance(updated_metadata["filters"], dict):
                    updated_metadata["filters"].update(metadata)
                else:
                    updated_metadata["filters"] = metadata

                update_data.append({"id": vector_id, "metadata": updated_metadata})

            # Update vectors in batches
            batch_size = 100
            for i in range(0, len(update_data), batch_size):
                batch = update_data[i : i + batch_size]
                self.index.update(vectors=batch, namespace=self.namespace)

            logger.debug(f"Updated metadata for {len(update_data)} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # PineconeDb doesn't use SearchType enum
