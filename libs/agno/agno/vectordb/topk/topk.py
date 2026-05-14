import json
import os
from hashlib import md5
from typing import Any, Dict, Final, FrozenSet, List, Optional

try:
    from topk_sdk import AsyncClient, Client
    from topk_sdk import schema as topk_schema
    from topk_sdk.data import f32_vector
    from topk_sdk.query import LogicalExpr, Query, field, filter, fn, match_tokens, select
    from topk_sdk.query import all as topk_all
    from topk_sdk.schema import FieldSpec
except ImportError:
    raise ImportError("topk_sdk not installed. Run: pip install topk_sdk")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType


class TopK(VectorDb):
    AGNO_DOCUMENT_FIELDS: Final[tuple] = ("name", "content", "content_id", "content_hash", "usage")
    TOPK_DOCUMENT_ID_FIELD: Final[str] = "_id"
    TOPK_DOCUMENT_EMBEDDING_FIELD: Final[str] = "embedding"
    TOPK_DOCUMENT_SCORE_FIELD: Final[str] = "score"
    SYSTEM_FIELDS: Final[FrozenSet[str]] = frozenset(
        {TOPK_DOCUMENT_ID_FIELD, *AGNO_DOCUMENT_FIELDS, TOPK_DOCUMENT_EMBEDDING_FIELD, TOPK_DOCUMENT_SCORE_FIELD}
    )

    def __init__(
        self,
        collection: str,
        api_key: Optional[str] = None,
        region: Optional[str] = None,
        host: str = "topk.io",
        https: bool = True,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        search_type: SearchType = SearchType.vector,
        id: Optional[str] = None,
        description: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ):
        if not collection:
            raise ValueError("collection is required")

        self.collection = collection
        self.api_key = api_key
        self.region = region
        self.host = host
        self.https = https
        self.distance = distance
        self.search_type = search_type

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            self.embedder: Embedder = OpenAIEmbedder()
        else:
            self.embedder = embedder

        self._client: Optional[Client] = None
        self._async_client: Optional[AsyncClient] = None

        _id = id or md5(f"{host}_{collection}".encode()).hexdigest()[:8]
        super().__init__(
            id=_id,
            name=collection,
            description=description,
            similarity_threshold=similarity_threshold,
        )

    @property
    def client(self) -> Client:
        if self._client is None:
            api_key = self.api_key or os.environ.get("TOPK_API_KEY")
            region = self.region or os.environ.get("TOPK_REGION")
            if not api_key:
                raise ValueError("api_key is required or set TOPK_API_KEY env var")
            if not region:
                raise ValueError("region is required or set TOPK_REGION env var")
            self._client = Client(api_key=api_key, region=region, host=self.host, https=self.https)
        return self._client

    @property
    def async_client(self) -> AsyncClient:
        if self._async_client is None:
            api_key = self.api_key or os.environ.get("TOPK_API_KEY")
            region = self.region or os.environ.get("TOPK_REGION")
            if not api_key:
                raise ValueError("api_key is required or set TOPK_API_KEY env var")
            if not region:
                raise ValueError("region is required or set TOPK_REGION env var")
            self._async_client = AsyncClient(api_key=api_key, region=region, host=self.host, https=self.https)
        return self._async_client

    def _distance_metric(self) -> str:
        return {
            Distance.cosine: "cosine",
            Distance.l2: "euclidean",
            Distance.max_inner_product: "dot_product",
        }.get(self.distance, "cosine")

    def _build_schema(self) -> Dict[str, FieldSpec]:
        dims = self.embedder.dimensions or 1536
        schema: Dict[str, FieldSpec] = {
            "embedding": topk_schema.f32_vector(dims).index(topk_schema.vector_index(metric=self._distance_metric())),
        }
        if self.search_type in (SearchType.keyword, SearchType.hybrid):
            schema["content"] = topk_schema.text().index(topk_schema.keyword_index())
        return schema

    def _document_to_topk_doc(
        self,
        document: Document,
        content_hash: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            self.TOPK_DOCUMENT_ID_FIELD: self._record_id(document, content_hash),
            self.TOPK_DOCUMENT_EMBEDDING_FIELD: f32_vector(document.embedding),
            "name": document.name,
            "content": document.content,
            "content_id": document.content_id,
            "content_hash": content_hash,
            "usage": json.dumps(document.usage) if document.usage is not None else None,
        }

        extras = _strip_unsupported_field_types({**(document.meta_data or {}), **(filters or {})})
        record.update(extras)

        return record

    def _record_id(self, document: Document, content_hash: str) -> str:
        # Include content_hash in the persisted record ID so distinct ingestions
        # of the same source document do not overwrite each other.
        base_id = document.id or md5(document.content.encode()).hexdigest()
        return md5(f"{base_id}_{content_hash}".encode()).hexdigest()

    def _topk_doc_to_document(self, record: Dict[str, Any]) -> Document:
        meta_data = {k: v for k, v in record.items() if k not in self.SYSTEM_FIELDS}
        content = record.get("content")

        return Document(
            content=content if isinstance(content, str) else "",
            id=record.get(self.TOPK_DOCUMENT_ID_FIELD),
            name=record.get("name"),
            meta_data=meta_data,
            usage=_deserialize_usage(record.get("usage")),
            content_id=record.get("content_id"),
        )

    def _build_filter_expr(self, filters: Dict[str, Any]) -> LogicalExpr:
        exprs = [field(key) == value for key, value in filters.items()]
        return topk_all(exprs)

    def _vector_score_asc(self) -> bool:
        # dot_product returns raw similarity (higher = more similar) → sort descending.
        # cosine and euclidean return a distance (lower = more similar) → sort ascending.
        return self.distance != Distance.max_inner_product

    def _search_query(
        self,
        query_embedding: List[float],
        query_text: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Query:
        filter_fields = list(filters.keys()) if filters else []
        filter_expr = self._build_filter_expr(filters) if filters else None
        select_fields = (*self.AGNO_DOCUMENT_FIELDS, *filter_fields)
        vector_asc = self._vector_score_asc()

        if self.search_type == SearchType.keyword:
            tokens = query_text.split() or []
            q = select(*select_fields, score=fn.bm25_score()).filter(match_tokens(tokens, "content", all=False))
            if filter_expr is not None:
                q = q.filter(filter_expr)
            return q.sort(field("score"), asc=False).limit(limit)
        elif self.search_type == SearchType.hybrid:
            q = select(*select_fields, score=fn.vector_distance("embedding", query_embedding))
            if filter_expr is not None:
                q = q.filter(filter_expr)
            return q.sort(field("score").boost(field("content").match_any(query_text), 0.5), asc=vector_asc).limit(
                limit
            )
        else:
            q = select(*select_fields, score=fn.vector_distance("embedding", query_embedding))
            if filter_expr is not None:
                q = q.filter(filter_expr)
            return q.sort(field("score"), asc=vector_asc).limit(limit)

    def create(self) -> None:
        """Create the collection if it does not already exist."""
        if not self.exists():
            log_info(f"Creating TopK collection: {self.collection}")
            self.client.collections().create(self.collection, schema=self._build_schema())

    async def async_create(self) -> None:
        """Async version of :meth:`create`."""
        if not await self.async_exists():
            log_info(f"Creating TopK collection: {self.collection}")
            await self.async_client.collections().create(self.collection, schema=self._build_schema())

    def exists(self) -> bool:
        """Check whether the collection exists in TopK.

        Returns:
            True if the collection exists, False otherwise.
        """
        try:
            collections = self.client.collections().list()
            return any(c.name == self.collection for c in collections)
        except Exception as e:
            log_error(f"Error checking TopK collection existence: {e}")
            return False

    async def async_exists(self) -> bool:
        """Async version of :meth:`exists`.

        Returns:
            True if the collection exists, False otherwise.
        """
        try:
            collections = await self.async_client.collections().list()
            return any(c.name == self.collection for c in collections)
        except Exception as e:
            log_error(f"Error checking TopK collection existence: {e}")
            return False

    def drop(self) -> None:
        """Delete the collection and all its documents."""
        try:
            self.client.collections().delete(self.collection)
            log_info(f"Dropped TopK collection: {self.collection}")
        except Exception as e:
            log_error(f"Error dropping TopK collection: {e}")

    async def async_drop(self) -> None:
        """Async version of :meth:`drop`."""
        try:
            await self.async_client.collections().delete(self.collection)
            log_info(f"Dropped TopK collection: {self.collection}")
        except Exception as e:
            log_error(f"Error dropping TopK collection: {e}")

    def name_exists(self, name: str) -> bool:
        """Check whether a document with the given name exists.

        Args:
            name: The document name to look up.

        Returns:
            True if a matching document exists, False otherwise.
        """
        try:
            results = self.client.collection(self.collection).query(filter(field("name") == name).limit(1))
            return len(results) > 0
        except Exception as e:
            log_error(f"Error in name_exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Async version of :meth:`name_exists`.

        Args:
            name: The document name to look up.

        Returns:
            True if a matching document exists, False otherwise.
        """
        try:
            results = await self.async_client.collection(self.collection).query(filter(field("name") == name).limit(1))
            return len(results) > 0
        except Exception as e:
            log_error(f"Error in async_name_exists: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check whether a document with the given ID exists.

        Args:
            id: The document ID to look up.

        Returns:
            True if the document exists, False otherwise.
        """
        try:
            result = self.client.collection(self.collection).get([id])
            return id in result
        except Exception as e:
            log_error(f"Error in id_exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check whether a document with the given content hash exists.

        Args:
            content_hash: The content hash of the document to check.

        Returns:
            True if the document exists, False otherwise.
        """
        try:
            results = self.client.collection(self.collection).query(
                filter(field("content_hash") == content_hash).limit(1)
            )
            return len(results) > 0
        except Exception as e:
            log_error(f"Error in content_hash_exists: {e}")
            return False

    def upsert_available(self) -> bool:
        """Return True — TopK supports upsert natively."""
        return True

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Embed and insert documents into the collection.

        Args:
            content_hash: Hash identifying the source content batch.
            documents: Documents to embed and store.
            filters: Optional metadata key/value pairs stored alongside each document.
        """
        if not documents:
            log_debug("No documents to insert, skipping.")
            return
        records = []
        for doc in documents:
            doc.embed(embedder=self.embedder)
            records.append(self._document_to_topk_doc(doc, content_hash, filters))
        log_debug(f"Inserting {len(records)} documents into TopK collection: {self.collection}")
        self.client.collection(self.collection).upsert(records)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async version of :meth:`insert`.

        Args:
            content_hash: Hash identifying the source content batch.
            documents: Documents to embed and store.
            filters: Optional metadata key/value pairs stored alongside each document.
        """
        if not documents:
            log_debug("No documents to insert, skipping.")
            return
        records = []
        for doc in documents:
            await doc.async_embed(embedder=self.embedder)
            records.append(self._document_to_topk_doc(doc, content_hash, filters))
        log_debug(f"Inserting {len(records)} documents into TopK collection: {self.collection}")
        await self.async_client.collection(self.collection).upsert(records)

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert or update documents. Delegates to :meth:`insert`.

        Args:
            content_hash: Hash identifying the source content batch.
            documents: Documents to embed and store.
            filters: Optional metadata key/value pairs stored alongside each document.
        """
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async version of :meth:`upsert`.

        Args:
            content_hash: Hash identifying the source content batch.
            documents: Documents to embed and store.
            filters: Optional metadata key/value pairs stored alongside each document.
        """
        await self.async_insert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        """Search the collection and return the top matching documents.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.
            filters: Optional metadata filters as a dict of field/value pairs.

        Returns:
            List of matching documents ordered by relevance.
        """
        try:
            embedding = self.embedder.get_embedding(query)
            filter_dict = filters if isinstance(filters, dict) else None
            q = self._search_query(embedding, query, limit, filter_dict)
            records = self.client.collection(self.collection).query(q)
            return [self._topk_doc_to_document(r) for r in records]
        except Exception as e:
            log_error(f"Error searching TopK collection: {e}")
            return []

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        """Async version of :meth:`search`.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.
            filters: Optional metadata filters as a dict of field/value pairs.

        Returns:
            List of matching documents ordered by relevance.
        """
        try:
            embedding = await self.embedder.async_get_embedding(query)
            filter_dict = filters if isinstance(filters, dict) else None
            q = self._search_query(embedding, query, limit, filter_dict)
            records = await self.async_client.collection(self.collection).query(q)
            return [self._topk_doc_to_document(r) for r in records]
        except Exception as e:
            log_error(f"Error searching TopK collection: {e}")
            return []

    def delete(self) -> bool:
        """Drop the entire collection.

        Returns:
            True if the collection was dropped successfully, False otherwise.
        """
        try:
            self.drop()
            return True
        except Exception:
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete a single document by its ID.

        Args:
            id: The document ID to delete.

        Returns:
            True if the document was deleted successfully, False otherwise.
        """
        try:
            self.client.collection(self.collection).delete([id])
            return True
        except Exception as e:
            log_error(f"Error deleting from TopK by id: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete all documents matching the given name.

        Args:
            name: The document name to match.

        Returns:
            True if the deletion succeeded, False otherwise.
        """
        try:
            self.client.collection(self.collection).delete(field("name") == name)
            return True
        except Exception as e:
            log_error(f"Error deleting from TopK by name: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete all documents matching the given metadata filters.

        Args:
            metadata: Key/value pairs that must all match for a document to be deleted.

        Returns:
            True if the deletion succeeded, False otherwise.
        """
        try:
            self.client.collection(self.collection).delete(self._build_filter_expr(metadata))
            return True
        except Exception as e:
            log_error(f"Error deleting by metadata: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete all documents with the given content ID.

        Args:
            content_id: The content ID to match.

        Returns:
            True if the deletion succeeded, False otherwise.
        """
        try:
            self.client.collection(self.collection).delete(field("content_id") == content_id)
            return True
        except Exception as e:
            log_error(f"Error deleting by content_id: {e}")
            return False

    def get_supported_search_types(self) -> List[str]:
        """Return the search types supported by this vector database.

        Returns:
            List containing ``vector``, ``keyword``, and ``hybrid``.
        """
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]


def _strip_unsupported_field_types(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip unsupported field types in TopK from the data.
    Supported field types are: bool, int, float, str, none, list of strings, list of ints, list of floats.

    Args:
        data: The data to strip unsupported field types from.

    Returns:
        The dictionary with unsupported field types stripped.
    """
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if v is None or isinstance(v, (bool, int, float, str)):
            out[k] = v
        elif isinstance(v, list) and v and all(isinstance(i, str) for i in v):
            out[k] = v
        elif isinstance(v, list) and v and all(isinstance(i, (int, float)) for i in v):
            out[k] = v
    return out


def _deserialize_usage(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
