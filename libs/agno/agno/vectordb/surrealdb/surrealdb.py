from typing import Any, Dict, Final, List, Optional, Union

try:
    from surrealdb import (
        AsyncHttpSurrealConnection,
        AsyncWsSurrealConnection,
        BlockingHttpSurrealConnection,
        BlockingWsSurrealConnection,
    )
except ImportError as e:
    msg = "The `surrealdb` package is not installed. Please install it via `pip install surrealdb`."
    raise ImportError(msg) from e

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class SurrealDb(VectorDb):
    """SurrealDB Vector Database implementation supporting both sync and async operations."""

    # SQL Query Constants
    CREATE_TABLE_QUERY: Final[str] = """
        DEFINE TABLE IF NOT EXISTS {collection} SCHEMAFUL;
        DEFINE FIELD IF NOT EXISTS content ON {collection} TYPE string;
        DEFINE FIELD IF NOT EXISTS embedding ON {collection} TYPE array<float>;
        DEFINE FIELD IF NOT EXISTS meta_data ON {collection} FLEXIBLE TYPE object;
        DEFINE INDEX IF NOT EXISTS vector_idx ON {collection} FIELDS embedding HNSW DIMENSION {dimensions} DIST {distance};
    """

    DOC_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE content = $content
        LIMIT 1
    """

    NAME_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE meta_data.name = $name
        LIMIT 1
    """

    ID_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE id = $id
        LIMIT 1
    """

    UPSERT_QUERY: Final[str] = """
        UPSERT {thing}
        SET content = $content,
            embedding = $embedding,
            meta_data = $meta_data
    """

    SEARCH_QUERY: Final[str] = """
        SELECT
            content,
            meta_data,
            vector::distance::knn() as distance
        FROM {collection}
        WHERE embedding <|{limit}, {search_ef}|> $query_embedding
        {filter_condition}
        ORDER BY distance ASC
        LIMIT {limit};
    """

    INFO_DB_QUERY: Final[str] = "INFO FOR DB;"
    DROP_TABLE_QUERY: Final[str] = "REMOVE TABLE {collection}"
    DELETE_ALL_QUERY: Final[str] = "DELETE {collection}"

    def __init__(
        self,
        client: Optional[Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection]] = None,
        async_client: Optional[Union[AsyncWsSurrealConnection, AsyncHttpSurrealConnection]] = None,
        collection: str = "documents",
        distance: Distance = Distance.cosine,
        efc: int = 150,
        m: int = 12,
        search_ef: int = 40,
        embedder: Optional[Embedder] = None,
    ):
        """Initialize SurrealDB connection.

        Args:
            url: SurrealDB server URL (e.g. ws://localhost:8000/rpc)
            client: A blocking connection, either HTTP or WS
            async_client: An async connection, either HTTP or WS (default: None)
            collection: Collection name to store documents (default: documents)
            distance: Distance metric to use (default: cosine)
            efc: HNSW construction time/accuracy trade-off (default: 150)
            m: HNSW max number of connections per element (default: 12)
            search_ef: HNSW search time/accuracy trade-off (default: 40)
            embedder: Embedder instance for creating embeddings (default: OpenAIEmbedder)

        """
        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions = self.embedder.dimensions
        self.collection = collection

        # Convert Distance enum to SurrealDB distance type
        self.distance = {Distance.cosine: "COSINE", Distance.l2: "EUCLIDEAN", Distance.max_inner_product: "DOT"}[
            distance
        ]

        self._client: Optional[Union[BlockingHttpSurrealConnection, BlockingWsSurrealConnection]] = client
        self._async_client: Optional[Union[AsyncWsSurrealConnection, AsyncHttpSurrealConnection]] = async_client

        if self._client is None and self._async_client is None:
            msg = "Client and async client are not provided. Please provide one of them."
            raise RuntimeError(msg)

        # HNSW index parameters
        self.efc = efc
        self.m = m
        self.search_ef = search_ef

    @property
    def async_client(self) -> Union[AsyncWsSurrealConnection, AsyncHttpSurrealConnection]:
        """Check if the async client is initialized.

        Raises:
            RuntimeError: If the async client is not initialized.

        Returns:
            The async client.

        """
        if self._async_client is None:
            msg = "Async client is not initialized"
            raise RuntimeError(msg)
        return self._async_client

    @property
    def client(self) -> Union[BlockingHttpSurrealConnection, BlockingWsSurrealConnection]:
        """Check if the client is initialized.

        Returns:
            The client.

        """
        if self._client is None:
            msg = "Client is not initialized"
            raise RuntimeError(msg)
        return self._client

    @staticmethod
    def _build_filter_condition(filters: Optional[Dict[str, Any]] = None) -> str:
        """Build filter condition for queries.

        Args:
            filters: A dictionary of filters to apply to the query.

        Returns:
            A string representing the filter condition.

        """
        if not filters:
            return ""
        conditions = [f"meta_data.{key} = ${key}" for key in filters]
        return "AND " + " AND ".join(conditions)

    # Synchronous methods
    def create(self) -> None:
        """Create the vector collection and index."""
        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")
            query = self.CREATE_TABLE_QUERY.format(
                collection=self.collection,
                distance=self.distance,
                dimensions=self.dimensions,
                efc=self.efc,
                m=self.m,
            )
            self.client.query(query)

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content.

        Args:
            document: The document to check.

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists: {document.content}")
        result = self.client.query(
            self.DOC_EXISTS_QUERY.format(collection=self.collection),
            {"content": document.content},
        )
        return bool(self._extract_result(result))

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by its name.

        Args:
            name: The name of the document to check.

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists: {name}")
        result = self.client.query(self.NAME_EXISTS_QUERY.format(collection=self.collection), {"name": name})
        return bool(self._extract_result(result))

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store.

        Args:
            documents: A list of documents to insert.
            filters: A dictionary of filters to apply to the query.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
            if filters:
                data["meta_data"].update(filters)
            self.client.create(self.collection, data)

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store.

        Args:
            documents: A list of documents to upsert.
            filters: A dictionary of filters to apply to the query.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
            if filters:
                data["meta_data"].update(filters)
            thing = f"{self.collection}:{doc.id}" if doc.id else self.collection
            self.client.query(self.UPSERT_QUERY.format(thing=thing), data)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents.

        Args:
            query: The query to search for.
            limit: The maximum number of documents to return.
            filters: A dictionary of filters to apply to the query.

        Returns:
            A list of documents that are similar to the query.

        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        filter_condition = self._build_filter_condition(filters)
        log_debug(f"Filter condition: {filter_condition}")
        search_query = self.SEARCH_QUERY.format(
            collection=self.collection,
            limit=limit,
            search_ef=self.search_ef,
            filter_condition=filter_condition,
            distance=self.distance,
        )
        log_debug(f"Search query: {search_query}")
        response = self.client.query(
            search_query,
            {"query_embedding": query_embedding, **filters} if filters else {"query_embedding": query_embedding},
        )
        log_debug(f"Search response: {response}")

        documents = []
        for item in response:
            if isinstance(item, dict):
                doc = Document(
                    content=item.get("content", ""),
                    embedding=item.get("embedding", []),
                    meta_data=item.get("meta_data", {}),
                    embedder=self.embedder,
                )
                documents.append(doc)
        log_debug(f"Found {len(documents)} documents")
        return documents

    def drop(self) -> None:
        """Drop the vector collection."""
        log_debug(f"Dropping collection: {self.collection}")
        self.client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    def exists(self) -> bool:
        """Check if the vector collection exists.

        Returns:
            True if the collection exists, False otherwise.

        """
        log_debug(f"Checking if collection exists: {self.collection}")
        response = self.client.query(self.INFO_DB_QUERY)
        result = self._extract_result(response)
        if isinstance(result, dict) and "tables" in result:
            return self.collection in result["tables"]
        return False

    def delete(self) -> bool:
        """Delete all documents from the vector store.

        Returns:
            True if the collection was deleted, False otherwise.

        """
        self.client.query(self.DELETE_ALL_QUERY.format(collection=self.collection))
        return True

    @staticmethod
    def _extract_result(query_result: Union[List[Dict[str, Any]], Dict[str, Any]]) -> Union[List[Any], Dict[str, Any]]:
        """Extract the actual result from SurrealDB query response.

        Args:
            query_result: The query result from SurrealDB.

        Returns:
            The actual result from SurrealDB query response.

        """
        log_debug(f"Query result: {query_result}")
        if isinstance(query_result, dict):
            return query_result
        if isinstance(query_result, list):
            if len(query_result) > 0:
                return query_result[0].get("result", {})
            return []
        return []

    async def async_create(self) -> None:
        """Create the vector collection and index asynchronously."""
        log_debug(f"Creating collection: {self.collection}")
        await self.async_client.query(
            self.CREATE_TABLE_QUERY.format(
                collection=self.collection,
                distance=self.distance,
                dimensions=self.dimensions,
                efc=self.efc,
                m=self.m,
            ),
        )

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content asynchronously.

        Returns:
            True if the document exists, False otherwise.

        """
        response = await self.async_client.query(
            self.DOC_EXISTS_QUERY.format(collection=self.collection),
            {"content": document.content},
        )
        return bool(self._extract_result(response))

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document exists by its name asynchronously.

        Returns:
            True if the document exists, False otherwise.

        """
        response = await self.async_client.query(
            self.NAME_EXISTS_QUERY.format(collection=self.collection),
            {"name": name},
        )
        return bool(self._extract_result(response))

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store asynchronously.

        Args:
            documents: A list of documents to insert.
            filters: A dictionary of filters to apply to the query.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
            if filters:
                data["meta_data"].update(filters)
            log_debug(f"Inserting document asynchronously: {doc.name} ({doc.meta_data})")
            await self.async_client.create(self.collection, data)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store asynchronously.

        Args:
            documents: A list of documents to upsert.
            filters: A dictionary of filters to apply to the query.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
            if filters:
                data["meta_data"].update(filters)
            log_debug(f"Upserting document asynchronously: {doc.name} ({doc.meta_data})")
            thing = f"{self.collection}:{doc.id}" if doc.id else self.collection
            await self.async_client.query(self.UPSERT_QUERY.format(thing=thing), data)

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Search for similar documents asynchronously.

        Args:
            query: The query to search for.
            limit: The maximum number of documents to return.
            filters: A dictionary of filters to apply to the query.

        Returns:
            A list of documents that are similar to the query.

        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        filter_condition = self._build_filter_condition(filters)
        search_query = self.SEARCH_QUERY.format(
            collection=self.collection,
            limit=limit,
            search_ef=self.search_ef,
            filter_condition=filter_condition,
            distance=self.distance,
        )
        response = await self.async_client.query(
            search_query,
            {"query_embedding": query_embedding, **filters} if filters else {"query_embedding": query_embedding},
        )
        log_debug(f"Search response: {response}")
        documents = []
        for item in response:
            if isinstance(item, dict):
                doc = Document(
                    content=item.get("content", ""),
                    embedding=item.get("embedding", []),
                    meta_data=item.get("meta_data", {}),
                    embedder=self.embedder,
                )
                documents.append(doc)
        log_debug(f"Found {len(documents)} documents asynchronously")
        return documents

    async def async_drop(self) -> None:
        """Drop the vector collection asynchronously."""
        log_debug(f"Dropping collection: {self.collection}")
        await self.async_client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    async def async_exists(self) -> bool:
        """Check if the vector collection exists asynchronously.

        Returns:
            True if the collection exists, False otherwise.

        """
        log_debug(f"Checking if collection exists: {self.collection}")
        response = await self.async_client.query(self.INFO_DB_QUERY)
        result = self._extract_result(response)
        if isinstance(result, dict) and "tables" in result:
            return self.collection in result["tables"]
        return False

    @staticmethod
    def upsert_available() -> bool:
        """Check if upsert is available.

        Returns:
            True if upsert is available, False otherwise.

        """
        return True
