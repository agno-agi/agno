from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel

from agno.document.base import Document


class DocumentStore(BaseModel, ABC):
    """
    Base class for document store.
    """

    name: str
    description: str

    @abstractmethod
    def add_document(self, document: Document) -> str:
        """Add a document to the store. Returns the document ID."""
        pass

    @abstractmethod
    def delete_document(self, document_id: str) -> bool:
        """Delete a document by ID. Returns True if successful."""
        pass

    @abstractmethod
    def delete_all_documents(self) -> bool:
        """Delete all documents from the store. Returns True if successful."""
        pass

    @abstractmethod
    def get_all_documents(self) -> List[Document]:
        """Get all documents from the store."""
        pass

    @abstractmethod
    def get_document_by_id(self, document_id: str) -> Optional[Document]:
        """Get a document by its ID."""
        pass

    @abstractmethod
    def get_document_by_name(self, name: str) -> Optional[Document]:
        """Get a document by its name."""
        pass

    @abstractmethod
    def enhance_document(self, document_id: str, **kwargs) -> bool:
        """Enhance a document with additional metadata or processing. Returns True if successful."""
        pass
