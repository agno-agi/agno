from abc import ABC, abstractmethod
from typing import List, Optional

from agno.document.base import Document
from agno.knowledge.content import Content


class Store(ABC):
    """
    Base class for document store.
    """

    name: str
    description: str
    read_from_store: Optional[bool] = False
    copy_to_store: Optional[bool] = False

    @abstractmethod
    def add_content(self, id: str, content: Content) -> str:
        """Add content to the store. Returns the content ID."""
        pass

    @abstractmethod
    def delete_content(self, content_id: str) -> bool:
        """Delete content by ID. Returns True if successful."""
        pass

    @abstractmethod
    def delete_all_content(self) -> bool:
        """Delete all contents from the store. Returns True if successful."""
        pass

    @abstractmethod
    def get_all_content(self) -> List[Content]:
        """Get all content entries from the store."""
        pass

    @abstractmethod
    def get_content_by_id(self, content_id: str) -> Optional[Content]:
        """Get a content by ID."""
        pass

    @abstractmethod
    def get_content_by_name(self, name: str) -> Optional[Content]:
        """Get a content entry by its name."""
        pass

    @abstractmethod
    def enhance_content(self, content_id: str, **kwargs) -> bool:
        """Enhance content with additional metadata or processing. Returns True if successful."""
        pass
