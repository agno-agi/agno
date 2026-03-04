"""LightRAG VectorDb — backwards-compatible wrapper.

This class extends VectorDb and delegates managed-backend operations to
``LightRagBackend``. Because the protocol methods are present on this class,
``isinstance(LightRag(), ManagedKnowledgeBackend)`` returns True automatically.
"""

import asyncio
from typing import Any, Dict, List, Optional, Union

import httpx

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.managed_backend.lightrag import LightRagBackend
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb

DEFAULT_SERVER_URL = "http://localhost:9621"


class LightRag(VectorDb):
    """LightRAG VectorDB implementation.

    Delegates all managed-backend operations to an internal ``LightRagBackend``
    instance. This satisfies the ``ManagedKnowledgeBackend`` protocol so that
    Knowledge auto-detects this as a managed backend.
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        api_key: Optional[str] = None,
        auth_header_name: str = "X-API-KEY",
        auth_header_format: str = "{api_key}",
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.server_url = server_url
        self.api_key = api_key
        super().__init__(name=name, description=description)

        self.auth_header_name = auth_header_name
        self.auth_header_format = auth_header_format

        # Internal backend handles all HTTP communication
        self._backend = LightRagBackend(
            server_url=server_url,
            api_key=api_key,
            auth_header_name=auth_header_name,
            auth_header_format=auth_header_format,
        )

    # ------------------------------------------------------------------
    # Header helpers (kept for any direct usage)
    # ------------------------------------------------------------------

    def _get_headers(self) -> Dict[str, str]:
        return self._backend._get_headers()

    def _get_auth_headers(self) -> Dict[str, str]:
        return self._backend._get_auth_headers()

    # ------------------------------------------------------------------
    # VectorDb overrides (no-ops for LightRAG)
    # ------------------------------------------------------------------

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        pass

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> None:
        pass

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        pass

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        return self._backend.query(query=query, limit=limit)

    async def async_search(
        self, query: str, limit: Optional[int] = None, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> Optional[List[Document]]:
        return await self._backend.aquery(query=query, limit=limit or 10)

    def drop(self) -> None:
        asyncio.run(self.async_drop())

    async def async_drop(self) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.delete(f"{self.server_url}/documents", headers=self._get_headers())
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{self.server_url}/documents/clear_cache",
                json={"modes": ["default", "naive"]},
                headers=self._get_headers(),
            )

    def exists(self) -> bool:
        return False

    async def async_exists(self) -> bool:
        return False

    def delete(self) -> bool:
        return False

    def delete_by_id(self, id: str) -> bool:
        return False

    def delete_by_name(self, name: str) -> bool:
        return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return False

    # ------------------------------------------------------------------
    # Legacy methods (kept for backwards compat, delegate to backend)
    # ------------------------------------------------------------------

    def delete_by_external_id(self, external_id: str) -> bool:
        return self._backend.delete_content(external_id)

    async def async_delete_by_external_id(self, external_id: str) -> bool:
        return await self._backend.adelete_content(external_id)

    async def _insert_text(self, text: str) -> Dict[str, Any]:
        """Legacy: insert text without tracking. Kept for backwards compat."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/text",
                json={"text": text},
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()
            log_debug(f"Text insertion result: {result}")
            return result

    async def insert_file_bytes(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        send_metadata: bool = False,
        skip_if_exists: bool = False,
    ) -> Optional[str]:
        """Legacy: delegate to backend."""
        return await self._backend.aingest_file(
            file_content=file_content,
            filename=filename,
            content_type=content_type,
        )

    async def insert_text(self, file_source: str, text: str) -> Optional[str]:
        """Legacy: delegate to backend."""
        return await self._backend.aingest_text(text=text, source_name=file_source)

    async def _get_document_id(self, track_id: str) -> Optional[str]:
        """Legacy: delegate to backend."""
        return await self._backend._get_document_id(track_id)

    async def lightrag_knowledge_retriever(self, query: str) -> Optional[List[Document]]:
        """Custom knowledge retriever function for LightRAG server."""
        try:
            return await self._backend.aquery(query=query)
        except Exception as e:
            log_error(f"Unexpected error during LightRAG server search: {type(e).__name__}: {str(e)}")
            return None

    def _format_lightrag_response(self, result: Any, query: str, mode: str) -> List[Document]:
        """Legacy: delegate to backend."""
        return self._backend._format_response(result, query, mode)

    # ------------------------------------------------------------------
    # ManagedKnowledgeBackend protocol methods
    # ------------------------------------------------------------------

    def ingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return self._backend.ingest_file(
            file_content=file_content, filename=filename, content_type=content_type, metadata=metadata
        )

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return await self._backend.aingest_file(
            file_content=file_content, filename=filename, content_type=content_type, metadata=metadata
        )

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return self._backend.ingest_text(text=text, source_name=source_name, metadata=metadata)

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return await self._backend.aingest_text(text=text, source_name=source_name, metadata=metadata)

    def query(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        return self._backend.query(query=query, limit=limit, mode=mode, filters=filters)

    async def aquery(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        return await self._backend.aquery(query=query, limit=limit, mode=mode, filters=filters)

    def delete_content(self, external_id: str) -> bool:
        return self._backend.delete_content(external_id)

    async def adelete_content(self, external_id: str) -> bool:
        return await self._backend.adelete_content(external_id)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        raise NotImplementedError("update_metadata not supported for LightRag - use LightRag's native methods")

    def get_supported_search_types(self) -> List[str]:
        return []
