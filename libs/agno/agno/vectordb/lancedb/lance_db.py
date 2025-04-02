import json
from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    import lancedb
    import pyarrow as pa
except ImportError:
    raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType


class LanceDb(VectorDb):
    """
    LanceDb class for managing vector operations with LanceDb

    Args:
        uri: The URI of the LanceDB database.
        connection: The LanceDB connection to use.
        table: The LanceDB table instance to use.
        async_connection: The LanceDB async connection to use.
        async_table: The LanceDB async table instance to use.
        table_name: The name of the LanceDB table to use.
        api_key: The API key to use for the LanceDB connection.
        embedder: The embedder to use when embedding the document contents.
        search_type: The search type to use when searching for documents.
        distance: The distance metric to use when searching for documents.
        nprobes: The number of probes to use when searching for documents.
        reranker: The reranker to use when reranking documents.
        use_tantivy: Whether to use Tantivy for full text search.
        on_bad_vectors: What to do if the vector is bad. One of "error", "drop", "fill", "null".
        fill_value: The value to fill the vector with if on_bad_vectors is "fill".
    """

    def __init__(
        self,
        uri: lancedb.URI = "/tmp/lancedb",
        connection: Optional[lancedb.LanceDBConnection] = None,
        table: Optional[lancedb.db.LanceTable] = None,
        async_connection: Optional[lancedb.AsyncConnection] = None,
        async_table: Optional[lancedb.db.AsyncTable] = None,
        table_name: Optional[str] = None,
        api_key: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        nprobes: Optional[int] = None,
        reranker: Optional[Reranker] = None,
        use_tantivy: bool = True,
        on_bad_vectors: Optional[str] = None,  # One of "error", "drop", "fill", "null".
        fill_value: Optional[float] = None,  # Only used if on_bad_vectors is "fill"
    ):
        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Search type
        self.search_type: SearchType = search_type
        # Distance metric
        self.distance: Distance = distance

        # LanceDB connection details
        self.uri: lancedb.URI = uri
        self.connection: lancedb.LanceDBConnection = connection or lancedb.connect(uri=self.uri, api_key=api_key)
        self.table: Optional[lancedb.db.LanceTable] = table

        self.async_connection: Optional[lancedb.AsyncConnection] = async_connection
        self.async_table: Optional[lancedb.db.AsyncTable] = async_table

        if table_name and table_name in self.connection.table_names():
            # Open the table if it exists
            self.table = self.connection.open_table(name=table_name)
            self.table_name = self.table.name
            self._vector_col = self.table.schema.names[0]
            self._id = self.table.schema.names[1]  # type: ignore

        # LanceDB table details
        if self.table is None:
            # LanceDB table details
            if table:
                if not isinstance(table, lancedb.db.LanceTable):
                    raise ValueError(
                        "table should be an instance of lancedb.db.LanceTable, ",
                        f"got {type(table)}",
                    )
                self.table = table
                self.table_name = self.table.name
                self._vector_col = self.table.schema.names[0]
                self._id = self.tbl.schema.names[1]  # type: ignore
            else:
                if not table_name:
                    raise ValueError("Either table or table_name should be provided.")
                self.table_name = table_name
                self._id = "id"
                self._vector_col = "vector"
                self.table = self._init_table()

        self.reranker: Optional[Reranker] = reranker
        self.nprobes: Optional[int] = nprobes
        self.on_bad_vectors: Optional[str] = on_bad_vectors
        self.fill_value: Optional[float] = fill_value
        self.fts_index_exists = False
        self.use_tantivy = use_tantivy

        if self.use_tantivy and (self.search_type in [SearchType.keyword, SearchType.hybrid]):
            try:
                import tantivy  # noqa: F401
            except ImportError:
                raise ImportError(
                    "Please install tantivy-py `pip install tantivy` to use the full text search feature."  # noqa: E501
                )

        log_debug(f"Initialized LanceDb with table: '{self.table_name}'")

    async def _get_async_connection(self) -> lancedb.AsyncConnection:
        """Get or create an async connection to LanceDB."""
        if self.async_connection is None:
            self.async_connection = await lancedb.connect_async(self.uri)
        if self.async_table is None:
            self.async_table = await self.async_connection.open_table(self.table_name)
        return self.async_connection

    def create(self) -> None:
        """Create the table if it does not exist."""
        if not self.exists():
            self.table = self._init_table()

    async def async_create(self) -> None:
        """Create the table asynchronously if it does not exist."""
        if not self.exists():
            conn = await self._get_async_connection()
            schema = self._base_schema()

            log_debug(f"Creating table asynchronously: {self.table_name}")
            self.async_table = await conn.create_table(self.table_name, schema=schema, mode="overwrite", exist_ok=True)

    def _base_schema(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field(
                    self._vector_col,
                    pa.list_(
                        pa.float32(),
                        len(self.embedder.get_embedding("test")),  # type: ignore
                    ),
                ),
                pa.field(self._id, pa.string()),
                pa.field("payload", pa.string()),
            ]
        )

    def _init_table(self) -> lancedb.db.LanceTable:
        schema = self._base_schema()

        log_info(f"Creating table: {self.table_name}")
        tbl = self.connection.create_table(self.table_name, schema=schema, mode="overwrite", exist_ok=True)  # type: ignore
        return tbl  # type: ignore

    def doc_exists(self, document: Document) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        try:
            if self.table is not None:
                cleaned_content = document.content.replace("\x00", "\ufffd")
                doc_id = md5(cleaned_content.encode()).hexdigest()
                result = self.table.search().where(f"{self._id}='{doc_id}'").to_arrow()
                return len(result) > 0
        except Exception:
            # Search sometimes fails with stale cache data, it means the doc doesn't exist
            return False

        return False

    async def async_doc_exists(self, document: Document) -> bool:
        """
        Asynchronously validate if the document exists

        Args:
            document (Document): Document to validate

        Returns:
            bool: True if document exists, False otherwise
        """
        if self.connection:
            self.table = self.connection.open_table(name=self.table_name)
        return self.doc_exists(document)

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
        """
        if len(documents) <= 0:
            log_info("No documents to insert")
            return

        log_info(f"Inserting {len(documents)} documents")
        data = []

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = str(md5(cleaned_content.encode()).hexdigest())
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            data.append(
                {
                    "id": doc_id,
                    "vector": document.embedding,
                    "payload": json.dumps(payload),
                }
            )
            log_debug(f"Parsed document: {document.name} ({document.meta_data})")

        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return

        if not data:
            log_debug("No new data to insert")
            return

        if self.on_bad_vectors is not None:
            self.table.add(data, on_bad_vectors=self.on_bad_vectors, fill_value=self.fill_value)
        else:
            self.table.add(data)

        log_debug(f"Inserted {len(data)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Asynchronously insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
        """
        if len(documents) <= 0:
            log_debug("No documents to insert")
            return

        log_info(f"Inserting {len(documents)} documents")
        data = []

        # Prepare documents for insertion
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = str(md5(cleaned_content.encode()).hexdigest())
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            data.append(
                {
                    "id": doc_id,
                    "vector": document.embedding,
                    "payload": json.dumps(payload),
                }
            )
            log_debug(f"Parsed document: {document.name} ({document.meta_data})")

        if not data:
            log_debug("No new data to insert")
            return

        try:
            await self._get_async_connection()

            if self.on_bad_vectors is not None:
                await self.async_table.add(data, on_bad_vectors=self.on_bad_vectors, fill_value=self.fill_value)  # type: ignore
            else:
                await self.async_table.add(data)  # type: ignore

            log_debug(f"Asynchronously inserted {len(data)} documents")
        except Exception as e:
            logger.error(f"Error during async document insertion: {e}")
            raise

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        self.insert(documents)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        await self.async_insert(documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        if self.connection:
            self.table = self.connection.open_table(name=self.table_name)
        if self.search_type == SearchType.vector:
            return self.vector_search(query, limit)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query, limit)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Asynchronously search for documents matching the query.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search

        Returns:
            List[Document]: List of matching documents
        """
        # TODO: Search is not yet supported in async (https://github.com/lancedb/lancedb/pull/2049)
        if self.connection:
            self.table = self.connection.open_table(name=self.table_name)
        if self.search_type == SearchType.vector:
            return self.vector_search(query, limit)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query, limit)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return []

        results = self.table.search(
            query=query_embedding,
            vector_column_name=self._vector_col,
        ).limit(limit)

        if self.nprobes:
            results.nprobes(self.nprobes)

        results = results.to_pandas()

        search_results = self._build_search_results(results)

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []
        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return []
        if not self.fts_index_exists:
            self.table.create_fts_index("payload", use_tantivy=self.use_tantivy, replace=True)
            self.fts_index_exists = True

        results = (
            self.table.search(
                vector_column_name=self._vector_col,
                query_type="hybrid",
            )
            .vector(query_embedding)
            .text(query)
            .limit(limit)
        )

        if self.nprobes:
            results.nprobes(self.nprobes)

        results = results.to_pandas()

        search_results = self._build_search_results(results)

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return []
        if not self.fts_index_exists:
            self.table.create_fts_index("payload", use_tantivy=self.use_tantivy, replace=True)
            self.fts_index_exists = True

        results = (
            self.table.search(
                query=query,
                query_type="fts",
            )
            .limit(limit)
            .to_pandas()
        )
        search_results = self._build_search_results(results)

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)
        return search_results

    def _build_search_results(self, results) -> List[Document]:  # TODO: typehint pandas?
        search_results: List[Document] = []
        try:
            for _, item in results.iterrows():
                payload = json.loads(item["payload"])
                search_results.append(
                    Document(
                        name=payload["name"],
                        meta_data=payload["meta_data"],
                        content=payload["content"],
                        embedder=self.embedder,
                        embedding=item["vector"],
                        usage=payload["usage"],
                    )
                )

        except Exception as e:
            logger.error(f"Error building search results: {e}")

        return search_results

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.table_name}")
            self.connection.drop_table(self.table_name)  # type: ignore

    async def async_drop(self) -> None:
        """Drop the table asynchronously."""
        if await self.async_exists():
            log_debug(f"Deleting collection: {self.table_name}")
            conn = await self._get_async_connection()
            await conn.drop_table(self.table_name)

    def exists(self) -> bool:
        if self.connection:
            return self.table_name in self.connection.table_names()
        return False

    async def async_exists(self) -> bool:
        """Check if the table exists asynchronously."""
        conn = await self._get_async_connection()
        table_names = await conn.table_names()
        return self.table_name in table_names

    async def async_get_count(self) -> int:
        """Get the number of rows in the table asynchronously."""
        await self._get_async_connection()
        if self.async_table is not None:
            return await self.async_table.count_rows()
        return 0

    def get_count(self) -> int:
        if self.exists() and self.table:
            return self.table.count_rows()
        return 0

    def optimize(self) -> None:
        pass

    def delete(self) -> bool:
        return False

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists in the database"""
        if self.table is None:
            return False

        try:
            result = self.table.search().select(["payload"]).to_pandas()
            # Convert the JSON strings in payload column to dictionaries
            payloads = result["payload"].apply(json.loads)

            # Check if the name exists in any of the payloads
            return any(payload.get("name") == name for payload in payloads)
        except Exception as e:
            logger.error(f"Error checking name existence: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
