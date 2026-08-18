import asyncio
import re
from typing import Any, Dict, List, Mapping, Optional, Union

try:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis
    from redisvl.index import AsyncSearchIndex, SearchIndex
    from redisvl.query import FilterQuery, HybridQuery, TextQuery, VectorQuery
    from redisvl.query.filter import FilterExpression, Tag
    from redisvl.redis.utils import array_to_buffer, convert_bytes
    from redisvl.schema import IndexSchema
except ImportError:
    raise ImportError("`redis` and `redisvl` not installed. Please install using `pip install redis redisvl`")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import hash_string_sha256
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

# Hash fields the adapter owns; caller meta_data must never overwrite them (an "id"
# key in meta_data would otherwise redirect the per-user key and break isolation).
RESERVED_HASH_FIELDS = {"id", "name", "content", "embedding", "content_hash", "content_id", "user_id"}


# Characters RediSearch treats as special inside a TAG query: redisvl's TokenEscaper set,
# plus the '|' union character it omits. Escaping anything else breaks the match.
_TAG_SPECIAL_CHARS = re.compile(r"[,.<>{}\[\]\\\"\':;!@#$%^&*()\-+=~\/ \?|]")


def _escape_tag_value(value: Any) -> str:
    """Escape FT.SEARCH TAG special characters so the value matches as one literal tag.

    redisvl's ``Tag`` leaves '|' unescaped, which widens an owner id such as ``auth0|507f...``
    into several owners.
    """
    return _TAG_SPECIAL_CHARS.sub(lambda m: f"\\{m.group(0)}", str(value))


