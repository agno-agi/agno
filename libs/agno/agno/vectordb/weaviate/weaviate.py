import asyncio
import json
import uuid
from hashlib import md5
from os import getenv
from typing import Any, Dict, List, Optional, Union

try:
    from warnings import filterwarnings

    import weaviate
    from weaviate import WeaviateAsyncClient
    from weaviate.classes.config import Configure, DataType, Property, Tokenization, VectorDistances
    from weaviate.classes.init import Auth
    from weaviate.classes.query import Filter

    filterwarnings("ignore", category=ResourceWarning)
except ImportError:
    raise ImportError("Weaviate is not installed. Install using 'pip install weaviate-client'.")

from agno.filters import FilterExpr
from agno.exceptions import EmbeddingError
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger
from agno.vectordb.base import VectorDb, aembed_before_replace, embed_before_replace, is_rate_limit_error, raise_embedding_failures
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate.index import Distance, VectorIndex


class Weaviate(VectorDb):
    """
    Weaviate class for managing vector operations with Weaviate vector database (v4 client).
    """

    # Owner property. user_id=None writes to the shared (null) bucket and reads unscoped.
    USER_ID_KEY: str = "user_id"

    def __init__(
        self,
        # Connection/Client params
        wcd_url: Optional[str] = None,
        wcd_api_key: Optional[str] = None,
        client: Optional[weaviate.WeaviateClient] = None,
        local: bool = False,
        # Collection params
        collection: str = "default",
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        vector_index: VectorIndex = VectorIndex.HNSW,
        distance: Distance = Distance.COSINE,
        # Search/Embedding params
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        reranker: Optional[Reranker] = None,
        hybrid_search_alpha: float = 0.5,
    ):
        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            connection_identifier = wcd_url or "local" if local else "default"
            seed = f"{connection_identifier}#{collection}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        # Connection setup
        self.wcd_url = wcd_url or getenv("WCD_URL")
        self.wcd_api_key = wcd_api_key or getenv("WCD_API_KEY")
        self.local = local
        self.client = client
        self.async_client = None

        # Collection setup
        self.collection = collection
        self.vector_index = vector_index
        self.distance = distance
        # Whether the live collection supports isolation; resolved lazily on first use.
        self._owner_property_exists: Optional[bool] = None

        # Embedder setup
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder

        # Search setup
        self.search_type: SearchType = search_type
        self.reranker: Optional[Reranker] = reranker
        self.hybrid_search_alpha = hybrid_search_alpha

    def get_client(self) -> weaviate.WeaviateClient:
        """Initialize and return a Weaviate client instance.

        Attempts to create a client using WCD (Weaviate Cloud Deployment) credentials if provided,
        otherwise falls back to local connection. Maintains a singleton pattern by reusing
        an existing client if already initialized.

        Returns:
            weaviate.WeaviateClient: An initialized Weaviate client instance.
        """
        if self.client is None:
            if self.wcd_url and self.wcd_api_key and not self.local:
                log_info("Initializing Weaviate Cloud client")
                self.client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=self.wcd_url, auth_credentials=Auth.api_key(self.wcd_api_key)
                )
            else:
                log_info("Initializing local Weaviate client")
                self.client = weaviate.connect_to_local()

        if not self.client.is_connected():  # type: ignore
            self.client.connect()  # type: ignore

        if not self.client.is_ready():  # type: ignore
            raise Exception("Weaviate client is not ready")

        return self.client

    async def get_async_client(self) -> WeaviateAsyncClient:
        """Get or create the async client."""
        if self.async_client is None:
            if self.wcd_url and self.wcd_api_key and not self.local:
                log_info("Initializing Weaviate Cloud async client")
                self.async_client = weaviate.use_async_with_weaviate_cloud(
                    cluster_url=self.wcd_url,
                    auth_credentials=Auth.api_key(self.wcd_api_key),  # type: ignore
                )
            else:
                log_info("Initializing local Weaviate async client")
                self.async_client = weaviate.use_async_with_local()  # type: ignore

        if not self.async_client.is_connected():  # type: ignore
            await self.async_client.connect()  # type: ignore

        if not await self.async_client.is_ready():  # type: ignore
            raise ConnectionError("Weaviate async client is not ready")

        return self.async_client  # type: ignore

    def _collection_properties(self) -> List[Property]:
        """The properties of the collection schema."""
        return [
            Property(name="name", data_type=DataType.TEXT),
            Property(name="content", data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
            Property(name="meta_data", data_type=DataType.TEXT),
            Property(name="content_id", data_type=DataType.TEXT),
            Property(name="content_hash", data_type=DataType.TEXT),
            # FIELD tokenization so the owner matches exactly; WORD would leak across owners.
            Property(name=self.USER_ID_KEY, data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        ]

    def create(self) -> None:
        """Create the collection in Weaviate if it doesn't exist."""
        if not self.exists():
            log_debug(f"Creating collection '{self.collection}' in Weaviate.")
            self.get_client().collections.create(
                name=self.collection,
                properties=self._collection_properties(),
                vectorizer_config=Configure.Vectorizer.none(),
                vector_index_config=self.get_vector_index_config(self.vector_index, self.distance),
                # Null-state indexing so the shared bucket can be filtered as user_id IS NULL.
                inverted_index_config=Configure.inverted_index(index_null_state=True),
            )
            log_debug(f"Collection '{self.collection}' created in Weaviate.")
            self._owner_property_exists = True

    async def async_create(self) -> None:
        client = await self.get_async_client()
        try:
            if not await client.collections.exists(self.collection):
                await client.collections.create(
                    name=self.collection,
                    properties=self._collection_properties(),
                    vectorizer_config=Configure.Vectorizer.none(),
                    vector_index_config=self.get_vector_index_config(self.vector_index, self.distance),
                    # Null-state indexing so the shared bucket can be filtered as user_id IS NULL.
                    inverted_index_config=Configure.inverted_index(index_null_state=True),
                )
                log_debug(f"Collection '{self.collection}' created in Weaviate asynchronously.")
                self._owner_property_exists = True
        finally:
            await client.close()

    def _user_id_property_exists(self) -> bool:
        """Whether the live collection can support per-user isolation.

        Needs both the ``user_id`` property and ``index_null_state=True``, which the shared-bucket
        ``is_none`` filters require and which is only settable at creation. Cached after the first
        lookup.
        """
        if self._owner_property_exists is None:
            try:
                client = self.get_client()
                if not client.collections.exists(self.collection):
                    # No live collection yet — it will be created with both.
                    self._owner_property_exists = True
                    return True
                config = client.collections.get(self.collection).config.get()
                has_property = any(prop.name == self.USER_ID_KEY for prop in config.properties)
                inverted_index = getattr(config, "inverted_index_config", None)
                null_state_indexed = bool(getattr(inverted_index, "index_null_state", False))
                self._owner_property_exists = has_property and null_state_indexed
            except Exception:
                # Assume migrated for this call only; caching a blip would permanently mask a legacy collection.
                log_warning(
                    f"Could not inspect collection '{self.collection}' for isolation support; "
                    "proceeding as migrated for this operation."
                )
                return True
        return self._owner_property_exists

    def _require_owner_property(self, user_id: Optional[str]) -> bool:
        """Gate every ``user_id``-property reference on the live schema.

        Returns False when the property is missing and the call is unscoped, so the caller can fall
        back to queries that never mention it. A scoped call on an unmigrated collection raises.
        """
        if self._user_id_property_exists():
            return True
        if user_id is None:
            return False
        # The cache may predate a migration run in this process — re-inspect once before refusing.
        self._owner_property_exists = None
        if self._user_id_property_exists():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but collection '{self.collection}' does not support "
            "per-user isolation: it lacks the 'user_id' property and/or null-state indexing "
            "(index_null_state=True, which the is_none shared-bucket filters require). "
            "index_null_state can only be set at collection creation, so recreate the collection "
            "and re-ingest — adding the property alone is not sufficient."
        )

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document with the given content hash exists in the collection.

        Args:
            content_hash (str): The content hash to check.
            user_id (Optional[str]): The owner to check. ``None`` scopes to the shared (null)
                bucket alone, the same bucket ``_delete_by_content_hash`` clears.
        """
        self._validate_user_id(user_id)
        # Before the query: on an unmigrated collection the unscoped check matches content_hash alone.
        scope_to_owner = self._require_owner_property(user_id)
        collection = self.get_client().collections.get(self.collection)
        where = Filter.by_property("content_hash").equal(content_hash)
        if scope_to_owner:
            if user_id is not None:
                where = where & Filter.by_property(self.USER_ID_KEY).equal(user_id)
            else:
                where = where & Filter.by_property(self.USER_ID_KEY).is_none(True)
        result = collection.query.fetch_objects(limit=1, filters=where)
        return len(result.objects) > 0

    def name_exists(self, name: str) -> bool:
        """
        Validate if a document with the given name exists in Weaviate.

        Args:
            name (str): The name of the document to check.

        Returns:
            bool: True if a document with the given name exists, False otherwise.
        """
        collection = self.get_client().collections.get(self.collection)
        result = collection.query.fetch_objects(
            limit=1,
            filters=Filter.by_property("name").equal(name),
        )
        return len(result.objects) > 0

    async def async_name_exists(self, name: str) -> bool:
        """
        Asynchronously validate if a document with the given name exists in Weaviate.

        Args:
            name (str): The name of the document to check.

        Returns:
            bool: True if a document with the given name exists, False otherwise.
        """
        client = await self.get_async_client()
        try:
            collection = client.collections.get(self.collection)
            result = await collection.query.fetch_objects(
                limit=1,
                filters=Filter.by_property("name").equal(name),
            )
            return len(result.objects) > 0
        finally:
            await client.close()

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Insert documents into Weaviate.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
            user_id (Optional[str]): Owner of these chunks. ``None`` writes to the shared bucket.
        """
        self._validate_user_id(user_id)
        # Only stamp when the schema has the property — Weaviate would auto-create a mis-configured one.
        stamp_owner = self._require_owner_property(user_id)
        log_debug(f"Inserting {len(documents)} documents into Weaviate.")
        collection = self.get_client().collections.get(self.collection)

        for document in documents:
            document.embed(embedder=self.embedder)
            if document.embedding is None:
                log_error(f"Document embedding is None: {document.name}")
                continue

            cleaned_content = document.content.replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            record_id = self._scoped_record_id(base_id, content_hash, user_id)
            doc_uuid = uuid.UUID(hex=record_id[:32])

            # Merge filters with metadata
            meta_data = document.meta_data or {}
            if filters:
                meta_data.update(filters)

            # Serialize meta_data to JSON string
            meta_data_str = json.dumps(meta_data) if meta_data else None

            properties: Dict[str, Any] = {
                "name": document.name,
                "content": cleaned_content,
                "meta_data": meta_data_str,
                "content_id": document.content_id,
                "content_hash": content_hash,
            }
            if stamp_owner:
                properties[self.USER_ID_KEY] = user_id

            collection.data.insert(
                properties=properties,
                vector=document.embedding,
                uuid=doc_uuid,
            )
            log_debug(f"Inserted document: {document.name} ({meta_data})")

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Insert documents into Weaviate asynchronously.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
            user_id (Optional[str]): Owner of these chunks. ``None`` writes to the shared bucket.
        """
        self._validate_user_id(user_id)
        # Only stamp when the schema has the property — Weaviate would auto-create a mis-configured one.
        stamp_owner = self._require_owner_property(user_id)
        log_debug(f"Inserting {len(documents)} documents into Weaviate asynchronously.")
        if not documents:
            return

        # Apply batch embedding logic
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

        client = await self.get_async_client()
        try:
            collection = client.collections.get(self.collection)

            # Process documents first
            for document in documents:
                try:
                    if document.embedding is None:
                        log_error(f"Document embedding is None: {document.name}")
                        continue

                    # Clean content and generate UUID
                    cleaned_content = document.content.replace("\x00", "\ufffd")
                    # Include content_hash in ID to ensure uniqueness across different content hashes
                    base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                    record_id = self._scoped_record_id(base_id, content_hash, user_id)
                    doc_uuid = uuid.UUID(hex=record_id[:32])

                    # Merge filters with metadata
                    meta_data = document.meta_data or {}
                    if filters:
                        meta_data.update(filters)

                    # Serialize meta_data to JSON string
                    meta_data_str = json.dumps(meta_data) if meta_data else None

                    # Insert properties and vector separately
                    properties = {
                        "name": document.name,
                        "content": cleaned_content,
                        "meta_data": meta_data_str,
                        "content_id": document.content_id,
                        "content_hash": content_hash,
                    }
                    if stamp_owner:
                        properties[self.USER_ID_KEY] = user_id

                    # Use the API correctly - properties, vector and uuid are separate parameters
                    await collection.data.insert(properties=properties, vector=document.embedding, uuid=doc_uuid)

                    log_debug(f"Inserted document asynchronously: {document.name}")

                except Exception as e:
                    log_error(f"Error inserting document {document.name}: {str(e)}: {str(e)}")
        finally:
            await client.close()

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents into Weaviate.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
        """
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        embed_before_replace(documents, self.embedder)
        self._validate_user_id(user_id)
        # Up front so a scoped upsert on an unmigrated collection raises before any read or write.
        self._require_owner_property(user_id)
        log_debug(f"Upserting {len(documents)} documents into Weaviate.")
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)
        self.insert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents into Weaviate asynchronously.
        When documents with the same ID already exist, they will be replaced.
        Otherwise, new documents will be created.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
            user_id (Optional[str]): Owner of these chunks for per-user isolation.
        """
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        await aembed_before_replace(documents, self.embedder)
        self._validate_user_id(user_id)
        # Up front so a scoped upsert on an unmigrated collection raises before any read or write.
        self._require_owner_property(user_id)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)
        await self.async_insert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)
        return

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a search based on the configured search type.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.
            user_id (Optional[str]): Restrict results to this user's chunks plus the shared
                bucket. ``None`` applies no scope.

        Returns:
            List[Document]: List of matching documents.
        """
        self._validate_user_id(user_id)
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Weaviate. No filters will be applied.")
            filters = None
        if self.search_type == SearchType.vector:
            return self.vector_search(query, limit, filters, user_id=user_id)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query, limit, filters, user_id=user_id)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit, filters, user_id=user_id)
        else:
            log_error(f"Invalid search type '{self.search_type}'.")
            return []

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a search based on the configured search type asynchronously.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.
            user_id (Optional[str]): Restrict results to this user's chunks plus the shared
                bucket. ``None`` applies no scope.

        Returns:
            List[Document]: List of matching documents.
        """
        self._validate_user_id(user_id)
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Weaviate. No filters will be applied.")
            filters = None
        if self.search_type == SearchType.vector:
            return await self.async_vector_search(query, limit, filters, user_id=user_id)
        elif self.search_type == SearchType.keyword:
            return await self.async_keyword_search(query, limit, filters, user_id=user_id)
        elif self.search_type == SearchType.hybrid:
            return await self.async_hybrid_search(query, limit, filters, user_id=user_id)
        else:
            log_error(f"Invalid search type '{self.search_type}'.")
            return []

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Error getting embedding for query: {query}")
                return []

            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._scoped_filter_expression(filters, user_id)

            response = collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                filters=filter_expr,
            )

            search_results: List[Document] = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except EmbeddingError:
            # A failed query embedding is not a store problem: let it surface instead
            # of returning an empty result set that looks like "no matches".
            raise
        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            self.get_client().close()

    async def async_vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a vector search in Weaviate asynchronously.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for query: {query}")
            return []

        search_results = []
        client = await self.get_async_client()
        try:
            collection = client.collections.get(self.collection)
            filter_expr = self._scoped_filter_expression(filters, user_id)

            response = await collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                filters=filter_expr,
            )

            search_results = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            await client.close()

    def keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)
        try:
            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._scoped_filter_expression(filters, user_id)

            response = collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                filters=filter_expr,
            )

            search_results: List[Document] = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            self.get_client().close()

    async def async_keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a keyword search in Weaviate asynchronously.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)

        search_results = []
        client = await self.get_async_client()
        try:
            collection = client.collections.get(self.collection)

            filter_expr = self._scoped_filter_expression(filters, user_id)
            response = await collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                filters=filter_expr,
            )

            search_results = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            await client.close()

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Error getting embedding for query: {query}")
                return []

            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._scoped_filter_expression(filters, user_id)

            response = collection.query.hybrid(
                query=query,
                vector=query_embedding,
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                query_properties=["content"],
                alpha=self.hybrid_search_alpha,
                filters=filter_expr,
            )

            search_results: List[Document] = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except EmbeddingError:
            # A failed query embedding is not a store problem: let it surface instead
            # of returning an empty result set that looks like "no matches".
            raise
        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            self.get_client().close()

    async def async_hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Perform a hybrid search combining vector and keyword search in Weaviate asynchronously.

        Args:
            query (str): The keyword query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        # Outside the try so a scoped search raises instead of returning [].
        self._require_owner_property(user_id)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for query: {query}")
            return []

        search_results = []
        client = await self.get_async_client()
        try:
            collection = client.collections.get(self.collection)

            filter_expr = self._scoped_filter_expression(filters, user_id)
            response = await collection.query.hybrid(
                query=query,
                vector=query_embedding,
                limit=limit,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
                query_properties=["content"],
                alpha=self.hybrid_search_alpha,
                filters=filter_expr,
            )

            search_results = self.get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")

            return search_results

        except Exception:
            logger.exception("Error searching for documents")
            return []

        finally:
            await client.close()

    def exists(self) -> bool:
        """Check if the collection exists in Weaviate."""
        return self.get_client().collections.exists(self.collection)

    async def async_exists(self) -> bool:
        """Check if the collection exists in Weaviate asynchronously."""
        client = await self.get_async_client()
        try:
            return await client.collections.exists(self.collection)
        finally:
            await client.close()

    def drop(self) -> None:
        """Delete the Weaviate collection."""
        if self.exists():
            log_debug(f"Deleting collection '{self.collection}' from Weaviate.")
            self.get_client().collections.delete(self.collection)
            # The next collection under this name is created with both — re-resolve lazily.
            self._owner_property_exists = None

    async def async_drop(self) -> None:
        """Delete the Weaviate collection asynchronously."""
        if await self.async_exists():
            log_debug(f"Deleting collection '{self.collection}' from Weaviate asynchronously.")
            client = await self.get_async_client()
            try:
                await client.collections.delete(self.collection)
                # See ``drop`` — re-resolve the cache lazily.
                self._owner_property_exists = None
            finally:
                await client.close()

    def optimize(self) -> None:
        """Optimize the vector database (e.g., rebuild indexes)."""
        pass

    def delete(self) -> bool:
        """Delete all records from the database."""
        self.drop()
        return True

    def delete_by_id(self, id: str) -> bool:
        """Delete document by ID."""
        try:
            try:
                doc_uuid = uuid.UUID(hex=id[:32]) if len(id) == 32 else uuid.UUID(id)
            except ValueError:
                log_info(f"Invalid UUID format for ID '{id}' - treating as non-existent")
                return True

            collection = self.get_client().collections.get(self.collection)

            if not collection.data.exists(doc_uuid):
                log_info(f"Document with ID {id} does not exist")
                return True

            collection.data.delete_by_id(doc_uuid)
            log_info(f"Deleted document with ID '{id}' from collection '{self.collection}'.")
            return True
        except Exception:
            logger.exception(f"Error deleting document by ID '{id}'")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete content by name using direct filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)

            collection.data.delete_many(where=Filter.by_property("name").equal(name))

            log_info(f"Deleted documents with name '{name}' from collection '{self.collection}'.")
            return True

        except Exception:
            logger.exception(f"Error deleting documents by name '{name}'")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete content by metadata using direct filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)

            # Build filter for metadata search
            filter_expr = self._build_filter_expression(metadata)
            if filter_expr is None:
                log_info(f"No valid filter could be built for metadata: {metadata}")
                return False

            collection.data.delete_many(where=filter_expr)

            log_info(f"Deleted documents with metadata '{metadata}' from collection '{self.collection}'.")
            return True

        except Exception:
            logger.exception(f"Error deleting documents by metadata '{metadata}'")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete content by content ID using direct filter deletion.

        Args:
            content_id (str): The content ID to delete.
            user_id (Optional[str]): Restrict the delete to this owner's chunks. ``None`` ignores ownership.
        """
        self._validate_user_id(user_id)
        # Before the try so a scoped delete raises instead of returning False; unscoped needs no fallback.
        self._require_owner_property(user_id)
        try:
            collection = self.get_client().collections.get(self.collection)

            where = Filter.by_property("content_id").equal(content_id)
            if user_id is not None:
                where = where & Filter.by_property(self.USER_ID_KEY).equal(user_id)

            result = collection.data.delete_many(where=where)

            log_info(f"Deleted documents with content_id '{content_id}' from collection '{self.collection}'.")
            return result.successful > 0

        except Exception:
            logger.exception(f"Error deleting documents by content_id '{content_id}'")
            return False

    def delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Delete content by content hash using direct filter deletion.

        Args:
            content_hash (str): The content hash to delete.
            user_id (Optional[str]): Restrict the delete to this owner's bucket. ``None`` scopes to
                the shared bucket only so it can't wipe every owner.
        """
        self._validate_user_id(user_id)
        return self._delete_by_content_hash(content_hash, user_id=user_id)

    def get_vector_index_config(self, index_type: VectorIndex, distance_metric: Distance):
        """
        Returns the appropriate vector index configuration with the specified distance metric.

        Args:
            index_type (VectorIndex): Type of vector index (HNSW, FLAT, DYNAMIC).
            distance_metric (Distance): Distance metric (COSINE, DOT, etc).

        Returns:
            Configure.VectorIndex: The configured vector index instance.
        """
        # Get the Weaviate distance metric
        distance = getattr(VectorDistances, distance_metric.name)

        # Define vector index configurations based on enum value
        configs = {
            VectorIndex.HNSW: Configure.VectorIndex.hnsw(distance_metric=distance),
            VectorIndex.FLAT: Configure.VectorIndex.flat(distance_metric=distance),
            VectorIndex.DYNAMIC: Configure.VectorIndex.dynamic(distance_metric=distance),
        }

        return configs[index_type]

    def get_search_results(self, response: Any) -> List[Document]:
        """
        Create search results from the Weaviate response.

        Args:
            response (Any): The Weaviate response object.

        Returns:
            List[Document]: List of matching documents.
        """
        search_results: List[Document] = []
        for obj in response.objects:
            properties = obj.properties
            meta_data = json.loads(properties["meta_data"]) if properties.get("meta_data") else {}
            embedding = obj.vector["default"] if isinstance(obj.vector, dict) else obj.vector

            search_results.append(
                Document(
                    name=properties.get("name"),
                    meta_data=meta_data,
                    content=properties.get("content", ""),
                    embedder=self.embedder,
                    embedding=embedding,
                    content_id=properties.get("content_id"),
                )
            )

        return search_results

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    def _build_filter_expression(self, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]):
        """
        Build a filter expression for Weaviate queries.

        Args:
            filters (Optional[Dict[str, Any]]): Dictionary of filters to apply.

        Returns:
            Optional[Filter]: The constructed filter expression, or None if no filters provided.
        """
        if not filters:
            return None
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Weaviate. No filters will be applied.")
            return None
        try:
            # Create a filter for each key-value pair
            filter_conditions = []
            for key, value in filters.items():
                # Create a pattern to match in the JSON string
                if isinstance(value, (list, tuple)):
                    # For list values
                    pattern = f'"{key}": {json.dumps(value)}'
                else:
                    # For single values
                    pattern = f'"{key}": "{value}"'

                # Add the filter condition using like operator
                filter_conditions.append(Filter.by_property("meta_data").like(f"*{pattern}*"))

            # If we have multiple conditions, combine them
            if len(filter_conditions) > 1:
                # Use the first condition as base and chain the rest
                filter_expr = filter_conditions[0]
                for condition in filter_conditions[1:]:
                    filter_expr = filter_expr & condition
                return filter_expr
            elif filter_conditions:
                return filter_conditions[0]

        except Exception:
            logger.exception("Error building filter expression")
            return None

        return None

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """Reject owner values FIELD tokenization would fold into the shared (null) bucket.

        An empty or whitespace-only owner indexes as null and is swept in by the ``is_none`` half of
        every scope clause. Use ``None`` for unscoped access.
        """
        if user_id is not None and user_id.strip() == "":
            raise ValueError("user_id must not be empty or whitespace-only")

    def _scoped_record_id(self, base_id: str, content_hash: str, user_id: Optional[str]) -> str:
        """Fold the owner into the record id so two users' identical content get distinct uuids.

        ``None`` keeps the base id. The base id is digested before the owner is folded in so it
        cannot slide across the '_' boundary: ('doc_1', 'alice') and ('doc', '1_alice') would collide.
        """
        record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
        if user_id is None:
            return record_id
        return md5(f"{record_id}_{user_id}".encode()).hexdigest()

    def _user_scope_filter(self, user_id: Optional[str]):
        """The per-user read scope: own rows OR shared (null). ``None`` returns no scope."""
        if user_id is None:
            return None
        return Filter.by_property(self.USER_ID_KEY).equal(user_id) | Filter.by_property(self.USER_ID_KEY).is_none(True)

    def _scoped_filter_expression(
        self, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]], user_id: Optional[str]
    ):
        """AND the per-user scope into the user-supplied metadata filter."""
        base = self._build_filter_expression(filters)
        scope = self._user_scope_filter(user_id)
        if scope is None:
            return base
        if base is None:
            return scope
        return base & scope

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the collection.

        Args:
            id (str): The document ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        try:
            doc_uuid = uuid.UUID(hex=id[:32]) if len(id) == 32 else uuid.UUID(id)
            collection = self.get_client().collections.get(self.collection)
            return collection.data.exists(doc_uuid)
        except ValueError:
            log_info(f"Invalid UUID format for ID '{id}' - treating as non-existent")
            return False
        except Exception:
            logger.exception(f"Error checking if ID '{id}' exists")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        # Never let caller metadata reassign chunk ownership.
        metadata = {k: v for k, v in metadata.items() if k != self.USER_ID_KEY}
        try:
            weaviate_client = self.get_client()
            collection = weaviate_client.collections.get(self.collection)

            # Query for objects with the given content_id
            query_result = collection.query.fetch_objects(  # type: ignore
                filters=Filter.by_property("content_id").equal(content_id),
                limit=1000,  # Get all matching objects
            )

            if not query_result.objects:
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Update each matching object
            updated_count = 0
            for obj in query_result.objects:
                # Get current properties
                current_properties = obj.properties or {}

                # Merge existing metadata with new metadata
                updated_properties = dict(current_properties)

                # meta_data is a JSON string: parse, merge, re-serialize. Emitting a typeless object property 422s.
                existing_meta = updated_properties.get("meta_data")
                if isinstance(existing_meta, str):
                    existing_meta = json.loads(existing_meta) if existing_meta else {}
                elif not isinstance(existing_meta, dict):
                    existing_meta = {}
                existing_meta.update(metadata)
                updated_properties["meta_data"] = json.dumps(existing_meta)

                # Update the object
                collection.data.update(uuid=obj.uuid, properties=updated_properties)
                updated_count += 1

            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception:
            logger.exception(f"Error updating metadata for content_id '{content_id}'")
            raise

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by content hash using direct filter deletion.

        Args:
            content_hash (str): The content hash to delete.
            user_id (Optional[str]): Restrict the delete to this owner's chunks. ``None`` scopes to
                the shared (null) bucket so a shared re-upsert never wipes an owner's row.
        """
        # Before the try so a scoped delete raises instead of returning False; unscoped matches content_hash alone.
        scope_to_owner = self._require_owner_property(user_id)
        try:
            collection = self.get_client().collections.get(self.collection)

            # Build filter for content_hash search
            filter_expr = Filter.by_property("content_hash").equal(content_hash)
            if scope_to_owner:
                if user_id is not None:
                    filter_expr = filter_expr & Filter.by_property(self.USER_ID_KEY).equal(user_id)
                else:
                    filter_expr = filter_expr & Filter.by_property(self.USER_ID_KEY).is_none(True)

            collection.data.delete_many(where=filter_expr)

            log_info(f"Deleted documents with content_hash '{content_hash}' from collection '{self.collection}'.")
            return True

        except Exception:
            logger.exception(f"Error deleting documents by content_hash '{content_hash}'")
            return False

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]
