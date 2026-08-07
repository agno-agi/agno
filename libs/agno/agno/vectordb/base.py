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

    # user_id identifies the OWNER of the chunks. Backends translate it into their
    # native primitive: pgvector writes a column, Chroma routes to a per-user
    # collection, Pinecone uses a namespace. What None means is per operation, not per
    # class: a search widens to every owner, a write lands in the shared bucket, a
    # delete narrows. Backends that don't yet implement isolation must still accept the
    # parameter as a no-op so the Knowledge wrapper can pass it uniformly.

    @abstractmethod
    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check whether the given content hash was already ingested for an owner.

        This is the guard half of the dedup pair: a True is followed by a delete of the
        same content hash under the same user_id, so the guard must match exactly the
        rows that delete would clear - never more. A guard that matched every owner
        would let one caller's private copy report "already exists" for a shared
        publish, skip the write, and leave the shared bucket empty.

        Args:
            content_hash (str): The content hash to look for
            user_id (Optional[str]): The owner to check. None checks the shared bucket

        Returns:
            bool: True if that owner already holds the content hash
        """
        raise NotImplementedError

    @abstractmethod
    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert the given documents.

        Args:
            content_hash (str): The content hash the documents were chunked from
            documents (List[Document]): The documents to insert
            filters (Optional[Dict[str, Any]]): Metadata to stamp on every chunk
            user_id (Optional[str]): The owner of the chunks. None writes the shared
                bucket, which every scoped reader can see
        """
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
        """Delete all chunks with the given content ID.

        Args:
            content_id (str): The content ID to delete
            user_id (Optional[str]): Scope the delete to that owner's chunks alone -
                shared chunks survive, and one caller cannot wipe another's by guessing
                their content_id. None is the admin view and deletes across every owner

        Returns:
            bool: True if chunks were deleted, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def get_supported_search_types(self) -> List[str]:
        raise NotImplementedError
