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

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class SurrealDb(VectorDb):
    """SurrealDB Vector Database implementation supporting both sync and async operations."""

    # SQL Query Constants
    CREATE_TABLE_QUERY: Final[str] = """
        DEFINE TABLE IF NOT EXISTS {collection} SCHEMAFUL;
        DEFINE FIELD IF NOT EXISTS content ON {collection} TYPE string;
        DEFINE FIELD IF NOT EXISTS embedding ON {collection} TYPE array<float>;
        DEFINE FIELD IF NOT EXISTS meta_data ON {collection} TYPE object FLEXIBLE;
        DEFINE FIELD IF NOT EXISTS content_id ON {collection} TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS user_id ON {collection} TYPE option<string>;
        DEFINE INDEX IF NOT EXISTS vector_idx ON {collection} FIELDS embedding HNSW DIMENSION {dimensions} DIST {distance};
    """

    NAME_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE meta_data.name = $name
        LIMIT 1
    """

    ID_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE id = type::record($table, $record_id)
        LIMIT 1
    """

    CONTENT_HASH_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE meta_data.content_hash = $content_hash
        AND user_id = $user_id
        LIMIT 1
    """

    DELETE_BY_ID_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE id = type::record($table, $record_id)
        OR string::starts_with(record::id(id), $owned_prefix)
        RETURN VALUE id
    """

    DELETE_BY_NAME_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE meta_data.name = $name
        RETURN VALUE id
    """

    DELETE_BY_METADATA_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE {conditions}
        RETURN VALUE id
    """

    DELETE_BY_CONTENT_ID_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE content_id = $content_id
        {scope_condition}
        RETURN VALUE id
    """

    DELETE_BY_CONTENT_HASH_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE meta_data.content_hash = $content_hash
        AND user_id = $user_id
        RETURN VALUE id
    """

    UPSERT_QUERY: Final[str] = """
        UPSERT type::record($table, $record_id)
        SET content = $content,
            embedding = $embedding,
            meta_data = $meta_data,
            content_id = $content_id,
            user_id = $user_id
    """

    SEARCH_QUERY: Final[str] = """
        SELECT
            content,
            meta_data,
            vector::distance::knn() as distance
        FROM {collection}
        WHERE embedding <|{limit}, {search_ef}|> $query_embedding
        {scope_condition}
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
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """Initialize SurrealDB connection.

        Args:
            client: A blocking connection, either HTTP or WS
            async_client: An async connection, either HTTP or WS (default: None)
            collection: Collection name to store documents (default: documents)
            distance: Distance metric to use (default: cosine)
            efc: HNSW construction time/accuracy trade-off (default: 150)
            m: HNSW max number of connections per element (default: 12)
            search_ef: HNSW search time/accuracy trade-off (default: 40)
            embedder: Embedder instance for creating embeddings (default: OpenAIEmbedder)

        """
        # Dynamic ID generation based on unique identifiers
        if id is None:
            from agno.utils.string import generate_id

            client_info = str(client) if client else str(async_client) if async_client else "default"
            seed = f"{client_info}#{collection}"
            id = generate_id(seed)

        # Initialize base class with name, description, and generated ID
        super().__init__(id=id, name=name, description=description)

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
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

        # Whether the DEFINE statements have run for this instance
        self._schema_ensured: bool = False

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
        # Bind the key as well as the value: an interpolated key is caller data in the WHERE clause
        conditions = [f"meta_data[$filter_key_{i}] = $filter_value_{i}" for i, _ in enumerate(filters.items())]
        return "AND " + " AND ".join(conditions)

    @staticmethod
    def _build_filter_params(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build the bound parameters for the placeholders ``_build_filter_condition`` emits.

        Args:
            filters: A dictionary of filters to apply to the query.

        Returns:
            The $filter_key_i / $filter_value_i bindings.

        """
        if not filters:
            return {}
        params: Dict[str, Any] = {}
        for i, (key, value) in enumerate(filters.items()):
            params[f"filter_key_{i}"] = key
            params[f"filter_value_{i}"] = value
        return params

    @staticmethod
    def _user_scope_condition(user_id: Optional[str]) -> str:
        """Build the per-user scope predicate for the search WHERE clause.

        An owner matches its own rows plus the shared (NONE) rows; None applies no scope.

        """
        if user_id is None:
            return ""
        return "AND (user_id = $scope_user_id OR user_id = NONE)"

    @staticmethod
    def _owner_scope_condition(user_id: Optional[str]) -> str:
        """Build the owner-only scope predicate for a delete WHERE clause.

        Unlike the search scope this never merges the shared rows in; None applies no scope.

        """
        if user_id is None:
            return ""
        return "AND user_id = $scope_user_id"

    @staticmethod
    def _escape_record_id_part(value: str) -> str:
        """Percent-escape one half of a folded record id.

        ':' is the fold delimiter and '%' the escape character, so both are encoded.

        """
        return value.replace("%", "%25").replace(":", "%3A")

    @classmethod
    def _fold_record_id(cls, doc_id: str, user_id: Optional[str]) -> str:
        """Fold the owner into the record id so two owners' identical content don't collide.

        Both halves are escaped first — ("a:x", "y") and ("a", "x:y") would otherwise fold to the same
        record, and so would an unfolded id that carries a ':' of its own.

        """
        if user_id is None:
            return cls._escape_record_id_part(doc_id)
        return f"{cls._escape_record_id_part(doc_id)}:{cls._escape_record_id_part(user_id)}"

    # Synchronous methods
    def _ensure_schema(self) -> None:
        """Run the DEFINE statements once for this instance.

        Idempotent, and it must run on collections created before v3 too: the table is
        SCHEMAFUL, so writes silently lose ``user_id``/``content_id`` until they are defined.

        """
        if self._schema_ensured:
            return
        log_debug(f"Ensuring schema for collection: {self.collection}")
        self.client.query(
            self.CREATE_TABLE_QUERY.format(
                collection=self.collection,
                distance=self.distance,
                dimensions=self.dimensions,
                efc=self.efc,
                m=self.m,
            )
        )
        self._schema_ensured = True

    async def _async_ensure_schema(self) -> None:
        """Async twin of ``_ensure_schema``."""
        if self._schema_ensured:
            return
        log_debug(f"Ensuring schema for collection: {self.collection}")
        await self.async_client.query(
            self.CREATE_TABLE_QUERY.format(
                collection=self.collection,
                distance=self.distance,
                dimensions=self.dimensions,
                efc=self.efc,
                m=self.m,
            )
        )
        self._schema_ensured = True

    def create(self) -> None:
        """Create the vector collection and index."""
        self._ensure_schema()

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

    def id_exists(self, id: str) -> bool:
        """Check if a document exists by its ID.

        Args:
            id: The ID of the document to check.

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists by ID: {id}")
        # Bind via type::record, the way the upsert writes it: a string never equals a record link
        result = self.client.query(
            self.ID_EXISTS_QUERY.format(collection=self.collection),
            {"table": self.collection, "record_id": id},
        )
        return bool(self._extract_result(result))

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by its content hash.

        Args:
            content_hash: The content hash of the document to check.
            user_id: The owner to check, so another owner's identical upload is not judged a
                duplicate. None (default) checks the shared (NONE-owned) rows alone.

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists by content hash: {content_hash}")
        params: Dict[str, Any] = {"content_hash": content_hash, "user_id": user_id}
        result = self.client.query(
            self.CONTENT_HASH_EXISTS_QUERY.format(collection=self.collection),
            params,
        )
        return bool(self._extract_result(result))

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents into the vector store.

        Args:
            content_hash: The content hash for the documents.
            documents: A list of documents to insert.
            filters: A dictionary of filters to apply to the query.
            user_id: Owner of these chunks. None (default) writes shared chunks, visible to everyone.

        """
        # Writes ensure the schema too: ``create()`` only runs for collections that don't exist yet
        self._ensure_schema()
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            meta_data["content_hash"] = content_hash
            if doc.name is not None:
                # name_exists and delete_by_name match meta_data.name, so the write has to put it there
                meta_data.setdefault("name", doc.name)
            data: Dict[str, Any] = {
                "content": doc.content,
                "embedding": doc.embedding,
                "meta_data": meta_data,
                "content_id": doc.content_id,
                "user_id": user_id,
            }
            if filters:
                data["meta_data"].update(filters)
            self.client.create(self.collection, data)

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the vector store.

        Args:
            content_hash: The content hash for the documents.
            documents: A list of documents to upsert.
            filters: A dictionary of filters to apply to the query.
            user_id: Owner of these chunks. None (default) writes shared chunks, visible to everyone.

        """
        # See ``insert``
        self._ensure_schema()
        # UPSERT replaces by record id, so clear this owner's chunks first or a shrunken document
        # leaves its dropped chunks behind
        if self.content_hash_exists(content_hash, user_id=user_id):
            self._delete_by_content_hash(content_hash, user_id=user_id)

        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            meta_data["content_hash"] = content_hash
            if doc.name is not None:
                # name_exists and delete_by_name match meta_data.name, so the write has to put it there
                meta_data.setdefault("name", doc.name)
            data: Dict[str, Any] = {
                "content": doc.content,
                "embedding": doc.embedding,
                "meta_data": meta_data,
                "content_id": doc.content_id,
                "user_id": user_id,
            }
            if filters:
                data["meta_data"].update(filters)
            if doc.id:
                # ``type::record`` accepts a reader-assigned UUID; the fold keeps two owners' ids apart
                data["table"] = self.collection
                data["record_id"] = self._fold_record_id(doc.id, user_id)
                self.client.query(self.UPSERT_QUERY, data)  # type: ignore[arg-type]
            else:
                self.client.create(self.collection, data)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search for similar documents.

        Args:
            query: The query to search for.
            limit: The maximum number of documents to return.
            filters: A dictionary of filters to apply to the query.
            user_id: Restrict results to this user's chunks plus the shared (NONE-owned) chunks.
                None (default) applies no scope.

        Returns:
            A list of documents that are similar to the query.

        """
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in SurrealDB. No filters will be applied.")
            filters = None
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
            scope_condition=self._user_scope_condition(user_id),
            filter_condition=filter_condition,
            distance=self.distance,
        )
        log_debug(f"Search query: {search_query}")
        search_params: Dict[str, Any] = {"query_embedding": query_embedding}
        if filters:
            search_params.update(self._build_filter_params(filters))
        if user_id is not None:
            search_params["scope_user_id"] = user_id
        response: Any = self.client.query(search_query, search_params)
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
        # The table is gone, so the next create()/write must re-run the DEFINEs
        self._schema_ensured = False

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
            True if the delete completed, False if it errored.

        """
        try:
            self.client.query(self.DELETE_ALL_QUERY.format(collection=self.collection))
            return True
        except Exception as e:
            log_error(f"Error deleting all documents: {str(e)}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete a document by its ID.

        Args:
            id: The ID of the document to delete.

        Returns:
            True if rows were deleted, False if none matched or the query errored. A bare DELETE
            answers with an empty list either way, so the query asks for ``RETURN VALUE id``.

        """
        log_debug(f"Deleting document by ID: {id}")
        try:
            # The write folds the owner into the id, so match the shared record plus every owned
            # fold of it: this method takes no user_id and clears the document for all owners
            escaped = self._escape_record_id_part(id)
            result = self.client.query(
                self.DELETE_BY_ID_QUERY.format(collection=self.collection),
                {"table": self.collection, "record_id": escaped, "owned_prefix": f"{escaped}:"},
            )
            return bool(self._extract_result(result))
        except Exception as e:
            log_error(f"Error deleting document by ID '{id}': {str(e)}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by their name.

        Args:
            name: The name of the documents to delete.

        Returns:
            True if rows were deleted, False if none matched or the query errored.

        """
        log_debug(f"Deleting documents by name: {name}")
        try:
            result = self.client.query(self.DELETE_BY_NAME_QUERY.format(collection=self.collection), {"name": name})
            return bool(self._extract_result(result))
        except Exception as e:
            log_error(f"Error deleting documents by name '{name}': {str(e)}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by their metadata.

        Args:
            metadata: The metadata to match for deletion.

        Returns:
            True if rows were deleted, False if none matched or the query errored.

        """
        log_debug(f"Deleting documents by metadata: {metadata}")
        if not metadata:
            log_warning("No metadata provided for deletion; refusing to match every row.")
            return False
        try:
            # Bind both halves: an interpolated key carrying a '.' becomes NONE = NONE, which
            # matches every row
            conditions = [f"meta_data[$key_{i}] = $value_{i}" for i, _ in enumerate(metadata.items())]
            params: Dict[str, Any] = {}
            for i, (key, value) in enumerate(metadata.items()):
                params[f"key_{i}"] = key
                params[f"value_{i}"] = value
            query = self.DELETE_BY_METADATA_QUERY.format(
                collection=self.collection, conditions=" AND ".join(conditions)
            )
            result = self.client.query(query, params)
            return bool(self._extract_result(result))
        except Exception as e:
            log_error(f"Error deleting documents by metadata {metadata}: {str(e)}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by their content ID.

        Args:
            content_id: The content ID of the documents to delete.
            user_id: Delete only this owner's chunks. None (default) deletes across all owners.

        Returns:
            True if rows were deleted, False if none matched or the query errored.

        """
        log_debug(f"Deleting documents by content ID: {content_id}")
        try:
            scope_condition = self._owner_scope_condition(user_id)
            params: Dict[str, Any] = {"content_id": content_id}
            if user_id is not None:
                params["scope_user_id"] = user_id
            result = self.client.query(
                self.DELETE_BY_CONTENT_ID_QUERY.format(collection=self.collection, scope_condition=scope_condition),
                params,
            )
            return bool(self._extract_result(result))
        except Exception as e:
            log_error(f"Error deleting documents by content ID '{content_id}': {str(e)}")
            return False

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by their content hash, scoped to one owner.

        Args:
            content_hash: The content hash of the documents to delete.
            user_id: The owner whose chunks to clear. None (default) clears the shared (NONE-owned)
                chunks alone, so a shared re-upsert never wipes an owner's identical content.

        Returns:
            True if rows were deleted, False if none matched. Errors propagate instead of being
            swallowed, so ``upsert`` never writes over chunks that were not cleared.

        """
        log_debug(f"Deleting documents by content hash: {content_hash}")
        params: Dict[str, Any] = {"content_hash": content_hash, "user_id": user_id}
        result = self.client.query(
            self.DELETE_BY_CONTENT_HASH_QUERY.format(collection=self.collection),
            params,
        )
        return bool(self._extract_result(result))

    @staticmethod
    def _extract_result(query_result: Any) -> Union[List[Any], Dict[str, Any]]:
        """Extract the actual result from SurrealDB query response.

        surrealdb >= 1.0 hands back the rows themselves: a list for a SELECT, a dict for INFO FOR DB.

        Args:
            query_result: The query result from SurrealDB.

        Returns:
            The actual result from SurrealDB query response.

        """
        log_debug(f"Query result: {query_result}")
        if isinstance(query_result, (dict, list)):
            return query_result
        return []

    async def async_create(self) -> None:
        """Create the vector collection and index asynchronously."""
        await self._async_ensure_schema()

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

    async def async_content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by its content hash asynchronously.

        Args:
            content_hash: The content hash of the document to check.
            user_id: The owner to check, so another owner's identical upload is not judged a
                duplicate. None (default) checks the shared (NONE-owned) rows alone.

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists by content hash: {content_hash}")
        params: Dict[str, Any] = {"content_hash": content_hash, "user_id": user_id}
        response = await self.async_client.query(
            self.CONTENT_HASH_EXISTS_QUERY.format(collection=self.collection),
            params,
        )
        return bool(self._extract_result(response))

    async def _async_delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by their content hash asynchronously, scoped to one owner.

        Args:
            content_hash: The content hash of the documents to delete.
            user_id: The owner whose chunks to clear. None (default) clears the shared (NONE-owned)
                chunks alone, so a shared re-upsert never wipes an owner's identical content.

        Returns:
            True if rows were deleted, False if none matched. See ``_delete_by_content_hash``
            for why errors propagate here.

        """
        log_debug(f"Deleting documents by content hash: {content_hash}")
        params: Dict[str, Any] = {"content_hash": content_hash, "user_id": user_id}
        result = await self.async_client.query(
            self.DELETE_BY_CONTENT_HASH_QUERY.format(collection=self.collection),
            params,
        )
        return bool(self._extract_result(result))

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents into the vector store asynchronously.

        Args:
            content_hash: The content hash for the documents.
            documents: A list of documents to insert.
            filters: A dictionary of filters to apply to the query.
            user_id: Owner of these chunks. None (default) writes shared chunks, visible to everyone.

        """
        # See ``insert``
        await self._async_ensure_schema()
        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            meta_data["content_hash"] = content_hash
            if doc.name is not None:
                # name_exists and delete_by_name match meta_data.name, so the write has to put it there
                meta_data.setdefault("name", doc.name)
            data: Dict[str, Any] = {
                "content": doc.content,
                "embedding": doc.embedding,
                "meta_data": meta_data,
                "content_id": doc.content_id,
                "user_id": user_id,
            }
            if filters:
                data["meta_data"].update(filters)
            log_debug(f"Inserting document asynchronously: {doc.name} ({doc.meta_data})")
            await self.async_client.create(self.collection, data)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the vector store asynchronously.

        Args:
            content_hash: The content hash for the documents.
            documents: A list of documents to upsert.
            filters: A dictionary of filters to apply to the query.
            user_id: Owner of these chunks. None (default) writes shared chunks, visible to everyone.

        """
        # See ``insert``
        await self._async_ensure_schema()
        # See ``upsert``; the guard and its delete run on the async client
        if await self.async_content_hash_exists(content_hash, user_id=user_id):
            await self._async_delete_by_content_hash(content_hash, user_id=user_id)

        for doc in documents:
            doc.embed(embedder=self.embedder)
            meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
            meta_data["content_hash"] = content_hash
            if doc.name is not None:
                # name_exists and delete_by_name match meta_data.name, so the write has to put it there
                meta_data.setdefault("name", doc.name)
            data: Dict[str, Any] = {
                "content": doc.content,
                "embedding": doc.embedding,
                "meta_data": meta_data,
                "content_id": doc.content_id,
                "user_id": user_id,
            }
            if filters:
                data["meta_data"].update(filters)
            log_debug(f"Upserting document asynchronously: {doc.name} ({doc.meta_data})")
            if doc.id:
                # ``type::record`` accepts a reader-assigned UUID; the fold keeps two owners' ids apart
                data["table"] = self.collection
                data["record_id"] = self._fold_record_id(doc.id, user_id)
                await self.async_client.query(self.UPSERT_QUERY, data)  # type: ignore[arg-type]
            else:
                await self.async_client.create(self.collection, data)

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search for similar documents asynchronously.

        Args:
            query: The query to search for.
            limit: The maximum number of documents to return.
            filters: A dictionary of filters to apply to the query.
            user_id: Restrict results to this user's chunks plus the shared (NONE-owned) chunks.
                None (default) applies no scope.

        Returns:
            A list of documents that are similar to the query.

        """
        if isinstance(filters, List):
            log_warning("Filters Expressions are not supported in SurrealDB. No filters will be applied.")
            filters = None

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        filter_condition = self._build_filter_condition(filters)
        search_query = self.SEARCH_QUERY.format(
            collection=self.collection,
            limit=limit,
            search_ef=self.search_ef,
            scope_condition=self._user_scope_condition(user_id),
            filter_condition=filter_condition,
            distance=self.distance,
        )
        search_params: Dict[str, Any] = {"query_embedding": query_embedding}
        if filters:
            search_params.update(self._build_filter_params(filters))
        if user_id is not None:
            search_params["scope_user_id"] = user_id
        response: Any = await self.async_client.query(search_query, search_params)
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
        # See ``drop``
        self._schema_ensured = False

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

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            # Query for documents with the given content_id
            query = f"SELECT * FROM {self.collection} WHERE content_id = $content_id"
            result: Any = self.client.query(query, {"content_id": content_id})

            if not result or not result[0].get("result"):
                log_debug(f"No documents found with content_id: {content_id}")
                return

            documents = result[0]["result"]
            updated_count = 0

            # Update each matching document
            for doc in documents:
                doc_id = doc["id"]
                current_metadata = doc.get("meta_data", {})
                current_filters = doc.get("filters", {})

                # Merge existing metadata with new metadata
                if isinstance(current_metadata, dict):
                    updated_metadata = current_metadata.copy()
                    updated_metadata.update(metadata)
                else:
                    updated_metadata = metadata

                # Merge existing filters with new metadata
                if isinstance(current_filters, dict):
                    updated_filters = current_filters.copy()
                    updated_filters.update(metadata)
                else:
                    updated_filters = metadata

                # Update the document
                update_query = f"UPDATE {doc_id} SET meta_data = $metadata, filters = $filters"
                self.client.query(update_query, {"metadata": updated_metadata, "filters": updated_filters})
                updated_count += 1

            log_debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # SurrealDb doesn't use SearchType enum
