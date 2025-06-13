from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from agno.document import Document
from agno.document.document_store import DocumentStore
from agno.utils.log import log_info


class VectorStore(BaseModel):
    """
    Base class for vector store.
    """

    name: str


class KnowledgeBase(BaseModel):
    """
    Base class for omni knowledge base.
    """

    name: str
    description: Optional[str] = None
    document_store: Optional[DocumentStore] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def search(self):
        pass

    async def async_search(self):
        pass

    def load(self):
        log_info("Loading documents from knowledge base")
        pass

    def add_document(self, document: Document):
        """Add a single document to the document store"""
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.add_document(document)

    def add_documents(self, documents: List[Document]):
        """Add multiple documents to the document store"""
        if self.document_store is None:
            raise ValueError("No document store provided")
        for document in documents:
            self.document_store.add_document(document)

    def get_document_by_id(self, document_id: str):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.get_document_by_id(document_id)

    def get_all_documents(self):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.get_all_documents()

    def delete_document(self, document_id: str):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.delete_document(document_id)

    def delete_all_documents(self):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.delete_all_documents()
