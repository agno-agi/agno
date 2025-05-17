from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, Final, List, Optional

from surrealdb import AsyncSurreal, Surreal

from agno.document import Document
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class BaseSurrealVectorDb:
    """Base class for SurrealDB Vector Database implementation"""

    # SQL Query Constants
    CREATE_TABLE_QUERY: Final[str] = """
        DEFINE TABLE {collection} SCHEMAFUL;
        DEFINE FIELD content ON {collection} TYPE string;
        DEFINE FIELD embedding ON {collection} TYPE array<float>;
        DEFINE FIELD meta_data ON {collection} TYPE object;
        -- Using HNSW index with optimized parameters
        DEFINE INDEX vector_idx ON {collection}
        FIELDS embedding
        HNSW
        DIMENSION {dimension}
        DIST {distance}
        EFC {efc}
        M {m};
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
            embedding,
            meta_data,
            vector::distance::knn() as distance
        FROM {collection}
        WHERE embedding <|{limit},{ef}|> $query_embedding
        {filter_condition}
        ORDER BY distance ASC
        LIMIT {limit}
    """

    DROP_TABLE_QUERY: Final[str] = "REMOVE TABLE {collection}"
    INFO_TABLE_QUERY: Final[str] = "INFO FOR TABLE {collection}"
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
        dimension: int = 1536,
        efc: int = 150,
        m: int = 12,
        search_ef: int = 40,
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
            dimension: Vector dimension (default: 1536)
            efc: HNSW construction time/accuracy trade-off (default: 150)
            m: HNSW max number of connections per element (default: 12)
            search_ef: HNSW search time/accuracy trade-off (default: 40)
        """
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
        self.client = None

        # HNSW index parameters
        self.dimension = dimension
        self.efc = efc
        self.m = m
        self.search_ef = search_ef

    def _build_filter_condition(self, filters: Optional[Dict[str, Any]] = None) -> str:
        """Build filter condition for queries"""
        if not filters:
            return ""
        conditions = []
        for key, value in filters.items():
            conditions.append(f"meta_data.{key} = ${key}")
        return "AND " + " AND ".join(conditions)


class SurrealVectorDb(BaseSurrealVectorDb, VectorDb):
    """Synchronous SurrealDB Vector Database implementation"""

    @contextmanager
    def connect(self):
        """Context manager for database connection"""
        try:
            self.client = Surreal(self.url)
            self.client.connect()
            self.client.signin({"username": self.username, "password": self.password})
            self.client.use(self.namespace, self.database)
            yield self
        finally:
            if self.client:
                self.client.close()

    def create(self) -> None:
        """Create the vector collection and index"""
        with self.connect():
            self.client.query(
                self.CREATE_TABLE_QUERY.format(
                    collection=self.collection, distance=self.distance, dimension=self.dimension, efc=self.efc, m=self.m
                )
            )

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content"""
        with self.connect():
            result = self.client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection), {"content": document.content}
            )
            return bool(result and result[0])

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by its name"""
        with self.connect():
            result = self.client.query(self.NAME_EXISTS_QUERY.format(collection=self.collection), {"name": name})
            return bool(result and result[0])

    def id_exists(self, id: str) -> bool:
        """Check if a document exists by its ID"""
        with self.connect():
            result = self.client.query(self.ID_EXISTS_QUERY.format(collection=self.collection), {"id": id})
            return bool(result and result[0])

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store"""
        with self.connect():
            for doc in documents:
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)

                self.client.create(self.collection, data)

    def upsert_available(self) -> bool:
        """Check if upsert is available"""
        return True

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store"""
        with self.connect():
            for doc in documents:
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)

                self.client.query(self.UPSERT_QUERY.format(collection=self.collection), data)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents"""
        with self.connect():
            filter_condition = self._build_filter_condition(filters)

            result = self.client.query(
                self.SEARCH_QUERY.format(
                    collection=self.collection, limit=limit, filter_condition=filter_condition, ef=self.search_ef
                ),
                {"embedding": query, **filters} if filters else {"embedding": query},
            )

            documents = []
            if result and result[0]:
                for item in result[0]:
                    doc = Document(content=item["content"], embedding=item["embedding"], meta_data=item["meta_data"])
                    documents.append(doc)

            return documents

    def drop(self) -> None:
        """Drop the vector collection"""
        with self.connect():
            self.client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    def exists(self) -> bool:
        """Check if the vector collection exists"""
        with self.connect():
            result = self.client.query(self.INFO_TABLE_QUERY.format(collection=self.collection))
            return bool(result and result[0])

    def delete(self) -> bool:
        """Delete all documents from the vector store"""
        with self.connect():
            self.client.query(self.DELETE_ALL_QUERY.format(collection=self.collection))
            return True


class AsyncSurrealVectorDb(BaseSurrealVectorDb, VectorDb):
    """Asynchronous SurrealDB Vector Database implementation"""

    @asynccontextmanager
    async def connect(self):
        """Async context manager for database connection"""
        try:
            self.client = AsyncSurreal(self.url)
            await self.client.connect()
            await self.client.signin({"username": self.username, "password": self.password})
            await self.client.use(self.namespace, self.database)
            yield self
        finally:
            if self.client:
                await self.client.close()

    async def async_create(self) -> None:
        """Create the vector collection and index asynchronously"""
        async with self.connect():
            await self.client.query(
                self.CREATE_TABLE_QUERY.format(
                    collection=self.collection, distance=self.distance, dimension=self.dimension, efc=self.efc, m=self.m
                )
            )

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists by its content asynchronously"""
        async with self.connect():
            result = await self.client.query(
                self.DOC_EXISTS_QUERY.format(collection=self.collection), {"content": document.content}
            )
            return bool(result and result[0])

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document exists by its name asynchronously"""
        async with self.connect():
            result = await self.client.query(self.NAME_EXISTS_QUERY.format(collection=self.collection), {"name": name})
            return bool(result and result[0])

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector store asynchronously"""
        async with self.connect():
            for doc in documents:
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)

                await self.client.create(self.collection, data)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector store asynchronously"""
        async with self.connect():
            for doc in documents:
                data = {"content": doc.content, "embedding": doc.embedding, "meta_data": doc.meta_data or {}}
                if filters:
                    data["meta_data"].update(filters)

                await self.client.query(self.UPSERT_QUERY.format(collection=self.collection), data)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for similar documents asynchronously"""
        async with self.connect():
            filter_condition = self._build_filter_condition(filters)

            result = await self.client.query(
                self.SEARCH_QUERY.format(
                    collection=self.collection, limit=limit, filter_condition=filter_condition, ef=self.search_ef
                ),
                {"embedding": query, **filters} if filters else {"embedding": query},
            )

            documents = []
            if result and result[0]:
                for item in result[0]:
                    doc = Document(content=item["content"], embedding=item["embedding"], meta_data=item["meta_data"])
                    documents.append(doc)

            return documents

    async def async_drop(self) -> None:
        """Drop the vector collection asynchronously"""
        async with self.connect():
            await self.client.query(self.DROP_TABLE_QUERY.format(collection=self.collection))

    async def async_exists(self) -> bool:
        """Check if the vector collection exists asynchronously"""
        async with self.connect():
            result = await self.client.query(self.INFO_TABLE_QUERY.format(collection=self.collection))
            return bool(result and result[0])
