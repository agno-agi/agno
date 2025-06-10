from dataclasses import dataclass
from agno.document.document_store import DocumentStore
from typing import Optional, List
from agno.document import Document
from agno.utils.log import log_info
from urllib.parse import urlparse
import os
from pathlib import Path
from agno.vectordb import VectorDb
from functools import cached_property
from agno.document.reader.pdf_reader import PDFReader


@dataclass
class KnowledgeBase:
    
    """Knowledge base class"""

    name: str
    description: Optional[str] = None
    document_store: Optional[DocumentStore] = None
    vector_store: Optional[VectorDb] = None

    def search(self):
        pass

    async def async_search(self):
        pass

    def load(self):
        log_info("Loading documents from knowledge base")
        # This will use the classic documents list like the v1 implementation
        # This should only be used for loading documents on startup of an app
        # or for a bulk load
        # The Add documents methods below should be used when adding files via the API 
        # using the new knowledge manager
        pass
    


    def add_document_by_path(self, path: str):
        """
        Add a document by path.
        - Read the document
        - Add it to the document store
        - Chunk and add it to the vector DB
        """
        if self.document_store is None:
            raise ValueError("No document store provided")
        
        if self.vector_store is None:
            raise ValueError("No vector DB provided")

        result = urlparse(path)
        if all([result.scheme, result.netloc]):
            # Handle URL
            self._add_from_url(path)
        elif os.path.isfile(path):
            # Handle filepath
            self._add_from_path(path)
        else:
            raise ValueError(f"Invalid path: {path}")
        


    def add_document(self, document: Document):
        """
        Process a single document.
        - Add it to the document store
        - Chunk and add it to the vector DB
        """
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



    @cached_property
    def pdf_reader(self) -> PDFReader:
        """PDF reader - lazy loaded and cached."""
        return PDFReader(chunk=True, chunk_size=100)
    
    def _add_from_path(self, path: str):
        path = Path(path)
        if path.is_file():
            if path.suffix == ".pdf":
                
                print("PDF file detected")
                document = self.pdf_reader.read(path)
                print(document)
                self.document_store.add_document(document)
        elif path.is_dir():
            pass
        else:
            raise ValueError(f"Invalid path: {path}")
       
        
    def add_from_url(self, url: str):
        pass