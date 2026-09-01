import asyncio
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

from agno.vectordb.clickhouse.index import HNSW

try:
    import clickhouse_connect
    import clickhouse_connect.driver.asyncclient
    import clickhouse_connect.driver.client
except ImportError:
    raise ImportError("`clickhouse-connect` not installed. Use `pip install clickhouse-connect` to install it")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger
from agno.vectordb.base import (
    VectorDb,
    aembed_before_replace,
    embed_before_replace,
    is_rate_limit_error,
    raise_embedding_failures,
)
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

# Empty string marks a shared/unowned chunk in the user_id String column.
SHARED_OWNER = ""


class Clickhouse(VectorDb):
    def __init__(
        self,
        table_name: str,
        host: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
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
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

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

        # Whether the live table has the ``user_id`` column; resolved lazily and cached.
        self._owner_column_exists: Optional[bool] = None

        # Embedder for embedding the document contents
        _embedder = embedder
        if _embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            _embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
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
                username=self.username,  # type: ignore
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
        except Exception:
            logger.exception("Error checking if table exists")
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
        except Exception:
            logger.exception("Async error checking if table exists")
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
                    f"INDEX embedding_index embedding TYPE vector_similarity('hnsw', 'L2Distance', {self.embedder.dimensions}, {self.index.quantization}, "
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
                    content_id String,
                    embedding Array(Float32),
                    usage JSON,
                    created_at DateTime('UTC') DEFAULT now(),
                    content_hash String,
                    user_id String DEFAULT '',
                    PRIMARY KEY (id),
                    {index}
                ) ENGINE = ReplacingMergeTree ORDER BY id""",
                parameters=parameters,
            )
            self._owner_column_exists = True

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
                    f"INDEX embedding_index embedding TYPE vector_similarity('hnsw', 'L2Distance', {self.embedder.dimensions}, {self.index.quantization}, "
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
                    content_id String,
                    embedding Array(Float32),
                    usage JSON,
                    created_at DateTime('UTC') DEFAULT now(),
                    content_hash String,
                    user_id String DEFAULT '',
                    PRIMARY KEY (id),
                    {index}
                ) ENGINE = ReplacingMergeTree ORDER BY id""",
                parameters=parameters,
            )
            self._owner_column_exists = True

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
        return len(result.result_rows) > 0 if result.result_rows else False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        parameters = self._get_base_parameters()
        async_client = await self._ensure_async_client()

        parameters["name"] = name

        result = await async_client.query(
            "SELECT name FROM {database_name:Identifier}.{table_name:Identifier} WHERE name = {name:String}",
            parameters=parameters,
        )
        return len(result.result_rows) > 0 if result.result_rows else False

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
        return len(result.result_rows) > 0 if result.result_rows else False

    def _user_id_column_exists(self) -> bool:
        """Whether the live table has the ``user_id`` column. Tables created before the v2 -> v3
        migration lack it, so the live schema is inspected. Cached after the first lookup."""
        if self._owner_column_exists is None:
            try:
                if not self.table_exists():
                    # No live table yet — it will be created with the column.
                    self._owner_column_exists = True
                else:
                    parameters = self._get_base_parameters()
                    result = self.client.query(
                        "SELECT 1 FROM system.columns WHERE database = {database_name:String} "
                        "AND table = {table_name:String} AND name = 'user_id'",
                        parameters=parameters,
                    )
                    self._owner_column_exists = len(result.result_rows) > 0 if result.result_rows else False
            except Exception:
                # Assume migrated for this call only, uncached, so the next call re-inspects.
                log_warning(
                    f"Could not inspect table '{self.table_name}' for the user_id column; "
                    "proceeding as migrated for this operation."
                )
                return True
        return self._owner_column_exists

    def _require_owner_column(self, user_id: Optional[str]) -> bool:
        """Whether SQL may reference the ``user_id`` column. False when it is missing and the
        operation is unscoped, so the caller falls back to pre-v3 SQL; a scoped operation raises."""
        if self._user_id_column_exists():
            return True
        if user_id is None:
            return False
        # The cached answer may predate a migration run, so re-inspect once before refusing.
        self._owner_column_exists = None
        if self._user_id_column_exists():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but table '{self.database_name}.{self.table_name}' predates per-user "
            "isolation and has no 'user_id' column. Run the v2 -> v3 migration "
            "(libs/agno/migrations/v2_to_v3/migrate_sql_vectordbs.py) or recreate the table."
        )

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """Reject an empty user_id: "" is the reserved shared-owner sentinel; use None for shared."""
        if user_id == "":
            raise ValueError(
                "user_id must not be an empty string - that value is reserved to mark content shared with every user"
            )

    def _scoped_record_id(self, cleaned_content: str, user_id: Optional[str]) -> str:
        """Fold the owner into the deterministic id so two users get distinct rows for the same
        content; None keeps the plain digest. Content is digested first so the '_' boundary is fixed."""
        _id = md5(cleaned_content.encode()).hexdigest()
        if user_id is None:
            return _id
        return md5(f"{_id}_{user_id}".encode()).hexdigest()

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self._validate_user_id(user_id)
        # Unscoped inserts fall back to the pre-v3 column list; scoped ones raise.
        include_owner = self._require_owner_column(user_id)
        owner = user_id if user_id is not None else SHARED_OWNER
        rows: List[List[Any]] = []
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = self._scoped_record_id(cleaned_content, user_id)

            row: List[Any] = [
                _id,
                document.name,
                document.meta_data,
                filters,
                cleaned_content,
                document.content_id,
                document.embedding,
                document.usage,
                content_hash,
            ]
            if include_owner:
                row.append(owner)
            rows.append(row)

        column_names = [
            "id",
            "name",
            "meta_data",
            "filters",
            "content",
            "content_id",
            "embedding",
            "usage",
            "content_hash",
        ]
        if include_owner:
            column_names.append("user_id")

        self.client.insert(
            f"{self.database_name}.{self.table_name}",
            rows,
            column_names=column_names,
        )
        log_debug(f"Inserted {len(documents)} documents")

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents asynchronously."""
        self._validate_user_id(user_id)
        # Unscoped inserts fall back to the pre-v3 column list; scoped ones raise.
        include_owner = self._require_owner_column(user_id)
        owner = user_id if user_id is not None else SHARED_OWNER
        rows: List[List[Any]] = []
        async_client = await self._ensure_async_client()

        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            # Use batch embedding when enabled and supported
            try:
                # Extract content from all documents
                doc_contents = [doc.content for doc in documents]

                # Get batch embeddings and usage
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                # Process documents with pre-computed embeddings
                for j, doc in enumerate(documents):
                    try:
                        if j < len(embeddings):
                            doc.embedding = embeddings[j]
                            doc.usage = usages[j] if j < len(usages) else None
                    except Exception:
                        logger.exception(f"Error assigning batch embedding to document '{doc.name}'")

            except Exception as e:
                # A throttle must not fall back to per-item calls, which would throttle harder.
                is_rate_limit = is_rate_limit_error(e)

                if is_rate_limit:
                    logger.exception("Rate limit detected during batch embedding.")
                    raise e
                else:
                    log_warning(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                    raise_embedding_failures(results)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            _id = self._scoped_record_id(cleaned_content, user_id)

            row: List[Any] = [
                _id,
                document.name,
                document.meta_data,
                filters,
                cleaned_content,
                document.content_id,
                document.embedding,
                document.usage,
                content_hash,
            ]
            if include_owner:
                row.append(owner)
            rows.append(row)

        column_names = [
            "id",
            "name",
            "meta_data",
            "filters",
            "content",
            "content_id",
            "embedding",
            "usage",
            "content_hash",
        ]
        if include_owner:
            column_names.append("user_id")

        await async_client.insert(
            f"{self.database_name}.{self.table_name}",
            rows,
            column_names=column_names,
        )
        log_debug(f"Async inserted {len(documents)} documents")

    def upsert_available(self) -> bool:
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents into the database.
        """
        self._validate_user_id(user_id)
        # Raise early on a scoped upsert against an unmigrated table.
        self._require_owner_column(user_id)
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        embed_before_replace(documents, self.embedder)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)
        self.insert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting documents
            user_id (Optional[str]): Explicit owner for per-user RAG isolation.
        """
        # We are using ReplacingMergeTree engine in our table, so we need to insert the documents,
        # then call SELECT with FINAL
        self.insert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)

        parameters = self._get_base_parameters()
        self.client.query(
            "SELECT id FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
            parameters=parameters,
        )

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously."""
        self._validate_user_id(user_id)
        # Raise early on a scoped upsert against an unmigrated table.
        self._require_owner_column(user_id)
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        await aembed_before_replace(documents, self.embedder)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)
        await self._async_upsert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)

    async def _async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously."""
        # We are using ReplacingMergeTree engine in our table, so we need to insert the documents,
        # then call SELECT with FINAL
        await self.async_insert(content_hash=content_hash, documents=documents, filters=filters, user_id=user_id)

        parameters = self._get_base_parameters()
        await self.async_client.query(  # type: ignore
            "SELECT id FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
            parameters=parameters,
        )

    def _user_scope_where_clause(self, parameters: Dict[str, Any], user_id: Optional[str]) -> str:
        """WHERE fragment matching the owner's rows plus shared ('') rows; "" when user_id is None."""
        if user_id is None:
            return ""
        parameters["user_id"] = user_id
        return "WHERE (user_id = {user_id:String} OR user_id = '')"

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        self._validate_user_id(user_id)
        # Ahead of the try below so a scoped search raises instead of returning [].
        self._require_owner_column(user_id)
        if filters is not None:
            log_warning("Filters are not yet supported in Clickhouse. No filters will be applied.")
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        parameters = self._get_base_parameters()
        where_query = self._user_scope_where_clause(parameters, user_id)

        order_by_query = ""
        if self.distance == Distance.l2 or self.distance == Distance.max_inner_product:
            order_by_query = "ORDER BY L2Distance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding
        if self.distance == Distance.cosine:
            order_by_query = "ORDER BY cosineDistance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding

        clickhouse_query = (
            "SELECT name, meta_data, content, content_id, embedding, usage FROM "
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
            logger.exception("Error searching for documents")
            log_error(f"Table might not exist, creating for future use: {str(e)}")
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
                    content_id=result[3],
                    embedder=self.embedder,
                    embedding=result[4],
                    usage=result[5],
                )
            )

        return search_results

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search for documents asynchronously."""
        self._validate_user_id(user_id)
        # See ``search`` — raises here instead of being swallowed into [].
        self._require_owner_column(user_id)
        async_client = await self._ensure_async_client()

        if filters is not None:
            log_warning("Filters are not yet supported in Clickhouse. No filters will be applied.")

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        parameters = self._get_base_parameters()
        where_query = self._user_scope_where_clause(parameters, user_id)

        order_by_query = ""
        if self.distance == Distance.l2 or self.distance == Distance.max_inner_product:
            order_by_query = "ORDER BY L2Distance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding
        if self.distance == Distance.cosine:
            order_by_query = "ORDER BY cosineDistance(embedding, {query_embedding:Array(Float32)})"
            parameters["query_embedding"] = query_embedding

        clickhouse_query = (
            "SELECT name, meta_data, content, content_id, embedding, usage FROM "
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
            logger.exception("Async error searching for documents")
            log_error(f"Table might not exist, creating for future use: {str(e)}")
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
                    content_id=result[3],
                    embedder=self.embedder,
                    embedding=result[4],
                    usage=result[5],
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
            # The next table under this name will have the owner column; re-resolve lazily.
            self._owner_column_exists = None

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

    def delete_by_id(self, id: str) -> bool:
        """

        Delete a document by its ID.

        Args:
            id (str): The document ID to delete

        Returns:
            bool: True if document was deleted, False otherwise
        """
        try:
            log_debug(f"ClickHouse VectorDB : Deleting document with ID {id}")
            if not self.id_exists(id):
                return False

            parameters = self._get_base_parameters()
            parameters["id"] = id

            self.client.command(
                "DELETE FROM {database_name:Identifier}.{table_name:Identifier} WHERE id = {id:String}",
                parameters=parameters,
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
            log_debug(f"ClickHouse VectorDB : Deleting documents with name {name}")
            if not self.name_exists(name):
                return False

            parameters = self._get_base_parameters()
            parameters["name"] = name

            self.client.command(
                "DELETE FROM {database_name:Identifier}.{table_name:Identifier} WHERE name = {name:String}",
                parameters=parameters,
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
            log_debug(f"ClickHouse VectorDB : Deleting documents with metadata {metadata}")
            parameters = self._get_base_parameters()

            # Build a parameterised WHERE clause so that user-supplied metadata
            # keys and values are never interpolated directly into SQL.
            # Each key/value pair gets its own named ClickHouse parameter
            # ({meta_key_N:String} / {meta_val_N:String|Float64|Bool}) so the
            # client driver handles escaping, eliminating the SQL-injection path.
            where_conditions = []
            for i, (key, value) in enumerate(metadata.items()):
                param_key = f"meta_key_{i}"
                param_val = f"meta_val_{i}"
                parameters[param_key] = key
                if isinstance(value, bool):
                    parameters[param_val] = value
                    where_conditions.append(
                        f"JSONExtractBool(toString(filters), {{{param_key}:String}}) = {{{param_val}:Bool}}"
                    )
                elif isinstance(value, (int, float)):
                    parameters[param_val] = float(value)
                    where_conditions.append(
                        f"JSONExtractFloat(toString(filters), {{{param_key}:String}}) = {{{param_val}:Float64}}"
                    )
                else:
                    parameters[param_val] = str(value)
                    where_conditions.append(
                        f"JSONExtractString(toString(filters), {{{param_key}:String}}) = {{{param_val}:String}}"
                    )

            if not where_conditions:
                return False

            where_clause = " AND ".join(where_conditions)

            self.client.command(
                f"DELETE FROM {{database_name:Identifier}}.{{table_name:Identifier}} WHERE {where_clause}",
                parameters=parameters,
            )
            return True
        except Exception as e:
            log_info(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id (str): The content ID to delete
            user_id (Optional[str]): When set, scope the delete to this owner's rows.

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        self._validate_user_id(user_id)
        # Outside the try so a scoped delete raises instead of returning False.
        self._require_owner_column(user_id)
        try:
            log_debug(f"ClickHouse VectorDB : Deleting documents with content_id {content_id}")
            parameters = self._get_base_parameters()
            parameters["content_id"] = content_id

            where_clause = "WHERE content_id = {content_id:String}"
            if user_id is not None:
                parameters["user_id"] = user_id
                where_clause += " AND user_id = {user_id:String}"

            self.client.command(
                f"DELETE FROM {{database_name:Identifier}}.{{table_name:Identifier}} {where_clause}",
                parameters=parameters,
            )
            return True
        except Exception as e:
            log_info(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Validate if a row with this content_hash exists or not

        Args:
            content_hash (str): Content hash to check
            user_id (Optional[str]): Owner to scope the check to; None checks the shared ("")
                bucket alone, matching what _delete_by_content_hash clears for None.
        """
        self._validate_user_id(user_id)
        # An unmigrated table has no owner column, so the whole table is the shared bucket.
        scope_to_owner = self._require_owner_column(user_id)
        parameters = self._get_base_parameters()
        parameters["content_hash"] = content_hash

        where_clause = "WHERE content_hash = {content_hash:String}"
        if scope_to_owner:
            parameters["user_id"] = user_id if user_id is not None else SHARED_OWNER
            where_clause += " AND user_id = {user_id:String}"

        result = self.client.query(
            f"SELECT content_hash FROM {{database_name:Identifier}}.{{table_name:Identifier}} {where_clause}",
            parameters=parameters,
        )
        return len(result.result_rows) > 0 if result.result_rows else False

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content hash.

        Args:
            content_hash (str): The content hash to delete
            user_id (Optional[str]): Owner to scope the delete to; None scopes to the shared ("")
                bucket so a shared re-upsert never wipes a scoped owner's identical-content row.
        """
        self._validate_user_id(user_id)
        # Outside the try so a scoped delete raises instead of returning False.
        scope_to_owner = self._require_owner_column(user_id)
        try:
            parameters = self._get_base_parameters()
            parameters["content_hash"] = content_hash

            where_clause = "WHERE content_hash = {content_hash:String}"
            if scope_to_owner:
                parameters["user_id"] = user_id if user_id is not None else SHARED_OWNER
                where_clause += " AND user_id = {user_id:String}"

            self.client.command(
                f"DELETE FROM {{database_name:Identifier}}.{{table_name:Identifier}} {where_clause}",
                parameters=parameters,
            )
            return True
        except Exception:
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
            parameters = self._get_base_parameters()
            parameters["content_id"] = content_id

            # First, get existing documents with their current metadata and filters
            result = self.client.query(
                "SELECT id, meta_data, filters FROM {database_name:Identifier}.{table_name:Identifier} WHERE content_id = {content_id:String}",
                parameters=parameters,
            )

            if not result.result_rows:
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Update each document
            updated_count = 0
            for row in result.result_rows:
                doc_id, current_meta_json, current_filters_json = row

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
                update_params["doc_id"] = doc_id
                update_params["metadata_json"] = json.dumps(updated_metadata)
                update_params["filters_json"] = json.dumps(updated_filters)

                self.client.command(
                    "ALTER TABLE {database_name:Identifier}.{table_name:Identifier} UPDATE meta_data = {metadata_json:String}, filters = {filters_json:String} WHERE id = {doc_id:String}",
                    parameters=update_params,
                )
                updated_count += 1

            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception:
            logger.exception(f"Error updating metadata for content_id '{content_id}'")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return [SearchType.vector]
