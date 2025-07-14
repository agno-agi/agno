from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, Final, List, Optional, Union

from surrealdb import (
    AsyncHttpSurrealConnection,
    AsyncSurreal,
    AsyncWsSurrealConnection,
    BlockingHttpSurrealConnection,
    BlockingWsSurrealConnection,
    Surreal,
)

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class SurrealDb(VectorDb):
    """SurrealDB Vector Database implementation supporting both sync and async operations"""

    # SQL Query Constants
    CREATE_TABLE_QUERY: Final[str] = """
        DEFINE TABLE IF NOT EXISTS {collection} SCHEMAFUL;
        DEFINE FIELD IF NOT EXISTS content ON {collection} TYPE string;
        DEFINE FIELD IF NOT EXISTS embedding ON {collection} TYPE array<float>;
        DEFINE FIELD IF NOT EXISTS meta_data ON {collection} TYPE object;
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
        url: str,
        namespace: str,
        database: str,
        username: str,
        password: str,
        collection: str = "documents",
        distance: Distance = Distance.cosine,
        efc: int = 150,
        m: int = 12,
        search_ef: int = 40,
        embedder: Optional[Embedder] = None,
    ):
        """Initialize SurrealDB connection

        Args:
            url: SurrealDB server URL (e.g. ws://localhost:8000/rpc)
            namespace: SurrealDB namespace
            database: SurrealDB database name
            username: SurrealDB username
            password: SurrealDB password
            collection: Collection name to store documents (default: documents)
            distance: Distance metric to use (default: cosine)
            dimensions: Vector dimensions (default: 1536)
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

        # Database connection parameters
        self.url = url
        self.namespace = namespace
        self.database = database
        self.collection = collection
        # Convert Distance enum to SurrealDB distance type
        self.distance = {Distance.cosine: "COSINE", Distance.l2: "EUCLIDEAN", Distance.max_inner_product: "DOT"}[
            distance
        ]
        self.username = username
        self.password = password
        self.sync_client: Union[BlockingHttpSurrealConnection, BlockingWsSurrealConnection, None] = None
        self.async_client: Union[AsyncWsSurrealConnection, AsyncHttpSurrealConnection, None] = None

        # HNSW index parameters
        self.efc = efc
        self.m = m
        self.search_ef = search_ef

    def _build_filter_condition(self, filters: Optional[Dict[str, Any]] = None) -> str:
        """Build filter condition for queries"""
        if not filters:
            return ""
        conditions = []
        for key, _ in filters.items():
            conditions.append(f"meta_data.{key} = ${key}")
        return "AND " + " AND ".join(conditions)

    @contextmanager
    def connect(self) -> Generator[Union[BlockingHttpSurrealConnection, BlockingWsSurrealConnection], None]:
        """Context manager for synchronous database connection"""
        try:
            self.sync_client = Surreal(self.url)
            self.sync_client.signin({"username": self.username, "password": self.password})
            self.sync_client.use(self.namespace, self.database)
            yield self.sync_client
        finally:
            if isinstance(self.sync_client, BlockingWsSurrealConnection):
                self.sync_client.close()

    @asynccontextmanager
    async def async_connect(self) -> AsyncGenerator[Union[AsyncWsSurrealConnection, AsyncHttpSurrealConnection], None]:
        """Context manager for asynchronous database connection"""
        try:
            self.async_client = AsyncSurreal(self.url)
            await self.async_client.signin({"username": self.username, "password": self.password})
            await self.async_client.use(self.namespace, self.database)
            yield self.async_client
        finally:
            if isinstance(self.async_client, AsyncWsSurrealConnection):
                await self.async_client.close()

    # Synchronous methods
    def create(self) -> None:
        """Create the vector collection and index"""
        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")
            with self.connect() as client:
                query = self.CREATE_TABLE_QUERY.format(
                    collection=self.collection,
                    distance=self.distance,
                    dimensions=self.dimensions,
                    efc=self.efc,
                    m=self.m,
                )
                client.query(query)

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content"""
        log_debug(f"Checking if document exists: {document.content}")
        with self.connect() as client:
            result = client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection), {"content": document.content}
            )
            return bool(self._extract_result(result))

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by its name"""
        log_debug(f"Checking if document exists: {name}")
        with self.connect() as client:
            result = client.query(self.NAME_EXISTS_QUERY.format(collection=self.collection), {"name": name})
            return bool(self._extract_result(result))

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store"""
        with self.connect() as client:
            for doc in documents:
                doc.embed(embedder=self.embedder)
                meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
                data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Inserting document: {doc.name} ({doc.meta_data})")
                client.create(self.collection, data)

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store"""
        with self.connect() as client:
            for doc in documents:
                doc.embed(embedder=self.embedder)
                meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
                data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Upserting document: {doc.name} ({doc.meta_data})")
                thing = f"{self.collection}:{doc.id}" if doc.id else self.collection
                client.query(self.UPSERT_QUERY.format(thing=thing), data)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents"""
        with self.connect() as client:
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
            response = client.query(
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
        """Drop the vector collection"""
        log_debug(f"Dropping collection: {self.collection}")
        with self.connect() as client:
            client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    def exists(self) -> bool:
        """Check if the vector collection exists"""
        log_debug(f"Checking if collection exists: {self.collection}")
        with self.connect() as client:
            response = client.query(self.INFO_DB_QUERY)
            result = self._extract_result(response)
            if isinstance(result, dict) and "tables" in result:
                return self.collection in result["tables"].keys()
            return False

    def delete(self) -> bool:
        """Delete all documents from the vector store"""
        with self.connect() as client:
            client.query(self.DELETE_ALL_QUERY.format(collection=self.collection))
            return True

    def _extract_result(
        self, query_result: Union[List[Dict[str, Any]], Dict[str, Any]]
    ) -> Union[List[Any], Dict[str, Any]]:
        """Extract the actual result from SurrealDB query response"""
        log_debug(f"Query result: {query_result}")
        if isinstance(query_result, dict):
            return query_result
        if isinstance(query_result, list):
            if len(query_result) > 0:
                return query_result[0].get("result", {})
            return []

    # Asynchronous methods
    async def async_create(self) -> None:
        """Create the vector collection and index asynchronously"""
        log_debug(f"Creating collection: {self.collection}")
        async with self.async_connect() as client:
            await client.query(
                self.CREATE_TABLE_QUERY.format(
                    collection=self.collection,
                    distance=self.distance,
                    dimensions=self.dimensions,
                    efc=self.efc,
                    m=self.m,
                )
            )

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content asynchronously"""
        async with self.async_connect() as client:
            response = await client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection), {"content": document.content}
            )
            return bool(self._extract_result(response))

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document exists by its name asynchronously"""
        async with self.async_connect() as client:
            response = await client.query(self.NAME_EXISTS_QUERY.format(collection=self.collection), {"name": name})
            return bool(self._extract_result(response))

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store asynchronously"""
        async with self.async_connect() as client:
            for doc in documents:
                doc.embed(embedder=self.embedder)
                meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
                data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Inserting document asynchronously: {doc.name} ({doc.meta_data})")
                await client.create(self.collection, data)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store asynchronously"""
        async with self.async_connect() as client:
            for doc in documents:
                doc.embed(embedder=self.embedder)
                meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
                data: Dict[str, Any] = {"content": doc.content, "embedding": doc.embedding, "meta_data": meta_data}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Upserting document asynchronously: {doc.name} ({doc.meta_data})")
                thing = f"{self.collection}:{doc.id}" if doc.id else self.collection
                await client.query(self.UPSERT_QUERY.format(thing=thing), data)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for similar documents asynchronously"""
        async with self.async_connect() as client:
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
            response = await client.query(
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
        """Drop the vector collection asynchronously"""
        log_debug(f"Dropping collection: {self.collection}")
        async with self.async_connect() as client:
            await client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    async def async_exists(self) -> bool:
        """Check if the vector collection exists asynchronously"""
        log_debug(f"Checking if collection exists: {self.collection}")
        async with self.async_connect() as client:
            response = await client.query(self.INFO_DB_QUERY)
            result = self._extract_result(response)
            if isinstance(result, dict) and "tables" in result:
                return self.collection in result["tables"].keys()
            return False

    def upsert_available(self) -> bool:
        """Check if upsert is available"""
        return True
