"""ManagedKnowledgeBackend — protocol for backends that manage their own indexing.

Backends implementing this protocol handle ingestion (file/text), search, and
deletion internally, bypassing Agno's default chunk-embed-store pipeline.
LightRAG is the canonical example: it runs its own graph-based indexing server
and exposes HTTP endpoints for upload, query, and delete.

Detection is automatic via ``isinstance(vector_db, ManagedKnowledgeBackend)``.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from agno.knowledge.document import Document


@runtime_checkable
class ManagedKnowledgeBackend(Protocol):
    """Protocol for knowledge backends that manage their own indexing pipeline.

    Any VectorDb subclass that implements these methods will automatically be
    detected as a managed backend. No registration or configuration needed.
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
    ) -> Optional[str]:
        """Ingest a file from raw bytes. Returns an external document ID."""
        ...

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
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
    ) -> Optional[str]:
        """Ingest plain text. Returns an external document ID."""
        ...

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
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
        """Search the backend. Returns matching documents."""
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
