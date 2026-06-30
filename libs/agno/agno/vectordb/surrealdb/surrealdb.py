from hashlib import md5
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

# Per-user isolation: the owner is stamped into a first-class user_id field and
# ANDed into the search WHERE clause. None is the shared bucket; scoped searches
# match own OR shared, and user_id=None applies no scope.
USER_ID_FIELD = "user_id"


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
        WHERE id = $id
        LIMIT 1
    """

    CONTENT_HASH_EXISTS_QUERY: Final[str] = """
        SELECT * FROM {collection}
        WHERE meta_data.content_hash = $content_hash
        {scope_condition}
        LIMIT 1
    """

    DELETE_BY_ID_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE id = $id
    """

    DELETE_BY_NAME_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE meta_data.name = $name
    """

    DELETE_BY_METADATA_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE {conditions}
    """

    DELETE_BY_CONTENT_ID_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE content_id = $content_id
        {scope_condition}
        RETURN BEFORE
    """

    DELETE_BY_CONTENT_HASH_QUERY: Final[str] = """
        DELETE FROM {collection}
        WHERE meta_data.content_hash = $content_hash
        {scope_condition}
    """

    UPSERT_QUERY: Final[str] = """
        UPSERT {thing}
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

    @staticmethod
    def _user_scope_condition(user_id: Optional[str]) -> str:
        """Build the per-user scope predicate for the search WHERE clause.

        user_id set -> AND (user_id = $scope_user_id OR user_id = NONE)
        (own plus shared); None -> "" (no scope). Bound as the dedicated
        $scope_user_id name so a caller's own $user_id metadata filter
        can't collide with the owner scope.
        """
        if not user_id:
            return ""
        return f"AND ({USER_ID_FIELD} = $scope_user_id OR {USER_ID_FIELD} = NONE)"

    @staticmethod
    def _record_id(base_id: str, content_hash: str, user_id: Optional[str]) -> str:
        """Derive the deterministic record id for a chunk.

        The owner is folded in so the same content maps to different ids for
        different users (UPSERT writes by id). The shared bucket
        (user_id=None) keeps the legacy two-part id.
        """
        if user_id:
            return md5(f"{base_id}_{content_hash}_{user_id}".encode()).hexdigest()
        return md5(f"{base_id}_{content_hash}".encode()).hexdigest()

    def _thing(self, document: Document, content_hash: str, user_id: Optional[str]) -> str:
        """Build the fully-qualified, owner-scoped record thing for an UPSERT.

        The hex id is backtick-quoted so SurrealDB treats it as a literal record
        key rather than parsing it as a number/identifier.
        """
        base_id = document.id or md5(document.content.encode()).hexdigest()
        record_id = self._record_id(base_id, content_hash, user_id)
        return f"{self.collection}:`{record_id}`"

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
        result = self.client.query(self.ID_EXISTS_QUERY.format(collection=self.collection), {"id": id})
        return bool(self._extract_result(result))

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by its content hash.

        Args:
            content_hash: The content hash of the document to check.
            user_id: When set, restrict the check to the owner's own chunks
                (exact match, shared bucket not consulted).

        Returns:
            True if the document exists, False otherwise.

        """
        log_debug(f"Checking if document exists by content hash: {content_hash}")
        params: Dict[str, Any] = {"content_hash": content_hash}
        if user_id:
            params["user_id"] = user_id
        result = self.client.query(
            self.CONTENT_HASH_EXISTS_QUERY.format(
                collection=self.collection, scope_condition=self._owner_exact_condition(user_id)
            ),
            params,
        )
        return bool(self._extract_result(result))

    @staticmethod
    def _owner_exact_condition(user_id: Optional[str]) -> str:
        """Build an exact-owner predicate for dedupe/delete on the upsert path.

        Unlike the search scope (own OR shared), this matches the caller's
        chunks only and never the shared bucket. user_id None -> no predicate.
        """
        if not user_id:
            return ""
        return f"AND {USER_ID_FIELD} = $user_id"

    @staticmethod
    def _dedupe_owner_condition(user_id: Optional[str]) -> str:
        """Owner predicate for the upsert dedupe-delete. Like the exact-owner
        condition, but a shared (None) upsert dedupes only the shared bucket
        (user_id = NONE) so it never wipes another owner's rows that share
        the same content_hash.
        """
        if not user_id:
            return f"AND {USER_ID_FIELD} = NONE"
        return f"AND {USER_ID_FIELD} = $user_id"

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> None:
        """Delete the caller's chunks for a content hash before a re-upsert.

        Scoped to the owner exactly so other owners and the shared bucket stay
        intact.
        """
        params: Dict[str, Any] = {"content_hash": content_hash}
        if user_id:
            params["user_id"] = user_id
        self.client.query(
            self.DELETE_BY_CONTENT_HASH_QUERY.format(
                collection=self.collection, scope_condition=self._dedupe_owner_condition(user_id)
            ),
            params,
        )

    async def _async_delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> None:
        """Async counterpart of _delete_by_content_hash."""
        params: Dict[str, Any] = {"content_hash": content_hash}
        if user_id:
            params["user_id"] = user_id
        await self.async_client.query(
            self.DELETE_BY_CONTENT_HASH_QUERY.format(
                collection=self.collection, scope_condition=self._dedupe_owner_condition(user_id)
            ),
            params,
        )

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
            user_id: Owner of these chunks for per-user isolation. None
                (default) writes to the shared bucket, visible to everyone.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            data = self._build_record(doc, content_hash, filters, user_id)
            # Write by an owner-folded id so two users sharing a content_hash
            # get distinct records.
            thing = self._thing(doc, content_hash, user_id)
            self.client.query(self.UPSERT_QUERY.format(thing=thing), data)  # type: ignore[arg-type]

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
            user_id: Owner of these chunks for per-user isolation. None
                (default) writes to the shared bucket, visible to everyone.

        """
        # Replace only the caller's own stale chunks for this content_hash;
        # other owners and the shared bucket are left intact.
        self._delete_by_content_hash(content_hash, user_id=user_id)
        for doc in documents:
            doc.embed(embedder=self.embedder)
            data = self._build_record(doc, content_hash, filters, user_id)
            thing = self._thing(doc, content_hash, user_id)
            self.client.query(self.UPSERT_QUERY.format(thing=thing), data)  # type: ignore[arg-type]

    def _build_record(
        self,
        doc: Document,
        content_hash: str,
        filters: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        """Assemble the record payload for an UPSERT.

        user_id is a first-class field, not folded into meta_data.
        """
        meta_data: Dict[str, Any] = doc.meta_data if isinstance(doc.meta_data, dict) else {}
        meta_data["content_hash"] = content_hash
        if filters:
            meta_data.update(filters)
        return {
            "content": doc.content,
            "embedding": doc.embedding,
            "meta_data": meta_data,
            "content_id": doc.content_id,
            "user_id": user_id,
        }

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
            user_id: When set, restrict results to the caller's own chunks plus
                the shared (NONE-owned) bucket. None (default) applies no scope.

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
            search_params.update(filters)
        if user_id:
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

    def delete_by_id(self, id: str) -> bool:
        """Delete a document by its ID.

        Args:
            id: The ID of the document to delete.

        Returns:
            True if the document was deleted, False otherwise.

        """
        log_debug(f"Deleting document by ID: {id}")
        result = self.client.query(self.DELETE_BY_ID_QUERY.format(collection=self.collection), {"id": id})
        return bool(result)

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by their name.

        Args:
            name: The name of the documents to delete.

        Returns:
            True if documents were deleted, False otherwise.

        """
        log_debug(f"Deleting documents by name: {name}")
        result = self.client.query(self.DELETE_BY_NAME_QUERY.format(collection=self.collection), {"name": name})
        return bool(result)

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by their metadata.

        Args:
            metadata: The metadata to match for deletion.

        Returns:
            True if documents were deleted, False otherwise.

        """
        log_debug(f"Deleting documents by metadata: {metadata}")
        conditions = [f"meta_data.{key} = ${key}" for key in metadata.keys()]
        conditions_str = " AND ".join(conditions)
        query = self.DELETE_BY_METADATA_QUERY.format(collection=self.collection, conditions=conditions_str)
        result = self.client.query(query, metadata)
        return bool(result)

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by their content ID.

        Args:
            content_id: The content ID of the documents to delete.
            user_id: When set, delete only the caller's own chunks (exact owner
                match, shared bucket and other owners untouched). None
                deletes across all owners.

        Returns:
            True if documents were deleted, False otherwise.

        """
        log_debug(f"Deleting documents by content ID: {content_id}")
        params: Dict[str, Any] = {"content_id": content_id}
        if user_id:
            params["user_id"] = user_id
        result = self.client.query(
            self.DELETE_BY_CONTENT_ID_QUERY.format(
                collection=self.collection, scope_condition=self._owner_exact_condition(user_id)
            ),
            params,
        )
        # RETURN BEFORE yields the deleted rows, so the list is truthy only
        # when something was removed.
        return bool(result)

    @staticmethod
    def _extract_result(query_result: Any) -> Union[List[Any], Dict[str, Any]]:
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

    @staticmethod
    def _extract_rows(query_result: Any) -> List[Dict[str, Any]]:
        """Return the row list from a SELECT regardless of client envelope.

        Newer surrealdb clients return the rows directly as a flat list, while
        older ones wrap them as [{"result": [...]}]. Normalise both so the
        caller always sees a plain list of row dicts.
        """
        if not isinstance(query_result, list) or not query_result:
            return []
        first = query_result[0]
        if isinstance(first, dict) and "result" in first and isinstance(first["result"], list):
            return first["result"]
        return [row for row in query_result if isinstance(row, dict)]

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

    async def async_content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by its content hash asynchronously.

        Args:
            content_hash: The content hash of the document to check.
            user_id: When set, restrict the check to the owner's own chunks.

        Returns:
            True if the document exists, False otherwise.

        """
        params: Dict[str, Any] = {"content_hash": content_hash}
        if user_id:
            params["user_id"] = user_id
        response = await self.async_client.query(
            self.CONTENT_HASH_EXISTS_QUERY.format(
                collection=self.collection, scope_condition=self._owner_exact_condition(user_id)
            ),
            params,
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
            user_id: Owner of these chunks for per-user isolation. None
                (default) writes to the shared bucket, visible to everyone.

        """
        for doc in documents:
            doc.embed(embedder=self.embedder)
            data = self._build_record(doc, content_hash, filters, user_id)
            log_debug(f"Inserting document asynchronously: {doc.name} ({doc.meta_data})")
            thing = self._thing(doc, content_hash, user_id)
            await self.async_client.query(self.UPSERT_QUERY.format(thing=thing), data)  # type: ignore[arg-type]

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
            user_id: Owner of these chunks for per-user isolation. None
                (default) writes to the shared bucket, visible to everyone.

        """
        # Replace only the caller's own stale chunks (see sync upsert).
        await self._async_delete_by_content_hash(content_hash, user_id=user_id)
        for doc in documents:
            doc.embed(embedder=self.embedder)
            data = self._build_record(doc, content_hash, filters, user_id)
            log_debug(f"Upserting document asynchronously: {doc.name} ({doc.meta_data})")
            thing = self._thing(doc, content_hash, user_id)
            await self.async_client.query(self.UPSERT_QUERY.format(thing=thing), data)  # type: ignore[arg-type]

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
            user_id: When set, restrict results to the caller's own chunks plus
                the shared (NONE-owned) bucket. None (default) applies no scope.

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
            search_params.update(filters)
        if user_id:
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
        # Never let caller metadata reassign the owner.
        metadata = {k: v for k, v in metadata.items() if k != USER_ID_FIELD}
        try:
            # Query for documents with the given content_id
            query = f"SELECT * FROM {self.collection} WHERE content_id = $content_id"
            result: Any = self.client.query(query, {"content_id": content_id})

            documents = self._extract_rows(result)
            if not documents:
                log_debug(f"No documents found with content_id: {content_id}")
                return

            updated_count = 0

            # Update each matching document
            for doc in documents:
                doc_id = doc["id"]
                current_metadata = doc.get("meta_data", {})

                # Merge existing metadata with new metadata
                if isinstance(current_metadata, dict):
                    updated_metadata = current_metadata.copy()
                    updated_metadata.update(metadata)
                else:
                    updated_metadata = metadata

                # Update only meta_data; the owner field stays put.
                update_query = f"UPDATE {doc_id} SET meta_data = $metadata"
                self.client.query(update_query, {"metadata": updated_metadata})
                updated_count += 1

            log_debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # SurrealDb doesn't use SearchType enum
