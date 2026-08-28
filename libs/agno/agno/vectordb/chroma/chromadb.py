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
from agno.vectordb.base import (
    VectorDb,
    aembed_before_replace,
    embed_before_replace,
    is_rate_limit_error,
    raise_embedding_failures,
)
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

# Stamped on every per-user collection. Unscoped reads and ``drop`` match on it rather
# than on the ``{collection_name}__`` prefix, which a sibling knowledge base can share.
BASE_COLLECTION_METADATA_KEY = "agno_base_collection"


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
        batch_size: Maximum number of documents per batch operation. If not provided,
            automatically detects ChromaDB's maximum batch size limit.
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
        batch_size: Optional[int] = None,
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

        # Chroma collection instance for the base/unscoped path
        self._collection: Optional[Collection] = None

        # Per-user collections, keyed by resolved collection name
        self._user_collections: Dict[str, Collection] = {}

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

        # Batch size for ChromaDB operations
        self._batch_size: Optional[int] = batch_size

    # One collection per user, ``{collection_name}__{user_id}``. ``None`` maps to the
    # base collection, which stays the shared bucket so existing deployments keep working.

    def _sanitize_user_id_for_collection(self, user_id: str) -> str:
        """Return the Chroma-safe name component for an owner.

        Always a hash, never the raw id. Chroma names are 3-63 chars of alphanumerics plus
        ``_`` / ``.`` / ``-``, so an id that does not fit has to be hashed anyway — and mixing
        the two schemes would let one owner land in another's collection: a hash digest is
        itself a valid verbatim name, so an owner who picks ``md5(victim)[:16]`` as their id
        resolves to the victim's collection and gets read, write and delete on it. Hashing
        unconditionally leaves a single namespace with no verbatim names to collide with.
        """
        return md5(user_id.encode("utf-8")).hexdigest()[:16]

    # Chroma rejects a collection name outside 3-512 chars, so the base has to leave room
    # for the ``__`` separator and the 16-char owner digest.
    _CHROMA_MAX_NAME_LEN = 512
    _OWNER_SUFFIX_LEN = 2 + 16  # "__" + md5[:16]

    def _collection_name_for(self, user_id: Optional[str]) -> str:
        """Resolve the physical collection name for a scope.

        ``None`` is the base collection; every other value, ``""`` included, is an owner
        and gets its own.

        A base name long enough to push the owner suffix past Chroma's limit is itself
        digested, so a scoped operation still resolves to a legal name instead of failing
        on every call. Unscoped access keeps the base name untouched.
        """
        if user_id is None:
            return self.collection_name
        base = self.collection_name
        if len(base) + self._OWNER_SUFFIX_LEN > self._CHROMA_MAX_NAME_LEN:
            # Keep a readable prefix so the collection is still recognisable, and fold the
            # whole base in so two long names cannot collide on their shared prefix.
            digest = md5(base.encode("utf-8")).hexdigest()[:16]
            keep = self._CHROMA_MAX_NAME_LEN - self._OWNER_SUFFIX_LEN - len(digest) - 1
            base = f"{base[:keep]}_{digest}"
        return f"{base}__{self._sanitize_user_id_for_collection(user_id)}"

    def _get_or_create_collection(self, user_id: Optional[str]) -> Collection:
        """Resolve, cache and if needed create the collection for an owner scope."""
        name = self._collection_name_for(user_id)
        # The base collection stays on ``self._collection`` for callers that read it directly
        if name == self.collection_name and self._collection is not None:
            return self._collection
        cached = self._user_collections.get(name)
        if cached is not None:
            return cached

        metadata: Dict[str, Any] = {"hnsw:space": self.distance.value}
        if name != self.collection_name:
            metadata[BASE_COLLECTION_METADATA_KEY] = self.collection_name
        collection = self.client.get_or_create_collection(name=name, metadata=metadata)
        if name == self.collection_name:
            self._collection = collection
        else:
            self._user_collections[name] = collection
        return collection

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

    @property
    def batch_size(self) -> int:
        """Get the batch size for ChromaDB operations.

        Returns user-provided batch_size if set, otherwise auto-detects ChromaDB's
        maximum batch size limit based on SQLite's MAX_VARIABLE_NUMBER constraint.

        Returns:
            int: Batch size for operations

        Note:
            - User-provided value takes precedence over auto-detection
            - Auto-detected value is cached after first calculation
            - Falls back to 100 if auto-detection fails
            - Eg: typical values: ~5461 on standard systems, ~41666 on systems with higher limits
        """
        if self._batch_size is None:
            try:
                max_size = self.client.get_max_batch_size()
                self._batch_size = max_size
                log_debug(f"ChromaDB max batch size: {max_size}")
            except Exception as e:
                # Fallback to conservative value if query fails
                log_warning(f"Could not query ChromaDB max batch size. Using fallback: 100: {str(e)}")
                self._batch_size = 100
        return self._batch_size

    def _batch_operation(
        self,
        ids: List[str],
        embeddings: List,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        operation_name: str,
        operation_func: Any,
    ) -> None:
        """Execute a batched ChromaDB operation to respect batch size limits."""
        num_documents = len(documents)
        if num_documents == 0:
            return

        batch_size = self.batch_size
        total_batches = (num_documents + batch_size - 1) // batch_size

        for i in range(0, num_documents, batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]
            batch_metadata = metadatas[i : i + batch_size]

            operation_func(
                ids=batch_ids,
                embeddings=batch_embeddings,
                documents=batch_docs,
                metadatas=batch_metadata,
            )

            if total_batches > 1:
                batch_num = (i // batch_size) + 1
                log_debug(
                    f"{operation_name.capitalize()} batch {batch_num}/{total_batches} ({len(batch_ids)} documents)"
                )

        log_debug(f"Committed {num_documents} documents")

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
        """Check if a document with a given name exists in any collection this knowledge base owns.
        Args:
            name (str): Name of the document to check.
        Returns:
            bool: True if document exists, False otherwise."""
        if not self.client:
            logger.warning("Client not initialized")
            return False

        try:
            for coll in self._all_owner_collections():
                try:
                    if coll.get(where=cast(Any, {"name": {"$eq": name}}), limit=1).get("ids", []):
                        return True
                except Exception:
                    log_debug(f"Could not check name '{name}' in collection {coll.name!r}")
        except Exception:
            logger.exception("Error checking name existence")
        return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents into the collection.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to merge with document metadata
            user_id (Optional[str]): Owner to route the write to. ``None`` writes to the
                base collection, the shared bucket scoped searches also read.
        """
        log_info(f"Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        target_collection = self._get_or_create_collection(user_id)

        id_counts: Dict[str, int] = {}
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # ChromaDB requires unique IDs within a batch — deduplicate collisions
            # from documents with identical content (e.g., empty pages from PDF parsing)
            if doc_id in id_counts:
                id_counts[doc_id] += 1
                doc_id = md5(f"{doc_id}_{id_counts[doc_id]}".encode()).hexdigest()
            else:
                id_counts[doc_id] = 0

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

        self._batch_operation(
            ids=ids,
            embeddings=docs_embeddings,
            documents=docs,
            metadatas=docs_metadata,
            operation_name="insert",
            operation_func=target_collection.add,
        )

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents asynchronously by running in a thread."""
        log_info(f"Async Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        target_collection = self._get_or_create_collection(user_id)

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
                    except Exception:
                        logger.exception(f"Error assigning batch embedding to document '{doc.name}'")

            except Exception as e:
                # A throttle must not fall back to per-item calls, which would throttle harder.
                is_rate_limit = is_rate_limit_error(e)

                if is_rate_limit:
                    logger.exception("Rate limit detected during batch embedding.")
                    raise e
                else:
                    log_warning(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                    raise_embedding_failures(results)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

        id_counts: Dict[str, int] = {}
        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # ChromaDB requires unique IDs within a batch — deduplicate collisions
            # from documents with identical content (e.g., empty pages from PDF parsing)
            if doc_id in id_counts:
                id_counts[doc_id] += 1
                doc_id = md5(f"{doc_id}_{id_counts[doc_id]}".encode()).hexdigest()
            else:
                id_counts[doc_id] = 0

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

        # Run the synchronous ChromaDB batch on a worker thread so the
        # asyncio event loop stays responsive while the (potentially large)
        # write completes.
        await asyncio.to_thread(
            self._batch_operation,
            ids=ids,
            embeddings=docs_embeddings,
            documents=docs,
            metadatas=docs_metadata,
            operation_name="async_insert",
            operation_func=target_collection.add,
        )

    def upsert_available(self) -> bool:
        """Check if upsert is available in ChromaDB."""
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
            user_id (Optional[str]): See ``insert``.
        """
        try:
            # Embed before the delete below: clearing the old chunks first would destroy
            # retrievable content if the embedder then fails.
            embed_before_replace(documents, self.embedder)
            if self.content_hash_exists(content_hash, user_id=user_id):
                self._delete_by_content_hash(content_hash, user_id=user_id)
            self._upsert(content_hash, documents, filters, user_id=user_id)
        except Exception:
            logger.exception("Error upserting documents by content hash")
            raise

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
            user_id (Optional[str]): See ``insert``.
        """
        log_info(f"Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        target_collection = self._get_or_create_collection(user_id)

        id_counts: Dict[str, int] = {}
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # ChromaDB requires unique IDs within a batch — deduplicate collisions
            # from documents with identical content (e.g., empty pages from PDF parsing)
            if doc_id in id_counts:
                id_counts[doc_id] += 1
                doc_id = md5(f"{doc_id}_{id_counts[doc_id]}".encode()).hexdigest()
            else:
                id_counts[doc_id] = 0

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

        self._batch_operation(
            ids=ids,
            embeddings=docs_embeddings,
            documents=docs,
            metadatas=docs_metadata,
            operation_name="upsert",
            operation_func=target_collection.upsert,
        )

    async def _async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
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

        target_collection = self._get_or_create_collection(user_id)

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
                    except Exception:
                        logger.exception(f"Error assigning batch embedding to document '{doc.name}'")

            except Exception as e:
                # A throttle must not fall back to per-item calls, which would throttle harder.
                is_rate_limit = is_rate_limit_error(e)

                if is_rate_limit:
                    logger.exception("Rate limit detected during batch embedding.")
                    raise e
                else:
                    log_warning(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                    raise_embedding_failures(results)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

        id_counts: Dict[str, int] = {}
        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

            # ChromaDB requires unique IDs within a batch — deduplicate collisions
            # from documents with identical content (e.g., empty pages from PDF parsing)
            if doc_id in id_counts:
                id_counts[doc_id] += 1
                doc_id = md5(f"{doc_id}_{id_counts[doc_id]}".encode()).hexdigest()
            else:
                id_counts[doc_id] = 0

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

        # Run the synchronous ChromaDB batch on a worker thread so the
        # asyncio event loop stays responsive while the (potentially large)
        # write completes.
        await asyncio.to_thread(
            self._batch_operation,
            ids=ids,
            embeddings=docs_embeddings,
            documents=docs,
            metadatas=docs_metadata,
            operation_name="async_upsert",
            operation_func=target_collection.upsert,
        )

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        try:
            # Embed before the delete below: clearing the old chunks first would destroy
            # retrievable content if the embedder then fails.
            await aembed_before_replace(documents, self.embedder)
            if self.content_hash_exists(content_hash, user_id=user_id):
                self._delete_by_content_hash(content_hash, user_id=user_id)
            await self._async_upsert(content_hash, documents, filters, user_id=user_id)
        except Exception:
            logger.exception("Error upserting documents by content hash")
            raise

    def _user_collection_names(self) -> List[str]:
        """The per-user collections this knowledge base created. The name prefix is only a
        pre-filter; the ``BASE_COLLECTION_METADATA_KEY`` tag decides."""
        prefix = f"{self.collection_name}__"
        names: List[str] = []
        for entry in self.client.list_collections():
            name = entry if isinstance(entry, str) else entry.name
            if not name.startswith(prefix):
                continue
            # Older Chroma hands back Collection objects, newer ones names.
            metadata = entry.metadata if not isinstance(entry, str) else self.client.get_collection(name=name).metadata
            if (metadata or {}).get(BASE_COLLECTION_METADATA_KEY) == self.collection_name:
                names.append(name)
        return names

    def _all_owner_collections(self) -> List[Collection]:
        """Every collection this knowledge base owns: the base one plus one per owner."""
        result: List[Collection] = []
        try:
            for name in self._user_collection_names():
                result.append(self.client.get_collection(name=name))
        except Exception:
            log_debug("Could not list collections for an unscoped query")

        try:
            result.append(self._get_or_create_collection(None))
        except Exception:
            log_debug("Base collection unavailable for an unscoped query")

        return result

    def _delete_where_across(self, collections: List[Collection], where: Dict[str, Any], description: str) -> bool:
        """Delete everything matching ``where`` from each of ``collections``."""
        deleted = 0
        for coll in collections:
            try:
                result = coll.get(where=cast(Any, where))
                ids_to_delete = result.get("ids", [])
                if not ids_to_delete:
                    continue
                coll.delete(ids=ids_to_delete)
                deleted += len(ids_to_delete)
            except Exception:
                log_debug(f"Could not delete by {description} from collection {coll.name!r}")

        if not deleted:
            log_info(f"No documents found with {description}")
            return False

        log_info(f"Deleted {deleted} documents with {description}")
        return True

    def _collections_to_query(self, user_id: Optional[str]) -> List[Collection]:
        """Build the list of collections to query for a scoped search.

        ``None`` reads every collection this knowledge base owns. A set ``user_id``,
        ``""`` included, reads that owner's collection plus the base one, which holds
        content uploaded with no owner. Collections that don't exist yet are skipped.
        """
        if user_id is None:
            return self._all_owner_collections()

        result: List[Collection] = []
        user_name = self._collection_name_for(user_id)
        if user_name != self.collection_name:
            try:
                cached = self._user_collections.get(user_name)
                if cached is not None:
                    result.append(cached)
                else:
                    # ``get_collection``, not get_or_create: a query must not create empty collections
                    result.append(self.client.get_collection(name=user_name))
                    self._user_collections[user_name] = result[-1]
            except Exception:
                log_debug(f"No collection yet for user_id={user_id!r}; only shared scope will be queried")

        try:
            result.append(self._get_or_create_collection(None))
        except Exception:
            log_debug("Base collection unavailable for scoped query")

        return result

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
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
            user_id (Optional[str]): Restrict results to this user's collection plus the
                base (shared) one. ``None`` queries every collection this knowledge base owns.
        Returns:
            List[Document]: List of search results.
        """
        if isinstance(filters, list):
            log_warning("Filter Expressions are not yet supported in ChromaDB. No filters will be applied.")
            filters = None

        collections = self._collections_to_query(user_id)
        if not collections:
            return []

        # Query each collection for ``limit`` results, then merge and take the top ``limit``
        merged: List[Document] = []
        for coll in collections:
            if self.search_type == SearchType.vector:
                merged.extend(self._vector_search(query, limit, filters, collection=coll))
            elif self.search_type == SearchType.keyword:
                merged.extend(self._keyword_search(query, limit, filters, collection=coll))
            elif self.search_type == SearchType.hybrid:
                merged.extend(self._hybrid_search(query, limit, filters, collection=coll))
            else:
                log_error(f"Invalid search type '{self.search_type}'.")
                return []

        # Dedupe by ``(name, content)`` in case a chunk lives in both collections
        seen: set = set()
        unique: List[Document] = []
        for doc in merged:
            key = (doc.name, doc.content)
            if key in seen:
                continue
            seen.add(key)
            unique.append(doc)

        # Chroma distance: lower is better, and unscored results (RRF) sort to the end via inf
        def _sort_key(d: Document) -> float:
            score = d.meta_data.get("similarity_score") if d.meta_data else None
            return float(score) if score is not None else float("inf")

        unique.sort(key=_sort_key)
        search_results = unique[:limit]

        if self.reranker and search_results:
            try:
                search_results = self.reranker.rerank(query=query, documents=search_results)
            except Exception as e:
                log_warning(f"Reranker failed, returning unranked results: {str(e)}")

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def _vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        collection: Optional[Collection] = None,
    ) -> List[Document]:
        """Perform pure vector similarity search.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.
            collection: The Chroma collection to query. Defaults to the base collection.

        Returns:
            List[Document]: List of search results.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        target = collection if collection is not None else self._get_or_create_collection(None)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        result: QueryResult = target.query(
            query_embeddings=query_embedding,
            n_results=limit,
            where=where_filter,
            include=["metadatas", "documents", "embeddings", "distances", "uris"],
        )

        return self._build_search_results(result)

    def _keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        collection: Optional[Collection] = None,
    ) -> List[Document]:
        """Perform keyword-based search using document content filtering.

        This uses ChromaDB's where_document filter with $contains operator
        for basic full-text search functionality.

        Args:
            query (str): Query to search for (keywords to match in document content).
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.
            collection: The Chroma collection to query. See ``_vector_search``.

        Returns:
            List[Document]: List of search results.
        """
        target = collection if collection is not None else self._get_or_create_collection(None)

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
            result = target.get(
                where=where_filter,
                where_document=cast(Any, where_document),
                limit=limit,
                include=["metadatas", "documents", "embeddings"],
            )

            return self._build_get_results(cast(Dict[str, Any], result), query)
        except Exception:
            logger.exception("Error in keyword search")
            return []

    def _hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        collection: Optional[Collection] = None,
    ) -> List[Document]:
        """Perform hybrid search combining vector similarity with full-text search using RRF.

        This method combines:
        1. Dense vector similarity search (semantic search)
        2. Full-text search (keyword/lexical search)

        Results are fused using Reciprocal Rank Fusion (RRF) for optimal ranking.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters to apply.
            collection: The Chroma collection to query. See ``_vector_search``.

        Returns:
            List[Document]: List of search results with RRF-fused ranking.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        target = collection if collection is not None else self._get_or_create_collection(None)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        # Fetch more candidates than needed for better fusion
        fetch_k = min(limit * 3, 100)

        def dense_vector_similarity_search() -> List[Tuple[str, float]]:
            """Dense vector similarity search."""
            try:
                results = target.query(  # type: ignore
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
                log_error(f"Error in vector search component: {str(e)}")
                return []

        def fts_search() -> List[Tuple[str, float]]:
            """Full-text search using ChromaDB's where_document filter."""
            try:
                query_words = query.split()
                if not query_words:
                    return []

                # Use first word for $contains filter
                fts_where_document: Dict[str, Any] = {"$contains": query_words[0]}

                results = target.query(  # type: ignore
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
                log_error(f"Error in FTS search component: {str(e)}")
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
            full_results = target.get(
                ids=top_ids,
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception as e:
            log_error(f"Error fetching full results: {str(e)}")
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
                # Stable key the cross-collection merge in ``search`` sorts on
                metadata[idx]["similarity_score"] = distance

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
            log_error(f"Error building search results: {str(e)}")

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
            log_error(f"Error building get results: {str(e)}")

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
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters, user_id)

    def drop(self) -> None:
        """Delete the collection, and any per-user collections under its base name."""
        try:
            names = self._user_collection_names()
        except Exception:
            names = []
        for name in names:
            try:
                self.client.delete_collection(name=name)
            except Exception:
                log_debug(f"Could not delete per-user collection {name!r}")
        self._user_collections.clear()

        if self.exists():
            log_debug(f"Deleting collection: {self.collection_name}")
            self.client.delete_collection(name=self.collection_name)
        # Without this a later ``_get_or_create_collection(None)`` hands back a deleted handle
        self._collection = None

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
        """Get the count of documents across every collection this knowledge base owns."""
        total = 0
        try:
            for coll in self._all_owner_collections():
                try:
                    total += coll.count()
                except Exception:
                    log_debug(f"Could not count collection {coll.name!r}")
        except Exception:
            logger.exception("Error getting count")
        return total

    def optimize(self) -> None:
        raise NotImplementedError

    def delete(self) -> bool:
        """Clear the knowledge base, including every per-user collection."""
        try:
            for name in self._user_collection_names():
                try:
                    self.client.delete_collection(name=name)
                except Exception:
                    log_debug(f"Could not delete per-user collection {name!r}")
            self._user_collections.clear()

            self.client.delete_collection(name=self.collection_name)
            self._collection = None
            return True
        except Exception:
            logger.exception("Error clearing collection")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete document by ID, across every collection this knowledge base owns."""
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            # Check if document exists
            if not self.id_exists(id):
                log_info(f"Document with ID '{id}' not found")
                return False

            deleted = False
            for coll in self._all_owner_collections():
                try:
                    if coll.get(ids=[id]).get("ids", []):
                        coll.delete(ids=[id])
                        deleted = True
                except Exception:
                    log_debug(f"Could not delete ID '{id}' from collection {coll.name!r}")

            if deleted:
                log_info(f"Deleted document with ID '{id}'")
            return deleted
        except Exception:
            logger.exception(f"Error deleting document by ID '{id}'")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name. Spans every owner — see ``delete_by_id``."""
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            return self._delete_where_across(self._all_owner_collections(), {"name": {"$eq": name}}, f"name '{name}'")
        except Exception:
            logger.exception(f"Error deleting documents by name '{name}'")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata. Spans every owner — see ``delete_by_id``."""
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            # Build where clause for metadata filtering
            where_clause = {}
            for key, value in metadata.items():
                where_clause[key] = {"$eq": value}

            return self._delete_where_across(self._all_owner_collections(), where_clause, f"metadata '{metadata}'")
        except Exception:
            logger.exception(f"Error deleting documents by metadata '{metadata}'")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by content ID, scoped to ``user_id`` when set.

        ``None`` deletes across every collection this knowledge base owns.
        """
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            if user_id is None:
                collections = self._all_owner_collections()
            else:
                # ``get_collection`` raises when the collection doesn't exist: nothing to delete
                name = self._collection_name_for(user_id)
                try:
                    collections = [self.client.get_collection(name=name)]
                except Exception:
                    log_debug(f"No collection {name!r} for content_id={content_id!r} delete; treating as no-op")
                    return False

            return self._delete_where_across(
                collections, {"content_id": {"$eq": content_id}}, f"content_id '{content_id}'"
            )
        except Exception:
            logger.exception(f"Error deleting documents by content_id '{content_id}'")
            return False

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by content hash, scoped to ``user_id`` when set.

        ``None`` deletes from the base collection only, so a re-upsert never wipes
        another owner's identical chunks.
        """
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            collection_name = self._collection_name_for(user_id)
            # ``get_collection`` raises when the collection doesn't exist: nothing to delete
            try:
                collection: Collection = self.client.get_collection(name=collection_name)
            except Exception:
                return False

            # Find all documents with the given content_hash
            result = collection.get(where=cast(Any, {"content_hash": {"$eq": content_hash}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with content_hash '{content_hash}' in {collection_name!r}")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(
                f"Deleted {len(ids_to_delete)} documents with content_hash '{content_hash}' from {collection_name!r}"
            )
            return True
        except Exception:
            logger.exception(f"Error deleting documents by content_hash '{content_hash}'")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in any collection this knowledge base owns.

        Args:
            id (str): The document ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            for coll in self._all_owner_collections():
                try:
                    if coll.get(ids=[id]).get("ids", []):
                        return True
                except Exception:
                    log_debug(f"Could not check ID '{id}' in collection {coll.name!r}")
            return False
        except Exception:
            logger.exception(f"Error checking if ID '{id}' exists")
            return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if documents with the given content hash exist.

        With ``user_id`` only that owner's collection is checked. ``None`` reads the base
        collection alone, matching what ``_delete_by_content_hash`` clears for ``None``.
        """
        if not self.client:
            log_error("Client not initialized")
            return False

        try:
            collection_name = self._collection_name_for(user_id)
            # ``get_collection`` raises when nothing has been written yet: no collection, no rows
            try:
                collection: Collection = self.client.get_collection(name=collection_name)
            except Exception:
                return False

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
                return False

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    # Known issue with ChromaDB 0.5.0 - internal bug
                    # As a workaround, assume content doesn't exist to allow processing to continue
                    log_warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Assuming content_hash '{content_hash}' does not exist."
                    )

                    return False
                else:
                    raise te

        except Exception:
            logger.exception(f"Error checking if content_hash '{content_hash}' exists")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id, across every
        collection this knowledge base owns.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            if not self.client:
                log_error("Client not initialized")
                return

            # Flatten the new metadata first
            flattened_new_metadata = self._flatten_metadata(metadata)

            # Find documents with the given content_id
            try:
                updated = 0
                for collection in self._all_owner_collections():
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
                        continue

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
                    updated += len(ids)

                if not updated:
                    log_debug(f"No documents found with content_id: {content_id}")
                    return

                log_debug(f"Updated metadata for {updated} documents with content_id: {content_id}")

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    log_warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Cannot update metadata for content_id '{content_id}'.",
                    )

                    return
                else:
                    raise te

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]
