from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    import asyncio

    from pymilvus import AsyncMilvusClient, MilvusClient  # type: ignore
except ImportError:
    raise ImportError("The `pymilvus` package is not installed. Please install it via `pip install pymilvus`.")

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class Milvus(VectorDb):
    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        uri: str = "http://localhost:19530",
        token: Optional[str] = None,
        **kwargs,
    ):
        """
        Milvus vector database.

        Args:
            collection (str): Name of the Milvus collection.
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
            **kwargs: Additional keyword arguments to pass to the MilvusClient.
        """
        self.collection: str = collection

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        self.distance: Distance = distance
        self.uri: str = uri
        self.token: Optional[str] = token
        self._client: Optional[MilvusClient] = None
        self._async_client: Optional[AsyncMilvusClient] = None
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

    def create(self) -> None:
        _distance = "COSINE"
        if self.distance == Distance.l2:
            _distance = "L2"
        elif self.distance == Distance.max_inner_product:
            _distance = "IP"

        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")
            self.client.create_collection(
                collection_name=self.collection,
                dimension=self.dimensions,
                metric_type=_distance,
                id_type="string",
                max_length=65_535,
            )

    async def async_create(self) -> None:
        """Create collection asynchronously if it doesn't exist."""
        _distance = "COSINE"
        if self.distance == Distance.l2:
            _distance = "L2"
        elif self.distance == Distance.max_inner_product:
            _distance = "IP"

        # Use the synchronous client to check if collection exists
        if not self.client.has_collection(self.collection):
            log_debug(f"Creating collection asynchronously: {self.collection}")
            # AsyncMilvusClient supports create_collection
            await self.async_client.create_collection(
                collection_name=self.collection,
                dimension=self.dimensions,
                metric_type=_distance,
                id_type="string",
                max_length=65_535,
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
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[doc_id],
            )
            return len(collection_points) > 0
        return False

    async def async_doc_exists(self, document: Document) -> bool:
        """
        Check if document exists asynchronously.
        AsyncMilvusClient supports get().
        """
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()
        collection_points = await self.async_client.get(
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
            expr = f"name == '{name}'"
            scroll_result = self.client.query(
                collection_name=self.collection,
                filter=expr,
                limit=1,
            )
            return len(scroll_result[0]) > 0
        return False

    def id_exists(self, id: str) -> bool:
        if self.client:
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[id],
            )
            return len(collection_points) > 0
        return False

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
            batch_size (int): Batch size for inserting documents
        """
        log_debug(f"Inserting {len(documents)} documents")
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            self.client.insert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Inserted document: {document.name} ({document.meta_data})")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously with controlled concurrency."""
        log_debug(f"Inserting {len(documents)} documents asynchronously")

        async def process_document(document):
            # Same processing code as before
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            await self.async_client.insert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Inserted document asynchronously: {document.name} ({document.meta_data})")
            return data

        await asyncio.gather(*[process_document(doc) for doc in documents])

        log_debug(f"Inserted {len(documents)} documents asynchronously")

    def upsert_available(self) -> bool:
        """
        Check if upsert operation is available.

        Returns:
            bool: Always returns True.
        """
        return True

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_debug(f"Upserting {len(documents)} documents")
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            self.client.upsert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Upserted document: {document.name} ({document.meta_data})")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_debug(f"Upserting {len(documents)} documents asynchronously")

        async def process_document(document):
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            await self.async_client.upsert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Upserted document asynchronously: {document.name} ({document.meta_data})")
            return data

        # Process all documents in parallel
        await asyncio.gather(*[process_document(doc) for doc in documents])

        log_debug(f"Upserted {len(documents)} documents asynchronously in parallel")

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
            data=[query_embedding],
            filter=self._build_expr(filters),
            output_fields=["*"],
            limit=limit,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            search_results.append(
                Document(
                    id=result["id"],
                    name=result["entity"].get("name", None),
                    meta_data=result["entity"].get("meta_data", {}),
                    content=result["entity"].get("content", ""),
                    embedder=self.embedder,
                    embedding=result["entity"].get("vector", None),
                    usage=result["entity"].get("usage", None),
                )
            )

        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = await self.async_client.search(
            collection_name=self.collection,
            data=[query_embedding],
            filter=self._build_expr(filters),
            output_fields=["*"],
            limit=limit,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            search_results.append(
                Document(
                    id=result["id"],
                    name=result["entity"].get("name", None),
                    meta_data=result["entity"].get("meta_data", {}),
                    content=result["entity"].get("content", ""),
                    embedder=self.embedder,
                    embedding=result["entity"].get("vector", None),
                    usage=result["entity"].get("usage", None),
                )
            )

        return search_results

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

    def _build_expr(self, filters: Optional[Dict[str, Any]]) -> str:
        if filters:
            kv_list = []
            for k, v in filters.items():
                if not isinstance(v, str):
                    kv_list.append(f"({k} == {v})")
                else:
                    kv_list.append(f"({k} == '{v}')")
            expr = " and ".join(kv_list)
        else:
            expr = ""
        return expr

    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
