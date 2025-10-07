import asyncio
import json
import uuid
from hashlib import md5
from os import getenv
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from warnings import filterwarnings

    import weaviate
    from weaviate.client import WeaviateClient, WeaviateAsyncClient
    from weaviate.auth import AuthApiKey
    from weaviate.classes.config import (
        Configure,
        Property,
        DataType,
        Tokenization,
        VectorDistances,
    )
    from weaviate.classes.query import Filter

    filterwarnings("ignore", category=ResourceWarning)
except ImportError:
    raise ImportError("Weaviate is not installed. Install using 'pip install weaviate-client'.")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate.index import Distance, VectorIndex


class Weaviate(VectorDb):
    """
    Weaviate class for managing vector operations with Weaviate vector database (v4 client).
    This class is rewritten to be compatible with weaviate-client >= v4.0.0
    """

    def __init__(
        self,
        wcd_url: Optional[str] = None,
        wcd_api_key: Optional[str] = None,
        client: Optional[WeaviateClient] = None,
        async_client: Optional[WeaviateAsyncClient] = None,
        collection: str = "default",
        vector_index: VectorIndex = VectorIndex.HNSW,
        distance: Distance = Distance.COSINE,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        reranker: Optional[Reranker] = None,
        hybrid_search_alpha: float = 0.5,
    ):
        self.wcd_url = wcd_url or getenv("WCD_URL")
        self.wcd_api_key = wcd_api_key or getenv("WCD_API_KEY")
        
        self._client = client
        self._async_client = async_client
        
        self.collection = collection
        self.vector_index = vector_index
        self.distance = distance

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder
            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder

        self.search_type: SearchType = search_type
        self.reranker: Optional[Reranker] = reranker
        self.hybrid_search_alpha = hybrid_search_alpha

    @staticmethod
    def _get_doc_uuid(document: Document) -> Tuple[uuid.UUID, str]:
        cleaned_content = document.content.replace("\x00", "\ufffd")
        content_hash = md5(cleaned_content.encode()).hexdigest()
        doc_uuid = uuid.UUID(hex=content_hash[:32])
        return doc_uuid, cleaned_content

    def get_client(self) -> WeaviateClient:
        if self._client is None:
            if not self.wcd_url:
                raise ValueError("Weaviate URL (wcd_url) is not set.")

            log_info(f"Initializing Weaviate client for URL: {self.wcd_url}")
            
            auth_credentials = AuthApiKey(self.wcd_api_key) if self.wcd_api_key else None
            
            self._client = weaviate.connect_to_custom(
                http_host=self.wcd_url.split("://")[1].split(":")[0],
                http_port=int(self.wcd_url.split(":")[-1]),
                http_secure=self.wcd_url.startswith("https"),
                grpc_host=self.wcd_url.split("://")[1].split(":")[0],
                grpc_port=50051,
                grpc_secure=self.wcd_url.startswith("https"),
                auth_credentials=auth_credentials
            )

        if not self._client.is_ready():
            raise ConnectionError("Weaviate client is not ready")

        return self._client

    async def get_async_client(self) -> WeaviateAsyncClient:
        if self._async_client is None:
            if not self.wcd_url:
                raise ValueError("Weaviate URL (wcd_url) is not set.")

            log_info(f"Initializing Weaviate async client for URL: {self.wcd_url}")
            
            auth_credentials = AuthApiKey(self.wcd_api_key) if self.wcd_api_key else None
            
            # Correct way to initialize async client in v4
            from weaviate.connect import ConnectionParams
            
            parsed_url = urlparse(self.wcd_url)
            
            connection_params = ConnectionParams.from_params(
                http_host=parsed_url.hostname,
                http_port=parsed_url.port,
                http_secure=parsed_url.scheme == "https",
                grpc_host=parsed_url.hostname,
                grpc_port=50051, # Default gRPC port
                grpc_secure=parsed_url.scheme == "https",
            )
            
            self._async_client = WeaviateAsyncClient(
                connection_params=connection_params,
                auth_client_secret=auth_credentials
            )

        if not self._async_client.is_connected():
            await self._async_client.connect()
        
        if not await self._async_client.is_ready():
            raise ConnectionError("Weaviate async client is not ready")
            
        return self._async_client

    def create(self) -> None:
        if not self.exists():
            log_debug(f"Creating collection '{self.collection}' in Weaviate.")
            self.get_client().collections.create(
                name=self.collection,
                properties=[
                    Property(name="name", data_type=DataType.TEXT),
                    Property(name="content", data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
                    Property(name="meta_data", data_type=DataType.TEXT),
                    Property(name="content_id", data_type=DataType.TEXT),
                    Property(name="content_hash", data_type=DataType.TEXT),
                ],
                vectorizer_config=Configure.Vectorizer.none(),
                vector_index_config=self._get_vector_index_config(),
            )
            log_debug(f"Collection '{self.collection}' created in Weaviate.")

    async def async_create(self) -> None:
        client = await self.get_async_client()
        if not await client.collections.exists(self.collection):
            log_debug(f"Creating collection '{self.collection}' in Weaviate asynchronously.")
            await client.collections.create(
                name=self.collection,
                properties=[
                    Property(name="name", data_type=DataType.TEXT),
                    Property(name="content", data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
                    Property(name="meta_data", data_type=DataType.TEXT),
                    Property(name="content_id", data_type=DataType.TEXT),
                    Property(name="content_hash", data_type=DataType.TEXT),
                ],
                vectorizer_config=Configure.Vectorizer.none(),
                vector_index_config=self._get_vector_index_config(),
            )
            log_debug(f"Collection '{self.collection}' created in Weaviate asynchronously.")

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document with the given content hash exists in the collection."""
        collection = self.get_client().collections.get(self.collection)
        result = collection.query.fetch_objects(
            limit=1,
            filters=Filter.by_property("content_hash").equal(content_hash),
        )
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
        except Exception as e:
            logger.error(f"Error checking async name existence: {e}")
            return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_debug(f"Inserting {len(documents)} documents into Weaviate.")
        collection = self.get_client().collections.get(self.collection)

        with collection.batch.dynamic() as batch:
            for document in documents:
                document.embed(embedder=self.embedder)
                if document.embedding is None:
                    logger.error(f"Document embedding is None: {document.name}")
                    continue

                properties = self._prepare_properties(document, content_hash, filters)
                doc_uuid = uuid.UUID(hex=md5(document.content.replace("\x00", "\ufffd").encode()).hexdigest()[:32])

                batch.add_object(
                    properties=properties,
                    uuid=doc_uuid,
                    vector=document.embedding
                )
        log_debug(f"Finished inserting {len(documents)} documents.")


    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        log_debug(f"Asynchronously inserting {len(documents)} documents.")
        if not documents:
            return

        client = await self.get_async_client()
        collection = client.collections.get(self.collection)

        # Embed all documents concurrently
        await asyncio.gather(*(doc.async_embed(embedder=self.embedder) for doc in documents))

        with collection.batch.dynamic() as batch:
            for document in documents:
                if document.embedding is None:
                    logger.error(f"Document embedding is None: {document.name}")
                    continue

                properties = self._prepare_properties(document, content_hash, filters)
                doc_uuid = uuid.UUID(hex=md5(document.content.replace("\x00", "\ufffd").encode()).hexdigest()[:32])
                
                batch.add_object(
                    properties=properties,
                    uuid=doc_uuid,
                    vector=document.embedding
                )
        log_debug(f"Finished async insertion of {len(documents)} documents.")
        
    def _prepare_properties(self, document: Document, content_hash: str, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cleaned_content = document.content.replace("\x00", "\ufffd")
        
        meta_data = document.meta_data.copy() if document.meta_data else {}
        if filters:
            meta_data.update(filters)
        meta_data_str = json.dumps(meta_data) if meta_data else "{}"

        return {
            "name": document.name,
            "content": cleaned_content,
            "meta_data": meta_data_str,
            "content_id": document.content_id,
            "content_hash": content_hash,
        }

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        # v4's batching handles upsert automatically if UUIDs are provided.
        # We generate deterministic UUIDs, so this insert is effectively an upsert.
        log_debug(f"Upserting {len(documents)} documents.")
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        log_debug(f"Async upserting {len(documents)} documents.")
        await self.async_insert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        if self.search_type == SearchType.vector:
            return self.vector_search(query, limit, filters)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query, limit, filters)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit, filters)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        if self.search_type == SearchType.vector:
            return await self.async_vector_search(query, limit, filters)
        elif self.search_type == SearchType.keyword:
            return await self.async_keyword_search(query, limit, filters)
        elif self.search_type == SearchType.hybrid:
            return await self.async_hybrid_search(query, limit, filters)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    def vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for query: {query}")
                return []

            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                filters=filter_expr,
                return_metadata=None, # No need for metadata in v4 this way
                return_properties=["name", "content", "meta_data", "content_id"],
            )

            search_results = self._get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during vector search: {e}")
            return []

    async def async_vector_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Perform a vector search in Weaviate asynchronously.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            query_embedding = await self.embedder.async_get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for query: {query}")
                return []

            client = await self.get_async_client()
            collection = client.collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = await collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                filters=filter_expr,
                return_metadata=None,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
            )

            search_results: List[Document] = self._get_search_results(response)
            return search_results
        except Exception as e:
            logger.error(f"Error during async vector search: {e}")
            return []

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        try:
            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=limit,
                filters=filter_expr,
                return_metadata=None,
                return_properties=["name", "content", "meta_data", "content_id"],
            )

            search_results = self._get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during keyword search: {e}")
            return []

    async def async_keyword_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Perform a keyword search in Weaviate asynchronously.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            client = await self.get_async_client()
            collection = client.collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = await collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=limit,
                filters=filter_expr,
                return_metadata=None,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
            )

            search_results: List[Document] = self._get_search_results(response)
            return search_results
        except Exception as e:
            logger.error(f"Error during async keyword search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for query: {query}")
                return []

            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = collection.query.hybrid(
                query=query,
                vector=query_embedding,
                query_properties=["content"],
                alpha=self.hybrid_search_alpha,
                limit=limit,
                filters=filter_expr,
                return_metadata=None,
                return_properties=["name", "content", "meta_data", "content_id"],
            )

            search_results = self._get_search_results(response)

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            return []

    async def async_hybrid_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Perform a hybrid search combining vector and keyword search in Weaviate asynchronously.

        Args:
            query (str): The keyword query.
            limit (int): Maximum number of results to return.

        Returns:
            List[Document]: List of matching documents.
        """
        try:
            query_embedding = await self.embedder.async_get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for query: {query}")
                return []

            client = await self.get_async_client()
            collection = client.collections.get(self.collection)
            filter_expr = self._build_filter_expression(filters)

            response = await collection.query.hybrid(
                query=query,
                vector=query_embedding,
                query_properties=["content"],
                limit=limit,
                alpha=self.hybrid_search_alpha,
                filters=filter_expr,
                return_metadata=None,
                return_properties=["name", "content", "meta_data", "content_id"],
                include_vector=True,
            )

            search_results: List[Document] = self._get_search_results(response)
            return search_results
        except Exception as e:
            logger.error(f"Error during async hybrid search: {e}")
            return []

    def exists(self) -> bool:
        return self.get_client().collections.exists(self.collection)

    async def async_exists(self) -> bool:
        client = await self.get_async_client()
        return await client.collections.exists(self.collection)

    async def async_close(self) -> None:
        """Close the async client if it exists."""
        if self._async_client and self._async_client.is_connected():
            await self._async_client.close()
            log_debug("Weaviate async client closed.")

    def drop(self) -> None:
        """Delete the Weaviate collection."""
        if self.exists():
            log_debug(f"Deleting collection '{self.collection}' from Weaviate.")
            self.get_client().collections.delete(self.collection)

    async def async_drop(self) -> None:
        """Delete the Weaviate collection asynchronously."""
        client = await self.get_async_client()
        if await client.collections.exists(self.collection):
            log_debug(f"Deleting collection '{self.collection}' from Weaviate asynchronously.")
            await client.collections.delete(self.collection)

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
            doc_uuid = uuid.UUID(hex=id[:32]) if len(id) == 32 else uuid.UUID(id)
            collection = self.get_client().collections.get(self.collection)
            
            if not collection.data.exists(doc_uuid):
                log_info(f"Document with ID {id} does not exist, skipping deletion.")
                return True

            collection.data.delete_by_id(doc_uuid)
            log_info(f"Deleted document with ID '{id}'.")
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID '{id}': {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete content by name using filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)
            collection.data.delete_many(where=Filter.by_property("name").equal(name))
            log_info(f"Deleted documents with name '{name}'.")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name '{name}': {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete content by metadata using filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)
            filter_expr = self._build_filter_expression(metadata)
            if filter_expr is None:
                log_info(f"No valid filter for metadata: {metadata}")
                return False

            result = collection.data.delete_many(where=filter_expr)
            log_info(f"Deletion result for metadata '{metadata}': {result}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata '{metadata}': {e}")
            return False
            
    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete content by content ID using direct filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)

            collection.data.delete_many(where=Filter.by_property("content_id").equal(content_id))

            log_info(f"Deleted documents with content_id '{content_id}' from collection '{self.collection}'.")
            return True

        except Exception as e:
            logger.error(f"Error deleting documents by content_id '{content_id}': {e}")
            return False

    def delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete content by content hash using direct filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)
            collection.data.delete_many(where=Filter.by_property("content_hash").equal(content_hash))
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_hash '{content_hash}': {e}")
            return False

    def _get_vector_index_config(self):
        """
        Returns the appropriate vector index configuration with the specified distance metric.

        Args:
            index_type (VectorIndex): Type of vector index (HNSW, FLAT, DYNAMIC).
            distance_metric (Distance): Distance metric (COSINE, DOT, etc).

        Returns:
            Configure.VectorIndex: The configured vector index instance.
        """
        # Get the Weaviate distance metric
        distance = getattr(VectorDistances, self.distance.name)

        # Define vector index configurations based on enum value
        configs = {
            VectorIndex.HNSW: Configure.VectorIndex.hnsw(distance_metric=distance),
            VectorIndex.FLAT: Configure.VectorIndex.flat(distance_metric=distance),
            VectorIndex.DYNAMIC: Configure.VectorIndex.dynamic(distance_metric=distance),
        }

        return configs[self.vector_index]

    def _get_search_results(self, response: Any) -> List[Document]:
        search_results: List[Document] = []
        
        objects_to_process = response.objects if hasattr(response, 'objects') else []

        for obj in objects_to_process:
            properties = obj.properties
            meta_data = json.loads(properties.get("meta_data", "{}")) if properties.get("meta_data") else {}
            
            # In v4, vector is accessed from obj.vector
            embedding = obj.vector.get("default") if obj.vector else None

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

    def _build_filter_expression(self, filters: Optional[Dict[str, Any]]):
        """
        Build a filter expression for Weaviate queries.

        Args:
            filters (Optional[Dict[str, Any]]): Dictionary of filters to apply.

        Returns:
            Optional[Filter]: The constructed filter expression, or None if no filters provided.
        """
        if not filters:
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

        except Exception as e:
            logger.error(f"Error building filter expression: {e}")
            return None

        return None

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
        except Exception as e:
            logger.error(f"Error checking if ID '{id}' exists: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
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

            # Update each matching object (async client doesn't support batch)
            updated_count = 0
            for obj in query_result.objects:
                try:
                    # Deserialize existing metadata, merge, and re-serialize
                    existing_meta_str = obj.properties.get("meta_data", "{}")
                    try:
                        existing_meta = json.loads(existing_meta_str) if existing_meta_str else {}
                    except (json.JSONDecodeError, TypeError):
                        existing_meta = {}
                    
                    existing_meta.update(metadata)
                    updated_meta_str = json.dumps(existing_meta)
                    
                    collection.data.update(
                        uuid=obj.uuid,
                        properties={
                            "meta_data": updated_meta_str
                        }
                    )
                    updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to update metadata for object {obj.uuid}: {e}")
            
            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete documents by content hash using direct filter deletion."""
        try:
            collection = self.get_client().collections.get(self.collection)

            # Build filter for content_hash search
            filter_expr = Filter.by_property("content_hash").equal(content_hash)

            collection.data.delete_many(where=filter_expr)

            log_info(f"Deleted documents with content_hash '{content_hash}' from collection '{self.collection}'.")
            return True

        except Exception as e:
            logger.error(f"Error deleting documents by content_hash '{content_hash}': {e}")
            return False
