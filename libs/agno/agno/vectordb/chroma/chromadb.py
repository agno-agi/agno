import asyncio
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union, cast

try:
    from chromadb import Client as ChromaDbClient
    from chromadb import PersistentClient as PersistentChromaDbClient
    from chromadb.api.client import ClientAPI
    from chromadb.api.models.Collection import Collection
    from chromadb.api.types import QueryResult

except ImportError:
    raise ImportError("The `chromadb` package is not installed. Please install it via `pip install chromadb`.")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType


def reciprocal_rank_fusion(
    ranked_lists: List[List[Tuple[str, float]]],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """
    Combine multiple ranked lists using Reciprocal Rank Fusion (RRF).

    RRF is a simple yet effective method for combining multiple rankings.
    The formula is: RRF(d) = sum(1 / (k + rank_i(d))) for each ranking i

    Args:
        ranked_lists: List of ranked results, each as [(doc_id, score), ...]
        k: RRF constant (default 60, as per original paper by Cormack et al.)

    Returns:
        Fused ranking as [(doc_id, rrf_score), ...] sorted by score descending
    """
    rrf_scores: Dict[str, float] = defaultdict(float)

    for ranked_list in ranked_lists:
        for rank, (doc_id, _) in enumerate(ranked_list, start=1):
            rrf_scores[doc_id] += 1.0 / (k + rank)

    sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results


class ChromaDb(VectorDb):
    """
    ChromaDb class for managing vector operations with ChromaDB.

    Args:
        collection: The name of the ChromaDB collection. If not provided, derived from 'name'.
        name: Name of the vector database. Also used as collection name if 'collection' is not provided.
        description: Description of the vector database.
        id: Unique identifier for this vector database instance.
        embedder: The embedder to use when embedding the document contents.
        distance: The distance metric to use when searching for documents.
        path: The path to store the ChromaDB data (for persistent client).
        persistent_client: Whether to use a persistent client.
        search_type: The search type to use when searching for documents.
            - SearchType.vector: Pure vector similarity search (default)
            - SearchType.keyword: Keyword-based search using document content
            - SearchType.hybrid: Combines vector + FTS with Reciprocal Rank Fusion
        hybrid_rrf_k: RRF (Reciprocal Rank Fusion) constant for hybrid search.
            Controls ranking smoothness - higher values give more weight to lower-ranked
            results, lower values make top results more dominant. Default is 60
            (per original RRF paper by Cormack et al.).
        reranker: The reranker to use when reranking documents.
        **kwargs: Additional arguments to pass to the ChromaDB client.
    """

    def __init__(
        self,
        collection: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        path: str = "tmp/chromadb",
        persistent_client: bool = False,
        search_type: SearchType = SearchType.vector,
        hybrid_rrf_k: int = 60,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        # Derive collection from name if not provided
        if collection is None:
            if name is not None:
                # Sanitize name: lowercase and replace spaces with underscores
                collection = name.lower().replace(" ", "_")
            else:
                raise ValueError("Either 'collection' or 'name' must be provided.")

        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            seed = f"{path}#{collection}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        # Collection attributes
        self.collection_name: str = collection
        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        # Distance metric
        self.distance: Distance = distance

        # Chroma client instance
        self._client: Optional[ClientAPI] = None

        # Chroma collection instance
        self._collection: Optional[Collection] = None

        # Persistent Chroma client instance
        self.persistent_client: bool = persistent_client
        self.path: str = path

        # Search type configuration
        self.search_type: SearchType = search_type
        self.hybrid_rrf_k: int = hybrid_rrf_k

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Chroma client kwargs
        self.kwargs = kwargs

    def _flatten_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Union[str, int, float, bool]]:
        """
        Flatten nested metadata to ChromaDB-compatible format.

        Args:
            metadata: Dictionary that may contain nested structures

        Returns:
            Flattened dictionary with only primitive values
        """
        flattened: Dict[str, Any] = {}

        def _flatten_recursive(obj: Any, prefix: str = "") -> None:
            if isinstance(obj, dict):
                if len(obj) == 0:
                    # Handle empty dictionaries by converting to JSON string
                    flattened[prefix] = json.dumps(obj)
                else:
                    for key, value in obj.items():
                        new_key = f"{prefix}.{key}" if prefix else key
                        _flatten_recursive(value, new_key)
            elif isinstance(obj, (list, tuple)):
                # Convert lists/tuples to JSON strings
                flattened[prefix] = json.dumps(obj)
            elif isinstance(obj, (str, int, float, bool)) or obj is None:
                if obj is not None:  # ChromaDB doesn't accept None values
                    flattened[prefix] = obj
            else:
                # Convert other complex types to JSON strings
                try:
                    flattened[prefix] = json.dumps(obj)
                except (TypeError, ValueError):
                    # If it can't be serialized, convert to string
                    flattened[prefix] = str(obj)

        _flatten_recursive(metadata)
        return flattened

    @property
    def client(self) -> ClientAPI:
        if self._client is None:
            if not self.persistent_client:
                log_debug("Creating Chroma Client")
                self._client = ChromaDbClient(
                    **self.kwargs,
                )
            elif self.persistent_client:
                log_debug("Creating Persistent Chroma Client")
                self._client = PersistentChromaDbClient(
                    path=self.path,
                    **self.kwargs,
                )
        return self._client

    def create(self) -> None:
        """Create the collection in ChromaDb."""
        if self.exists():
            log_debug(f"Collection already exists: {self.collection_name}")
            self._collection = self.client.get_collection(name=self.collection_name)
        else:
            log_debug(f"Creating collection: {self.collection_name}")
            self._collection = self.client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": self.distance.value}
            )

    async def async_create(self) -> None:
        """Create the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection.
        Args:
            name (str): Name of the document to check.
        Returns:
            bool: True if document exists, False otherwise."""
        if not self.client:
            logger.warning("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)
            result = collection.get(where=cast(Any, {"name": {"$eq": name}}), limit=1)
            return len(result.get("ids", [])) > 0
        except Exception as e:
            logger.error(f"Error checking name existence: {e}")
        return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the collection.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to merge with document metadata
        """
        log_info(f"Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            # Flatten metadata for ChromaDB compatibility
            flattened_metadata = self._flatten_metadata(metadata)

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(flattened_metadata)
            log_debug(f"Prepared document: {document.id} | {document.name} | {flattened_metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.add(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents asynchronously by running in a thread."""
        log_info(f"Async Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

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
            try:
                embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
                await asyncio.gather(*embed_tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error processing document: {e}")

        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            # Flatten metadata for ChromaDB compatibility
            flattened_metadata = self._flatten_metadata(metadata)

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(flattened_metadata)
            log_debug(f"Prepared document: {document.id} | {document.name} | {flattened_metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.add(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    def upsert_available(self) -> bool:
        """Check if upsert is available in ChromaDB."""
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        try:
            if self.content_hash_exists(content_hash):
                self._delete_by_content_hash(content_hash)
            self._upsert(content_hash, documents, filters)
        except Exception as e:
            logger.error(f"Error upserting documents by content hash: {e}")
            raise

    def _upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_info(f"Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            # Flatten metadata for ChromaDB compatibility
            flattened_metadata = self._flatten_metadata(metadata)

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(flattened_metadata)
            log_debug(f"Upserted document: {document.id} | {document.name} | {flattened_metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.upsert(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def _async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_info(f"Async Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

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

        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            # Flatten metadata for ChromaDB compatibility
            flattened_metadata = self._flatten_metadata(metadata)

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(flattened_metadata)
            log_debug(f"Upserted document: {document.id} | {document.name} | {flattened_metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.upsert(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        try:
            if self.content_hash_exists(content_hash):
                self._delete_by_content_hash(content_hash)
            await self._async_upsert(content_hash, documents, filters)
        except Exception as e:
            logger.error(f"Error upserting documents by content hash: {e}")
            raise

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Search the collection for a query.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Union[Dict[str, Any], List[FilterExpr]]]): Filters to apply while searching.
                Supports ChromaDB's filtering operators:
                - $eq, $ne: Equality/Inequality
                - $gt, $gte, $lt, $lte: Numeric comparisons
                - $in, $nin: List inclusion/exclusion
                - $and, $or: Logical operators
        Returns:
            List[Document]: List of search results.
        """
        if isinstance(filters, list):
            log_warning("Filter Expressions are not yet supported in ChromaDB. No filters will be applied.")
            filters = None

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        # Route to appropriate search method based on search_type
        if self.search_type == SearchType.vector:
            search_results = self._vector_search(query, limit, filters)
        elif self.search_type == SearchType.keyword:
            search_results = self._keyword_search(query, limit, filters)
        elif self.search_type == SearchType.hybrid:
            search_results = self._hybrid_search(query, limit, filters)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

        if self.reranker and search_results:
            try:
                search_results = self.reranker.rerank(query=query, documents=search_results)
            except Exception as e:
                log_warning(f"Reranker failed, returning unranked results: {e}")

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def _vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Perform pure vector similarity search.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.

        Returns:
            List[Document]: List of search results.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        result: QueryResult = self._collection.query(
            query_embeddings=query_embedding,
            n_results=limit,
            where=where_filter,
            include=["metadatas", "documents", "embeddings", "distances", "uris"],
        )

        return self._build_search_results(result)

    def _keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Perform keyword-based search using document content filtering.

        This uses ChromaDB's where_document filter with $contains operator
        for basic full-text search functionality.

        Args:
            query (str): Query to search for (keywords to match in document content).
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.

        Returns:
            List[Document]: List of search results.
        """
        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        # Get first significant word for $contains filter
        query_words = query.split()
        if not query_words:
            return []

        # Use where_document to filter by document content
        where_document: Dict[str, Any] = {"$contains": query_words[0]}

        try:
            # Get documents matching the keyword filter
            result = self._collection.get(
                where=where_filter,
                where_document=cast(Any, where_document),
                limit=limit,
                include=["metadatas", "documents", "embeddings"],
            )

            return self._build_get_results(cast(Dict[str, Any], result), query)
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []

    def _hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Perform hybrid search combining vector similarity with full-text search using RRF.

        This method combines:
        1. Dense vector similarity search (semantic search)
        2. Full-text search (keyword/lexical search)

        Results are fused using Reciprocal Rank Fusion (RRF) for optimal ranking.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.

        Returns:
            List[Document]: List of search results with RRF-fused ranking.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        # Fetch more candidates than needed for better fusion
        fetch_k = min(limit * 3, 100)

        def dense_vector_similarity_search() -> List[Tuple[str, float]]:
            """Dense vector similarity search."""
            try:
                results = self._collection.query(  # type: ignore
                    query_embeddings=query_embedding,
                    n_results=fetch_k,
                    where=where_filter,
                    include=["documents", "metadatas", "distances"],
                )

                ranked: List[Tuple[str, float]] = []
                if results.get("ids") and results["ids"][0]:
                    for i, doc_id in enumerate(results["ids"][0]):
                        distance = results["distances"][0][i] if results.get("distances") else 0  # type: ignore
                        # Convert distance to similarity score (lower distance = higher score)
                        score = 1.0 / (1.0 + distance)
                        ranked.append((doc_id, score))
                return ranked
            except Exception as e:
                log_error(f"Error in vector search component: {e}")
                return []

        def fts_search() -> List[Tuple[str, float]]:
            """Full-text search using ChromaDB's where_document filter."""
            try:
                query_words = query.split()
                if not query_words:
                    return []

                # Use first word for $contains filter
                fts_where_document: Dict[str, Any] = {"$contains": query_words[0]}

                results = self._collection.query(  # type: ignore
                    query_embeddings=query_embedding,
                    n_results=fetch_k,
                    where=where_filter,
                    where_document=cast(Any, fts_where_document),
                    include=["documents", "metadatas", "distances"],
                )

                ranked: List[Tuple[str, float]] = []
                if results.get("ids") and results["ids"][0]:
                    for i, doc_id in enumerate(results["ids"][0]):
                        # Score based on term overlap (simple BM25-like scoring)
                        doc = results["documents"][0][i] if results.get("documents") else ""  # type: ignore
                        query_terms = set(query.lower().split())
                        doc_terms = set(doc.lower().split()) if doc else set()
                        overlap = len(query_terms & doc_terms)
                        score = overlap / max(len(query_terms), 1)
                        ranked.append((doc_id, score))

                # Sort by score descending
                ranked.sort(key=lambda x: x[1], reverse=True)
                return ranked
            except Exception as e:
                log_error(f"Error in FTS search component: {e}")
                return []

        # Execute searches in parallel for better performance
        with ThreadPoolExecutor(max_workers=2) as executor:
            vector_future = executor.submit(dense_vector_similarity_search)
            fts_future = executor.submit(fts_search)

            vector_results = vector_future.result()
            fts_results = fts_future.result()

        # Apply RRF fusion
        fused_ranking = reciprocal_rank_fusion(
            [vector_results, fts_results],
            k=self.hybrid_rrf_k,
        )

        # Get top IDs from fused ranking
        top_ids = [doc_id for doc_id, _ in fused_ranking[:limit]]

        if not top_ids:
            return []

        # Fetch full document data for top results
        try:
            full_results = self._collection.get(
                ids=top_ids,
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception as e:
            log_error(f"Error fetching full results: {e}")
            return []

        # Build lookup dict for results
        doc_lookup: Dict[str, Dict[str, Any]] = {}
        result_ids = full_results.get("ids", [])
        result_docs = full_results.get("documents")
        result_metas = full_results.get("metadatas")
        result_embeds = full_results.get("embeddings")

        for i, doc_id in enumerate(result_ids if result_ids is not None else []):
            doc_lookup[doc_id] = {
                "document": result_docs[i] if result_docs is not None and i < len(result_docs) else None,
                "metadata": result_metas[i] if result_metas is not None and i < len(result_metas) else None,
                "embedding": result_embeds[i] if result_embeds is not None and i < len(result_embeds) else None,
            }

        # Build final results in fused ranking order
        search_results: List[Document] = []
        rrf_scores = dict(fused_ranking)

        for doc_id in top_ids:
            if doc_id not in doc_lookup:
                continue

            doc_data = doc_lookup[doc_id]
            doc_metadata = dict(doc_data["metadata"]) if doc_data["metadata"] else {}

            # Add RRF score to metadata
            doc_metadata["rrf_score"] = rrf_scores.get(doc_id, 0.0)

            # Extract the fields we added to metadata
            name_val = doc_metadata.pop("name", None)
            content_id_val = doc_metadata.pop("content_id", None)

            # Convert types to match Document constructor expectations
            name = str(name_val) if name_val is not None and not isinstance(name_val, str) else name_val
            content_id = (
                str(content_id_val)
                if content_id_val is not None and not isinstance(content_id_val, str)
                else content_id_val
            )
            content = str(doc_data["document"]) if doc_data["document"] is not None else ""

            # Process embedding
            embedding = None
            if doc_data["embedding"] is not None:
                embed_data = doc_data["embedding"]
                if hasattr(embed_data, "tolist") and callable(getattr(embed_data, "tolist", None)):
                    try:
                        embedding = list(cast(Any, embed_data).tolist())
                    except (AttributeError, TypeError):
                        embedding = list(embed_data) if isinstance(embed_data, (list, tuple)) else None
                elif isinstance(embed_data, (list, tuple)):
                    embedding = [float(x) for x in embed_data if isinstance(x, (int, float))]

            search_results.append(
                Document(
                    id=doc_id,
                    name=name,
                    meta_data=doc_metadata,
                    content=content,
                    embedding=embedding,
                    content_id=content_id,
                )
            )

        return search_results

    def _build_search_results(self, result: QueryResult) -> List[Document]:
        """Build Document list from ChromaDB QueryResult.

        Args:
            result: The QueryResult from ChromaDB query.

        Returns:
            List[Document]: List of Document objects.
        """
        search_results: List[Document] = []

        ids_list = result.get("ids", [[]])  # type: ignore
        metadata_list = result.get("metadatas", [[{}]])  # type: ignore
        documents_list = result.get("documents", [[]])  # type: ignore
        embeddings_list = result.get("embeddings")  # type: ignore
        distances_list = result.get("distances", [[]])  # type: ignore

        # Check if we have valid results - handle numpy arrays carefully
        if ids_list is None or len(ids_list) == 0:
            return search_results
        if metadata_list is None or len(metadata_list) == 0:
            return search_results
        if documents_list is None or len(documents_list) == 0:
            return search_results
        if distances_list is None or len(distances_list) == 0:
            return search_results

        ids = ids_list[0]
        metadata = [dict(m) if m else {} for m in metadata_list[0]]  # Convert to mutable dicts
        documents = documents_list[0]

        # Handle embeddings - may be None or numpy array
        embeddings_raw: Any = []
        if embeddings_list is not None:
            try:
                if len(embeddings_list) > 0:
                    embeddings_raw = embeddings_list[0]
            except (TypeError, ValueError):
                # numpy array truth value issue - try direct access
                try:
                    embeddings_raw = embeddings_list[0]
                except Exception:
                    embeddings_raw = []

        embeddings = []
        for e in embeddings_raw:
            if hasattr(e, "tolist") and callable(getattr(e, "tolist", None)):
                try:
                    embeddings.append(list(cast(Any, e).tolist()))
                except (AttributeError, TypeError):
                    embeddings.append(list(e) if isinstance(e, (list, tuple)) else [])
            elif isinstance(e, (list, tuple)):
                embeddings.append([float(x) for x in e if isinstance(x, (int, float))])
            elif isinstance(e, (int, float)):
                embeddings.append([float(e)])
            else:
                embeddings.append([])

        distances = distances_list[0] if len(distances_list) > 0 else []

        for idx, distance in enumerate(distances):
            if idx < len(metadata):
                metadata[idx]["distances"] = distance

        try:
            for idx, (id_, doc_metadata, document) in enumerate(zip(ids, metadata, documents)):
                # Extract the fields we added to metadata
                name_val = doc_metadata.pop("name", None)
                content_id_val = doc_metadata.pop("content_id", None)

                # Convert types to match Document constructor expectations
                name = str(name_val) if name_val is not None and not isinstance(name_val, str) else name_val
                content_id = (
                    str(content_id_val)
                    if content_id_val is not None and not isinstance(content_id_val, str)
                    else content_id_val
                )
                content = str(document) if document is not None else ""
                embedding = embeddings[idx] if idx < len(embeddings) else None

                search_results.append(
                    Document(
                        id=id_,
                        name=name,
                        meta_data=doc_metadata,
                        content=content,
                        embedding=embedding,
                        content_id=content_id,
                    )
                )
        except Exception as e:
            log_error(f"Error building search results: {e}")

        return search_results

    def _build_get_results(self, result: Dict[str, Any], query: str = "") -> List[Document]:
        """Build Document list from ChromaDB GetResult.

        Args:
            result: The GetResult from ChromaDB get.
            query: The original query for scoring.

        Returns:
            List[Document]: List of Document objects.
        """
        search_results: List[Document] = []

        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])
        documents = result.get("documents", [])
        embeddings_raw = result.get("embeddings")

        # Check ids safely (may be numpy array)
        if ids is None:
            return search_results
        try:
            if len(ids) == 0:
                return search_results
        except (TypeError, ValueError):
            return search_results

        embeddings = []
        # Handle embeddings - may be None or numpy array
        if embeddings_raw is not None:
            try:
                for e in embeddings_raw:
                    if hasattr(e, "tolist") and callable(getattr(e, "tolist", None)):
                        try:
                            embeddings.append(list(cast(Any, e).tolist()))
                        except (AttributeError, TypeError):
                            embeddings.append(list(e) if isinstance(e, (list, tuple)) else [])
                    elif isinstance(e, (list, tuple)):
                        embeddings.append([float(x) for x in e if isinstance(x, (int, float))])
                    elif isinstance(e, (int, float)):
                        embeddings.append([float(e)])
                    else:
                        embeddings.append([])
            except (TypeError, ValueError):
                # numpy array iteration issue
                embeddings = []

        try:
            for idx, id_ in enumerate(ids):
                doc_metadata = dict(metadatas[idx]) if metadatas and idx < len(metadatas) and metadatas[idx] else {}
                document = documents[idx] if documents and idx < len(documents) else ""

                # Calculate simple keyword score if query provided
                if query and document:
                    query_terms = set(query.lower().split())
                    doc_terms = set(document.lower().split())
                    overlap = len(query_terms & doc_terms)
                    doc_metadata["keyword_score"] = overlap / max(len(query_terms), 1)

                # Extract the fields we added to metadata
                name_val = doc_metadata.pop("name", None)
                content_id_val = doc_metadata.pop("content_id", None)

                # Convert types to match Document constructor expectations
                name = str(name_val) if name_val is not None and not isinstance(name_val, str) else name_val
                content_id = (
                    str(content_id_val)
                    if content_id_val is not None and not isinstance(content_id_val, str)
                    else content_id_val
                )
                content = str(document) if document is not None else ""
                embedding = embeddings[idx] if idx < len(embeddings) else None

                search_results.append(
                    Document(
                        id=id_,
                        name=name,
                        meta_data=doc_metadata,
                        content=content,
                        embedding=embedding,
                        content_id=content_id,
                    )
                )
        except Exception as e:
            log_error(f"Error building get results: {e}")

        return search_results

    def _convert_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simple filters to ChromaDB's filter format.

        Handles conversion of simple key-value filters to ChromaDB's operator format
        when needed.
        """
        if not filters:
            return {}

        # If filters already use ChromaDB operators ($eq, $ne, etc.), return as is
        if any(key.startswith("$") for key in filters.keys()):
            return filters

        # Convert simple key-value pairs to ChromaDB's format
        converted = {}
        for key, value in filters.items():
            if isinstance(value, (list, tuple)):
                # Convert lists to $in operator
                converted[key] = {"$in": list(value)}
            else:
                # Convert simple equality to $eq
                converted[key] = {"$eq": value}

        return converted

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        """Delete the collection."""
        if self.exists():
            log_debug(f"Deleting collection: {self.collection_name}")
            self.client.delete_collection(name=self.collection_name)

    async def async_drop(self) -> None:
        """Drop the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """Check if the collection exists."""
        try:
            self.client.get_collection(name=self.collection_name)
            return True
        except Exception as e:
            log_debug(f"Collection does not exist: {e}")
        return False

    async def async_exists(self) -> bool:
        """Check if collection exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        """Get the count of documents in the collection."""
        if self.exists():
            try:
                collection: Collection = self.client.get_collection(name=self.collection_name)
                return collection.count()
            except Exception as e:
                logger.error(f"Error getting count: {e}")
        return 0

    def optimize(self) -> None:
        raise NotImplementedError

    def delete(self) -> bool:
        try:
            self.client.delete_collection(name=self.collection_name)
            return True
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete document by ID."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Check if document exists
            if not self.id_exists(id):
                log_info(f"Document with ID '{id}' not found")
                return False

            # Delete the document
            collection.delete(ids=[id])
            log_info(f"Deleted document with ID '{id}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID '{id}': {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given name
            result = collection.get(where=cast(Any, {"name": {"$eq": name}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with name '{name}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with name '{name}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name '{name}': {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Build where clause for metadata filtering
            where_clause = {}
            for key, value in metadata.items():
                where_clause[key] = {"$eq": value}

            # Find all documents with the matching metadata
            result = collection.get(where=cast(Any, where_clause))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with metadata '{metadata}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with metadata '{metadata}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata '{metadata}': {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given content_id
            result = collection.get(where=cast(Any, {"content_id": {"$eq": content_id}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with content_id '{content_id}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with content_id '{content_id}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_id '{content_id}': {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete documents by content hash."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given content_hash
            result = collection.get(where=cast(Any, {"content_hash": {"$eq": content_hash}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with content_hash '{content_hash}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with content_hash '{content_hash}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_hash '{content_hash}': {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the collection.

        Args:
            id (str): The document ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)
            # Try to get the document by ID
            result = collection.get(ids=[id])
            found_ids = result.get("ids", [])

            # Return True if the document was found
            return len(found_ids) > 0
        except Exception as e:
            logger.error(f"Error checking if ID '{id}' exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if documents with the given content hash exist."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Try to query for documents with the given content_hash
            try:
                result = collection.get(where=cast(Any, {"content_hash": {"$eq": content_hash}}))
                # Safely extract ids from result
                if hasattr(result, "get") and callable(result.get):
                    found_ids = result.get("ids", [])
                elif hasattr(result, "__getitem__") and "ids" in result:
                    found_ids = result["ids"]
                else:
                    found_ids = []

                # Return True if any documents were found
                if isinstance(found_ids, (list, tuple)):
                    return len(found_ids) > 0
                elif isinstance(found_ids, int):
                    # Some ChromaDB versions might return a count instead of a list
                    return found_ids > 0
                else:
                    return False

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    # Known issue with ChromaDB 0.5.0 - internal bug
                    # As a workaround, assume content doesn't exist to allow processing to continue
                    logger.warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Assuming content_hash '{content_hash}' does not exist."
                    )
                    return False
                else:
                    raise te

        except Exception as e:
            logger.error(f"Error checking if content_hash '{content_hash}' exists: {e}")
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
                logger.error("Client not initialized")
                return

            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find documents with the given content_id
            try:
                result = collection.get(where=cast(Any, {"content_id": {"$eq": content_id}}))

                # Extract IDs and current metadata
                if hasattr(result, "get") and callable(result.get):
                    ids = result.get("ids", [])
                    current_metadatas = result.get("metadatas", [])
                elif hasattr(result, "__getitem__"):
                    ids = result.get("ids", []) if "ids" in result else []
                    current_metadatas = result.get("metadatas", []) if "metadatas" in result else []
                else:
                    ids = []
                    current_metadatas = []

                if not ids:
                    log_debug(f"No documents found with content_id: {content_id}")
                    return

                # Flatten the new metadata first
                flattened_new_metadata = self._flatten_metadata(metadata)

                # Merge metadata for each document
                updated_metadatas = []
                for i, current_meta in enumerate(current_metadatas or []):
                    if current_meta is None:
                        meta_dict: Dict[str, Any] = {}
                    else:
                        meta_dict = dict(current_meta)  # Convert Mapping to dict

                    # Update with flattened metadata
                    meta_dict.update(flattened_new_metadata)
                    updated_metadatas.append(meta_dict)

                # Convert to the expected type for ChromaDB
                chroma_metadatas = cast(List[Mapping[str, Union[str, int, float, bool]]], updated_metadatas)
                chroma_metadatas = [{k: v for k, v in m.items() if k and v} for m in chroma_metadatas]
                collection.update(ids=ids, metadatas=chroma_metadatas)  # type: ignore
                log_debug(f"Updated metadata for {len(ids)} documents with content_id: {content_id}")

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    log_warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Cannot update metadata for content_id '{content_id}'."
                    )
                    return
                else:
                    raise te

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]
