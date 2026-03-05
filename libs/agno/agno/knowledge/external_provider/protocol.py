"""ExternalKnowledgeProvider — protocol for external providers that manage their own indexing.

Providers implementing this protocol handle ingestion (file/text), search,
deletion, and status polling internally, bypassing Agno's default chunk-embed-store
pipeline. LightRAG is the canonical example: it runs its own graph-based indexing
server and exposes HTTP endpoints for upload, query, and delete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

from agno.knowledge.document import Document

if TYPE_CHECKING:
    from agno.knowledge.external_provider.schemas import ProcessingResult


@runtime_checkable
class ExternalKnowledgeProvider(Protocol):
    """Protocol for external knowledge providers that manage their own indexing pipeline.

    Any class that implements these methods can be passed to
    ``Knowledge(external_provider=...)``.
    """

    # ------------------------------------------------------------------
    # Ingestion — file bytes
    # ------------------------------------------------------------------

    def ingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Ingest a file from raw bytes. Returns a ProcessingResult."""
        ...

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Async variant of ingest_file."""
        ...

    # ------------------------------------------------------------------
    # Ingestion — plain text
    # ------------------------------------------------------------------

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Ingest plain text. Returns a ProcessingResult."""
        ...

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Async variant of ingest_text."""
        ...

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Search the provider. Returns matching documents."""
        ...

    async def aquery(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Async variant of query."""
        ...

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_content(
        self,
        external_id: str,
    ) -> bool:
        """Delete a document by its external ID. Returns True on success."""
        ...

    async def adelete_content(
        self,
        external_id: str,
    ) -> bool:
        """Async variant of delete_content."""
        ...

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    def get_status(
        self,
        processing_id: str,
    ) -> ProcessingResult:
        """Get the processing status of a document by its processing ID."""
        ...

    async def aget_status(
        self,
        processing_id: str,
    ) -> ProcessingResult:
        """Async variant of get_status."""
        ...
