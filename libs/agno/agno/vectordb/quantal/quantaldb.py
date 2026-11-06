import asyncio
import json
import os
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    import numpy as np
    from quantal import Index
except ImportError:
    raise ImportError("The `quantaldb` package is not installed. Please install it via `pip install quantaldb`.")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, log_warning, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class QuantalDb(VectorDb):
    """
    QuantalDb class for managing vector operations with quantal.

    quantal is an embedded vector index: it runs in-process (no server) and
    combines graph routing with quantized storage, so search stays sub-linear
    as the knowledge base grows while using a fraction of the memory of a
    full-precision index. Vectors are stored normalized and scored by inner
    product, i.e. cosine similarity. Deletes are O(1) tombstones.

    The index is persisted to `<path>/<collection>.tq` with document
    contents and metadata in a JSON file alongside it.

    Args:
        collection: The name of the collection. If not provided, derived from 'name'.
        name: Name of the vector database. Also used as collection name if 'collection' is not provided.
        description: Description of the vector database.
        id: Unique identifier for this vector database instance.
        embedder: The embedder to use when embedding the document contents.
        path: The directory where the index and metadata are stored.
        reranker: The reranker to use when reranking documents.
    """

    def __init__(
        self,
        collection: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        path: str = "tmp/quantal",
        reranker: Optional[Reranker] = None,
        similarity_threshold: Optional[float] = None,
    ):
        if collection is None:
            if name is not None:
                collection = name.lower().replace(" ", "_")
            else:
                raise ValueError("Either 'collection' or 'name' must be provided.")

        if id is None:
            from agno.utils.string import generate_id

            id = generate_id(f"{path}#{collection}")

        super().__init__(id=id, name=name, description=description, similarity_threshold=similarity_threshold)

        self.collection_name: str = collection
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.path: str = path
        self.reranker: Optional[Reranker] = reranker

        self._index: Optional[Index] = None
        # doc id -> {"content", "name", "content_id", "meta_data"}
        self._docstore: Dict[str, Dict[str, Any]] = {}
        self._id_map: Dict[str, int] = {}  # doc id -> internal id
        self._rev_map: Dict[int, str] = {}  # internal id -> doc id
        self._next_id: int = 0

    # --- persistence ---

    def _index_path(self) -> str:
        return os.path.join(self.path, f"{self.collection_name}.tq")

    def _meta_path(self) -> str:
        return os.path.join(self.path, f"{self.collection_name}.json")

    def _save(self) -> None:
        if self._index is None:
            return
        os.makedirs(self.path, exist_ok=True)
        self._index.save(self._index_path())
        meta = {"docstore": self._docstore, "id_map": self._id_map, "next_id": self._next_id}
        with open(self._meta_path(), "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def _load(self) -> bool:
        if not (os.path.exists(self._index_path()) and os.path.exists(self._meta_path())):
            return False
        try:
            self._index = Index.load(self._index_path())
            with open(self._meta_path(), "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._docstore = meta.get("docstore", {})
            self._id_map = {k: int(v) for k, v in meta.get("id_map", {}).items()}
            self._rev_map = {v: k for k, v in self._id_map.items()}
            self._next_id = int(meta.get("next_id", 0))
            log_debug(f"Loaded quantal index from {self._index_path()} with {len(self._index)} vectors")
            return True
        except Exception:
            logger.exception(f"Error loading quantal index from {self._index_path()}")
            return False

    # --- helpers ---

    def _normalize(self, vectors: Any) -> "np.ndarray":
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-30)

    def _matches(self, meta_data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        for key, value in filters.items():
            if key not in meta_data:
                return False
            if isinstance(value, list):
                if meta_data[key] not in value:
                    return False
            elif meta_data[key] != value:
                return False
        return True

    def _prepare(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]]) -> List[tuple]:
        """Build (doc_id, content, meta_data, name, content_id, embedding) rows
        for embedded documents, mirroring the id scheme other backends use."""
        rows = []
        id_counts: Dict[str, int] = {}
        for document in documents:
            if document.embedding is None:
                continue
            cleaned_content = document.content.replace("\x00", "�")
            base_id = document.id or md5(cleaned_content.encode()).hexdigest()
            doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
            if doc_id in id_counts:
                id_counts[doc_id] += 1
                doc_id = md5(f"{doc_id}_{id_counts[doc_id]}".encode()).hexdigest()
            else:
                id_counts[doc_id] = 0

            meta_data = dict(document.meta_data or {})
            if filters:
                meta_data.update(filters)
            meta_data["content_hash"] = content_hash

            rows.append((doc_id, cleaned_content, meta_data, document.name, document.content_id, document.embedding))
        return rows

    def _store(self, rows: List[tuple]) -> None:
        if self._index is None:
            self.create()
        if not rows:
            return
        internal_ids = np.arange(self._next_id, self._next_id + len(rows), dtype=np.uint64)
        embeddings = self._normalize([row[5] for row in rows])
        self._index.add(embeddings, ids=internal_ids)  # type: ignore[union-attr]
        for internal_id, (doc_id, content, meta_data, name, content_id, _) in zip(internal_ids, rows):
            self._docstore[doc_id] = {
                "content": content,
                "meta_data": meta_data,
                "name": name,
                "content_id": content_id,
            }
            self._id_map[doc_id] = int(internal_id)
            self._rev_map[int(internal_id)] = doc_id
        self._next_id += len(rows)
        self._save()

    def _delete_doc_ids(self, doc_ids: List[str]) -> int:
        deleted = 0
        for doc_id in doc_ids:
            internal_id = self._id_map.pop(doc_id, None)
            if internal_id is None:
                continue
            self._index.remove(internal_id)  # type: ignore[union-attr]
            self._rev_map.pop(internal_id, None)
            self._docstore.pop(doc_id, None)
            deleted += 1
        if deleted:
            self._save()
        return deleted

    def _to_document(self, doc_id: str, score: Optional[float] = None) -> Document:
        entry = self._docstore[doc_id]
        meta_data = dict(entry["meta_data"])
        if score is not None:
            meta_data["score"] = score
        return Document(
            id=doc_id,
            content=entry["content"],
            name=entry["name"],
            content_id=entry["content_id"],
            meta_data=meta_data,
        )

    # --- VectorDb interface ---

    def create(self) -> None:
        if self._load():
            return
        log_debug(f"Creating quantal collection: {self.collection_name}")
        dim = self.embedder.dimensions
        if not dim:
            raise ValueError("The embedder must define `dimensions` to size the quantal index.")
        self._index = Index(dim=dim)
        self._save()

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    def exists(self) -> bool:
        return self._index is not None or os.path.exists(self._index_path())

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def name_exists(self, name: str) -> bool:
        return any(entry["name"] == name for entry in self._docstore.values())

    async def async_name_exists(self, name: str) -> bool:
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        return id in self._docstore

    def content_hash_exists(self, content_hash: str) -> bool:
        return any(entry["meta_data"].get("content_hash") == content_hash for entry in self._docstore.values())

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_info(f"Inserting {len(documents)} documents")
        for document in documents:
            document.embed(embedder=self.embedder)
        self._store(self._prepare(content_hash, documents, filters))

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        log_info(f"Async inserting {len(documents)} documents")
        await asyncio.gather(
            *[document.async_embed(embedder=self.embedder) for document in documents], return_exceptions=True
        )
        await asyncio.to_thread(self._store, self._prepare(content_hash, documents, filters))

    def upsert_available(self) -> bool:
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_doc_ids(
                [
                    doc_id
                    for doc_id, entry in self._docstore.items()
                    if entry["meta_data"].get("content_hash") == content_hash
                ]
            )
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await asyncio.to_thread(self.upsert, content_hash, documents, filters)

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """Vector search. With metadata filters, scoring is restricted to the
        matching documents up front (the index supports allowlist search)
        rather than over-fetching and post-filtering."""
        if isinstance(filters, list):
            log_warning("Filter expressions are not yet supported in QuantalDb. No filters will be applied.")
            filters = None

        if self._index is None and not self._load():
            log_warning("Collection does not exist")
            return []
        if not self._docstore:
            return []

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []
        query_vector = self._normalize(query_embedding)

        if filters:
            allowlist = [
                self._id_map[doc_id]
                for doc_id, entry in self._docstore.items()
                if doc_id in self._id_map and self._matches(entry["meta_data"], filters)
            ]
            if not allowlist:
                return []
            hits = self._index.search_filtered(query_vector, allowlist, k=limit)  # type: ignore[union-attr]
        else:
            hits = self._index.search(query_vector, k=limit)  # type: ignore[union-attr]

        results = []
        for internal_id, score in hits:
            if self.similarity_threshold is not None and score < self.similarity_threshold:
                continue
            doc_id = self._rev_map.get(int(internal_id))
            if doc_id is None or doc_id not in self._docstore:
                continue
            results.append(self._to_document(doc_id, score=float(score)))

        if self.reranker and results:
            try:
                results = self.reranker.rerank(query=query, documents=results)
            except Exception as e:
                log_warning(f"Reranker failed, returning unranked results: {str(e)}")

        log_info(f"Found {len(results)} documents")
        return results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        log_debug(f"Dropping quantal collection: {self.collection_name}")
        for file_path in (self._index_path(), self._meta_path()):
            if os.path.exists(file_path):
                os.remove(file_path)
        if self._index is not None:
            self._index.close()
        self._index = None
        self._docstore = {}
        self._id_map = {}
        self._rev_map = {}
        self._next_id = 0

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def delete(self) -> bool:
        try:
            self.drop()
            return True
        except Exception:
            logger.exception("Error clearing collection")
            return False

    def delete_by_id(self, id: str) -> bool:
        if id not in self._docstore:
            log_info(f"Document with ID '{id}' not found")
            return False
        return self._delete_doc_ids([id]) > 0

    def delete_by_name(self, name: str) -> bool:
        doc_ids = [doc_id for doc_id, entry in self._docstore.items() if entry["name"] == name]
        if not doc_ids:
            log_info(f"No documents found with name '{name}'")
            return False
        return self._delete_doc_ids(doc_ids) > 0

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        doc_ids = [doc_id for doc_id, entry in self._docstore.items() if self._matches(entry["meta_data"], metadata)]
        if not doc_ids:
            log_info(f"No documents found with metadata '{metadata}'")
            return False
        return self._delete_doc_ids(doc_ids) > 0

    def delete_by_content_id(self, content_id: str) -> bool:
        doc_ids = [doc_id for doc_id, entry in self._docstore.items() if entry["content_id"] == content_id]
        if not doc_ids:
            log_info(f"No documents found with content_id '{content_id}'")
            return False
        return self._delete_doc_ids(doc_ids) > 0

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        updated = 0
        for entry in self._docstore.values():
            if entry["content_id"] == content_id:
                entry["meta_data"].update(metadata)
                updated += 1
        if updated:
            self._save()
        else:
            log_info(f"No documents found with content_id '{content_id}'")

    def get_count(self) -> int:
        return len(self._docstore)

    def get_supported_search_types(self) -> List[str]:
        return [SearchType.vector]
