from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_warning
from agno.utils.string import generate_id


class VectorDb(ABC):
    """Base class for Vector Databases"""

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ):
        """Initialize base VectorDb.

        Args:
            id: Optional custom ID. If not provided, an id will be generated.
            name: Optional name for the vector database.
            description: Optional description for the vector database.
            similarity_threshold: Minimum similarity (0.0-1.0) to filter results.
        """
        if similarity_threshold is not None and not (0.0 <= similarity_threshold <= 1.0):
            raise ValueError("similarity_threshold must be between 0.0 and 1.0")

        if name is None:
            name = self.__class__.__name__

        self.name = name
        self.description = description
        self.similarity_threshold = similarity_threshold
        # Last resort fallback to generate id from name if ID not specified
        self.id = id if id else generate_id(name)

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def name_exists(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def id_exists(self, id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def content_hash_exists(self, content_hash: str) -> bool:
        raise NotImplementedError

    # ---- ``user_id`` semantics for per-user RAG isolation ----
    #
    # ``user_id`` is a first-class parameter on every insert / upsert /
    # search method below. It identifies the OWNER of the chunks. Backends
    # translate it into their native primitive: pgvector writes a column,
    # Chroma routes to a per-user collection, Pinecone uses a namespace,
    # etc.
    #
    # ``None`` means "shared / org-wide / unscoped" — chunks become
    # visible to every caller, and searches with ``user_id=None`` see
    # everything (admin / RBAC-off view).
    #
    # Backends that don't yet implement isolation must still accept the
    # parameter (no-op) so the Knowledge wrapper can pass it uniformly.
    # When you wire up a new backend, write a smoke test that proves the
    # native primitive actually isolates (alice's search doesn't surface
    # bob's chunks) before claiming support.

    @abstractmethod
    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    def upsert_available(self) -> bool:
        return False

    @abstractmethod
    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Any] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Any] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    def drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def async_exists(self) -> bool:
        raise NotImplementedError

    def optimize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_id(self, id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_name(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Default implementation logs a warning. Subclasses should override this method
        to provide their specific implementation.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        log_warning(
            f"{self.__class__.__name__}.update_metadata() is not implemented. "
            f"Metadata update for content_id '{content_id}' was skipped."
        )

    @abstractmethod
    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """Delete all chunks with the given ``content_id``.

        ``user_id`` scopes the delete to the owner's bucket — preventing
        cross-user delete races where one caller could wipe another's
        chunks by guessing their content_id. ``None`` deletes across all
        owners (legacy behaviour; safe only for unscoped deployments).
        Backends that don't yet implement per-user isolation accept the
        parameter as a no-op for forward-compatibility.
        """
        raise NotImplementedError

    @abstractmethod
    def get_supported_search_types(self) -> List[str]:
        raise NotImplementedError
