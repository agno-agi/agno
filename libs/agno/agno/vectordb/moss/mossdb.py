import asyncio
import os
from typing import Any, Dict, List, Optional

try:
    from moss import DocumentInfo, MossClient  # type: ignore

    moss_available = True
except ImportError:
    moss_available = False

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb


class MossVectorDb(VectorDb):
    """
    VectorDb implementation backed by Moss.

    Moss manages embeddings internally, so no external embedder is needed.
    Call create() once at startup to create and load the index; subsequent
    search() calls hit Moss's in-memory runtime for sub-10ms latency.

    Args:
        index_name (str): Name of the Moss index (equivalent to a collection).
        project_id (Optional[str]): Moss project ID. Falls back to MOSS_PROJECT_ID env var.
        project_key (Optional[str]): Moss project key. Falls back to MOSS_PROJECT_KEY env var.
        embedding_model (str): Moss embedding model ('moss-minilm' or 'moss-mediumlm').
        alpha (float): Hybrid search weight — 1.0 = pure semantic, 0.0 = pure keyword. Defaults to 0.8.
        auto_refresh (bool): Auto-refresh the loaded index when new docs are added. Defaults to False.
        polling_interval_in_seconds (int): Interval for auto-refresh in seconds. Defaults to 600.
    """

    def __init__(
        self,
        index_name: str,
        project_id: Optional[str] = None,
        project_key: Optional[str] = None,
        embedding_model: str = "moss-minilm", 
        alpha: float = 0.8,
        auto_refresh: bool = False,
        polling_interval_in_seconds: int = 600,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
    ):
        if not moss_available:
            raise ImportError(
                "`moss` not installed. Please install using `pip install moss`."
            )

        self.index_name = index_name
        self.embedding_model = embedding_model
        self.alpha = alpha
        self.auto_refresh = auto_refresh
        self.polling_interval_in_seconds = polling_interval_in_seconds

        self.project_id: str = project_id or os.getenv("MOSS_PROJECT_ID") or ""
        self.project_key: str = project_key or os.getenv("MOSS_PROJECT_KEY") or ""

        if not self.project_id or not self.project_key:
            raise ValueError(
                "Moss credentials required. Provide project_id and project_key "
                "or set MOSS_PROJECT_ID and MOSS_PROJECT_KEY environment variables."
            )

        self.client: MossClient = MossClient(self.project_id, self.project_key)
        self._index_loaded: bool = False

        super().__init__(id=id, name=name or index_name, description=description)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_moss_doc(self, document: Document, content_hash: Optional[str] = None) -> DocumentInfo:
        meta: Dict[str, str] = {str(k): str(v) for k, v in (document.meta_data or {}).items()}
        if content_hash:
            meta["content_hash"] = content_hash
        if document.content_id:
            meta["content_id"] = document.content_id
        if document.name:
            meta["name"] = document.name
        return DocumentInfo(
            id=document.id or document.content_id,
            text=document.content,
            metadata=meta,
        )

    def _to_document(self, result: Any) -> Document:
        meta = dict(result.metadata) if result.metadata else {}
        return Document(
            id=result.id,
            content=result.text,
            meta_data=meta,
            name=meta.get("name"),
            content_id=meta.get("content_id"),
        )

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)


    def create(self) -> None:
        """Load the index into memory if it already exists. Index is created on first upsert."""
        if self.exists():
            self._run(self._load_index())

    async def async_create(self) -> None:
        if await self.async_exists():
            await self._load_index()

    async def _load_index(self) -> None:
        if not self._index_loaded:
            log_debug(f"Loading Moss index '{self.index_name}' into memory")
            await self.client.load_index(
                self.index_name,
                auto_refresh=self.auto_refresh,
                polling_interval_in_seconds=self.polling_interval_in_seconds,
            )
            self._index_loaded = True

    def drop(self) -> None:
        """Delete the Moss index."""
        try:
            self._run(self.client.delete_index(self.index_name))
            self._index_loaded = False
            log_info(f"Deleted Moss index '{self.index_name}'")
        except Exception as e:
            log_error(f"Error deleting Moss index '{self.index_name}': {e}")

    async def async_drop(self) -> None:
        try:
            await self.client.delete_index(self.index_name)
            self._index_loaded = False
            log_info(f"Deleted Moss index '{self.index_name}'")
        except Exception as e:
            log_error(f"Error deleting Moss index '{self.index_name}': {e}")

    # ------------------------------------------------------------------
    # Existence checks
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            indexes = self._run(self.client.list_indexes())
            return any(idx.name == self.index_name for idx in indexes)
        except Exception:
            return False

    async def async_exists(self) -> bool:
        try:
            indexes = await self.client.list_indexes()
            return any(idx.name == self.index_name for idx in indexes)
        except Exception:
            return False

    def name_exists(self, name: str) -> bool:
        return name == self.index_name and self.exists()

    async def async_name_exists(self, name: str) -> bool:
        return name == self.index_name and await self.async_exists()

    def id_exists(self, id: str) -> bool:
        try:
            docs = self._run(self.client.get_docs(self.index_name, doc_ids=[id]))
            return bool(docs)
        except Exception:
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if any document with this content_hash exists in the index."""
        try:
            from moss import QueryOptions  # type: ignore

            results = self._run(
                self.client.query(
                    self.index_name,
                    "_",
                    options=QueryOptions(
                        top_k=1,
                        filter={"field": "content_hash", "condition": {"$eq": content_hash}},
                    ),
                )
            )
            return bool(results and results.docs)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Insert / Upsert
    # ------------------------------------------------------------------

    def upsert_available(self) -> bool:
        return True

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self.upsert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await self.async_upsert(content_hash=content_hash, documents=documents, filters=filters)

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        moss_docs = [self._to_moss_doc(doc, content_hash) for doc in documents]
        if not moss_docs:
            return
        try:
            from moss import MutationOptions  # type: ignore

            async def _upsert() -> None:
                if not await self.async_exists():
                    log_info(f"Creating Moss index '{self.index_name}' with model '{self.embedding_model}'")
                    await self.client.create_index(self.index_name, moss_docs, self.embedding_model)
                    self._index_loaded = False
                else:
                    await self.client.add_docs(self.index_name, moss_docs, options=MutationOptions(upsert=True))
                await self._load_index()

            self._run(_upsert())
            log_info(f"Upserted {len(moss_docs)} documents into Moss index '{self.index_name}'")
        except Exception as e:
            log_error(f"Error upserting documents into Moss: {e}")

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        moss_docs = [self._to_moss_doc(doc, content_hash) for doc in documents]
        if not moss_docs:
            return
        try:
            from moss import MutationOptions  # type: ignore

            if not await self.async_exists():
                log_info(f"Creating Moss index '{self.index_name}' with model '{self.embedding_model}'")
                await self.client.create_index(self.index_name, moss_docs, self.embedding_model)
                self._index_loaded = False
            else:
                await self.client.add_docs(self.index_name, moss_docs, options=MutationOptions(upsert=True))
            await self._load_index()
            log_info(f"Upserted {len(moss_docs)} documents into Moss index '{self.index_name}'")
        except Exception as e:
            log_error(f"Error upserting documents into Moss: {e}")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        try:
            from moss import QueryOptions  # type: ignore

            options = QueryOptions(top_k=limit, alpha=self.alpha, filter=filters)
            results = self._run(self.client.query(self.index_name, query, options=options))
            if not results or not results.docs:
                return []
            docs = [self._to_document(r) for r in results.docs]
            log_debug(f"Moss search returned {len(docs)} results for '{query}'")
            return docs
        except Exception as e:
            log_error(f"Error searching Moss index '{self.index_name}': {e}")
            return []

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        try:
            from moss import QueryOptions  # type: ignore

            options = QueryOptions(top_k=limit, alpha=self.alpha, filter=filters)
            results = await self.client.query(self.index_name, query, options=options)
            if not results or not results.docs:
                return []
            docs = [self._to_document(r) for r in results.docs]
            log_debug(f"Moss async_search returned {len(docs)} results for '{query}'")
            return docs
        except Exception as e:
            log_error(f"Error searching Moss index '{self.index_name}': {e}")
            return []

        

    def delete(self) -> bool:
        try:
            self._run(self.client.delete_index(self.index_name))
            self._index_loaded = False
            return True
        except Exception as e:
            log_error(f"Error deleting Moss index: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        try:
            self._run(self.client.delete_docs(self.index_name, [id]))
            return True
        except Exception as e:
            log_error(f"Error deleting document '{id}' from Moss: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        log_warning("delete_by_name is not supported by MossVectorDb.")
        return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        log_warning("delete_by_metadata is not supported by MossVectorDb.")
        return False

    def delete_by_content_id(self, content_id: str) -> bool:
        log_warning("delete_by_content_id is not supported by MossVectorDb.")
        return False

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def optimize(self) -> None:
        pass

    def get_supported_search_types(self) -> List[str]:
        return ["vector", "keyword", "hybrid"]
