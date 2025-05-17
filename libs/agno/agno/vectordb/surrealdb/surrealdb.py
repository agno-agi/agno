from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, Final, List, Optional

from surrealdb import AsyncSurrealDB, SurrealDB

from agno.document import Document
from agno.embedder import Embedder
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.utils.log import log_debug, log_info, logger


class SurrealVectorDb(VectorDb):
    """SurrealDB Vector Database implementation supporting both sync and async operations"""

    # TODO: Improve the vector index creation
    # SQL Query Constants
    CREATE_TABLE_QUERY: Final[str] = """
        DEFINE TABLE IF NOT EXISTS {collection} SCHEMAFUL;
        DEFINE FIELD IF NOT EXISTS content ON {collection} TYPE string;
        DEFINE FIELD IF NOT EXISTS embedding ON {collection} TYPE array<float>;
        DEFINE FIELD IF NOT EXISTS meta_data ON {collection} TYPE object;
        DEFINE INDEX IF NOT EXISTS vector_idx ON {collection} FIELDS embedding HNSW DIMENSION {dimensions} DIST COSINE;
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
        INSERT INTO {collection}
        SET content = $content,
            embedding = $embedding,
            meta_data = $meta_data
        ON DUPLICATE KEY UPDATE
            content = $content,
            embedding = $embedding,
            meta_data = $meta_data;
    """

    SEARCH_QUERY: Final[str] = """
        LET $query_embedding = $embedding;
        SELECT
            content,
            meta_data,
            vector::distance::knn() as distance
        FROM {collection}
        WHERE embedding <|{limit},{ef}|> $query_embedding
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
        self.sync_client = None
        self.async_client = None

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
    def connect(self):
        """Context manager for synchronous database connection"""
        try:
            self.sync_client = SurrealDB(self.url)
            self.sync_client.connect()
            self.sync_client.sign_in(self.username, self.password)
            self.sync_client.use(self.namespace, self.database)
            yield self
        finally:
            if self.sync_client:
                self.sync_client.close()

    @asynccontextmanager
    async def async_connect(self):
        """Context manager for asynchronous database connection"""
        try:
            self.async_client = AsyncSurrealDB(self.url)
            await self.async_client.connect()
            await self.async_client.sign_in(self.username, self.password)
            await self.async_client.use(self.namespace, self.database)
            yield self
        finally:
            if self.async_client:
                await self.async_client.close()

    # Synchronous methods
    def create(self) -> None:
        """Create the vector collection and index"""
        if not self.exists():
            log_debug(f"Creating collection: {self.collection}")
            with self.connect():
                query = self.CREATE_TABLE_QUERY.format(
                        collection=self.collection,
                        distance=self.distance,
                        dimensions=self.dimensions,
                        efc=self.efc,
                        m=self.m
                    )
                self.sync_client.query(query)

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content"""
        log_debug(f"Checking if document exists: {document.content}")
        with self.connect():
            result = self.sync_client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection),
                {"content": document.content}
            )
            return bool(self._extract_result(result))

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by its name"""
        log_debug(f"Checking if document exists: {name}")
        with self.connect():
            result = self.sync_client.query(
                self.NAME_EXISTS_QUERY.format(collection=self.collection),
                {"name": name}
            )
            return bool(self._extract_result(result))

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store"""
        with self.connect():
            for doc in documents:
                doc.embed(embedder=self.embedder)
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Inserting document: {doc.name} ({doc.meta_data})")
                self.sync_client.create(self.collection, data)

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store"""
        with self.connect():
            for doc in documents:
                doc.embed(embedder=self.embedder)
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Upserting document: {doc.name} ({doc.meta_data})")
                self.sync_client.query(self.UPSERT_QUERY.format(collection=self.collection), data)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents"""
        with self.connect():
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for Query: {query}")
                return []

            filter_condition = self._build_filter_condition(filters)
            query = self.SEARCH_QUERY.format(
                    collection=self.collection,
                    limit=limit,
                    filter_condition=filter_condition,
                    ef=self.search_ef
                )
            response = self.sync_client.query(
                query,
                {"embedding": query_embedding, **filters} if filters else {"embedding": query_embedding}
            )
            log_debug(f"Search response: {response}")

            documents = []
            items = response[-1]["result"]
            log_debug(f"Items: {items}")
            for item in items:
                if isinstance(item, dict):
                    doc = Document(
                        content=item.get('content'),
                        embedding=item.get('embedding'),
                        meta_data=item.get('meta_data', {}),
                        embedder=self.embedder
                    )
                    documents.append(doc)
            log_debug(f"Found {len(documents)} documents")
            return documents

    def drop(self) -> None:
        """Drop the vector collection"""
        log_debug(f"Dropping collection: {self.collection}")
        with self.connect():
            self.sync_client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    def exists(self) -> bool:
        """Check if the vector collection exists"""
        log_debug(f"Checking if collection exists: {self.collection}")
        with self.connect():
            response = self.sync_client.query(self.INFO_DB_QUERY)
            result = self._extract_result(response)
            return self.collection in result["tables"].keys()

    def delete(self) -> bool:
        """Delete all documents from the vector store"""
        with self.connect():
            self.sync_client.query(self.DELETE_ALL_QUERY.format(collection=self.collection))
            return True

    def _extract_result(self, query_result: List[Dict[str, Any]]) -> List[Any]:
        """Extract the actual result from SurrealDB query response"""
        return query_result[0].get('result', [])

    # Asynchronous methods
    async def async_create(self) -> None:
        """Create the vector collection and index asynchronously"""
        log_debug(f"Creating collection: {self.collection}")
        async with self.async_connect():
            await self.async_client.query(
                self.CREATE_TABLE_QUERY.format(
                    collection=self.collection,
                    distance=self.distance,
                    dimensions=self.dimensions,
                    efc=self.efc,
                    m=self.m
                )
            )

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content asynchronously"""
        async with self.async_connect():
            response = await self.async_client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection),
                {"content": document.content}
            )
            return bool(self._extract_result(response))

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document exists by its name asynchronously"""
        async with self.async_connect():
            response = await self.async_client.query(
                self.NAME_EXISTS_QUERY.format(collection=self.collection),
                {"name": name}
            )
            return bool(self._extract_result(response))

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store asynchronously"""
        async with self.async_connect():
            for doc in documents:
                doc.embed(embedder=self.embedder)
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Inserting document asynchronously: {doc.name} ({doc.meta_data})")
                await self.async_client.create(self.collection, data)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store asynchronously"""
        async with self.async_connect():
            for doc in documents:
                doc.embed(embedder=self.embedder)
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)
                log_debug(f"Upserting document asynchronously: {doc.name} ({doc.meta_data})")
                await self.async_client.query(self.UPSERT_QUERY.format(collection=self.collection), data)

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents asynchronously"""
        async with self.async_connect():
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Error getting embedding for Query: {query}")
                return []

            filter_condition = self._build_filter_condition(filters)
            response = await self.async_client.query(
                self.SEARCH_QUERY.format(
                    collection=self.collection,
                    limit=limit,
                    filter_condition=filter_condition,
                    ef=self.search_ef
                ),
                {"embedding": query_embedding, **filters} if filters else {"embedding": query_embedding}
            )

            documents = []
            items = response[-1]["result"]
            for item in items:
                if isinstance(item, dict):
                    doc = Document(
                        content=item.get('content'),
                        embedding=item.get('embedding'),
                        meta_data=item.get('meta_data', {}),
                        embedder=self.embedder
                    )
                    documents.append(doc)
            log_debug(f"Found {len(documents)} documents asynchronously")
            return documents

    async def async_drop(self) -> None:
        """Drop the vector collection asynchronously"""
        log_debug(f"Dropping collection: {self.collection}")
        async with self.async_connect():
            await self.async_client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    async def async_exists(self) -> bool:
        """Check if the vector collection exists asynchronously"""
        log_debug(f"Checking if collection exists: {self.collection}")
        async with self.async_connect():
            response = await self.async_client.query(self.INFO_DB_QUERY)
            result = self._extract_result(response)
            return self.collection in result["tables"].keys()

    def upsert_available(self) -> bool:
        """Check if upsert is available"""
        return True
