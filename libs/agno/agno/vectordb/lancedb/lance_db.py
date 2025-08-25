import asyncio
import json
from hashlib import md5
from os import getenv
from typing import Any, Dict, List, Optional

try:
    import lancedb
    import pyarrow as pa
except ImportError:
    raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
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
            from agno.knowledge.embedder.openai import OpenAIEmbedder

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

        # Remote LanceDB connection details
        self.api_key: Optional[str] = api_key

        # LanceDB connection details
        self.uri: lancedb.URI = uri
        self.connection: lancedb.DBConnection = connection or lancedb.connect(uri=self.uri, api_key=api_key)
        self.table: Optional[lancedb.db.LanceTable] = table

        self.async_connection: Optional[lancedb.AsyncConnection] = async_connection
        self.async_table: Optional[lancedb.db.AsyncTable] = async_table

        if table_name and table_name in self.connection.table_names():
            # Open the table if it exists
            try:
                self.table = self.connection.open_table(name=table_name)
                self.table_name = self.table.name
                self._vector_col = self.table.schema.names[0]
                self._id = self.table.schema.names[1]  # type: ignore
            except ValueError as e:
                # Table might have been dropped by async operations but sync connection hasn't updated
                if "was not found" in str(e):
                    log_debug(f"Table {table_name} listed but not accessible, will create if needed")
                    self.table = None
                else:
                    raise

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
                self._id = self.table.schema.names[1]  # type: ignore
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
        # Only try to open table if it exists and we don't have it already
        if self.async_table is None:
            table_names = await self.async_connection.table_names()
            if self.table_name in table_names:
                try:
                    self.async_table = await self.async_connection.open_table(self.table_name)
                except ValueError:
                    # Table might have been dropped by another operation
                    pass
        return self.async_connection

    def _refresh_sync_connection(self) -> None:
        """Refresh the sync connection to see changes made by async operations."""
        try:
            # Re-establish sync connection to see async changes
            if self.connection and self.table_name in self.connection.table_names():
                self.table = self.connection.open_table(self.table_name)
                log_debug(f"Refreshed sync connection for table: {self.table_name}")
        except Exception as e:
            log_debug(f"Could not refresh sync connection: {e}")
            # If refresh fails, we can still function but sync methods might not see async changes

    def create(self) -> None:
        """Create the table if it does not exist."""
        if not self.exists():
            self.table = self._init_table()

    async def async_create(self) -> None:
        """Create the table asynchronously if it does not exist."""
        if not await self.async_exists():
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
        if self.api_key or getenv("LANCEDB_API_KEY"):
            log_info("API key found, creating table in remote LanceDB")
            tbl = self.connection.create_table(name=self.table_name, schema=schema, mode="overwrite")  # type: ignore
        else:
            tbl = self.connection.create_table(name=self.table_name, schema=schema, mode="overwrite", exist_ok=True)  # type: ignore
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

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to add as metadata to documents
        """
        if len(documents) <= 0:
            log_info("No documents to insert")
            return

        log_debug(f"Inserting {len(documents)} documents")
        data = []

        for document in documents:
            if self.doc_exists(document):
                continue

            # Add filters to document metadata if provided
            if filters:
                meta_data = document.meta_data.copy() if document.meta_data else {}
                meta_data.update(filters)
                document.meta_data = meta_data

            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = str(md5(cleaned_content.encode()).hexdigest())
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
                "content_id": document.content_id,
                "content_hash": content_hash,
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

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Asynchronously insert documents into the database.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
        """
        if len(documents) <= 0:
            log_debug("No documents to insert")
            return

        log_debug(f"Inserting {len(documents)} documents")
        data = []

        # Prepare documents for insertion.
        embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
        await asyncio.gather(*embed_tasks, return_exceptions=True)

        for document in documents:
            if await self.async_doc_exists(document):
                continue

            # Add filters to document metadata if provided
            if filters:
                meta_data = document.meta_data.copy() if document.meta_data else {}
                meta_data.update(filters)
                document.meta_data = meta_data

            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = str(md5(cleaned_content.encode()).hexdigest())
            payload = {
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
                "content_id": document.content_id,
                "content_hash": content_hash,
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

            # Refresh sync connection to see async changes
            self._refresh_sync_connection()
        except Exception as e:
            logger.error(f"Error during async document insertion: {e}")
            raise

    def upsert_available(self) -> bool:
        """Check if upsert is available in LanceDB."""
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self.insert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        await self.async_insert(content_hash=content_hash, documents=documents, filters=filters)

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
        if self.connection:
            self.table = self.connection.open_table(name=self.table_name)

        results = None

        if self.search_type == SearchType.vector:
            results = self.vector_search(query, limit)
        elif self.search_type == SearchType.keyword:
            results = self.keyword_search(query, limit)
        elif self.search_type == SearchType.hybrid:
            results = self.hybrid_search(query, limit)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

        if results is None:
            return []

        search_results = self._build_search_results(results)

        # Filter results based on metadata if filters are provided
        if filters and search_results:
            filtered_results = []
            for doc in search_results:
                if doc.meta_data is None:
                    continue

                # Check if all filter criteria match
                match = True
                for key, value in filters.items():
                    if key not in doc.meta_data or doc.meta_data[key] != value:
                        match = False
                        break

                if match:
                    filtered_results.append(doc)

            search_results = filtered_results

        if self.reranker and search_results:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        log_info(f"Found {len(search_results)} documents")
        return search_results

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

        results = None

        if self.search_type == SearchType.vector:
            results = self.vector_search(query, limit)
        elif self.search_type == SearchType.keyword:
            results = self.keyword_search(query, limit)
        elif self.search_type == SearchType.hybrid:
            results = self.hybrid_search(query, limit)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

        if results is None:
            return []

        search_results = self._build_search_results(results)

        # Filter results based on metadata if filters are provided
        if filters and search_results:
            filtered_results = []
            for doc in search_results:
                if doc.meta_data is None:
                    continue

                # Check if all filter criteria match
                match = True
                for key, value in filters.items():
                    if key not in doc.meta_data or doc.meta_data[key] != value:
                        match = False
                        break

                if match:
                    filtered_results.append(doc)

            search_results = filtered_results

        if self.reranker and search_results:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return None

        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return None  # type: ignore

        results = self.table.search(
            query=query_embedding,
            vector_column_name=self._vector_col,
        ).limit(limit)

        if self.nprobes:
            results.nprobes(self.nprobes)

        return results.to_pandas()

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

        return results.to_pandas()

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        if self.table is None:
            logger.error("Table not initialized. Please create the table first")
            return []

        if not self.fts_index_exists:
            self.table.create_fts_index("payload", use_tantivy=self.use_tantivy, replace=True)
            self.fts_index_exists = True

        results = self.table.search(
            query=query,
            query_type="fts",
        ).limit(limit)

        return results.to_pandas()

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
                        content_id=payload.get("content_id"),
                    )
                )

        except Exception as e:
            logger.error(f"Error building search results: {e}")

        return search_results

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.table_name}")
            self.connection.drop_table(self.table_name)  # type: ignore
            # Clear the table reference after dropping
            self.table = None

    async def async_drop(self) -> None:
        """Drop the table asynchronously."""
        if await self.async_exists():
            log_debug(f"Deleting collection: {self.table_name}")
            conn = await self._get_async_connection()
            await conn.drop_table(self.table_name)
            # Clear the async table reference after dropping
            self.async_table = None

    def exists(self) -> bool:
        # If we have an async table that was created, the table exists
        if self.async_table is not None:
            return True
        if self.connection:
            return self.table_name in self.connection.table_names()
        return False

    async def async_exists(self) -> bool:
        """Check if the table exists asynchronously."""
        # If we have an async table that was created, the table exists
        if self.async_table is not None:
            return True
        # Check if table exists in database without trying to open it
        if self.async_connection is None:
            self.async_connection = await lancedb.connect_async(self.uri)
        table_names = await self.async_connection.table_names()
        return self.table_name in table_names

    async def async_get_count(self) -> int:
        """Get the number of rows in the table asynchronously."""
        await self._get_async_connection()
        if self.async_table is not None:
            return await self.async_table.count_rows()
        return 0

    def _async_get_count_sync(self) -> int:
        """Helper method to run async_get_count in a new thread with its own event loop"""
        import asyncio

        return asyncio.run(self.async_get_count())

    def get_count(self) -> int:
        # If we have data in the async table but sync table isn't available, try to get count from async table
        if self.async_table is not None:
            try:
                import asyncio

                # Check if we're already in an async context
                try:
                    return self._async_get_count_sync()
                except RuntimeError:
                    # No event loop running, safe to use asyncio.run
                    return asyncio.run(self.async_get_count())
            except Exception:
                pass

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

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the database"""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            # Search for the document with the specific ID
            result = self.table.search().where(f"{self._id} = '{id}'").to_pandas()
            return len(result) > 0
        except Exception as e:
            logger.error(f"Error checking id existence: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete content by ID."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            # Delete rows where the id matches
            self.table.delete(f"{self._id} = '{id}'")
            log_info(f"Deleted records with id '{id}' from table '{self.table_name}'.")
            return True
        except Exception as e:
            logger.error(f"Error deleting rows by id '{id}': {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete content by name."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            total_count = self.table.count_rows()
            result = self.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

            # Find matching IDs
            ids_to_delete = []
            for _, row in result.iterrows():
                payload = json.loads(row["payload"])
                if payload.get("name") == name:
                    ids_to_delete.append(row["id"])

            # Delete matching records
            if ids_to_delete:
                for doc_id in ids_to_delete:
                    self.table.delete(f"{self._id} = '{doc_id}'")
                log_info(f"Deleted {len(ids_to_delete)} records with name '{name}' from table '{self.table_name}'.")
                return True
            else:
                log_info(f"No records found with name '{name}' to delete.")
                return False

        except Exception as e:
            logger.error(f"Error deleting rows by name '{name}': {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete content by metadata."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            total_count = self.table.count_rows()
            result = self.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

            # Find matching IDs
            ids_to_delete = []
            for _, row in result.iterrows():
                payload = json.loads(row["payload"])
                doc_metadata = payload.get("meta_data", {})

                # Check if all metadata key-value pairs match
                match = True
                for key, value in metadata.items():
                    if key not in doc_metadata or doc_metadata[key] != value:
                        match = False
                        break

                if match:
                    ids_to_delete.append(row["id"])

            # Delete matching records
            if ids_to_delete:
                for doc_id in ids_to_delete:
                    self.table.delete(f"{self._id} = '{doc_id}'")
                log_info(
                    f"Deleted {len(ids_to_delete)} records with metadata '{metadata}' from table '{self.table_name}'."
                )
                return True
            else:
                log_info(f"No records found with metadata '{metadata}' to delete.")
                return False

        except Exception as e:
            logger.error(f"Error deleting rows by metadata '{metadata}': {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete content by content ID."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            total_count = self.table.count_rows()
            result = self.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

            # Find matching IDs
            ids_to_delete = []
            for _, row in result.iterrows():
                payload = json.loads(row["payload"])
                if payload.get("content_id") == content_id:
                    ids_to_delete.append(row["id"])

            # Delete matching records
            if ids_to_delete:
                for doc_id in ids_to_delete:
                    self.table.delete(f"{self._id} = '{doc_id}'")
                log_info(
                    f"Deleted {len(ids_to_delete)} records with content_id '{content_id}' from table '{self.table_name}'."
                )
                return True
            else:
                log_info(f"No records found with content_id '{content_id}' to delete.")
                return False

        except Exception as e:
            logger.error(f"Error deleting rows by content_id '{content_id}': {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete content by content hash."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            total_count = self.table.count_rows()
            result = self.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

            # Find matching IDs
            ids_to_delete = []
            for _, row in result.iterrows():
                payload = json.loads(row["payload"])
                if payload.get("content_hash") == content_hash:
                    ids_to_delete.append(row["id"])

            # Delete matching records
            if ids_to_delete:
                for doc_id in ids_to_delete:
                    self.table.delete(f"{self._id} = '{doc_id}'")
                log_info(
                    f"Deleted {len(ids_to_delete)} records with content_hash '{content_hash}' from table '{self.table_name}'."
                )
                return True
            else:
                log_info(f"No records found with content_hash '{content_hash}' to delete.")
                return False

        except Exception as e:
            logger.error(f"Error deleting rows by content_hash '{content_hash}': {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if documents with the given content hash exist."""
        if self.table is None:
            logger.error("Table not initialized")
            return False

        try:
            total_count = self.table.count_rows()
            result = self.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

            # Check if any records match the content_hash
            for _, row in result.iterrows():
                payload = json.loads(row["payload"])
                if payload.get("content_hash") == content_hash:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking content_hash existence '{content_hash}': {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        import json

        try:
            if self.table is None:
                logger.error("Table not initialized")
                return

            # Search for documents with the given content_id
            query_filter = f"payload->>'content_id' = '{content_id}'"
            results = self.table.search().where(query_filter).to_pandas()

            if results.empty:
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Update each matching document
            updated_count = 0
            for _, row in results.iterrows():
                row_id = row["id"]
                current_payload = json.loads(row["payload"])

                # Merge existing metadata with new metadata
                if "meta_data" in current_payload:
                    current_payload["meta_data"].update(metadata)
                else:
                    current_payload["meta_data"] = metadata

                if "filters" in current_payload:
                    if isinstance(current_payload["filters"], dict):
                        current_payload["filters"].update(metadata)
                    else:
                        current_payload["filters"] = metadata
                else:
                    current_payload["filters"] = metadata

                # Update the document
                update_data = {"id": row_id, "payload": json.dumps(current_payload)}

                # LanceDB doesn't have a direct update, so we need to delete and re-insert
                # First, get all the existing data
                vector_data = row["vector"] if "vector" in row else None
                text_data = row["text"] if "text" in row else None

                # Create complete update record
                if vector_data is not None:
                    update_data["vector"] = vector_data
                if text_data is not None:
                    update_data["text"] = text_data

                # Delete old record and insert updated one
                self.table.delete(f"id = '{row_id}'")
                self.table.add([update_data])
                updated_count += 1

            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise
