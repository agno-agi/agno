import json
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    import asyncio

    from pymilvus import AsyncMilvusClient, MilvusClient  # type: ignore
except ImportError:
    raise ImportError("The `pymilvus` package is not installed. Please install it via `pip install pymilvus`.")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb, normalize_user_id
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

MILVUS_DISTANCE_MAP = {
    Distance.cosine: "COSINE",
    Distance.l2: "L2",
    Distance.max_inner_product: "IP",
}

# Per-user isolation: user_id is the chunk owner, stored as a top-level field so the
# owner scope can be AND-ed into vector and hybrid search. NULL/unset is the shared bucket.
USER_ID_FIELD = "user_id"


def _quote(value: str) -> str:
    """Escape a string for a double-quoted Milvus filter literal.

    Backslash first so it isn't double-escaped, then the quote, then the newline,
    carriage return and tab that Milvus's filter lexer rejects inside a quoted literal.
    """
    return (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )


class Milvus(VectorDb):
    USER_ID_KEY = USER_ID_FIELD

    def __init__(
        self,
        collection: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        uri: str = "http://localhost:19530",
        token: Optional[str] = None,
        search_type: SearchType = SearchType.vector,
        reranker: Optional[Reranker] = None,
        sparse_vector_dimensions: int = 10000,
        **kwargs,
    ):
        """
        Milvus vector database.

        Args:
            collection (str): Name of the Milvus collection.
            name (Optional[str]): Name of the vector database.
            description (Optional[str]): Description of the vector database.
            embedder (Embedder): Embedder to use for embedding documents.
            distance (Distance): Distance metric to use for vector similarity.
            uri (Optional[str]): URI of the Milvus server.
                - If you only need a local vector database for small scale data or prototyping,
                  setting the uri as a local file, e.g.`./milvus.db`, is the most convenient method,
                  as it automatically utilizes [Milvus Lite](https://milvus.io/docs/milvus_lite.md)
                  to store all data in this file.
                - If you have large scale of data, say more than a million vectors, you can set up
                  a more performant Milvus server on [Docker or Kubernetes](https://milvus.io/docs/quickstart.md).
                  In this setup, please use the server address and port as your uri, e.g.`http://localhost:19530`.
                  If you enable the authentication feature on Milvus,
                  use "<your_username>:<your_password>" as the token, otherwise don't set the token.
                - If you use [Zilliz Cloud](https://zilliz.com/cloud), the fully managed cloud
                  service for Milvus, adjust the `uri` and `token`, which correspond to the
                  [Public Endpoint and API key](https://docs.zilliz.com/docs/on-zilliz-cloud-console#cluster-details)
                  in Zilliz Cloud.
            token (Optional[str]): Token for authentication with the Milvus server.
            search_type (SearchType): Type of search to perform (vector, keyword, or hybrid)
            reranker (Optional[Reranker]): Reranker to use for hybrid search results
            **kwargs: Additional keyword arguments to pass to the MilvusClient.
        """
        # Validate required parameters
        if not collection:
            raise ValueError("Collection name must be provided.")

        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            seed = f"{uri or 'milvus'}#{collection}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        self.collection: str = collection

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        self.distance: Distance = distance
        self.uri: str = uri
        self.token: Optional[str] = token
        self._client: Optional[MilvusClient] = None
        self._async_client: Optional[AsyncMilvusClient] = None
        self.search_type: SearchType = search_type
        self.reranker: Optional[Reranker] = reranker
        self.sparse_vector_dimensions = sparse_vector_dimensions
        self.kwargs = kwargs

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            log_debug("Creating Milvus Client")
            self._client = MilvusClient(
                uri=self.uri,
                token=self.token,
                **self.kwargs,
            )
        return self._client

    @property
    def async_client(self) -> AsyncMilvusClient:
        if not hasattr(self, "_async_client") or self._async_client is None:
            log_debug("Creating Async Milvus Client")
            self._async_client = AsyncMilvusClient(
                uri=self.uri,
                token=self.token,
                **self.kwargs,
            )
        return self._async_client

    def _get_sparse_vector(self, text: str) -> Dict[int, float]:
        """
        Convert text into a sparse vector representation using a simple TF-IDF-like scoring.

        This method creates a sparse vector by:
        1. Converting text to lowercase and splitting into words
        2. Computing word frequencies
        3. Creating a hash-based word ID (modulo 10000)
        4. Computing a TF-IDF-like score for each word

        Args:
            text: Input text to convert to sparse vector

        Returns:
            Dictionary mapping word IDs (int) to their TF-IDF-like scores (float)
        """
        from collections import Counter

        import numpy as np

        # Simple word-based sparse vector creation
        words = text.lower().split()
        word_counts = Counter(words)

        # Create sparse vector (word_id: tf-idf_score)
        sparse_vector = {}
        for word, count in word_counts.items():
            word_id = hash(word) % self.sparse_vector_dimensions
            # Simple tf-idf-like score
            score = count * np.log(1 + len(words))
            sparse_vector[word_id] = float(score)

        return sparse_vector

    def _create_hybrid_schema(self) -> Any:
        """Create a schema for hybrid collection with all necessary fields."""
        from pymilvus import DataType

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
        )

        # Define field configurations
        fields = [
            ("id", DataType.VARCHAR, 128, True),  # (name, type, max_length, is_primary)
            ("name", DataType.VARCHAR, 1000, False),
            ("content", DataType.VARCHAR, 65535, False),
            ("content_id", DataType.VARCHAR, 1000, False),
            ("content_hash", DataType.VARCHAR, 1000, False),
            ("text", DataType.VARCHAR, 65535, False),
            ("meta_data", DataType.VARCHAR, 65535, False),
            ("usage", DataType.VARCHAR, 65535, False),
        ]

        # Add VARCHAR fields
        for field_name, datatype, max_length, is_primary in fields:
            schema.add_field(field_name=field_name, datatype=datatype, max_length=max_length, is_primary=is_primary)

        # Declare the owner field explicitly - hybrid search cannot filter on a dynamic field
        schema.add_field(field_name=self.USER_ID_KEY, datatype=DataType.VARCHAR, max_length=256, nullable=True)

        # Add vector fields
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=self.dimensions)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        return schema

    def _prepare_hybrid_index_params(self) -> Any:
        """Prepare index parameters for both dense and sparse vectors."""
        index_params = self.client.prepare_index_params()

        # Add indexes for both vector types
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_index",
            index_type="IVF_FLAT",
            metric_type=self._get_metric_type(),
            params={"nlist": 1024},
        )

        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"drop_ratio_build": 0.2},
        )

        return index_params

    def _prepare_document_data(
        self,
        content_hash: str,
        document: Document,
        include_vectors: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Union[str, List[float], Dict[int, float], None]]:
        """
        Prepare document data for insertion.

        Args:
            document: Document to prepare data for
            include_vectors: Whether to include vector data
            filters: Optional metadata filters merged into meta_data
            user_id: Owner of this chunk for per-user isolation

        Returns:
            Dictionary with document data where values can be strings, vectors (List[float]),
            sparse vectors (Dict[int, float]), or None
        """

        cleaned_content = document.content.replace("\x00", "\ufffd")
        # Fold content_hash and user_id into the id so two users sharing a content_hash don't collide
        base_id = document.id or md5(cleaned_content.encode()).hexdigest()
        doc_id = self._doc_id(base_id, content_hash, user_id)

        meta_data = document.meta_data or {}
        if filters:
            meta_data = {**meta_data, **filters}

        # Convert dictionary fields to JSON strings
        meta_data_str = json.dumps(meta_data) if meta_data else "{}"
        usage_str = json.dumps(document.usage) if document.usage else "{}"

        data: Dict[str, Union[str, List[float], Dict[int, float], None]] = {
            "id": doc_id,
            "text": cleaned_content,
            "name": document.name,
            "content_id": document.content_id or "",
            "meta_data": meta_data_str,
            "content": cleaned_content,
            "usage": usage_str,
            "content_hash": content_hash,
            self.USER_ID_KEY: user_id,
        }

        if include_vectors:
            if self.search_type == SearchType.hybrid:
                data.update(
                    {
                        "dense_vector": document.embedding,  # List[float] or None # Dict[int, float]
                        "sparse_vector": self._get_sparse_vector(cleaned_content),
                    }
                )
            else:
                vector_data: Optional[List[float]] = document.embedding
                data["vector"] = vector_data

        return data

    def _create_hybrid_collection(self) -> None:
        """Create a collection specifically for hybrid search."""
        log_debug(f"Creating hybrid collection: {self.collection}")

        schema = self._create_hybrid_schema()
        index_params = self._prepare_hybrid_index_params()

        self.client.create_collection(collection_name=self.collection, schema=schema, index_params=index_params)

    async def _async_create_hybrid_collection(self) -> None:
        """Create a hybrid collection asynchronously."""
        log_debug(f"Creating hybrid collection asynchronously: {self.collection}")

        schema = self._create_hybrid_schema()
        index_params = self._prepare_hybrid_index_params()

        await self.async_client.create_collection(
            collection_name=self.collection, schema=schema, index_params=index_params
        )

    def create(self) -> None:
        """Create a collection based on search type if it doesn't exist."""
        if self.exists():
            return

        if self.search_type == SearchType.hybrid:
            self._create_hybrid_collection()
            return

        _distance = self._get_metric_type()
        log_debug(f"Creating collection: {self.collection}")
        self.client.create_collection(
            collection_name=self.collection,
            dimension=self.dimensions,
            metric_type=_distance,
            id_type="string",
            max_length=65_535,
        )

    async def async_create(self) -> None:
        """Create collection asynchronously based on search type."""
        # Use the synchronous client to check if collection exists
        if not self.client.has_collection(self.collection):
            if self.search_type == SearchType.hybrid:
                await self._async_create_hybrid_collection()
            else:
                # Original async create logic for regular vector search
                _distance = self._get_metric_type()
                log_debug(f"Creating collection asynchronously: {self.collection}")
                await self.async_client.create_collection(
                    collection_name=self.collection,
                    dimension=self.dimensions,
                    metric_type=_distance,
                    id_type="string",
                    max_length=65_535,
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
            expr = f"name == '{name}'"
            scroll_result = self.client.query(
                collection_name=self.collection,
                filter=expr,
                output_fields=["id"],
                limit=1,
            )
            return len(scroll_result) > 0 and len(scroll_result[0]) > 0
        return False

    def id_exists(self, id: str) -> bool:
        if self.client:
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[id],
            )
            return len(collection_points) > 0
        return False

    def _content_hash_expr(self, content_hash: str, user_id: Optional[str], scope_none_to_shared: bool = False) -> str:
        """Build the content_hash predicate for upsert dedupe and existence checks.

        A set user_id matches the owner. When None, scope_none_to_shared=True matches only
        the shared (null) bucket so a dedupe-delete never wipes a scoped owner, while the
        default matches any owner.
        """
        expr = f'content_hash == "{_quote(content_hash)}"'
        if user_id:
            expr += f' and {self.USER_ID_KEY} == "{_quote(user_id)}"'
        elif scope_none_to_shared:
            expr += f" and {self.USER_ID_KEY} is null"
        return expr

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Check if a document with the given content hash exists.

        Args:
            content_hash (str): The content hash to check.
            user_id (Optional[str]): Restrict the check to the owner's chunks.

        Returns:
            bool: True if a document with the given content hash exists, False otherwise.
        """
        if self.client:
            expr = self._content_hash_expr(content_hash, normalize_user_id(user_id))
            scroll_result = self.client.query(
                collection_name=self.collection,
                filter=expr,
                output_fields=["id"],
                limit=1,
            )
            return len(scroll_result) > 0 and len(scroll_result[0]) > 0
        return False

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content hash.

        Args:
            content_hash (str): The content hash to delete.
            user_id (Optional[str]): Restrict the delete to the owner's chunks.

        Returns:
            bool: True if documents were deleted, False otherwise.
        """
        if self.client:
            expr = self._content_hash_expr(content_hash, normalize_user_id(user_id), scope_none_to_shared=True)
            self.client.delete(collection_name=self.collection, filter=expr)
            log_info(f"Deleted documents with content_hash '{content_hash}' from collection '{self.collection}'.")
            return True
        return False

    def _insert_hybrid_document(
        self,
        content_hash: str,
        document: Document,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert a document with both dense and sparse vectors."""
        # Embed before building the row so _prepare_document_data sees the dense_vector
        document.embed(embedder=self.embedder)
        data = self._prepare_document_data(
            content_hash=content_hash, document=document, include_vectors=True, filters=filters, user_id=user_id
        )
        self.client.insert(
            collection_name=self.collection,
            data=data,
        )
        log_debug(f"Inserted hybrid document: {document.name} ({document.meta_data})")

    async def _async_insert_hybrid_document(
        self,
        content_hash: str,
        document: Document,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert a document with both dense and sparse vectors asynchronously."""
        data = self._prepare_document_data(
            content_hash=content_hash, document=document, include_vectors=True, filters=filters, user_id=user_id
        )

        await self.async_client.insert(
            collection_name=self.collection,
            data=data,
        )
        log_debug(f"Inserted hybrid document asynchronously: {document.name} ({document.meta_data})")

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents based on search type.

        Args:
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
                None (default) writes to the shared bucket.
        """
        user_id = normalize_user_id(user_id)
        log_debug(f"Inserting {len(documents)} documents")

        if self.search_type == SearchType.hybrid:
            for document in documents:
                self._insert_hybrid_document(
                    content_hash=content_hash, document=document, filters=filters, user_id=user_id
                )
        else:
            for document in documents:
                document.embed(embedder=self.embedder)
                if not document.embedding:
                    log_debug(f"Skipping document without embedding: {document.name} ({document.meta_data})")
                    continue
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Fold content_hash and user_id into the id so two users sharing a content_hash don't collide
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                doc_id = self._doc_id(base_id, content_hash, user_id)

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "content_id": document.content_id or "",
                    "meta_data": json.dumps(meta_data),
                    "content": cleaned_content,
                    "usage": json.dumps(document.usage) if document.usage else "{}",
                    "content_hash": content_hash,
                    self.USER_ID_KEY: user_id,
                }
                self.client.insert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Inserted document: {document.name} ({meta_data})")

        log_info(f"Inserted {len(documents)} documents")

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents asynchronously based on search type.

        Args:
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
                None (default) writes to the shared bucket.
        """
        user_id = normalize_user_id(user_id)
        log_info(f"Inserting {len(documents)} documents asynchronously")

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
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {str(e)}")

            except Exception as e:
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding.: {str(e)}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

        if self.search_type == SearchType.hybrid:
            await asyncio.gather(
                *[
                    self._async_insert_hybrid_document(
                        content_hash=content_hash, document=doc, filters=filters, user_id=user_id
                    )
                    for doc in documents
                ]
            )
        else:

            async def process_document(document):
                document.embed(embedder=self.embedder)
                if not document.embedding:
                    log_debug(f"Skipping document without embedding: {document.name} ({document.meta_data})")
                    return None
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Fold content_hash and user_id into the id so two users sharing a content_hash don't collide
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                doc_id = self._doc_id(base_id, content_hash, user_id)

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "content_id": document.content_id or "",
                    "meta_data": json.dumps(meta_data),
                    "content": cleaned_content,
                    "usage": json.dumps(document.usage) if document.usage else "{}",
                    "content_hash": content_hash,
                    self.USER_ID_KEY: user_id,
                }
                await self.async_client.insert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Inserted document asynchronously: {document.name} ({document.meta_data})")
                return data

            await asyncio.gather(*[process_document(doc) for doc in documents])

        log_info(f"Inserted {len(documents)} documents asynchronously")

    def upsert_available(self) -> bool:
        """
        Check if upsert operation is available.

        Returns:
            bool: Always returns True.
        """
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
        """
        user_id = normalize_user_id(user_id)
        log_debug(f"Upserting {len(documents)} documents")

        # Dedupe-delete scoped to the owner: replace only the caller's stale chunks for this content_hash.
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)

        if self.search_type == SearchType.hybrid:
            for document in documents:
                document.embed(embedder=self.embedder)
                data = self._prepare_document_data(
                    content_hash=content_hash, document=document, include_vectors=True, filters=filters, user_id=user_id
                )
                self.client.upsert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Upserted hybrid document: {document.name} ({document.meta_data})")
        else:
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                doc_id = self._doc_id(base_id, content_hash, user_id)

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "content_id": document.content_id or "",
                    "meta_data": json.dumps(meta_data),
                    "content": cleaned_content,
                    "usage": json.dumps(document.usage) if document.usage else "{}",
                    "content_hash": content_hash,
                    self.USER_ID_KEY: user_id,
                }
                self.client.upsert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Upserted document: {document.name} ({document.meta_data})")

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously.

        Args:
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
        """
        user_id = normalize_user_id(user_id)
        log_debug(f"Upserting {len(documents)} documents asynchronously")

        # Mirror sync upsert: dedupe-delete the owner's stale chunks before re-inserting.
        if await self._async_content_hash_exists(content_hash, user_id=user_id):
            await self._async_delete_by_content_hash(content_hash, user_id=user_id)

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
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {str(e)}")

            except Exception as e:
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding.: {str(e)}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

        if self.search_type == SearchType.hybrid:

            async def process_hybrid_document(document):
                data = self._prepare_document_data(
                    content_hash=content_hash, document=document, include_vectors=True, filters=filters, user_id=user_id
                )
                await self.async_client.upsert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Upserted hybrid document asynchronously: {document.name} ({document.meta_data})")
                return data

            await asyncio.gather(*[process_hybrid_document(doc) for doc in documents])
        else:

            async def process_document(document):
                cleaned_content = document.content.replace("\x00", "\ufffd")
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                doc_id = self._doc_id(base_id, content_hash, user_id)

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "content_id": document.content_id or "",
                    "meta_data": json.dumps(meta_data),
                    "content": cleaned_content,
                    "usage": json.dumps(document.usage) if document.usage else "{}",
                    "content_hash": content_hash,
                    self.USER_ID_KEY: user_id,
                }
                await self.async_client.upsert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Upserted document asynchronously: {document.name} ({document.meta_data})")
                return data

            await asyncio.gather(*[process_document(doc) for doc in documents])

        log_debug(f"Upserted {len(documents)} documents asynchronously in parallel")

    def _get_metric_type(self) -> str:
        """
        Get the Milvus metric type string for the current distance setting.

        Returns:
            Milvus metric type string, defaults to "COSINE" if distance not found
        """
        return MILVUS_DISTANCE_MAP.get(self.distance, "COSINE")

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Search for documents matching the query.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search
            search_params (Optional[Dict[str, Any]]): Milvus search parameters including:
                - radius (float): Minimum similarity threshold for range search
                - range_filter (float): Maximum similarity threshold for range search
                - params (dict): Index-specific search params (e.g., nprobe, ef)
            user_id (Optional[str]): Restrict results to the caller's chunks plus
                the shared bucket. None means no scope (admin view, sees all).

        Returns:
            List[Document]: List of matching documents
        """
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Milvus. No filters will be applied.")
            filters = None
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit, filters, user_id=user_id)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        results = self.client.search(
            collection_name=self.collection,
            data=[query_embedding],
            filter=self._scoped_expr(filters, user_id),
            output_fields=["*"],
            limit=limit,
            search_params=search_params,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            entity = result["entity"]
            meta_data = self._decode_json_field(entity.get("meta_data"), default={})
            usage = self._decode_json_field(entity.get("usage"), default=None)
            search_results.append(
                Document(
                    id=result["id"],
                    name=entity.get("name", None),
                    meta_data=meta_data,
                    content=entity.get("content", ""),
                    content_id=entity.get("content_id", None),
                    embedder=self.embedder,
                    embedding=entity.get("vector", None),
                    usage=usage,
                )
            )

        # Apply reranker if available
        if self.reranker and search_results:
            search_results = self.reranker.rerank(query=query, documents=search_results)
            search_results = search_results[:limit]

        log_info(f"Found {len(search_results)} documents")
        return search_results

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Asynchronously search for documents matching the query.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search
            search_params (Optional[Dict[str, Any]]): Milvus search parameters including:
                - radius (float): Minimum similarity threshold for range search
                - range_filter (float): Maximum similarity threshold for range search
                - params (dict): Index-specific search params (e.g., nprobe, ef)
            user_id (Optional[str]): Restrict results to the caller's chunks plus
                the shared bucket. None means no scope (admin view, sees all).

        Returns:
            List[Document]: List of matching documents
        """
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Milvus. No filters will be applied.")
            filters = None
        if self.search_type == SearchType.hybrid:
            return await self.async_hybrid_search(query, limit, filters, user_id=user_id)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        results = await self.async_client.search(
            collection_name=self.collection,
            data=[query_embedding],
            filter=self._scoped_expr(filters, user_id),
            output_fields=["*"],
            limit=limit,
            search_params=search_params,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            entity = result["entity"]
            meta_data = self._decode_json_field(entity.get("meta_data"), default={})
            usage = self._decode_json_field(entity.get("usage"), default=None)
            search_results.append(
                Document(
                    id=result["id"],
                    name=entity.get("name", None),
                    meta_data=meta_data,
                    content=entity.get("content", ""),
                    content_id=entity.get("content_id", None),
                    embedder=self.embedder,
                    embedding=entity.get("vector", None),
                    usage=usage,
                )
            )

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a hybrid search combining dense and sparse vector similarity.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search
            user_id (Optional[str]): Restrict results to the caller's chunks plus
                the shared bucket. None means no scope (admin view, sees all).

        Returns:
            List[Document]: List of matching documents
        """
        from pymilvus import AnnSearchRequest, RRFRanker

        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Milvus. No filters will be applied.")
            filters = None

        # Get query embeddings
        dense_vector = self.embedder.get_embedding(query)
        sparse_vector = self._get_sparse_vector(query)

        if dense_vector is None:
            log_error(f"Error getting dense embedding for Query: {query}")
            return []

        if self._client is None:
            log_error("Milvus client not initialized")
            return []

        # Apply the owner scope as a pre-filter on each AnnSearchRequest - the per-branch
        # top-k is computed before fusion, so a post-filter would starve scoped users out
        scope_expr = self._scoped_expr(filters, user_id)

        try:
            # Refer to docs for details- https://milvus.io/docs/multi-vector-search.md

            # Create search request for dense vectors
            dense_search_param = {
                "data": [dense_vector],
                "anns_field": "dense_vector",
                "param": {"metric_type": self._get_metric_type(), "params": {"nprobe": 10}},
                "limit": limit
                * 2,  # Fetch more candidates for better reranking quality - each vector search returns 2x results which are then merged and reranked
            }

            # Create search request for sparse vectors
            sparse_search_param = {
                "data": [sparse_vector],
                "anns_field": "sparse_vector",
                "param": {"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
                "limit": limit * 2,  # Match dense search limit to ensure balanced candidate pool for reranking
            }

            if scope_expr:
                dense_search_param["expr"] = scope_expr
                sparse_search_param["expr"] = scope_expr

            # Create search requests
            dense_request = AnnSearchRequest(**dense_search_param)
            sparse_request = AnnSearchRequest(**sparse_search_param)
            reqs = [dense_request, sparse_request]

            # Use RRFRanker for balanced importance between vectors
            ranker = RRFRanker(60)  # Default k=60

            log_info("Performing hybrid search")
            results = self._client.hybrid_search(
                collection_name=self.collection, reqs=reqs, ranker=ranker, limit=limit, output_fields=["*"]
            )

            # Build search results
            search_results: List[Document] = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", {})
                    meta_data = self._decode_json_field(entity.get("meta_data"), default={})
                    usage = self._decode_json_field(entity.get("usage"), default=None)

                    search_results.append(
                        Document(
                            id=hit.get("id"),
                            name=entity.get("name", None),
                            meta_data=meta_data,  # Now a dictionary
                            content=entity.get("content", ""),
                            content_id=entity.get("content_id", None),
                            embedder=self.embedder,
                            embedding=entity.get("dense_vector", None),
                            usage=usage,  # Now a dictionary or None
                        )
                    )

            # Apply additional reranking if custom reranker is provided
            if self.reranker and search_results:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            log_error(f"Error during hybrid search: {str(e)}")
            return []

    async def async_hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform an asynchronous hybrid search combining dense and sparse vector similarity.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search
            user_id (Optional[str]): Restrict results to the caller's chunks plus
                the shared bucket. None means no scope (admin view, sees all).

        Returns:
            List[Document]: List of matching documents
        """
        from pymilvus import AnnSearchRequest, RRFRanker

        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Milvus. No filters will be applied.")
            filters = None

        # Get query embeddings
        dense_vector = self.embedder.get_embedding(query)
        sparse_vector = self._get_sparse_vector(query)

        if dense_vector is None:
            log_error(f"Error getting dense embedding for Query: {query}")
            return []

        # See hybrid_search: the owner scope is a pre-filter on each branch
        scope_expr = self._scoped_expr(filters, user_id)

        try:
            # Refer to docs for details- https://milvus.io/docs/multi-vector-search.md

            # Create search request for dense vectors
            dense_search_param = {
                "data": [dense_vector],
                "anns_field": "dense_vector",
                "param": {"metric_type": self._get_metric_type(), "params": {"nprobe": 10}},
                "limit": limit
                * 2,  # Fetch more candidates for better reranking quality - each vector search returns 2x results which are then merged and reranked
            }

            # Create search request for sparse vectors
            sparse_search_param = {
                "data": [sparse_vector],
                "anns_field": "sparse_vector",
                "param": {"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
                "limit": limit * 2,  # Match dense search limit to ensure balanced candidate pool for reranking
            }

            if scope_expr:
                dense_search_param["expr"] = scope_expr
                sparse_search_param["expr"] = scope_expr

            # Create search requests
            dense_request = AnnSearchRequest(**dense_search_param)
            sparse_request = AnnSearchRequest(**sparse_search_param)
            reqs = [dense_request, sparse_request]

            # Use RRFRanker for balanced importance between vectors
            ranker = RRFRanker(60)  # Default k=60

            log_info("Performing async hybrid search")
            results = await self.async_client.hybrid_search(
                collection_name=self.collection, reqs=reqs, ranker=ranker, limit=limit, output_fields=["*"]
            )

            # Build search results
            search_results: List[Document] = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", {})
                    meta_data = self._decode_json_field(entity.get("meta_data"), default={})
                    usage = self._decode_json_field(entity.get("usage"), default=None)

                    search_results.append(
                        Document(
                            id=hit.get("id"),
                            name=entity.get("name", None),
                            meta_data=meta_data,  # Now a dictionary
                            content=entity.get("content", ""),
                            content_id=entity.get("content_id", None),
                            embedder=self.embedder,
                            embedding=entity.get("dense_vector", None),
                            usage=usage,  # Now a dictionary or None
                        )
                    )

            # Apply additional reranking if custom reranker is provided
            if self.reranker and search_results:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            log_error(f"Error during async hybrid search: {str(e)}")
            return []

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.collection}")
            self.client.drop_collection(self.collection)

    async def async_drop(self) -> None:
        """
        Drop collection asynchronously.
        AsyncMilvusClient supports drop_collection().
        """
        # Check using synchronous client
        if self.client.has_collection(self.collection):
            log_debug(f"Deleting collection asynchronously: {self.collection}")
            await self.async_client.drop_collection(self.collection)

    def exists(self) -> bool:
        if self.client:
            if self.client.has_collection(self.collection):
                return True
        return False

    async def async_exists(self) -> bool:
        """
        Check if collection exists asynchronously.

        has_collection() is not supported by AsyncMilvusClient,
        so we use the synchronous client.
        """
        return self.client.has_collection(self.collection)

    def get_count(self) -> int:
        return self.client.get_collection_stats(collection_name="test_collection")["row_count"]

    def delete(self) -> bool:
        if self.client:
            self.client.drop_collection(self.collection)
            return True
        return False

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a document by its ID.

        Args:
            id (str): The document ID to delete

        Returns:
            bool: True if document was deleted, False otherwise
        """
        try:
            log_debug(f"Milvus VectorDB : Deleting document with ID {id}")
            if not self.id_exists(id):
                return False

            # Delete by ID using Milvus delete operation
            self.client.delete(collection_name=self.collection, ids=[id])
            log_info(f"Deleted document with ID '{id}' from collection '{self.collection}'.")
            return True
        except Exception as e:
            log_info(f"Error deleting document with ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name (str): The document name to delete

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Milvus VectorDB : Deleting documents with name {name}")
            if not self.name_exists(name):
                return False

            # Delete by name using Milvus delete operation with filter
            expr = f'name == "{name}"'
            self.client.delete(collection_name=self.collection, filter=expr)
            log_info(f"Deleted documents with name '{name}' from collection '{self.collection}'.")
            return True
        except Exception as e:
            log_info(f"Error deleting documents with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.

        Args:
            metadata (Dict[str, Any]): The metadata to match for deletion

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Milvus VectorDB : Deleting documents with metadata {metadata}")

            # Build filter expression for metadata matching
            expr = self._build_expr(metadata)
            if not expr:
                return False

            # Delete by metadata using Milvus delete operation with filter
            self.client.delete(collection_name=self.collection, filter=expr)
            log_info(f"Deleted documents with metadata '{metadata}' from collection '{self.collection}'.")
            return True
        except Exception as e:
            log_info(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content ID, scoped to user_id when set.

        user_id set deletes only that owner's chunks (never another user's or the
        shared NULL bucket); None deletes all chunks with this content_id.

        Args:
            content_id (str): The content ID to delete
            user_id (Optional[str]): Restrict the delete to the owner's chunks.

        Returns:
            bool: True if documents were actually deleted, False otherwise.
        """
        user_id = normalize_user_id(user_id)
        try:
            log_debug(f"Milvus VectorDB : Deleting documents with content_id {content_id} (user_id={user_id})")

            expr = f'content_id == "{_quote(content_id)}"'
            if user_id:
                # Scope to the owner; never matches shared (NULL) chunks.
                expr += f' and {self.USER_ID_KEY} == "{_quote(user_id)}"'

            result = self.client.delete(collection_name=self.collection, filter=expr)
            count = self._delete_count(result)
            # None means the result shape is unrecognized, so assume the delete ran
            deleted = count is None or count > 0
            if deleted:
                log_info(f"Deleted documents with content_id '{content_id}' from collection '{self.collection}'.")
            return deleted
        except Exception as e:
            log_info(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    @staticmethod
    def _delete_count(result: Any) -> Optional[int]:
        """Normalize the Milvus delete result into a deleted-row count.

        Milvus Lite returns a list of deleted primary keys; a Milvus server returns a
        mapping with a delete_count field. Returns None when the count is undeterminable.
        """
        if isinstance(result, list):
            return len(result)
        if isinstance(result, dict):
            try:
                return int(result.get("delete_count", 0) or 0)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _decode_json_field(value: Any, default: Any) -> Any:
        """Decode a Milvus VARCHAR field that stores JSON."""
        if value is None or value == "":
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError) as e:
                log_debug(f"Failed to decode JSON field, returning default: {e}")
                return default
        return value

    def _build_expr(self, filters: Optional[Dict[str, Any]]) -> Optional[str]:
        """Build Milvus expression from filters."""
        if not filters:
            return None

        expressions = []
        for k, v in filters.items():
            if isinstance(v, (list, tuple)):
                # For array values, use json_contains_any
                values_str = json.dumps(v)
                expr = f'json_contains_any(meta_data["{k}"], {values_str})'
            elif isinstance(v, str):
                # For string values
                expr = f'meta_data["{k}"] == "{v}"'
            elif isinstance(v, bool):
                # For boolean values
                expr = f'meta_data["{k}"] == {str(v).lower()}'
            elif isinstance(v, (int, float)):
                # For numeric values
                expr = f'meta_data["{k}"] == {v}'
            elif v is None:
                # For null values
                expr = f'meta_data["{k}"] is null'
            else:
                # For other types, convert to string
                expr = f'meta_data["{k}"] == "{str(v)}"'

            expressions.append(expr)

        if expressions:
            return " and ".join(expressions)
        return None

    def _doc_id(self, base_id: str, content_hash: str, user_id: Optional[str]) -> str:
        """Deterministic primary key with the owner folded in. The shared bucket keeps the legacy id."""
        if user_id:
            return md5(f"{base_id}_{content_hash}_{user_id}".encode()).hexdigest()
        return md5(f"{base_id}_{content_hash}".encode()).hexdigest()

    def _user_scope_expr(self, user_id: Optional[str]) -> Optional[str]:
        """Owner scope for a search: the caller's own chunks plus the shared (null) bucket.

        user_id=None returns None (no scope, admin sees everything).
        """
        if not user_id:
            return None
        return f'({self.USER_ID_KEY} == "{_quote(user_id)}" or {self.USER_ID_KEY} is null)'

    def _scoped_expr(self, filters: Optional[Dict[str, Any]], user_id: Optional[str]) -> Optional[str]:
        """Combine the caller's metadata filter with the owner scope.

        The owner scope is OR-based (own OR shared), so it is parenthesized and
        AND-ed with the metadata filter rather than flattened into it.
        """
        user_id = normalize_user_id(user_id)
        base = self._build_expr(filters)
        scope = self._user_scope_expr(user_id)
        if base and scope:
            return f"({base}) and {scope}"
        return scope or base

    async def _async_content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Async counterpart to content_hash_exists used by async_upsert."""
        expr = self._content_hash_expr(content_hash, normalize_user_id(user_id))
        scroll_result = await self.async_client.query(
            collection_name=self.collection,
            filter=expr,
            output_fields=["id"],
            limit=1,
        )
        return len(scroll_result) > 0

    async def _async_delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Async counterpart to _delete_by_content_hash used by async_upsert."""
        expr = self._content_hash_expr(content_hash, normalize_user_id(user_id), scope_none_to_shared=True)
        await self.async_client.delete(collection_name=self.collection, filter=expr)
        log_info(f"Deleted documents with content_hash '{content_hash}' from collection '{self.collection}'.")
        return True

    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            # Fetch the full row so we can do a complete upsert. Milvus only supports
            # partial-field upsert from 2.6.2+, so we read every field and rewrite it.
            # Vector fields are listed explicitly because some Milvus versions exclude
            # them from output_fields=["*"].
            search_expr = f'content_id == "{_quote(content_id)}"'
            output_fields = (
                ["*", "dense_vector", "sparse_vector"] if self.search_type == SearchType.hybrid else ["*", "vector"]
            )
            results = self.client.query(
                collection_name=self.collection,
                filter=search_expr,
                output_fields=output_fields,
            )

            if not results:
                log_debug(f"No documents found with content_id: {content_id}")
                return

            # Owner is never caller-writable; strip it so metadata can't reassign the chunk's tenant.
            safe_metadata = {k: v for k, v in metadata.items() if k != self.USER_ID_KEY}

            updated_count = 0
            for row in results:
                current_metadata = self._decode_json_field(row.get("meta_data"), default={})
                if not isinstance(current_metadata, dict):
                    current_metadata = {}

                updated_metadata = {**current_metadata, **safe_metadata}

                # Rebuild the full row, preserving the existing owner field.
                new_row: Dict[str, Any] = dict(row)
                new_row["meta_data"] = json.dumps(updated_metadata)
                if "filters" in row:
                    current_filters = self._decode_json_field(row.get("filters"), default={})
                    if not isinstance(current_filters, dict):
                        current_filters = {}
                    new_row["filters"] = json.dumps({**current_filters, **safe_metadata})

                usage_value = row.get("usage")
                if isinstance(usage_value, (dict, list)):
                    new_row["usage"] = json.dumps(usage_value)
                elif usage_value is None:
                    new_row["usage"] = "{}"

                self.client.upsert(
                    collection_name=self.collection,
                    data=[new_row],
                )
                updated_count += 1

            log_debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.hybrid]
