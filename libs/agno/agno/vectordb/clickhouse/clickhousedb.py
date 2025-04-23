from hashlib import md5
from typing import Any, Dict, List, Optional

from agno.vectordb.clickhouse.index import HNSW

try:
    import clickhouse_connect
    import clickhouse_connect.driver.asyncclient
    import clickhouse_connect.driver.client
except ImportError:
    raise ImportError("`clickhouse-connect` not installed. Use `pip install clickhouse-connect` to install it")

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class Clickhouse(VectorDb):
    def __init__(
        self,
        table_name: str,
        host: str,
        username: Optional[str] = None,
        password: str = "",
        port: int = 0,
        database_name: str = "ai",
        dsn: Optional[str] = None,
        compress: str = "lz4",
        client: Optional[clickhouse_connect.driver.client.Client] = None,
        asyncclient: Optional[clickhouse_connect.driver.asyncclient.AsyncClient] = None,
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
        self.compress = compress
        self.database_name = database_name

        if not client:
            client = clickhouse_connect.get_client(
                host=self.host,
                username=self.username,  # type: ignore
                password=self.password,
                database=self.database_name,
                port=self.port,
                dsn=self.dsn,
                compress=self.compress,
            )

        # Database attributes
        self.client = client
        self.async_client = asyncclient
        self.table_name = table_name

        # Embedder for embedding the document contents
        _embedder = embedder
        if _embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            _embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = _embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        # Distance metric
        self.distance: Distance = distance

        # Index for the collection
        self.index: Optional[HNSW] = index

    async def _ensure_async_client(self):
        """Ensure we have an initialized async client."""
        if self.async_client is None:
            self.async_client = await clickhouse_connect.get_async_client(
                host=self.host,
                username=self.username,
                password=self.password,
                database=self.database_name,
                port=self.port,
                dsn=self.dsn,
                compress=self.compress,
                settings={"allow_experimental_vector_similarity_index": 1},
            )
        return self.async_client

    def _get_base_parameters(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "database_name": self.database_name,
        }

    def table_exists(self) -> bool:
        log_debug(f"Checking if table exists: {self.table_name}")
        try:
            parameters = self._get_base_parameters()
            return bool(
                self.client.command(
                    "EXISTS TABLE {database_name:Identifier}.{table_name:Identifier}",
                    parameters=parameters,
                )
            )
        except Exception as e:
            logger.error(e)
            return False

    async def async_table_exists(self) -> bool:
        """Check if a table exists asynchronously."""
        log_debug(f"Async checking if table exists: {self.table_name}")
        try:
            async_client = await self._ensure_async_client()

            parameters = self._get_base_parameters()
            result = await async_client.command(
                "EXISTS TABLE {database_name:Identifier}.{table_name:Identifier}",
                parameters=parameters,
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Async error checking if table exists: {e}")
            return False

    def create(self) -> None:
        if not self.table_exists():
            log_debug(f"Creating Database: {self.database_name}")
            parameters = {"database_name": self.database_name}
            self.client.command(
                "CREATE DATABASE IF NOT EXISTS {database_name:Identifier}",
                parameters=parameters,
            )

            log_debug(f"Creating table: {self.table_name}")

            parameters = self._get_base_parameters()

            if isinstance(self.index, HNSW):
                index = (
                    f"INDEX embedding_index embedding TYPE vector_similarity('hnsw', 'L2Distance', {self.index.quantization}, "
                    f"{self.index.hnsw_max_connections_per_layer}, {self.index.hnsw_candidate_list_size_for_construction})"
                )
                self.client.command("SET allow_experimental_vector_similarity_index = 1")
            else:
                raise NotImplementedError(f"Not implemented index {type(self.index)!r} is passed")

            self.client.command("SET enable_json_type = 1")

            self.client.command(
                f"""CREATE TABLE IF NOT EXISTS {{database_name:Identifier}}.{{table_name:Identifier}}
                (
                    id String,
                    name String,
                    meta_data JSON DEFAULT '{{}}',
                    filters JSON DEFAULT '{{}}',
                    content String,
                    embedding Array(Float32),
                    usage JSON,
                    created_at DateTime('UTC') DEFAULT now(),
                    content_hash String,
                    PRIMARY KEY (id),
                    {index}
                ) ENGINE = ReplacingMergeTree ORDER BY id""",
                parameters=parameters,
            )

    async def async_create(self) -> None:
        """Create database and table asynchronously."""
        if not await self.async_table_exists():
            log_debug(f"Async creating Database: {self.database_name}")
            async_client = await self._ensure_async_client()

            parameters = {"database_name": self.database_name}
            await async_client.command(
                "CREATE DATABASE IF NOT EXISTS {database_name:Identifier}",
                parameters=parameters,
            )

            log_debug(f"Async creating table: {self.table_name}")
            parameters = self._get_base_parameters()

            if isinstance(self.index, HNSW):
                index = (
                    f"INDEX embedding_index embedding TYPE vector_similarity('hnsw', 'L2Distance', {self.index.quantization}, "
                    f"{self.index.hnsw_max_connections_per_layer}, {self.index.hnsw_candidate_list_size_for_construction})"
                )
                await async_client.command("SET allow_experimental_vector_similarity_index = 1")
            else:
                raise NotImplementedError(f"Not implemented index {type(self.index)!r} is passed")

            await self.async_client.command("SET enable_json_type = 1")  # type: ignore

            await self.async_client.command(  # type: ignore
                f"""CREATE TABLE IF NOT EXISTS {{database_name:Identifier}}.{{table_name:Identifier}}
                (
                    id String,
                    name String,
                    meta_data JSON DEFAULT '{{}}',
                    filters JSON DEFAULT '{{}}',
                    content String,
                    embedding Array(Float32),
                    usage JSON,
                    created_at DateTime('UTC') DEFAULT now(),
                    content_hash String,
                    PRIMARY KEY (id),
                    {index}
                ) ENGINE = ReplacingMergeTree ORDER BY id""",
                parameters=parameters,
            )

    def doc_exists(self, document: Document) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        cleaned_content = document.content.replace("\x00", "\ufffd")
        parameters = self._get_base_parameters()
        parameters["content_hash"] = md5(cleaned_content.encode()).hexdigest()

        result = self.client.query(
            "SELECT content_hash FROM {database_name:Identifier}.{table_name:Identifier} WHERE content_hash = {content_hash:String}",
            parameters=parameters,
        )
        return bool(result.result_rows)

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists asynchronously."""
        cleaned_content = document.content.replace("\x00", "\ufffd")
        async_client = await self._ensure_async_client()

        parameters = self._get_base_parameters()
        parameters["content_hash"] = md5(cleaned_content.encode()).hexdigest()

        result = await async_client.query(
            "SELECT content_hash FROM {database_name:Identifier}.{table_name:Identifier} WHERE content_hash = {content_hash:String}",
            parameters=parameters,
        )
        return bool(result.result_rows)

    def name_exists(self, name: str) -> bool:
        """
        Validate if a row with this name exists or not

        Args:
            name (str): Name to check
        """
        parameters = self._get_base_parameters()
        parameters["name"] = name

        result = self.client.query(
            "SELECT name FROM {database_name:Identifier}.{table_name:Identifier} WHERE name = {name:String}",
            parameters=parameters,
        )
        return bool(result)

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        parameters = self._get_base_parameters()
        async_client = await self._ensure_async_client()

        parameters["name"] = name

        result = await async_client.query(
            "SELECT name FROM {database_name:Identifier}.{table_name:Identifier} WHERE name = {name:String}",
            parameters=parameters,
        )
        return bool(result)

    def id_exists(self, id: str) -> bool:
        """
        Validate if a row with this id exists or not

        Args:
            id (str): Id to check
        """
        parameters = self._get_base_parameters()
        parameters["id"] = id

        result = self.client.query(
            "SELECT id FROM {database_name:Identifier}.{table_name:Identifier} WHERE id = {id:String}",
            parameters=parameters,
        )
        return bool(result)

    def insert(
        self,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        rows: List[List[Any]] = []
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            content_hash = md5(cleaned_content.encode()).hexdigest()
            _id = document.id or content_hash

            row: List[Any] = [
                _id,
                document.name,
                document.meta_data,
                filters,
                cleaned_content,
                document.embedding,
                document.usage,
                content_hash,
            ]
            rows.append(row)

        self.client.insert(
            f"{self.database_name}.{self.table_name}",
            rows,
            column_names=[
                "id",
                "name",
                "meta_data",
                "filters",
                "content",
                "embedding",
                "usage",
                "content_hash",
            ],
        )
        log_debug(f"Inserted {len(documents)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously."""
        rows: List[List[Any]] = []
        async_client = await self._ensure_async_client()

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            content_hash = md5(cleaned_content.encode()).hexdigest()
            _id = document.id or content_hash

            row: List[Any] = [
                _id,
                document.name,
                document.meta_data,
                filters,
                cleaned_content,
                document.embedding,
                document.usage,
                content_hash,
            ]
            rows.append(row)

        await async_client.insert(
            f"{self.database_name}.{self.table_name}",
            rows,
            column_names=[
                "id",
                "name",
                "meta_data",
                "filters",
                "content",
                "embedding",
                "usage",
                "content_hash",
            ],
        )
        log_debug(f"Async inserted {len(documents)} documents")

    def upsert_available(self) -> bool:
        return True

    def upsert(
        self,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting documents
            batch_size (int): Batch size for upserting documents
        """
        # We are using ReplacingMergeTree engine in our table, so we need to insert the documents,
        # then call SELECT with FINAL
        self.insert(documents=documents, filters=filters)

        parameters = self._get_base_parameters()
        self.client.query(
            "SELECT id FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
            parameters=parameters,
        )

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously."""
        # We are using ReplacingMergeTree engine in our table, so we need to insert the documents,
        # then call SELECT with FINAL
        await self.async_insert(documents=documents, filters=filters)

        parameters = self._get_base_parameters()
        await self.async_client.query(  # type: ignore
            "SELECT id FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
            parameters=parameters,
        )

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        parameters = self._get_base_parameters()
        where_query = ""
        if filters:
            query_filters: List[str] = []
            for key, value in filters.values():
                query_filters.append(f"{{{key}_key:String}} = {{{key}_value:String}}")
                parameters[f"{key}_key"] = key
                parameters[f"{key}_value"] = value
            where_query = f"WHERE {' AND '.join(query_filters)}"

        order_by_query = ""
        if self.distance == Distance.l2 or self.distance == Distance.max_inner_product:
            order_by_query = "ORDER BY L2Distance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding
        if self.distance == Distance.cosine:
            order_by_query = "ORDER BY cosineDistance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding

        clickhouse_query = (
            "SELECT name, meta_data, content, embedding, usage FROM "
            "{database_name:Identifier}.{table_name:Identifier} "
            f"{where_query} {order_by_query} LIMIT {limit}"
        )
        log_debug(f"Query: {clickhouse_query}")
        log_debug(f"Params: {parameters}")

        try:
            results = self.client.query(
                clickhouse_query,
                parameters=parameters,
            )
        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            logger.error("Table might not exist, creating for future use")
            self.create()
            return []

        # Build search results
        search_results: List[Document] = []
        for result in results.result_rows:
            search_results.append(
                Document(
                    name=result[0],
                    meta_data=result[1],
                    content=result[2],
                    embedder=self.embedder,
                    embedding=result[3],
                    usage=result[4],
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

        parameters = self._get_base_parameters()
        where_query = ""
        if filters:
            query_filters: List[str] = []
            for key, value in filters.values():
                query_filters.append(f"{{{key}_key:String}} = {{{key}_value:String}}")
                parameters[f"{key}_key"] = key
                parameters[f"{key}_value"] = value
            where_query = f"WHERE {' AND '.join(query_filters)}"

        order_by_query = ""
        if self.distance == Distance.l2 or self.distance == Distance.max_inner_product:
            order_by_query = "ORDER BY L2Distance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding
        if self.distance == Distance.cosine:
            order_by_query = "ORDER BY cosineDistance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding

        clickhouse_query = (
            "SELECT name, meta_data, content, embedding, usage FROM "
            "{database_name:Identifier}.{table_name:Identifier} "
            f"{where_query} {order_by_query} LIMIT {limit}"
        )
        log_debug(f"Async Query: {clickhouse_query}")
        log_debug(f"Async Params: {parameters}")

        try:
            results = await async_client.query(
                clickhouse_query,
                parameters=parameters,
            )
        except Exception as e:
            logger.error(f"Async error searching for documents: {e}")
            logger.error("Table might not exist, creating for future use")
            await self.async_create()
            return []

        # Build search results
        search_results: List[Document] = []
        for result in results.result_rows:
            search_results.append(
                Document(
                    name=result[0],
                    meta_data=result[1],
                    content=result[2],
                    embedder=self.embedder,
                    embedding=result[3],
                    usage=result[4],
                )
            )

        return search_results

    def drop(self) -> None:
        if self.table_exists():
            log_debug(f"Deleting table: {self.table_name}")
            parameters = self._get_base_parameters()
            self.client.command(
                "DROP TABLE {database_name:Identifier}.{table_name:Identifier}",
                parameters=parameters,
            )

    async def async_drop(self) -> None:
        """Drop the table asynchronously."""
        if await self.async_exists():
            log_debug(f"Async dropping table: {self.table_name}")
            parameters = self._get_base_parameters()
            await self.async_client.command(  # type: ignore
                "DROP TABLE {database_name:Identifier}.{table_name:Identifier}",
                parameters=parameters,
            )

    def exists(self) -> bool:
        return self.table_exists()

    async def async_exists(self) -> bool:
        return await self.async_table_exists()

    def get_count(self) -> int:
        parameters = self._get_base_parameters()
        result = self.client.query(
            "SELECT count(*) FROM {database_name:Identifier}.{table_name:Identifier}",
            parameters=parameters,
        )

        if result.first_row:
            return int(result.first_row[0])
        return 0

    def optimize(self) -> None:
        log_debug("==== No need to optimize Clickhouse DB. Skipping this step ====")

    def delete(self) -> bool:
        parameters = self._get_base_parameters()
        self.client.command(
            "DELETE FROM {database_name:Identifier}.{table_name:Identifier}",
            parameters=parameters,
        )
        return True
