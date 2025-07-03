from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    import asyncio

    from pyobvector import MilvusLikeClient  # type: ignore
except ImportError as e:
    print(e.msg)
    raise ImportError("The `pyobvector` package is not installed. Please install it via `pip install pyobvector`.")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

OB_INDEX_DISTANCE_MAP = {
    Distance.l2: "l2",
    Distance.max_inner_product: "inner_product",
}

OB_SEARCH_DISTANCE_MAP = {
    Distance.l2: "l2",
    Distance.max_inner_product: "neg_ip",
}


class OceanBase(VectorDb):
    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.l2,
        uri: str = "http://localhost:2881",
        user: Optional[str] = None,
        password: Optional[str] = None,
        db_name: Optional[str] = None,
        search_type: SearchType = SearchType.vector,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        """
        Initialize the OceanBase vector database client.
        Args:
            collection: Name of the collection to use
            embedder: Embedder to use for document embedding
            distance: Distance metric to use for search
            uri: URI of the OceanBase instance
            user: Username for authentication
            password: Password for authentication
            db_name: Name of the database to use
            search_type: Type of search to perform (vector, keyword, hybrid)
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
        self.user: Optional[str] = user
        self.password: Optional[str] = password
        self.db_name: Optional[str] = db_name
        self._client: Optional[MilvusLikeClient] = None
        self.search_type: SearchType = search_type
        self.reranker: Optional[Reranker] = reranker
        self.kwargs = kwargs

    @property
    def client(self) -> MilvusLikeClient:
        if self._client is None:
            log_debug("Creating OB Vector Client")
            self._client = MilvusLikeClient(
                uri=self.uri,
                user=self.user,
                password=self.password,
                db_name=self.db_name,
                **self.kwargs,
            )
        return self._client

    def create(self) -> None:
        """Create a collection based on search type if it doesn't exist."""
        from pyobvector import DataType, VecIndexType

        if self.exists():
            return

        log_debug(f"Creating collection: {self.collection}")
        schema = self.client.create_schema()

        # Define field configurations
        fields = [
            ("id", DataType.VARCHAR, 128, True),  # (name, type, max_length, is_primary)
            ("name", DataType.VARCHAR, 65535, False),
            ("meta_data", DataType.JSON, 65535, False),
            ("content", DataType.STRING, 65535, False),
            ("usage", DataType.JSON, 65535, False),
        ]
        # Add VARCHAR fields
        for field_name, datatype, max_length, is_primary in fields:
            schema.add_field(field_name=field_name, datatype=datatype, max_length=max_length, is_primary=is_primary)

        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            max_length=self.dimensions,
            is_primary=False,
            dim=self.dimensions,
        )

        idx_params = self.client.prepare_index_params()
        idx_params.add_index(
            field_name="vector",
            index_name="embedding_index",
            index_type=VecIndexType.HNSW,
            metric_type=OB_INDEX_DISTANCE_MAP.get(self.distance, "L2"),
            params={"M": 16, "efConstruction": 256},
        )

        self.client.create_collection(
            collection_name=self.collection,
            dimension=self.dimensions,
            id_type="string",
            schema=schema,
            index_params=idx_params,
            max_length=3600,
        )

    async def async_create(self) -> None:
        """Create the table asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

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
        return await asyncio.to_thread(self.doc_exists, document)

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

    async def async_name_exists(self, name: str) -> bool:
        """Check if name exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        if self.client:
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[id],
            )
            return len(collection_points) > 0
        return False

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents based on search type."""
        log_info(f"Inserting {len(documents)} documents")

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

        log_info(f"Inserted {len(documents)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously based on search type."""
        await asyncio.to_thread(self.insert, documents, filters)

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
        await asyncio.to_thread(self.upsert, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents matching the query.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search

        Returns:
            List[Document]: List of matching documents
        """
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = self.client.search(
            collection_name=self.collection,
            data=query_embedding,
            anns_field="vector",
            output_fields=["id", "name", "meta_data", "content", "usage", "vector"],
            limit=limit,
            search_params={
                "metric_type": OB_SEARCH_DISTANCE_MAP.get(self.distance, "L2"),
            },
        )

        # Build search results
        search_results: List[Document] = []
        for result in results:
            search_results.append(
                Document(
                    id=result["id"],
                    name=result.get("name", None),
                    meta_data=result.get("meta_data", {}),
                    content=result.get("content", ""),
                    usage=result.get("usage", None),
                    embedding=result.get("vector", None),
                )
            )

        log_info(f"Found {len(search_results)} documents")
        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.collection}")
            self.client.drop_collection(self.collection)

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        if self.client:
            if self.client.has_collection(self.collection):
                return True
        return False

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        return self.client.get_collection_stats(collection_name="test_collection")["row_count"]

    def delete(self) -> bool:
        if self.client:
            self.client.drop_collection(self.collection)
            return True
        return False
