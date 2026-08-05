import asyncio
import math
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

# Metadata fields declared as TAG fields in the index schema and therefore filterable.
# "linked_to" is the filter Knowledge injects when isolate_vector_search is enabled, so
# it must be indexed for that isolation to be enforced server-side.
FILTERABLE_TAG_FIELDS = {
    "id",
    "name",
    "content_hash",
    "content_id",
    "status",
    "category",
    "tag",
    "source",
    "mode",
    "linked_to",
}

# Hash fields the adapter owns; caller meta_data must never overwrite them (an "id"
# key in meta_data would otherwise redirect the per-user key and break isolation).
RESERVED_HASH_FIELDS = {"id", "name", "content", "embedding", "content_hash", "content_id", "user_id"}


def _escape_tag_value(value: Any) -> str:
    """Escape FT.SEARCH TAG special characters (spaces, pipes, braces, dashes, ...)
    so the value is matched as a single literal tag."""
    return "".join(c if c.isalnum() or c == "_" else f"\\{c}" for c in str(value))


def _escape_query_text(query: str) -> str:
    """Reduce a free-text keyword query to whitespace-separated alphanumeric tokens,
    so FT.SEARCH operator characters cannot break out of the caller's scope clause."""
    tokens = ["".join(c for c in tok if c.isalnum() or c == "_") for tok in query.split()]
    return " ".join(tok for tok in tokens if tok)


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

    # Owner tag for per-user isolation. valkey-search has no ismissing(), so
    # shared chunks store the sentinel owner and the scope query matches either.
    USER_ID_FIELD: str = "user_id"
    SHARED_OWNER_TAG: str = "__shared__"
    # Reserved owner tag that is never stored; negating it is the match-all
    # keyword query (valkey-search rejects a bare '*' outside a KNN pre-filter).
    MATCH_ALL_TAG: str = "__match_all__"

    # TAG fields split stored values on a separator (default ","), so "a,b,c"
    # would index as three tags. 0x1f never appears in real values, keeping
    # each value one atomic tag; the owner field is also case sensitive.
    USER_ID_SEPARATOR: str = "\x1f"
    TAG_SEPARATOR: str = "\x1f"

    def __init__(
        self,
        index_name: str,
        host: str = "localhost",
        port: int = 6379,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = False,
        database_id: Optional[int] = None,
        request_timeout: Optional[int] = None,
        client_name: str = "agno_vectordb_client",
        glide_client: Optional[GlideClient] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        vector_algorithm: str = "HNSW",
        reranker: Optional[Reranker] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
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
            request_timeout (Optional[int]): Duration in milliseconds to wait for a request to complete.
                If not set, the client default (250 milliseconds) is used.
            client_name (str): Connection name set via CLIENT SETNAME, visible in CLIENT LIST.
            glide_client (Optional[GlideClient]): Pre-configured GlideClient instance.
                If not provided, one will be created from host/port and optional auth/TLS settings.
            embedder (Optional[Embedder]): Embedder instance for creating embeddings.
            search_type (SearchType): Type of search to perform.
            distance (Distance): Distance metric for vector comparisons.
            vector_algorithm (str): Vector indexing algorithm ("HNSW" or "FLAT").
            reranker (Optional[Reranker]): Reranker instance.
            id (Optional[str]): Optional custom ID. If not provided, an id will be generated.
            name (Optional[str]): Optional name for the vector database.
            description (Optional[str]): Optional description for the vector database.
        """
        if not index_name:
            raise ValueError("Index name must be provided.")
        if username and not password:
            raise ValueError("password must be provided when username is set")

        super().__init__(id=id, name=name, description=description)

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.database_id = database_id
        self.request_timeout = request_timeout
        self.client_name = client_name
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
                request_timeout=self.request_timeout,
                client_name=self.client_name,
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
        sep = self.TAG_SEPARATOR
        fields = [
            TagField("id", separator=sep),
            TagField("name", separator=sep),
            TextField("content"),
            TagField("content_hash", separator=sep),
            TagField("content_id", separator=sep),
            # Owner of the chunk for per-user isolation (see USER_ID_SEPARATOR)
            TagField(self.USER_ID_FIELD, separator=self.USER_ID_SEPARATOR, case_sensitive=True),
            TagField("status", separator=sep),
            TagField("category", separator=sep),
            TagField("tag", separator=sep),
            TagField("source", separator=sep),
            TagField("mode", separator=sep),
            # Knowledge injects this filter for isolate_vector_search; index it so the scope is enforced
            TagField("linked_to", separator=sep),
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

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """Reject user_id values that would break TAG-based isolation.

        The separator would index one value as several owner tags, the shared
        sentinel would let a caller impersonate the shared bucket, a stored
        match-all tag would break the match-all query, braces can never be
        matched by a scope clause, wildcards match other owners' tags even
        when escaped, and an empty string is an owner tag no scope clause can
        ever match.
        """
        if user_id is None:
            return
        if user_id == "":
            raise ValueError("user_id must not be an empty string; use None for unscoped access")
        if self.USER_ID_SEPARATOR in user_id:
            raise ValueError("user_id must not contain the reserved separator character (0x1f)")
        if user_id == self.SHARED_OWNER_TAG:
            raise ValueError(f"user_id must not equal the reserved shared-owner tag '{self.SHARED_OWNER_TAG}'")
        if user_id == self.MATCH_ALL_TAG:
            raise ValueError(f"user_id must not equal the reserved match-all tag '{self.MATCH_ALL_TAG}'")
        if "{" in user_id or "}" in user_id:
            raise ValueError("user_id must not contain brace characters ('{' or '}')")
        if "*" in user_id or "?" in user_id:
            raise ValueError("user_id must not contain wildcard characters ('*' or '?')")

    def _scoped_doc_id(self, base_id: str, user_id: Optional[str]) -> str:
        """Fold the owner into the deterministic id so two users uploading the
        same content get distinct keys. The shared bucket keeps the legacy id.
        """
        if user_id is None:
            return base_id
        return hash_string_sha256(f"{base_id}_{user_id}")

    def _parse_hash(self, doc: Document, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a dict serializable into a Valkey HASH structure.

        Valkey HASH fields only accept string or bytes values, so all
        non-bytes values are coerced to strings before returning.
        """
        doc_dict = doc.to_dict()
        base_id = doc.id or hash_string_sha256(doc.content)
        doc_dict["id"] = self._scoped_doc_id(base_id, user_id)

        if not doc.embedding:
            doc.embed(self.embedder)

        if doc.embedding is None:
            raise ValueError(f"Document embedding is None after embed() call for doc id={doc.id}")
        # A wrong-size vector is stored but never indexed (hash_indexing_failures),
        # making the doc silently invisible to vector search — fail loudly instead.
        if len(doc.embedding) != self.dimensions:
            raise ValueError(
                f"Document embedding has {len(doc.embedding)} dimensions, expected {self.dimensions} "
                f"for doc id={doc.id}"
            )
        # A NaN/Inf vector is indexed but ranks out of every KNN result, the same
        # silent invisibility as a wrong-size vector — fail loudly instead.
        if not all(math.isfinite(value) for value in doc.embedding):
            raise ValueError(f"Document embedding contains non-finite values for doc id={doc.id}")
        doc_dict["embedding"] = _float_list_to_bytes(doc.embedding)

        if hasattr(doc, "content_id") and doc.content_id:
            doc_dict["content_id"] = doc.content_id

        if "meta_data" in doc_dict:
            meta_data = doc_dict.pop("meta_data", {})
            # Drop keys the adapter owns so caller meta_data can't overwrite the id,
            # embedding or owner and thereby escape its per-user key.
            reserved = {k: v for k, v in meta_data.items() if k in RESERVED_HASH_FIELDS}
            if reserved:
                log_warning(f"Ignoring reserved meta_data keys that cannot be overwritten: {sorted(reserved)}")
            doc_dict.update({k: v for k, v in meta_data.items() if k not in RESERVED_HASH_FIELDS})

        # Stamp the owner after merging meta_data so caller meta_data can't overwrite
        # it. Shared chunks (user_id None) store the sentinel owner tag.
        doc_dict[self.USER_ID_FIELD] = user_id if user_id is not None else self.SHARED_OWNER_TAG

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

    def _indexed_field_names(self) -> set:
        """Extract the set of indexed field identifiers from FT.INFO output.

        info["attributes"] is a list of flat key/value lists, e.g.
        [b'identifier', b'id', b'attribute', b'id', b'type', b'TAG', ...].
        """
        client = self._get_client()
        info = glide_ft.info(client, self.index_name)
        attributes = cast(List[List[Any]], next((v for k, v in info.items() if _decode_value(k) == "attributes"), []))
        names = set()
        for attr in attributes:
            for i in range(0, len(attr) - 1, 2):
                if _decode_value(attr[i]) == "identifier":
                    names.add(_decode_value(attr[i + 1]))
                    break
        return names

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
                if self.USER_ID_FIELD not in self._indexed_field_names():
                    log_warning(
                        f"Valkey index '{self.index_name}' was created without the "
                        f"'{self.USER_ID_FIELD}' field; per-user scoped searches will not match. "
                        f"Drop and recreate the index to enable per-user isolation."
                    )
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
            query = f"@name:{{{_escape_tag_value(name)}}}"
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
            query = f"@id:{{{_escape_tag_value(id)}}}"
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
            query = f"@content_hash:{{{_escape_tag_value(content_hash)}}}"
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
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents into the Valkey index."""
        try:
            self._validate_user_id(user_id)
            client = self._get_client()
            for doc in documents:
                parsed_doc = self._parse_hash(doc, user_id=user_id)
                parsed_doc["content_hash"] = content_hash
                # Keep "id" as a hash field so it is indexed (used by id_exists/delete_by_id)
                doc_id = parsed_doc["id"]
                key = f"{self.prefix}{doc_id}"
                client.hset(key, cast(Mapping[str, Union[str, bytes]], parsed_doc))  # type: ignore[arg-type]
            log_debug(f"Inserted {len(documents)} documents with content_hash: {content_hash}")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Async version of insert method."""
        await asyncio.to_thread(self.insert, content_hash, documents, filters, user_id)

    def upsert_available(self) -> bool:
        """Check if upsert is available (always True for Valkey)."""
        return True

    def _dedupe_query(self, content_hash: str, user_id: Optional[str]) -> str:
        """Query for the upsert dedupe-delete, scoped to the caller's bucket.

        A scoped upsert (user_id set) deletes only the caller's prior chunks
        for this content_hash; a shared upsert (None) deletes only shared chunks.
        """
        owner = user_id if user_id is not None else self.SHARED_OWNER_TAG
        return (
            f"@content_hash:{{{_escape_tag_value(content_hash)}}} @{self.USER_ID_FIELD}:{{{_escape_tag_value(owner)}}}"
        )

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the Valkey index.
        Strategy: delete existing docs with the same content_hash (scoped to the
        caller's bucket), then insert new docs.
        """
        try:
            self._validate_user_id(user_id)
            # Find and delete existing docs for this content_hash in the caller's bucket
            self._delete_by_query(self._dedupe_query(content_hash, user_id))
            # Insert new docs
            self.insert(content_hash, documents, filters, user_id=user_id)
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Async version of upsert method."""
        await asyncio.to_thread(self.upsert, content_hash, documents, filters, user_id)

    def _build_filter_expression(self, filters: Optional[Dict[str, Any]]) -> str:
        """Build an FT.SEARCH TAG filter expression from a metadata filters dict.

        Only fields declared as TAG fields in the index schema can be filtered
        server-side; other keys are stored but unindexed, so they are skipped
        with a warning. List values match any of the listed tags.
        """
        if not filters:
            return ""
        clauses = []
        for key, value in filters.items():
            if key not in FILTERABLE_TAG_FIELDS:
                log_warning(
                    f"Metadata filter '{key}' is not an indexed field and will be ignored. "
                    f"Filterable fields: {sorted(FILTERABLE_TAG_FIELDS)}"
                )
                continue
            if value is None:
                log_warning(f"Metadata filter '{key}' has a None value and will be ignored.")
                continue
            if isinstance(value, (list, tuple, set)):
                if not value:
                    log_warning(f"Metadata filter '{key}' has an empty list value and will be ignored.")
                    continue
                tag = "|".join(_escape_tag_value(v) for v in value)
            else:
                tag = _escape_tag_value(value)
            clauses.append(f"@{key}:{{{tag}}}")
        return " ".join(clauses)

    def _user_scope_expression(self, user_id: Optional[str]) -> str:
        """Build the owner-OR-shared scope clause for a search.

        user_id set  -> match the caller's own chunks OR the shared chunks
        (which store the sentinel owner tag).
        user_id None -> empty string (no scope; admin sees everything).
        """
        if user_id is None:
            return ""
        return f"@{self.USER_ID_FIELD}:{{{_escape_tag_value(user_id)}|{self.SHARED_OWNER_TAG}}}"

    def _filter_exprs_to_dict(self, filters: List[FilterExpr]) -> Dict[str, Any]:
        """Translate a list of FilterExpr into an equivalent equality-filter dict.

        A List[FilterExpr] is an implicit AND. Only EQ and IN map to TAG matches;
        any other operator, a None or empty value, or conflicting EQs raise
        ValueError so search fails closed instead of dropping a filter (the
        injected linked_to isolation filter must never be discarded).
        """
        result: Dict[str, Any] = {}
        for expr in filters:
            spec = expr.to_dict()
            op = spec.get("op")
            key = spec.get("key")
            if not isinstance(key, str):
                raise ValueError(f"FilterExpr '{op}' has no field key; cannot apply server-side")
            if op == "EQ":
                value: Any = spec.get("value")
                if value is None:
                    raise ValueError(f"FilterExpr EQ on '{key}' has a None value; no stored tag can match it")
            elif op == "IN":
                value = list(spec.get("values") or [])
                if not value:
                    raise ValueError(f"FilterExpr IN on '{key}' has no values; it can never match")
            else:
                raise ValueError(f"FilterExpr operator '{op}' is not supported by Valkey vector search")
            if key in result and result[key] != value:
                raise ValueError(f"Conflicting FilterExpr conditions on field '{key}'")
            result[key] = value
        return result

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search for documents using the specified search type.

        Both the metadata filters and the per-user scope are applied as a
        pre-filter in every search mode, so scoped callers never see other
        owners' chunks and shared chunks stay visible to everyone. A
        List[FilterExpr] is translated to server-side TAG clauses; an
        untranslatable expression fails closed instead of being dropped.
        """
        if self.search_type == SearchType.hybrid:
            raise ValueError("Hybrid search is currently unsupported for Valkey")
        try:
            self._validate_user_id(user_id)
            if filters and isinstance(filters, List):
                filters = self._filter_exprs_to_dict(cast(List[FilterExpr], filters))
            if self.search_type == SearchType.keyword:
                return self.keyword_search(
                    query, limit, filters=cast(Optional[Dict[str, Any]], filters), user_id=user_id
                )
            return self.vector_search(query, limit, filters=cast(Optional[Dict[str, Any]], filters), user_id=user_id)
        except Exception as e:
            log_error(f"Error in search: {str(e)}")
            return []

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Async version of search method."""
        return await asyncio.to_thread(self.search, query, limit, filters, user_id)

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Perform vector similarity search using FT.SEARCH with KNN.

        Args:
            query (str): The query to embed and search for.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters applied as a KNN
                pre-filter on indexed TAG fields.
            user_id (Optional[str]): Scope results to this owner plus shared chunks.
                None applies no scope (admin view).
        """
        try:
            client = self._get_client()
            query_embedding = self.embedder.get_embedding(query)
            query_vector_bytes = _float_list_to_bytes(query_embedding)

            clauses = [self._build_filter_expression(filters), self._user_scope_expression(user_id)]
            filter_expression = " ".join(c for c in clauses if c)
            prefilter = f"({filter_expression})" if filter_expression else "*"
            ft_query = f"{prefilter}=>[KNN {limit} @embedding $query_vector]"
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

    def keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Perform keyword search using FT.SEARCH full-text query on TEXT fields.

        Args:
            query (str): The text to search for in document content.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Metadata filters applied as additional
                TAG clauses on indexed fields.
            user_id (Optional[str]): Scope results to this owner plus shared chunks.
                None applies no scope (admin view).

        Note:
            The query is reduced to alphanumeric search terms before it reaches
            FT.SEARCH, so query punctuation cannot alter the filter or user-scope
            clauses. A query with no alphanumeric terms matches every chunk in scope.
        """
        try:
            client = self._get_client()
            escaped_query = _escape_query_text(query)
            clauses = [
                f"(@content:{escaped_query})" if escaped_query else "",
                self._build_filter_expression(filters),
                self._user_scope_expression(user_id),
            ]
            expression = " ".join(c for c in clauses if c)
            # Match-all negates the reserved owner tag no chunk can ever store
            ft_query = expression if expression else f"-@{self.USER_ID_FIELD}:{{{self.MATCH_ALL_TAG}}}"
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
        """Delete documents by metadata.

        Unlike search, an unfilterable key is not skipped: dropping a clause
        would widen the delete beyond what the caller asked for, so the whole
        call is refused instead.
        """
        try:
            if not metadata:
                return False
            for key, value in metadata.items():
                if key not in FILTERABLE_TAG_FIELDS:
                    log_warning(
                        f"Cannot delete by metadata key '{key}': not an indexed field. "
                        f"Filterable fields: {sorted(FILTERABLE_TAG_FIELDS)}"
                    )
                    return False
                if value is None:
                    log_warning(f"Cannot delete by metadata key '{key}': value is None.")
                    return False
            # Build a combined tag filter query
            filter_parts = [f"@{key}:{{{_escape_tag_value(value)}}}" for key, value in metadata.items()]
            query = " ".join(filter_parts)
            return self._delete_by_query(query)
        except Exception as e:
            log_error(f"Error deleting documents by metadata: {str(e)}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by content ID.

        user_id set  -> delete only the caller's own chunks (must NOT touch
        the shared bucket). None -> delete across all owners (legacy/admin).
        """
        self._validate_user_id(user_id)
        try:
            if user_id is None:
                return self._delete_by_tag_filter("content_id", content_id)
            query = (
                f"@content_id:{{{_escape_tag_value(content_id)}}} "
                f"@{self.USER_ID_FIELD}:{{{_escape_tag_value(user_id)}}}"
            )
            return self._delete_by_query(query)
        except Exception as e:
            log_error(f"Error deleting documents by content_id: {str(e)}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Update metadata for documents with the given content ID."""
        try:
            # Drop keys the adapter owns so caller metadata can't overwrite the id,
            # embedding or owner and thereby corrupt indexing or escape isolation,
            # mirroring the insert path (_parse_hash).
            reserved = {k: v for k, v in metadata.items() if k in RESERVED_HASH_FIELDS}
            if reserved:
                log_warning(f"Ignoring reserved meta_data keys that cannot be overwritten: {sorted(reserved)}")
            metadata = {k: v for k, v in metadata.items() if k not in RESERVED_HASH_FIELDS}

            client = self._get_client()
            keys = self._find_keys_by_tag("content_id", content_id)
            # Valkey HASH values must be str or bytes — coerce everything else
            sanitized = {k: v if isinstance(v, bytes) else str(v) for k, v in metadata.items() if v is not None}
            for key in keys:
                if sanitized:
                    client.hset(key, cast(Mapping[str, Union[str, bytes]], sanitized))  # type: ignore[arg-type]
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
        query = f"@{tag_field}:{{{_escape_tag_value(tag_value)}}}"
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
        """Delete all documents matching an FT.SEARCH query.

        FT.SEARCH caps a page at a fixed size, so we page through the matches
        until none remain — otherwise a content_hash with more chunks than one
        page would leave stale chunks behind on an upsert.
        """
        client = self._get_client()
        options = FtSearchOptions(
            limit=FtSearchLimit(0, 1000),
        )
        any_deleted = False
        while True:
            results = glide_ft.search(client, self.index_name, query, options)
            if not results or len(results) < 2:
                break
            result_map = results[1]
            if not isinstance(result_map, dict) or not result_map:
                break
            keys: List[Union[str, bytes]] = [_decode_value(k) for k in result_map.keys()]
            deleted = client.delete(keys)
            if deleted is not None and int(deleted) > 0:
                any_deleted = True
            if len(keys) < 1000:
                break
        return any_deleted

    def _delete_all_keys(self) -> None:
        """Delete all keys with the index prefix."""
        client = self._get_client()
        # Escape glob metacharacters in the prefix so an index_name containing them
        # neither leaves this index's keys behind nor deletes another index's keys.
        escaped_prefix = "".join(f"\\{c}" if c in "*?[]\\" else c for c in self.prefix)
        cursor: Union[bytes, str] = b"0"
        while True:
            scan_result = client.scan(cursor=cursor, match=f"{escaped_prefix}*", count=100)
            cursor = scan_result[0]  # type: ignore[assignment]
            keys = scan_result[1]
            if keys:
                str_keys: List[Union[str, bytes]] = [_decode_value(k) for k in keys]
                client.delete(str_keys)
            cursor_str = cursor.decode("utf-8") if isinstance(cursor, bytes) else str(cursor)
            if cursor_str == "0":
                break
