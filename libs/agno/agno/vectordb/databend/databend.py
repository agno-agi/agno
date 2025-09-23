import asyncio
import json
from hashlib import md5
from typing import Any, Dict, List, Optional
from datetime import datetime

from agno.vectordb.databend.index import HNSW

try:
    from databend_driver import BlockingDatabendClient
    from databend_driver import BlockingDatabendConnection
    from databend_driver import AsyncDatabendClient
    from databend_driver import AsyncDatabendConnection
except ImportError:
    raise ImportError("`databend-driver` not installed. Use `pip install databend-driver` to install it")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class Databend(VectorDb):
    """
    Databend class for managing vector operations with Databend.

    This class provides methods for creating, inserting, searching, and managing
    vector data in Databend.
    """

    def __init__(
        self,
        table_name: str,
        host: str,
        username: Optional[str] = None,
        password: str = "",
        port: int = 0,
        database_name: str = "ai",
        dsn: Optional[str] = None,
        client: Optional[BlockingDatabendConnection] = None,
        asyncclient: Optional[AsyncDatabendConnection] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        index: Optional[HNSW] = HNSW(),
    ):
        # Store connection parameters as instance attributes
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.dsn = dsn
        self.database_name = database_name

        if not client:
            databend_client = BlockingDatabendClient(
                f"databend://{self.username}:{self.password}@{self.host}:{self.port}/{self.database_name}?sslmode=disable"
            )
            client = databend_client.get_conn()

        # Database attributes
        self.client = client
        self.async_client = asyncclient
        self.table_name = table_name

        # Embedder for embedding the document contents
        _embedder = embedder
        if _embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            _embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = _embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Distance metric
        self.distance: Distance = distance

        # Index for the collection
        self.index: Optional[HNSW] = index

    async def _ensure_async_client(self):
        """Ensure we have an initialized async client."""
        if self.async_client is None:
            databend_async_client = AsyncDatabendClient(
                f"databend://{self.username}:{self.password}@{self.host}:{self.port}/{self.database_name}?sslmode=disable"
            )
            self.async_client = await databend_async_client.get_conn()
        return self.async_client

    def _get_table_columns(self) -> List[str]:
        columns = [
            "id String",
            "name String",
            "meta_data Variant DEFAULT '{}'",
            "filters Variant DEFAULT '{}'",
            "content String",
            "content_id String",
            f"embedding Vector({self.dimensions})",
            "usage Variant",
            "created_at DateTime DEFAULT now()",
            "content_hash String",
        ]

        if isinstance(self.index, HNSW):
            allow_vector_index_feature = False
            try:
                result = self.client.query_row("CALL license_info()")
                if result is not None:
                    features = str(result.values()[6])
                    if "Unlimited" in features or "vector_index" in features:
                        allow_vector_index_feature = True
            except Exception:
                pass

            if allow_vector_index_feature:
                name = f"idx_{self.table_name}_embedding"
                if self.index.name is not None:
                    name = self.index.name
                m = self.index.m
                ef_construct = self.index.ef_construct

                distance = "cosine"
                if self.distance == Distance.l2:
                    distance = "l2"

                columns.append(
                    f"VECTOR INDEX {name}(embedding) distance='{distance}' m='{m}' ef_construct='{ef_construct}'"
                )
        return columns

    def table_exists(self) -> bool:
        log_debug(f"Checking if table exists: {self.table_name}")
        try:
            result = self.client.query_row(
                f"EXISTS TABLE {self.database_name}.{self.table_name}",
            )
            if result is not None:
                return bool(result.values()[0])
            else:
                return False
        except Exception as e:
            logger.error(e)
            return False

    async def async_table_exists(self) -> bool:
        """Check if a table exists asynchronously."""
        log_debug(f"Async checking if table exists: {self.table_name}")
        try:
            async_client = await self._ensure_async_client()

            result = await async_client.query_row(
                f"EXISTS TABLE {self.database_name}.{self.table_name}",
            )
            if result is not None:
                return bool(result.values()[0])
            else:
                return False
        except Exception as e:
            logger.error(f"Async error checking if table exists: {e}")
            return False

    def create(self) -> None:
        if not self.table_exists():
            log_debug(f"Creating Database: {self.database_name}")
            self.client.exec(f"CREATE DATABASE IF NOT EXISTS {self.database_name}")

            log_debug(f"Creating table: {self.table_name}")

            columns = self._get_table_columns()
            column_defs = ", ".join(columns)

            self.client.exec(
                f"CREATE TABLE IF NOT EXISTS {self.database_name}.{self.table_name}({column_defs}) ENGINE = Fuse"
            )

    async def async_create(self) -> None:
        """Create database and table asynchronously."""
        if not await self.async_table_exists():
            log_debug(f"Async creating Database: {self.database_name}")
            async_client = await self._ensure_async_client()

            await async_client.exec(
                f"CREATE DATABASE IF NOT EXISTS {self.database_name}",
            )

            log_debug(f"Async creating table: {self.table_name}")

            columns = self._get_table_columns()
            column_defs = ", ".join(columns)

            await self.async_client.exec(
                f"CREATE TABLE IF NOT EXISTS {self.database_name}.{self.table_name}({column_defs}) ENGINE = Fuse"
            )

    def name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists in the table.

        Args:
            name (str): The name to check.

        Returns:
            bool: True if a document with the name exists, False otherwise.
        """

        result = self.client.query_row(
            f"SELECT name FROM {self.database_name}.{self.table_name} WHERE name = '{name}'",
        )
        if result is not None:
            return bool(len(result) > 0)
        else:
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if name exists asynchronously by running in a thread."""
        async_client = await self._ensure_async_client()

        result = await async_client.query_row(
            f"SELECT name FROM {self.database_name}.{self.table_name} WHERE name = '{name}'",
        )
        if result is not None:
            return bool(len(result) > 0)
        else:
            return False

    def id_exists(self, id: str) -> bool:
        """
        Check if a document with the given ID exists in the table.

        Args:
            id (str): The ID to check.

        Returns:
            bool: True if a document with the ID exists, False otherwise.
        """

        result = self.client.query_row(
            f"SELECT id FROM {self.database_name}.{self.table_name} WHERE id = '{id}'",
        )
        if result is not None:
            return bool(len(result) > 0)
        else:
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """
        Check if a document with the given content hash exists in the table.

        Args:
            content_hash (str): The content hash to check.

        Returns:
            bool: True if a document with the given content hash exists, False otherwise.
        """
        result = self.client.query_row(
            f"SELECT content_hash FROM {self.database_name}.{self.table_name} WHERE content_hash = '{content_hash}'",
        )
        if not result or len(result) == 0:
            return False
        else:
            return True

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Insert documents into the database.

        Args:
            content_hash (str): The content hash to insert.
            documents (List[Document]): List of documents to insert.
            filters (Optional[Dict[str, Any]]): Filters to apply to the documents.
        """
        rows: List[List[Any]] = []
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = md5(cleaned_content.encode()).hexdigest()

            meta_data = document.meta_data or {}
            if filters:
                meta_data.update(filters)

            row: List[Any] = [
                _id,
                document.name,
                json.dumps(meta_data),
                json.dumps(filters),
                cleaned_content,
                document.content_id,
                str(document.embedding),
                json.dumps(document.usage),
                created_at,
                content_hash,
            ]
            rows.append(row)

        self.client.stream_load(
            f"INSERT INTO {self.database_name}.{self.table_name} VALUES",
            rows,
        )
        log_debug(f"Inserted {len(documents)} documents")

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents asynchronously."""
        rows: List[List[Any]] = []
        async_client = await self._ensure_async_client()

        embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
        await asyncio.gather(*embed_tasks, return_exceptions=True)

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = md5(cleaned_content.encode()).hexdigest()

            meta_data = document.meta_data or {}
            if filters:
                meta_data.update(filters)

            row: List[Any] = [
                _id,
                document.name,
                json.dumps(meta_data),
                json.dumps(filters),
                cleaned_content,
                document.content_id,
                str(document.embedding),
                json.dumps(document.usage),
                created_at,
                content_hash,
            ]
            rows.append(row)

        await async_client.stream_load(
            f"INSERT INTO {self.database_name}.{self.table_name} VALUES",
            rows,
        )
        log_debug(f"Async inserted {len(documents)} documents")

    def upsert_available(self) -> bool:
        """
        Check if upsert operation is available.

        Returns:
            bool: Always returns True for Databend.
        """
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Upsert documents by content hash.
        First delete all documents with the same content hash.
        Then upsert the new documents.
        """
        try:
            if self.content_hash_exists(content_hash):
                self._delete_by_content_hash(content_hash)
            self._upsert(content_hash, documents, filters)
        except Exception as e:
            logger.error(f"Error upserting documents by content hash: {e}")
            raise

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Upsert (insert or update) documents in the database.

        Args:
            content_hash (str): The content hash to upsert.
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Filters to apply to the documents.
        """
        rows: List[List[Any]] = []
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = md5(cleaned_content.encode()).hexdigest()

            meta_data = document.meta_data or {}
            if filters:
                meta_data.update(filters)

            row: List[Any] = [
                _id,
                document.name,
                json.dumps(meta_data),
                json.dumps(filters),
                cleaned_content,
                document.content_id,
                str(document.embedding),
                json.dumps(document.usage),
                created_at,
                content_hash,
            ]
            rows.append(row)

        self.client.stream_load(
            f"REPLACE INTO {self.database_name}.{self.table_name} ON(id) VALUES",
            rows,
        )
        log_debug(f"Replaced {len(documents)} documents")

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents asynchronously."""
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        await self._async_upsert(content_hash=content_hash, documents=documents, filters=filters)

    async def _async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Upsert (insert or update) documents in the database.

        Args:
            content_hash (str): The content hash to upsert.
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Filters to apply to the documents.
        """
        rows: List[List[Any]] = []
        async_client = await self._ensure_async_client()

        embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
        await asyncio.gather(*embed_tasks, return_exceptions=True)

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = md5(cleaned_content.encode()).hexdigest()

            row: List[Any] = [
                _id,
                document.name,
                json.dumps(document.meta_data),
                json.dumps(filters),
                cleaned_content,
                document.content_id,
                str(document.embedding),
                json.dumps(document.usage),
                created_at,
                content_hash,
            ]
            rows.append(row)

        await async_client.stream_load(
            f"REPLACE INTO {self.database_name}.{self.table_name} ON(id) VALUES",
            rows,
        )
        log_debug(f"Async replaced {len(documents)} documents")

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """

        try:
            # First, get existing documents with their current metadata and filters
            result = self.client.query_all(
                f"SELECT id, meta_data, filters FROM {self.database_name}.{self.table_name} WHERE content_id = '{content_id}'",
            )

            if result is None or len(result) == 0:
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Update each document
            updated_count = 0
            for row in result:
                doc_id, current_meta_json, current_filters_json = row.values()

                # Parse existing metadata
                try:
                    current_metadata = json.loads(current_meta_json) if current_meta_json else {}
                except (json.JSONDecodeError, TypeError):
                    current_metadata = {}

                # Parse existing filters
                try:
                    current_filters = json.loads(current_filters_json) if current_filters_json else {}
                except (json.JSONDecodeError, TypeError):
                    current_filters = {}

                # Merge existing metadata with new metadata
                updated_metadata = current_metadata.copy()
                updated_metadata.update(metadata)

                # Merge existing filters with new metadata
                updated_filters = current_filters.copy()
                updated_filters.update(metadata)

                # Update the document
                update_params = parameters.copy()
                metadata_json = json.dumps(updated_metadata)
                filters_json = json.dumps(updated_filters)

                self.client.command(
                    f"ALTER TABLE {self.database_name}.{self.table_name} UPDATE meta_data = '{metadata_json}', filters = '{filters_json}' WHERE id = '{doc_id}'",
                )
                updated_count += 1

            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform a search based on the configured search type.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        where_clause = ""
        if filters is not None:
            where_conditions = []
            for key, value in filters.items():
                if isinstance(value, bool):
                    where_conditions.append(f"meta_data['{key}'] = {str(value).lower()}")
                elif isinstance(value, (int, float)):
                    where_conditions.append(f"meta_data['{key}'] = {value}")
                else:
                    where_conditions.append(f"meta_data['{key}'] = '{value}'")
            if len(where_conditions) > 0:
                conditions = " AND ".join(where_conditions)
                where_clause = f"WHERE {conditions}"

        order_by_clause = ""
        if self.distance == Distance.l2:
            order_by_clause = f"ORDER BY l2_distance(embedding, {query_embedding}::Vector({self.dimensions}))"
        if self.distance == Distance.cosine or self.distance == Distance.max_inner_product:
            order_by_clause = f"ORDER BY cosine_distance(embedding, {query_embedding}::Vector({self.dimensions}))"

        query = (
            "SELECT name, meta_data, content, content_id, embedding, usage FROM "
            f"{self.database_name}.{self.table_name} "
            f"{where_clause} {order_by_clause} LIMIT {limit}"
        )
        log_debug(f"Query: {query}")

        try:
            results = self.client.query_all(
                query,
            )
        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            logger.error("Table might not exist, creating for future use")
            self.create()
            return []

        # Build search results
        search_results: List[Document] = []
        for row in results:
            search_results.append(
                Document(
                    name=row.values()[0],
                    meta_data=row.values()[1],
                    content=row.values()[2],
                    content_id=row.values()[3],
                    embedder=self.embedder,
                    embedding=row.values()[4],
                    usage=row.values()[5],
                )
            )

        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for documents asynchronously."""
        async_client = await self._ensure_async_client()

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        where_clause = ""
        if filters is not None:
            where_conditions = []
            for key, value in filters.items():
                if isinstance(value, bool):
                    where_conditions.append(f"meta_data['{key}'] = {str(value).lower()}")
                elif isinstance(value, (int, float)):
                    where_conditions.append(f"meta_data['{key}'] = {value}")
                else:
                    where_conditions.append(f"meta_data['{key}'] = '{value}'")
            if len(where_conditions) > 0:
                conditions = " AND ".join(where_conditions)
                where_clause = f"WHERE {conditions}"

        order_by_clause = ""
        if self.distance == Distance.l2:
            order_by_clause = f"ORDER BY l2_distance(embedding, {query_embedding}::Vector({self.dimensions}))"
        if self.distance == Distance.cosine or self.distance == Distance.max_inner_product:
            order_by_clause = f"ORDER BY cosine_distance(embedding, {query_embedding}::Vector({self.dimensions}))"

        query = (
            "SELECT name, meta_data, content, content_id, embedding, usage FROM "
            f"{self.database_name}.{self.table_name} "
            f"{where_clause} {order_by_clause} LIMIT {limit}"
        )
        log_debug(f"Async Query: {query}")

        try:
            results = await async_client.query_all(
                query,
            )
        except Exception as e:
            logger.error(f"Async error searching for documents: {e}")
            logger.error("Table might not exist, creating for future use")
            await self.async_create()
            return []

        # Build search results
        search_results: List[Document] = []
        for row in results:
            search_results.append(
                Document(
                    name=row.values()[0],
                    meta_data=row.values()[1],
                    content=row.values()[2],
                    content_id=row.values()[3],
                    embedder=self.embedder,
                    embedding=row.values()[4],
                    usage=row.values()[5],
                )
            )

        return search_results

    def drop(self) -> None:
        """
        Drop the table from the database.
        """
        if self.table_exists():
            log_debug(f"Drop table: {self.table_name}")
            self.client.exec(
                f"DROP TABLE {self.database_name}.{self.table_name}",
            )

    async def async_drop(self) -> None:
        """Drop the table asynchronously."""
        if await self.async_exists():
            log_debug(f"Async dropping table: {self.table_name}")
            await self.async_client.exec(
                f"DROP TABLE {self.database_name}.{self.table_name}",
            )

    def exists(self) -> bool:
        """
        Check if the table exists in the database.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        return self.table_exists()

    async def async_exists(self) -> bool:
        """Check if table exists asynchronously by running in a thread."""
        return await self.async_table_exists()

    def get_count(self) -> int:
        """
        Get the number of records in the table.

        Returns:
            int: The number of records in the table.
        """
        result = self.client.query_row(
            f"SELECT count(*) FROM {self.database_name}.{self.table_name}",
        )

        if result is not None:
            return int(result.values()[0])
        return 0

    def optimize(self) -> None:
        log_debug("==== No need to optimize Databend. Skipping this step ====")

    def delete(self) -> bool:
        """
        Delete all records from the table.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        self.client.exec(
            f"DELETE FROM {self.database_name}.{self.table_name}",
        )
        return True

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a document by its ID.

        Args:
            id (str): The document ID to delete

        Returns:
            bool: True if document was deleted, False otherwise
        """
        try:
            log_debug(f"Databend : Deleting document with ID {id}")
            if not self.id_exists(id):
                return False

            self.client.exec(
                f"DELETE FROM {self.database_name}.{self.table_name} WHERE id = '{id}'",
            )
            return True
        except Exception as e:
            log_info(f"Error deleting document with ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name (str): The document name to delete

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Databend : Deleting documents with name {name}")
            if not self.name_exists(name):
                return False

            self.client.exec(
                f"DELETE FROM {self.database_name}.{self.table_name} WHERE name = '{name}'",
            )
            return True
        except Exception as e:
            log_info(f"Error deleting documents with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.

        Args:
            metadata (Dict[str, Any]): The metadata to match for deletion

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Databend : Deleting documents with metadata {metadata}")

            where_conditions = []
            for key, value in metadata.items():
                if isinstance(value, bool):
                    where_conditions.append(f"filters['{key}'] = {str(value).lower()}")
                elif isinstance(value, (int, float)):
                    where_conditions.append(f"filters['{key}'] = {value}")
                else:
                    where_conditions.append(f"filters['{key}'] = '{value}'")

            if not where_conditions:
                return False

            where_clause = " AND ".join(where_conditions)

            self.client.exec(
                f"DELETE FROM {self.database_name}.{self.table_name} WHERE {where_clause}",
            )
            return True
        except Exception as e:
            log_info(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id (str): The content ID to delete

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Databend : Deleting documents with content_id {content_id}")

            self.client.exec(
                f"DELETE FROM {self.database_name}.{self.table_name} WHERE content_id = '{content_id}'",
            )
            return True
        except Exception as e:
            log_info(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """
        Delete documents by content hash.
        """
        try:
            self.client.exec(
                f"DELETE FROM {self.database_name}.{self.table_name} WHERE content_hash = '{content_hash}'",
            )
            return True
        except Exception:
            return False