class RedisDb(VectorDb):
    """
    Redis class for managing vector operations with Redis and RedisVL.

    This class provides methods for creating, inserting, searching, and managing
    vector data in a Redis database using the RedisVL library.
    """

    # TAG field storing a chunk's owner for per-user isolation. Shared chunks store
    # the sentinel owner tag and the owner-OR-shared scope matches either.
    USER_ID_FIELD: str = "user_id"
    SHARED_OWNER_TAG: str = "__shared__"
    # TAG fields split stored values on a separator (default ","), so "a,b,c" would index
    # as three tags. 0x1f never appears in real values, keeping each owner one atomic tag.
    USER_ID_SEPARATOR: str = "\x1f"
    # RediSearch truncates an indexed TAG at 4096 bytes, so a longer owner id would index
    # as a prefix of another owner's tag.
    MAX_USER_ID_BYTES: int = 4096

    def __init__(
        self,
        index_name: str,
        redis_url: Optional[str] = None,
        redis_client: Optional[Redis] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        vector_score_weight: float = 0.7,
        reranker: Optional[Reranker] = None,
        **redis_kwargs,
    ):
        """
        Initialize the Redis instance.

        Args:
            index_name (str): Name of the Redis index to store vector data.
            redis_url (Optional[str]): Redis connection URL.
            redis_client (Optional[redis.Redis]): Redis client instance.
            embedder (Optional[Embedder]): Embedder instance for creating embeddings.
            search_type (SearchType): Type of search to perform.
            distance (Distance): Distance metric for vector comparisons.
            vector_score_weight (float): Weight for vector similarity in hybrid search.
            reranker (Optional[Reranker]): Reranker instance.
            **redis_kwargs: Additional Redis connection parameters.
        """
        if not index_name:
            raise ValueError("Index name must be provided.")

        if redis_client is None and redis_url is None:
            raise ValueError("Either 'redis_url' or 'redis_client' must be provided.")

        self.redis_url = redis_url

        # Initialize Redis client
        if redis_client is None:
            assert redis_url is not None
            self.redis_client = Redis.from_url(redis_url, **redis_kwargs)
        else:
            self.redis_client = redis_client

        # Index settings
        self.index_name: str = index_name

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
        self.vector_score_weight: float = vector_score_weight

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Create index schema
        self.schema = self._get_schema()
        self.index = self._create_index()
        self.meta_data_fields: set[str] = set()

        # Async components - created lazily when needed
        self._async_redis_client: Optional[AsyncRedis] = None
        self._async_index: Optional[AsyncSearchIndex] = None

        # Whether the live index schema has the owner field; resolved lazily and cached
        self._owner_field_exists: Optional[bool] = None

        log_debug(f"Initialized Redis with index '{self.index_name}'")

    async def _get_async_index(self) -> AsyncSearchIndex:
        """Get or create the async index and client."""
        if self._async_index is None:
            if self.redis_url is None:
                raise ValueError("redis_url must be provided for async operations")
            url: str = self.redis_url
            self._async_redis_client = AsyncRedis.from_url(url)
            self._async_index = AsyncSearchIndex(schema=self.schema, redis_client=self._async_redis_client)
        return self._async_index

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """Reject user_id values that would break TAG-based isolation.

        Each rejected form indexes or matches as another owner's tag, or impersonates the
        shared bucket. '|' is allowed: ``_escape_tag_value`` escapes it and OIDC ids carry it.
        """
        if user_id is None:
            return
        if user_id == "":
            raise ValueError("user_id must not be an empty string")
        if "\x00" in user_id:
            raise ValueError("user_id must not contain a NUL byte")
        if len(user_id.encode()) > self.MAX_USER_ID_BYTES:
            raise ValueError(f"user_id must not exceed {self.MAX_USER_ID_BYTES} bytes")
        if self.USER_ID_SEPARATOR in user_id:
            raise ValueError("user_id must not contain the reserved separator character (0x1f)")
        if user_id == self.SHARED_OWNER_TAG:
            raise ValueError(
                f"user_id must not be '{self.SHARED_OWNER_TAG}' - that value is reserved to mark content "
                "shared with every user"
            )
        if "{" in user_id or "}" in user_id:
            raise ValueError("user_id must not contain brace characters ('{' or '}')")
        if "*" in user_id or "?" in user_id:
            raise ValueError("user_id must not contain wildcard characters ('*' or '?')")
        if user_id != user_id.strip():
            raise ValueError("user_id must not have leading or trailing whitespace")

    def _scoped_doc_id(self, base_id: str, user_id: Optional[str]) -> str:
        """Fold the owner into the deterministic id so two users uploading the same content
        get distinct keys. The shared bucket keeps the legacy id.

        The base id is hashed first so the '_' boundary is fixed - otherwise ('doc_1',
        'alice') and ('doc', '1_alice') fold to the same key.
        """
        if user_id is None:
            return base_id
        return hash_string_sha256(f"{hash_string_sha256(base_id)}_{user_id}")

    def _owner_tag(self, user_id: str) -> str:
        """Tag clause matching the given owner."""
        return f"@{self.USER_ID_FIELD}:{{{_escape_tag_value(user_id)}}}"

    def _user_scope_filter(self, user_id: Optional[str]) -> Optional["FilterExpression"]:
        """Scope a search to the caller's own chunks plus the shared ones (which store the
        sentinel owner tag). ``None`` returns no scope, so an unscoped caller sees everything.
        """
        if user_id is None:
            return None
        owners = f"{_escape_tag_value(user_id)}|{_escape_tag_value(self.SHARED_OWNER_TAG)}"
        return FilterExpression(f"@{self.USER_ID_FIELD}:{{{owners}}}")

    def _get_schema(self):
        """Get default redis schema"""
        distance_mapping = {
            Distance.cosine: "cosine",
            Distance.l2: "l2",
            Distance.max_inner_product: "ip",
        }

        return IndexSchema.from_dict(
            {
                "index": {
                    "name": self.index_name,
                    "prefix": f"{self.index_name}:",
                    "storage_type": "hash",
                },
                "fields": [
                    {"name": "id", "type": "tag"},
                    {"name": "name", "type": "tag"},
                    {"name": "content", "type": "text"},
                    {"name": "content_hash", "type": "tag"},
                    {"name": "content_id", "type": "tag"},
                    # Owner of the chunk for per-user isolation (see USER_ID_SEPARATOR)
                    {
                        "name": self.USER_ID_FIELD,
                        "type": "tag",
                        "attrs": {"separator": self.USER_ID_SEPARATOR, "case_sensitive": True},
                    },
                    # Common metadata fields used in operations/tests
                    {"name": "status", "type": "tag"},
                    {"name": "category", "type": "tag"},
                    {"name": "tag", "type": "tag"},
                    {"name": "source", "type": "tag"},
                    {"name": "mode", "type": "tag"},
                    {
                        "name": "embedding",
                        "type": "vector",
                        "attrs": {
                            "dims": self.dimensions,
                            "distance_metric": distance_mapping[self.distance],
                            "algorithm": "flat",
                        },
                    },
                ],
            }
        )

    def _create_index(self) -> SearchIndex:
        """Create the RedisVL index object for this schema."""
        return SearchIndex(self.schema, redis_url=self.redis_url)

    def _index_has_user_id_field(self) -> Optional[bool]:
        """Whether the live index schema contains the owner tag field.

        Returns None when the index cannot be inspected (connection failure, restricted
        FT.INFO, unexpected response) — inconclusive, not a verdict either way.
        """
        try:
            info = self.index.info()
            attributes = info.get("attributes", []) if isinstance(info, dict) else []

            def _as_str(value: Any) -> str:
                return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)

            for attr in attributes:
                parts = attr if isinstance(attr, (list, tuple)) else [attr]
                if any(_as_str(part) == self.USER_ID_FIELD for part in parts):
                    return True
            return False
        except Exception:
            return None

    def _user_id_field_exists(self) -> bool:
        """Cached wrapper around ``_index_has_user_id_field``.

        Only conclusive answers are cached — an inconclusive inspection assumes "migrated"
        for this call alone.
        """
        if self._owner_field_exists is None:
            answer = self._index_has_user_id_field()
            if answer is None:
                log_warning(
                    f"Could not inspect Redis index '{self.index_name}' for the "
                    f"'{self.USER_ID_FIELD}' field; proceeding as migrated for this operation."
                )
                return True
            self._owner_field_exists = answer
        return self._owner_field_exists

    def _require_owner_field(self, user_id: Optional[str]) -> bool:
        """Gate every owner-tag reference on the live index schema.

        True when the field is indexed, False when it is missing and the operation is
        unscoped. A scoped operation on a pre-v3 index raises rather than matching nothing.
        """
        if self._user_id_field_exists():
            return True
        if user_id is None:
            return False
        # The cached answer may predate an index rebuild — re-inspect once before refusing
        self._owner_field_exists = None
        if self._user_id_field_exists():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but Redis index '{self.index_name}' predates per-user "
            f"isolation and has no '{self.USER_ID_FIELD}' field. Recreate the index (or FT.ALTER it) "
            "and run the v2 -> v3 migration (libs/agno/migrations/v2_to_v3/migrate_sentinel_vectordbs.py)."
        )

    def create(self) -> None:
        """Create the Redis index if it does not exist."""
        try:
            if not self.exists():
                self.index.create()
                log_debug(f"Created Redis index: {self.index_name}")
            else:
                log_debug(f"Redis index already exists: {self.index_name}")
                # Warn only on a conclusive verdict — None means the index couldn't be inspected
                if self._index_has_user_id_field() is False:
                    log_warning(
                        f"Redis index '{self.index_name}' was created without the "
                        f"'{self.USER_ID_FIELD}' field; per-user scoped searches will not match. "
                        "Run the v2 -> v3 migration "
                        "(libs/agno/migrations/v2_to_v3/migrate_sentinel_vectordbs.py), which "
                        "stamps the vectors and rebuilds the index schema in place. Do not call "
                        "drop() to fix this — it deletes the stored vectors along with the index."
                    )
        except Exception as e:
            log_error(f"Error creating Redis index: {str(e)}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        try:
            async_index = await self._get_async_index()
            await async_index.create(overwrite=False, drop=False)
            log_debug(f"Created Redis index: {self.index_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                log_debug(f"Redis index already exists: {self.index_name}")
            else:
                log_error(f"Error creating Redis index: {str(e)}")
                raise

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        try:
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if name exists: {str(e)}")
            return False

    async def async_name_exists(self, name: str) -> bool:  # type: ignore[override]
        """Async version of name_exists method."""
        try:
            async_index = await self._get_async_index()
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = await async_index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if name exists: {str(e)}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        try:
            id_filter = Tag("id") == id
            query = FilterQuery(
                filter_expression=id_filter,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if ID exists: {str(e)}")
            return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document with the given content hash exists.

        Scoped to the same bucket ``_dedupe_filter`` clears, so the dedup guard and the
        upsert delete never disagree.
        """
        # Outside the try so an invalid user_id or a scoped check on a pre-v3 index raises
        self._validate_user_id(user_id)
        scope_to_owner = self._require_owner_field(user_id)
        try:
            if scope_to_owner:
                filter_expression: "FilterExpression" = self._dedupe_filter(content_hash, user_id)
            else:
                # Pre-v3 index: no owner field, so the whole index is the shared bucket
                filter_expression = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=filter_expression,
                return_fields=["id"],
                num_results=1,
            )
            results = self.index.query(query)
            return len(results) > 0
        except Exception as e:
            log_error(f"Error checking if content hash exists: {str(e)}")
            return False

    def _parse_redis_hash(self, doc: Document, user_id: Optional[str] = None):
        """
        Create object serializable into Redis HASH structure
        """
        doc_dict = doc.to_dict()
        # Ensure an ID is present; derive a deterministic one from content when missing
        # Fold in the owner so two users uploading identical content get distinct keys
        base_id = doc.id or hash_string_sha256(doc.content)
        doc_dict["id"] = self._scoped_doc_id(base_id, user_id)
        if not doc.embedding:
            doc.embed(self.embedder)

        # TODO: determine how we want to handle dtypes
        doc_dict["embedding"] = array_to_buffer(doc.embedding, "float32")

        # Add content_id if available
        if hasattr(doc, "content_id") and doc.content_id:
            doc_dict["content_id"] = doc.content_id

        if "meta_data" in doc_dict:
            meta_data = doc_dict.pop("meta_data", {})
            # Drop keys the adapter owns so caller meta_data can't overwrite the id,
            # embedding or owner and thereby escape its per-user key.
            reserved = {k: v for k, v in meta_data.items() if k in RESERVED_HASH_FIELDS}
            if reserved:
                log_warning(f"Ignoring reserved meta_data keys that cannot be overwritten: {sorted(reserved)}")
            for md, mv in meta_data.items():
                if md in RESERVED_HASH_FIELDS:
                    continue
                self.meta_data_fields.add(md)
                doc_dict[md] = mv

        # Stamp the owner after merging meta_data so caller meta_data can't overwrite it.
        # Shared chunks (user_id None) store the sentinel owner tag.
        doc_dict[self.USER_ID_FIELD] = user_id if user_id is not None else self.SHARED_OWNER_TAG

        return doc_dict

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents into the Redis index."""
        self._validate_user_id(user_id)
        # A scoped write on a pre-v3 index raises: the owner tag would be stored unindexed
        self._require_owner_field(user_id)
        try:
            # Store content hash for tracking
            parsed_documents = []
            for doc in documents:
                parsed_doc = self._parse_redis_hash(doc, user_id=user_id)
                parsed_doc["content_hash"] = content_hash
                parsed_documents.append(parsed_doc)

            self.index.load(parsed_documents, id_field="id")
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
        self._validate_user_id(user_id)
        # See ``insert`` for why a scoped write on a pre-v3 index raises
        # Inspects the live schema over the sync client, so it goes to a worker thread
        # rather than stalling the event loop on a cold cache.
        await asyncio.to_thread(self._require_owner_field, user_id)
        try:
            async_index = await self._get_async_index()
            parsed_documents = []
            for doc in documents:
                parsed_doc = self._parse_redis_hash(doc, user_id=user_id)
                parsed_doc["content_hash"] = content_hash
                parsed_documents.append(parsed_doc)
            await async_index.load(parsed_documents, id_field="id")
            log_debug(f"Inserted {len(documents)} documents with content_hash: {content_hash}")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    def upsert_available(self) -> bool:
        """Check if upsert is available (always True for Redis)."""
        return True

    def _dedupe_filter(self, content_hash: str, user_id: Optional[str]) -> "FilterExpression":
        """Filter for the upsert dedupe-delete, scoped to the caller's bucket.

        A scoped upsert (user_id set) deletes only the caller's prior chunks for
        this content_hash; a shared upsert (None) deletes only shared chunks.
        """
        owner = user_id if user_id is not None else self.SHARED_OWNER_TAG
        return (Tag("content_hash") == content_hash) & FilterExpression(self._owner_tag(owner))

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents into the Redis index.
        Strategy: delete existing docs with the same content_hash in the caller's
        bucket, then insert new docs.
        """
        self._validate_user_id(user_id)
        scope_to_owner = self._require_owner_field(user_id)
        try:
            # Find and delete existing docs for this content_hash in the caller's bucket.
            # A pre-v3 index has no owner field, so it dedupes by content_hash alone.
            if scope_to_owner:
                dedupe: "FilterExpression" = self._dedupe_filter(content_hash, user_id)
            else:
                dedupe = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=dedupe,
                return_fields=["id"],
                num_results=1000,
            )
            existing = self.index.query(query)
            parsed = convert_bytes(existing)
            for r in parsed:
                key = r.get("id")
                if key:
                    self.index.drop_keys(key)

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
        """Async version of upsert method.
        Strategy: delete existing docs with the same content_hash in the caller's
        bucket, then insert new docs.
        """
        self._validate_user_id(user_id)
        # Inspects the live schema over the sync client, so it goes to a worker thread
        # rather than stalling the event loop on a cold cache.
        scope_to_owner = await asyncio.to_thread(self._require_owner_field, user_id)
        try:
            async_index = await self._get_async_index()

            # See ``upsert`` — pre-v3 indices dedupe by content_hash alone.
            if scope_to_owner:
                dedupe: "FilterExpression" = self._dedupe_filter(content_hash, user_id)
            else:
                dedupe = Tag("content_hash") == content_hash
            query = FilterQuery(
                filter_expression=dedupe,
                return_fields=["id"],
                num_results=1000,
            )
            existing = await async_index.query(query)
            parsed = convert_bytes(existing)
            for r in parsed:
                key = r.get("id")
                if key:
                    await async_index.drop_keys(key)

            # Insert new docs
            await self.async_insert(content_hash, documents, filters, user_id=user_id)
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search for documents using the specified search type."""

        if filters and isinstance(filters, List):
            log_warning("Filters Expressions are not supported in Redis. No filters will be applied.")
            filters = None
        # Outside the try so an invalid user_id or a scoped search on a pre-v3 index raises
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        try:
            filter_expression = self._user_scope_filter(user_id)
            if self.search_type == SearchType.vector:
                return self.vector_search(query, limit, filter_expression)
            elif self.search_type == SearchType.keyword:
                return self.keyword_search(query, limit, filter_expression)
            elif self.search_type == SearchType.hybrid:
                return self.hybrid_search(query, limit, filter_expression)
            else:
                raise ValueError(f"Unsupported search type: {self.search_type}")
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
        self, query: str, limit: int = 5, filter_expression: Optional["FilterExpression"] = None
    ) -> List[Document]:
        """Perform vector similarity search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(self.embedder.get_embedding(query), "float32")

            # TODO: do we want to pass back the embedding?
            # Create vector query
            vector_query = VectorQuery(
                vector=query_embedding,
                vector_field_name="embedding",
                return_fields=["id", "name", "content"],
                return_score=False,
                num_results=limit,
                filter_expression=filter_expression,
            )

            # Execute search
            results = self.index.query(vector_query)

            # Convert results to documents
            documents = [Document.from_dict(r) for r in results]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in vector search: {str(e)}")
            return []

    def keyword_search(
        self, query: str, limit: int = 5, filter_expression: Optional["FilterExpression"] = None
    ) -> List[Document]:
        """Perform keyword search using Redis text search."""
        try:
            # Create text query
            text_query = TextQuery(
                text=query,
                text_field_name="content",
                filter_expression=filter_expression,
            )

            # Execute search
            results = self.index.query(text_query)

            # Convert results to documents
            parsed = convert_bytes(results)

            # Convert results to documents
            documents = [Document.from_dict(p) for p in parsed]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in keyword search: {str(e)}")
            return []

    def hybrid_search(
        self, query: str, limit: int = 5, filter_expression: Optional["FilterExpression"] = None
    ) -> List[Document]:
        """Perform hybrid search combining vector and keyword search."""
        try:
            # Get query embedding
            query_embedding = array_to_buffer(self.embedder.get_embedding(query), "float32")

            # Create vector query
            vector_query = HybridQuery(
                vector=query_embedding,
                vector_field_name="embedding",
                text=query,
                text_field_name="content",
                linear_alpha=self.vector_score_weight,
                return_fields=["id", "name", "content"],
                num_results=limit,
                filter_expression=filter_expression,
            )

            # Execute search
            results = self.index.query(vector_query)
            parsed = convert_bytes(results)

            # Convert results to documents
            documents = [Document.from_dict(p) for p in parsed]

            # Apply reranking if reranker is available
            if self.reranker:
                documents = self.reranker.rerank(query=query, documents=documents)

            return documents
        except Exception as e:
            log_error(f"Error in hybrid search: {str(e)}")
            return []

    def drop(self) -> bool:  # type: ignore[override]
        """Drop the Redis index."""
        try:
            self.index.delete(drop=True)
            log_debug(f"Deleted Redis index: {self.index_name}")
            # The next index under this name has the owner field — re-resolve lazily
            self._owner_field_exists = None
            return True
        except Exception as e:
            log_error(f"Error dropping Redis index: {str(e)}")
            return False

    async def async_drop(self) -> None:
        """Async version of drop method."""
        try:
            async_index = await self._get_async_index()
            await async_index.delete(drop=True)
            log_debug(f"Deleted Redis index: {self.index_name}")
            # See ``drop`` — re-resolve the cached schema answer lazily
            self._owner_field_exists = None
        except Exception as e:
            log_error(f"Error dropping Redis index: {str(e)}")
            raise

    def exists(self) -> bool:
        """Check if the Redis index exists."""
        try:
            return self.index.exists()
        except Exception as e:
            log_error(f"Error checking if index exists: {str(e)}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        try:
            async_index = await self._get_async_index()
            return await async_index.exists()
        except Exception as e:
            log_error(f"Error checking if index exists: {str(e)}")
            return False

    def optimize(self) -> None:
        """Optimize the Redis index (no-op for Redis)."""
        log_debug("Redis optimization not required")
        pass

    def delete(self) -> bool:
        """Delete the Redis index (same as drop)."""
        try:
            self.index.clear()
            return True
        except Exception as e:
            log_error(f"Error deleting Redis index: {str(e)}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete documents by ID."""
        try:
            # Use RedisVL to drop documents by document ID
            result = self.index.drop_documents(id)
            log_debug(f"Deleted document with id '{id}' from Redis index")
            return result > 0
        except Exception as e:
            log_error(f"Error deleting document by ID: {str(e)}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name."""
        try:
            # First find documents with the given name
            name_filter = Tag("name") == name
            query = FilterQuery(
                filter_expression=name_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with name '{name}'")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by name: {str(e)}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        try:
            # Build filter expression for metadata using Tag filters
            filters = []
            for key, value in metadata.items():
                filters.append(Tag(key) == str(value))

            # Combine filters with AND logic
            if len(filters) == 1:
                combined_filter = filters[0]
            else:
                combined_filter = filters[0]
                for f in filters[1:]:
                    combined_filter = combined_filter & f

            # Find documents with the given metadata
            query = FilterQuery(
                filter_expression=combined_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with metadata {metadata}")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by metadata: {str(e)}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete documents by content ID.

        ``user_id`` deletes only that owner's chunks, never the shared bucket; ``None``
        deletes across every owner.
        """
        # Outside the try so a scoped delete on a pre-v3 index raises instead of returning False
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        try:
            # Find documents with the given content_id, scoped to the caller's bucket.
            if user_id is None:
                content_id_filter: "FilterExpression" = Tag("content_id") == content_id
            else:
                cid = str(Tag("content_id") == content_id)
                content_id_filter = FilterExpression(f"{cid} {self._owner_tag(user_id)}")
            query = FilterQuery(
                filter_expression=content_id_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Delete each found document by key (result['id'] is the Redis key)
            deleted_count = 0
            for result in parsed:
                key = result.get("id")
                if key:
                    deleted_count += self.index.drop_keys(key)

            log_debug(f"Deleted {deleted_count} documents with content_id '{content_id}'")
            return deleted_count > 0
        except Exception as e:
            log_error(f"Error deleting documents by content_id: {str(e)}")
            return False

    def update_metadata(self, content_id: str, metadata: Mapping[str, Any]) -> None:
        """Update metadata for documents with the given content ID."""
        try:
            # Drop keys the adapter owns so caller metadata can't overwrite the id,
            # embedding or owner, mirroring the insert path (_parse_redis_hash).
            reserved = {k: v for k, v in metadata.items() if k in RESERVED_HASH_FIELDS}
            if reserved:
                log_warning(f"Ignoring reserved meta_data keys that cannot be overwritten: {sorted(reserved)}")
            metadata = {k: v for k, v in metadata.items() if k not in RESERVED_HASH_FIELDS}

            # Find documents with the given content_id
            content_id_filter = Tag("content_id") == content_id
            query = FilterQuery(
                filter_expression=content_id_filter,
                return_fields=["id"],
                num_results=1000,  # Get all matching documents
            )
            results = self.index.query(query)
            parsed = convert_bytes(results)

            # Update metadata for each found document
            for result in parsed:
                key = result.get("id")
                if key and metadata:
                    self.redis_client.hset(key, mapping=metadata)  # type: ignore[arg-type]

            log_debug(f"Updated metadata for documents with content_id '{content_id}'")
        except Exception as e:
            log_error(f"Error updating metadata: {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get list of supported search types."""
        return ["vector", "keyword", "hybrid"]
