import asyncio
import struct
from typing import Any, Dict, List, Mapping, Optional, Union, cast

try:
    from glide_sync import (
        DataType,
        DistanceMetricType,
        FtCreateOptions,
        FtSearchLimit,
        FtSearchOptions,
        GlideClient,
        GlideClientConfiguration,
        NodeAddress,
        ReturnField,
        ServerCredentials,
        TagField,
        TextField,
        VectorAlgorithm,
        VectorField,
        VectorFieldAttributesFlat,
        VectorFieldAttributesHnsw,
        VectorType,
    )
    from glide_sync import (
        ft as glide_ft,
    )
except ImportError:
    raise ImportError("`valkey-glide-sync` not installed. Please install it using `pip install valkey-glide-sync`")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import hash_string_sha256
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType


def _float_list_to_bytes(floats: List[float]) -> bytes:
    """Convert a list of floats to a binary buffer (little-endian float32)."""
    return struct.pack(f"<{len(floats)}f", *floats)


def _decode_value(val: Any) -> str:
    """Decode a bytes value to string if needed."""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


class ValkeyDB(VectorDb):
    """
    Valkey class for managing vector operations with Valkey and valkey-search.

    This class provides methods for creating, inserting, searching, and managing
    vector data in a Valkey database using the valkey-glide-sync client and the
    valkey-search module (FT.* commands).
    """

    def __init__(
        self,
        index_name: str,
        host: str = "localhost",
        port: int = 6379,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = False,
        database_id: Optional[int] = None,
        glide_client: Optional[GlideClient] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        vector_algorithm: str = "HNSW",
        reranker: Optional[Reranker] = None,
    ):
        """
        Initialize the ValkeyDB instance.

        Args:
            index_name (str): Name of the Valkey index to store vector data.
            host (str): Valkey server host. Defaults to "localhost".
            port (int): Valkey server port. Defaults to 6379.
            username (Optional[str]): Username for Valkey server authentication.
            password (Optional[str]): Password for Valkey server authentication.
                If not supplied, "default" will be used by the server.
            use_tls (bool): Whether to use TLS for the connection. Defaults to False.
            database_id (Optional[int]): Index of the logical database to connect to (e.g. 0-15).
                If not set, the server default (database 0) is used.
            glide_client (Optional[GlideClient]): Pre-configured GlideClient instance.
                If not provided, one will be created from host/port and optional auth/TLS settings.
            embedder (Optional[Embedder]): Embedder instance for creating embeddings.
            search_type (SearchType): Type of search to perform.
            distance (Distance): Distance metric for vector comparisons.
            vector_algorithm (str): Vector indexing algorithm ("HNSW" or "FLAT").
            reranker (Optional[Reranker]): Reranker instance.
        """
        if not index_name:
            raise ValueError("Index name must be provided.")

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.database_id = database_id
        self.index_name: str = index_name
        self.prefix: str = f"{index_name}:"

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        # Search type and distance metric
        self.search_type: SearchType = search_type
        self.distance: Distance = distance
        self.vector_algorithm: str = vector_algorithm.upper()

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Client management
        self._glide_client: Optional[GlideClient] = glide_client
        self._client_initialized: bool = glide_client is not None

        log_debug(f"Initialized ValkeyDB with index '{self.index_name}'")

    def _get_client(self) -> GlideClient:
        """Get or create the GlideClient."""
        if self._glide_client is None or not self._client_initialized:
            credentials = ServerCredentials(username=self.username, password=self.password) if self.password else None
            config = GlideClientConfiguration(
                addresses=[NodeAddress(host=self.host, port=self.port)],
                database_id=self.database_id,
                credentials=credentials,
                use_tls=self.use_tls,
            )
            self._glide_client = GlideClient.create(config)
            self._client_initialized = True
        return self._glide_client

    def _get_distance_metric(self) -> DistanceMetricType:
        """Map agno Distance to valkey-glide DistanceMetricType."""
        mapping = {
            Distance.cosine: DistanceMetricType.COSINE,
            Distance.l2: DistanceMetricType.L2,
            Distance.max_inner_product: DistanceMetricType.IP,
        }
        return mapping[self.distance]

    def _build_schema(self) -> list:
        """Build the FT.CREATE schema field list."""
        fields = [
            TagField("id"),
            TagField("name"),
            TextField("content"),
            TagField("content_hash"),
            TagField("content_id"),
            TagField("status"),
            TagField("category"),
            TagField("tag"),
            TagField("source"),
            TagField("mode"),
        ]

        distance_metric = self._get_distance_metric()

        if self.vector_algorithm == "HNSW":
            vector_attrs = VectorFieldAttributesHnsw(
                dimensions=self.dimensions,  # type: ignore
                distance_metric=distance_metric,
                type=VectorType.FLOAT32,
            )
            fields.append(VectorField("embedding", VectorAlgorithm.HNSW, vector_attrs))
        else:
            vector_attrs_flat = VectorFieldAttributesFlat(
                dimensions=self.dimensions,  # type: ignore
                distance_metric=distance_metric,
                type=VectorType.FLOAT32,
            )
            fields.append(VectorField("embedding", VectorAlgorithm.FLAT, vector_attrs_flat))

        return fields

    def _parse_hash(self, doc: Document) -> Dict[str, Any]:
        """Create a dict serializable into a Valkey HASH structure.

        Valkey HASH fields only accept string or bytes values, so all
        non-bytes values are coerced to strings before returning.
        """
        doc_dict = doc.to_dict()
        doc_id = doc.id or hash_string_sha256(doc.content)
        doc_dict["id"] = doc_id

        if not doc.embedding:
            doc.embed(self.embedder)

        if doc.embedding is None:
            raise ValueError(f"Document embedding is None after embed() call for doc id={doc.id}")
        doc_dict["embedding"] = _float_list_to_bytes(doc.embedding)

        if hasattr(doc, "content_id") and doc.content_id:
            doc_dict["content_id"] = doc.content_id

        if "meta_data" in doc_dict:
            meta_data = doc_dict.pop("meta_data", {})
            doc_dict.update(meta_data)

        # Valkey HASH values must be str or bytes — coerce everything else
        sanitized: Dict[str, Any] = {}
        for k, v in doc_dict.items():
            if v is None:
                continue
            if isinstance(v, bytes):
                sanitized[k] = v
            else:
                sanitized[k] = str(v)
        return sanitized

    def _parse_search_results(self, results: Any) -> List[Dict[str, Any]]:
        """Parse FT.SEARCH response into a list of dicts.

        FT.SEARCH returns: [count, {key: {field: value, ...}, ...}]
        """
        if not results or len(results) < 2:
            return []

        docs = []
        result_map = results[1] if len(results) > 1 else {}
        if isinstance(result_map, dict):
            for key, fields in result_map.items():
                doc_data = {}
                if isinstance(fields, dict):
                    for field_name, field_value in fields.items():
                        fname = _decode_value(field_name)
                        # Skip binary embedding field
                        if fname == "embedding":
                            continue
                        doc_data[fname] = _decode_value(field_value)
                docs.append(doc_data)

        return docs

    # -- VectorDb interface --

    def create(self) -> None:
        """Create the Valkey index if it does not exist."""
        try:
            if not self.exists():
                client = self._get_client()
                schema = self._build_schema()
                options = FtCreateOptions(
                    data_type=DataType.HASH,
                    prefixes=[self.prefix],
                )
                glide_ft.create(client, self.index_name, schema, options)
                log_debug(f"Created Valkey index: {self.index_name}")
            else:
                log_debug(f"Valkey index already exists: {self.index_name}")
        except Exception as e:
            log_error(f"Error creating Valkey index: {str(e)}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        await asyncio.to_thread(self.create)

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        try:
            client = self._get_client()
            query = f"@name:{{{name}}}"
            options = FtSearchOptions(
                limit=FtSearchLimit(0, 0),
            )
            results = glide_ft.search(client, self.index_name, query, options)
            count = results[0] if results else 0
            return int(_decode_value(count)) > 0
        except Exception as e:
            log_error(f"Error checking if name exists: {str(e)}")
            return False

    async def async_name_exists(self, name: str) -> bool:  # type: ignore[override]
        """Async version of name_exists method."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        try:
            client = self._get_client()
            query = f"@id:{{{id}}}"
            options = FtSearchOptions(
                limit=FtSearchLimit(0, 0),
            )
            results = glide_ft.search(client, self.index_name, query, options)
            count = results[0] if results else 0
            return int(_decode_value(count)) > 0
        except Exception as e:
            log_error(f"Error checking if ID exists: {str(e)}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document with the given content hash exists."""
        try:
            client = self._get_client()
            query = f"@content_hash:{{{content_hash}}}"
            options = FtSearchOptions(
                limit=FtSearchLimit(0, 0),
            )
            results = glide_ft.search(client, self.index_name, query, options)
            count = results[0] if results else 0
            return int(_decode_value(count)) > 0
        except Exception as e:
            log_error(f"Error checking if content hash exists: {str(e)}")
            return False

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert documents into the Valkey index."""
        try:
            client = self._get_client()
            for doc in documents:
                parsed_doc = self._parse_hash(doc)
                parsed_doc["content_hash"] = content_hash
                doc_id = parsed_doc.pop("id")
                key = f"{self.prefix}{doc_id}"
                client.hset(key, cast(Mapping[str, str | bytes], parsed_doc))  # type: ignore[arg-type]
            log_debug(f"Inserted {len(documents)} documents with content_hash: {content_hash}")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async version of insert method."""
        await asyncio.to_thread(self.insert, content_hash, documents, filters)

    def upsert_available(self) -> bool:
        """Check if upsert is available (always True for Valkey)."""
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upsert documents into the Valkey index.
        Strategy: delete existing docs with the same content_hash, then insert new docs.
        """
        try:
            # Find and delete existing docs for this content_hash
            self._delete_by_tag_filter("content_hash", content_hash)
            # Insert new docs
            self.insert(content_hash, documents, filters)
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async version of upsert method."""
        await asyncio.to_thread(self.upsert, content_hash, documents, filters)

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Search for documents using the specified search type."""
        if filters and isinstance(filters, List):
            log_warning("Filter Expressions are not supported in Valkey. No filters will be applied.")
            filters = None
        try:
            if self.search_type == SearchType.keyword:
                return self.keyword_search(query, limit)
            if self.search_type == SearchType.hybrid:
                raise ValueError("Hybrid search is currently unsupported for Valkey")
            return self.vector_search(query, limit)
        except Exception as e:
            log_error(f"Error in search: {str(e)}")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Async version of search method."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform vector similarity search using FT.SEARCH with KNN."""
        try:
            client = self._get_client()
            query_embedding = self.embedder.get_embedding(query)
            query_vector_bytes = _float_list_to_bytes(query_embedding)

            ft_query = f"*=>[KNN {limit} @embedding $query_vector]"
            options = FtSearchOptions(
                params={"query_vector": query_vector_bytes},
                return_fields=[
                    ReturnField("id"),
                    ReturnField("name"),
                    ReturnField("content"),
                ],
                limit=FtSearchLimit(0, limit),
            )

            results = glide_ft.search(client, self.index_name, ft_query, options)
            parsed = self._parse_search_results(results)
            documents = [Document.from_dict(r) for r in parsed]

            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in vector search: {str(e)}")
            return []

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform keyword search using FT.SEARCH full-text query on TEXT fields.

        Note:
            The query is passed directly to FT.SEARCH without escaping special characters
            (@, {, }, -, |, etc.). Left as-is for consistent behavior with the Redis implementation.
            Queries containing these characters may fail or produce unexpected results.
        """
        try:
            client = self._get_client()
            ft_query = f"@content:{query}"
            options = FtSearchOptions(
                return_fields=[
                    ReturnField("id"),
                    ReturnField("name"),
                    ReturnField("content"),
                ],
                limit=FtSearchLimit(0, limit),
            )

            results = glide_ft.search(client, self.index_name, ft_query, options)
            parsed = self._parse_search_results(results)
            documents = [Document.from_dict(r) for r in parsed]

            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in keyword search: {str(e)}")
            return []

    def drop(self) -> bool:  # type: ignore[override]
        """Drop the Valkey index."""
        try:
            client = self._get_client()
            glide_ft.dropindex(client, self.index_name)
            # Also delete all keys with the prefix
            self._delete_all_keys()
            log_debug(f"Deleted Valkey index: {self.index_name}")
            return True
        except Exception as e:
            if "not found" in str(e).lower():
                log_debug(f"Valkey index '{self.index_name}' does not exist, nothing to drop")
                # Still clean up any orphaned keys with the prefix
                self._delete_all_keys()
                return True
            log_error(f"Error dropping Valkey index: {str(e)}")
            return False

    async def async_drop(self) -> None:
        """Async version of drop method."""
        result = await asyncio.to_thread(self.drop)
        if not result:
            raise RuntimeError(f"Failed to drop Valkey index: {self.index_name}")

    def exists(self) -> bool:
        """Check if the Valkey index exists."""
        try:
            client = self._get_client()
            index_list = glide_ft.list(client)
            index_names = [_decode_value(n) for n in index_list]
            return self.index_name in index_names
        except Exception as e:
            log_error(f"Error checking if index exists: {str(e)}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        return await asyncio.to_thread(self.exists)

    def optimize(self) -> None:
        """Optimize the Valkey index (no-op for Valkey)."""
        log_debug("Valkey optimization not required")

    def delete(self) -> bool:
        """Delete all documents from the index without dropping the index."""
        try:
            self._delete_all_keys()
            return True
        except Exception as e:
            log_error(f"Error deleting Valkey index contents: {str(e)}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete documents by ID."""
        try:
            return self._delete_by_tag_filter("id", id)
        except Exception as e:
            log_error(f"Error deleting document by ID: {str(e)}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name."""
        try:
            return self._delete_by_tag_filter("name", name)
        except Exception as e:
            log_error(f"Error deleting documents by name: {str(e)}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        try:
            # Build a combined tag filter query
            filter_parts = [f"@{key}:{{{value}}}" for key, value in metadata.items()]
            query = " ".join(filter_parts)
            return self._delete_by_query(query)
        except Exception as e:
            log_error(f"Error deleting documents by metadata: {str(e)}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID."""
        try:
            return self._delete_by_tag_filter("content_id", content_id)
        except Exception as e:
            log_error(f"Error deleting documents by content_id: {str(e)}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Update metadata for documents with the given content ID."""
        try:
            client = self._get_client()
            keys = self._find_keys_by_tag("content_id", content_id)
            for key in keys:
                client.hset(key, cast(Mapping[str, str | bytes], metadata))  # type: ignore[arg-type]
            log_debug(f"Updated metadata for documents with content_id '{content_id}'")
        except Exception as e:
            log_error(f"Error updating metadata: {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get list of supported search types."""
        return ["vector", "keyword"]

    # -- Internal helpers --

    def _find_keys_by_tag(self, tag_field: str, tag_value: str) -> List[str]:
        """Find all keys matching a tag filter.

        Note:
            Results are capped at 1000 documents, consistent with the Redis implementation.
            If more than 1000 documents share the same tag value, excess documents will not
            be returned. If it becomes a limitation, paginating FT.SEARCH results works too.
        """
        client = self._get_client()
        query = f"@{tag_field}:{{{tag_value}}}"
        options = FtSearchOptions(
            limit=FtSearchLimit(0, 1000),
        )
        results = glide_ft.search(client, self.index_name, query, options)
        if not results or len(results) < 2:
            return []

        result_map = results[1] if len(results) > 1 else {}
        if isinstance(result_map, dict):
            return [_decode_value(k) for k in result_map.keys()]
        return []

    def _delete_by_tag_filter(self, tag_field: str, tag_value: str) -> bool:
        """Delete all documents matching a tag filter in a single batch call."""
        keys = self._find_keys_by_tag(tag_field, tag_value)
        if not keys:
            return False
        client = self._get_client()
        deleted = client.delete(cast(List[Union[str, bytes]], keys))
        log_debug(f"Deleted {deleted} documents with {tag_field}='{tag_value}'")
        return deleted is not None and int(deleted) > 0

    def _delete_by_query(self, query: str) -> bool:
        """Delete all documents matching an FT.SEARCH query in a single batch call."""
        client = self._get_client()
        options = FtSearchOptions(
            limit=FtSearchLimit(0, 1000),
        )
        results = glide_ft.search(client, self.index_name, query, options)
        if not results or len(results) < 2:
            return False

        result_map = results[1] if len(results) > 1 else {}
        if isinstance(result_map, dict):
            keys: List[Union[str, bytes]] = [_decode_value(k) for k in result_map.keys()]
            if keys:
                deleted = client.delete(keys)
                return deleted is not None and int(deleted) > 0
        return False

    def _delete_all_keys(self) -> None:
        """Delete all keys with the index prefix."""
        client = self._get_client()
        cursor: bytes | str = b"0"
        while True:
            scan_result = client.scan(cursor=cursor, match=f"{self.prefix}*", count=100)
            cursor = scan_result[0]  # type: ignore[assignment]
            keys = scan_result[1]
            if keys:
                str_keys: List[str | bytes] = [_decode_value(k) for k in keys]
                client.delete(str_keys)
            cursor_str = cursor.decode("utf-8") if isinstance(cursor, bytes) else str(cursor)
            if cursor_str == "0":
                break
