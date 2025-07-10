from abc import ABC, abstractmethod
from typing import List, Optional

from agno.document.base import Document
from agno.knowledge.source import Source


class Store(ABC):
    """
    Base class for document store.
    """

    name: str
    description: str
    read_from_store: Optional[bool] = False
    copy_to_store: Optional[bool] = False

    @abstractmethod
    def add_source(self, id: str, source: Source) -> str:
        """Add a document to the store. Returns the document ID."""
        pass

    @abstractmethod
    def delete_source(self, source_id: str) -> bool:
        """Delete a document by ID. Returns True if successful."""
        pass

    @abstractmethod
    def delete_all_sources(self) -> bool:
        """Delete all documents from the store. Returns True if successful."""
        pass

    @abstractmethod
    def get_all_sources(self) -> List[Source]:
        """Get all documents from the store."""
        pass

    @abstractmethod
    def get_source_by_id(self, source_id: str) -> Optional[Source]:
        """Get a document by its ID."""
        pass

    @abstractmethod
    def get_source_by_name(self, name: str) -> Optional[Source]:
        """Get a document by its name."""
        pass

    @abstractmethod
    def enhance_source(self, source_id: str, **kwargs) -> bool:
        """Enhance a document with additional metadata or processing. Returns True if successful."""
        pass
