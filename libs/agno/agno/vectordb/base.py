from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agno.exceptions import EmbeddingError
from agno.knowledge.document import Document
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id


def raise_embedding_failures(results: List[Any]) -> None:
    """Re-raise the first real embedding failure among gathered per-document results."""
    first_error: Optional[BaseException] = None

    for i, result in enumerate(results):
        if not isinstance(result, BaseException):
            continue

        if "Event loop is closed" in str(result):
            log_warning(
                f"Event loop closure during embedding for document {i}, but operation may have succeeded: {result}"
            )
            continue

        log_error(f"Error embedding document {i}: {result}")
        if first_error is None:
            first_error = result

    if first_error is not None:
        raise first_error


def embed_before_replace(documents: List[Document], embedder: Any) -> None:
    """Embed ``documents`` in place before an upsert deletes the chunks they replace."""
    if embedder is None:
        return
    for document in documents:
        if document.embedding is None:
            document.embed(embedder=embedder)


async def aembed_before_replace(documents: List[Document], embedder: Any) -> None:
    """Asynchronous twin of ``embed_before_replace``."""
    import asyncio

    if embedder is None:
        return
    pending = [d for d in documents if d.embedding is None]
    if not pending:
        return

    # Use the batch API where the embedder has one, so guarding the delete does not
    # turn one batched call into one call per document.
    if getattr(embedder, "enable_batch", False) is True and hasattr(embedder, "async_get_embeddings_batch_and_usage"):
        embeddings, usages = await embedder.async_get_embeddings_batch_and_usage([d.content for d in pending])
        for index, document in enumerate(pending):
            if index < len(embeddings):
                document.embedding = embeddings[index]
                document.usage = usages[index] if index < len(usages) else None
        return

    results = await asyncio.gather(*[d.async_embed(embedder=embedder) for d in pending], return_exceptions=True)
    raise_embedding_failures(results)


def retrievable_documents(documents: List[Document]) -> List[Document]:
    """Drop documents that carry no embedding, so the rest of the batch can still be written.

    A vector store rejects an empty vector outright ("vector must have at least 1
    dimension"), which fails the whole write and discards the chunks that did embed.
    Skipping the unembedded ones lets the good chunks land; ingestion counts the
    shortfall and reports it as PARTIAL.
    """
    keep, dropped = [], 0
    for document in documents:
        if document.embedding is None or len(document.embedding) == 0:
            dropped += 1
            continue
        keep.append(document)
    if dropped:
        log_warning(f"Skipping {dropped} of {len(documents)} chunks with no embedding; they are not retrievable")
    return keep


def is_rate_limit_error(error: BaseException) -> bool:
    """Whether ``error`` is a provider throttle, which must not fall back to per-item calls."""
    if isinstance(error, EmbeddingError):
        # The embedder already classified this; prefer that over matching text.
        return error.reason == "rate_limit"
    error_str = str(error).lower()
    return any(
        phrase in error_str for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
    )


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

    # user_id is the owner of the chunks, mapped by each backend to its native primitive.
    # None widens a search, writes the shared bucket, and deletes across every owner.

    @abstractmethod
    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check whether the given content hash was already ingested for an owner.

        Must match exactly the rows a delete of the same content hash under the same user_id
        would clear, never more.

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
            user_id (Optional[str]): The owner of the chunks. None writes the shared bucket
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
            user_id (Optional[str]): Scope the delete to that owner's chunks; shared chunks
                survive. None deletes across every owner

        Returns:
            bool: True if chunks were deleted, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def get_supported_search_types(self) -> List[str]:
        raise NotImplementedError
