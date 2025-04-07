from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    from qdrant_client import AsyncQdrantClient, QdrantClient  # noqa: F401
    from qdrant_client.http import models
except ImportError:
    raise ImportError(
        "The `qdrant-client` package is not installed. Please install it via `pip install qdrant-client`."
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class Qdrant(VectorDb):
    def __init__(
        self,
        collection: str,
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
        **kwargs,
    ):
        # Collection attributes
        self.collection: str = collection

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
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
        # Collection distance
        _distance = models.Distance.COSINE
        if self.distance == Distance.l2:
            _distance = models.Distance.EUCLID
        elif self.distance == Distance.max_inner_product:
            _distance = models.Distance.DOT

        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=self.dimensions, distance=_distance),
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
            await self.async_client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=self.dimensions, distance=_distance),
            )

    def doc_exists(self, document: Document) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        if self.client:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            collection_points = self.client.retrieve(
                collection_name=self.collection,
                ids=[doc_id],
            )
            return len(collection_points) > 0
        return False

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists asynchronously."""
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()
        collection_points = await self.async_client.retrieve(
            collection_name=self.collection,
            ids=[doc_id],
        )
        return len(collection_points) > 0

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

    async def async_name_exists(self, name: str) -> bool:
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

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None, batch_size: int = 10) -> None:
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
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            points.append(
                models.PointStruct(
                    id=doc_id,
                    vector=document.embedding,
                    payload={
                        "name": document.name,
                        "meta_data": document.meta_data,
                        "content": cleaned_content,
                        "usage": document.usage,
                    },
                )
            )
            log_debug(f"Inserted document: {document.name} ({document.meta_data})")
        if len(points) > 0:
            self.client.upsert(collection_name=self.collection, wait=False, points=points)
        log_debug(f"Upsert {len(points)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously."""
        log_debug(f"Inserting {len(documents)} documents asynchronously")

        async def process_document(document):
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            log_debug(f"Inserted document asynchronously: {document.name} ({document.meta_data})")
            return models.PointStruct(
                id=doc_id,
                vector=document.embedding,
                payload={
                    "name": document.name,
                    "meta_data": document.meta_data,
                    "content": cleaned_content,
                    "usage": document.usage,
                },
            )

        import asyncio

        # Process all documents in parallel
        points = await asyncio.gather(*[process_document(doc) for doc in documents])

        if len(points) > 0:
            await self.async_client.upsert(collection_name=self.collection, wait=False, points=points)
        log_debug(f"Upserted {len(points)} documents asynchronously")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_debug("Redirecting the request to insert")
        self.insert(documents)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously."""
        log_debug("Redirecting the async request to async_insert")
        await self.async_insert(documents)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents in the database.

        Args:
            query (str): Query to search for
            limit (int): Number of search results to return
            filters (Optional[Dict[str, Any]]): Filters to apply while searching
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = self.client.search(
            collection_name=self.collection,
            query_vector=query_embedding,
            with_vectors=True,
            with_payload=True,
            limit=limit,
        )

        # Build search results
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
                    usage=result.payload["usage"],
                )
            )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for documents asynchronously."""
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = await self.async_client.search(
            collection_name=self.collection,
            query_vector=query_embedding,
            with_vectors=True,
            with_payload=True,
            limit=limit,
        )

        # Build search results
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
                    usage=result.payload["usage"],
                )
            )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

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
        if self.client:
            collections_response: models.CollectionsResponse = self.client.get_collections()
            collections: List[models.CollectionDescription] = collections_response.collections
            for collection in collections:
                if collection.name == self.collection:
                    # collection.status == models.CollectionStatus.GREEN
                    return True
        return False

    async def async_exists(self) -> bool:
        """Check if the collection exists asynchronously."""
        collections_response = await self.async_client.get_collections()
        collections: List[models.CollectionDescription] = collections_response.collections
        for collection in collections:
            if collection.name == self.collection:
                return True
        return False

    def get_count(self) -> int:
        count_result: models.CountResult = self.client.count(collection_name=self.collection, exact=True)
        return count_result.count

    def optimize(self) -> None:
        pass

    def delete(self) -> bool:
        return False
