import io
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse
from uuid import uuid4

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.document import Document
from agno.document.document_store import DocumentStore
from agno.document.document_v2 import DocumentV2
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.url_reader import URLReader
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb import VectorDb


@dataclass
class Knowledge:
    """Knowledge class"""

    name: str
    description: Optional[str] = None
    vector_store: Optional[VectorDb] = None
    document_store: Optional[Union[DocumentStore, List[DocumentStore]]] = None
    documents_db: Optional[PostgresDb] = None
    documents: Optional[Union[DocumentV2, List[DocumentV2]]] = None
    paths: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    valid_metadata_filters: Optional[List[str]] = None
    num_documents: int = 10

    def __post_init__(self):
        if self.vector_store and not self.vector_store.exists():
            self.vector_store.create()

        if self.document_store is not None:
            self.document_store.read_from_store = True

    #

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_store is None:
                log_warning("No vector db provided")
                return []

            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            return self.vector_store.search(query=query, limit=_num_documents, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    async def async_search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_store is None:
                log_warning("No vector db provided")
                return []

            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            try:
                return await self.vector_store.async_search(query=query, limit=_num_documents, filters=filters)
            except NotImplementedError:
                log_info("Vector db does not support async search")
                return self.search(query=query, num_documents=_num_documents, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []
        pass

    def load(self):
        log_info("Loading documents from knowledge base")

        if self.documents:
            if isinstance(self.documents, list):
                for document in self.documents:
                    self.add_documents(document)
            else:
                self.add_documents(self.documents)

        if self.document_store is not None:
            if isinstance(self.document_store, list):
                for store in self.document_store:
                    # Process each store in the list
                    log_info(f"Processing document store: {store.name}")
                    if store.read_from_store:
                        self.load_documents_from_store(store)
            else:
                log_info(f"Processing single document store: {self.document_store.name}")
                if self.document_store.read_from_store:
                    self.load_documents_from_store(self.document_store)

    def load_documents_from_store(self, document_store: DocumentStore):
        if document_store.read_from_store:
            for file_content, metadata in document_store.get_all_documents():
                if metadata["file_type"] == ".pdf":
                    _pdf = io.BytesIO(file_content) if isinstance(file_content, bytes) else file_content
                    document = self.pdf_reader.read(pdf=_pdf, name=metadata["name"])

                    if self.vector_store.upsert_available():
                        self.vector_store.upsert(documents=document, filters=metadata)
                    else:
                        self.vector_store.insert(document)

        if document_store.copy_to_store:
            # TODO: Need to implement this part. Copy only when the file does not already exist in that store.
            pass

    def _add_document_by_path(self, id: str, document: DocumentV2):
        path = document.paths
        if isinstance(path, str):
            path = [path]
        for path in path:
            path = Path(path)
            if path.is_file():
                if path.suffix in [".pdf", ".csv"]:
                    if document.reader:
                        read_documents = document.reader.read(path)
                    else:
                        read_documents = self.pdf_reader.read(path, name=path.name)
                    self._add_to_documents_db(id, document)
                    for read_document in read_documents:
                        read_document.source_id = id
                        self.vector_store.upsert(documents=[read_document], filters=document.metadata)
                else:
                    log_warning(f"File is not a supported file type: {path}.")
            elif path.is_dir():
                for file in path.iterdir():
                    # Create a new DocumentV2 object for each file in the directory
                    file_document = DocumentV2(
                        name=document.name, paths=str(file), metadata=document.metadata, reader=document.reader
                    )
                    self._add_document_by_path(id, file_document)
            else:
                raise ValueError(f"Invalid path: {path}")

    def _add_document_by_content(self, id: str, document: DocumentV2):
        log_info("Adding document from content")

        if document.content:
            if "pdf" in document.content.type:
                # Convert bytes to BytesIO for the reader
                if isinstance(document.content.content, bytes):
                    content_io = io.BytesIO(document.content.content)
                else:
                    content_io = document.content.content

                read_documents = self.pdf_reader.read(content_io, name=document.name)

                # Process each document in the list
                for read_document in read_documents:
                    # Add the original metadata to each document
                    if document.metadata:
                        read_document.meta_data.update(document.metadata)
                    read_document.source_id = id

                    # Add to vector store - pass as a list
                    if self.vector_store:
                        self.vector_store.upsert(documents=[read_document], filters=document.metadata)

            self._add_to_documents_db(id, document)

            # Add to document store if available
            if self.document_store:
                self.document_store.add_document(id, document)

            else:
                # For non-PDF content, log warning for now
                log_warning("Non-PDF content not supported yet")
        else:
            raise ValueError("No content provided")

    def add_document(self, document: Union[str, DocumentV2]) -> None:
        log_debug("Adding document")
        # TODO: Update document ID handling
        if isinstance(document, DocumentV2) and document.id:
            id = document.id
        else:
            id = str(uuid4())

        if isinstance(document, DocumentV2):
            if document.paths:
                self._add_document_by_path(id, document)
            elif document.urls:
                self._add_from_url(document)
            elif document.content:
                self._add_document_by_content(id, document)
            else:
                raise ValueError("No document provided")
        elif isinstance(document, str):
            # Check if the string is a valid URL
            parsed_url = urlparse(document)
            if parsed_url.scheme and parsed_url.netloc:
                # It's a valid URL, treat as URL document
                url_document = DocumentV2(name=document, urls=[document])
                self._add_from_url(url_document)
            else:
                # It's a file path, treat as file document
                document = DocumentV2(name=document, paths=document)
                self._add_document_by_path(id, document)
        else:
            raise ValueError("No document provided")
        # elif isinstance(document, str):
        #     self._add_from_file(document)
        # else:
        #     raise ValueError("No document provided")

    def add_documents(self, documents: Union[DocumentV2, List[DocumentV2]]) -> None:
        """
        Implementation of add_documents that handles both overloads.
        """
        if isinstance(documents, list):
            log_debug(f"Adding {len(documents)} documents")
            for document in documents:
                self.add_document(document)

        elif isinstance(documents, DocumentV2):
            self.add_document(documents)

    def get_document(self, document_id: str):
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        document_row = self.documents_db.get_knowledge_document(document_id)
        document = DocumentV2(
            id=document_row.id,
            name=document_row.name,
            description=document_row.description,
            metadata=document_row.metadata,
        )
        return document

    def get_documents(self) -> List[DocumentV2]:
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        documents = self.documents_db.get_knowledge_documents()
        # Convert database rows to DocumentV2 objects
        result = []
        for doc_row in documents:
            # Create DocumentV2 from database row
            doc = DocumentV2(
                id=doc_row.id, name=doc_row.name, description=doc_row.description, metadata=doc_row.metadata
            )
            result.append(doc)
        return result

    def remove_document(self, document_id: str):
        if self.documents_db is not None:
            self.documents_db.delete_knowledge_document(document_id)

        if self.document_store is not None:
            self.document_store.delete_document(document_id)

        if self.vector_store is not None:
            self.vector_store.delete_by_source_id(document_id)

    def remove_all_documents(self):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.delete_all_documents()

    def _add_to_documents_db(self, id: str, document: DocumentV2):
        if self.documents_db:
            document_row = KnowledgeRow(
                id=id,
                name=document.name if document.name else "",
                description=document.description if document.description else "",
                metadata=document.metadata,
                type=document.content.type if document.content else None,
                size=len(document.content.content) if document.content else None,
                linked_to=self.name,
                access_count=0,
            )
            self.documents_db.upsert_knowledge_document(knowledge_row=document_row)

    @cached_property
    def pdf_reader(self) -> PDFReader:
        """PDF reader - lazy loaded and cached."""
        return PDFReader(chunk=True, chunk_size=100)

    @cached_property
    def url_reader(self) -> URLReader:
        """URL reader - lazy loaded and cached."""
        return URLReader()

    def _add_from_file(self, file_path: str):
        path = Path(file_path)
        if path.is_file():
            if path.suffix == ".pdf":
                document = self.pdf_reader.read(
                    path, name=path
                )  # TODO: Need to make naming consistent with files and their extensions.
                self.document_store.add_document(document)
                self.vector_store.insert(document)
        elif path.is_dir():
            pass
        else:
            raise ValueError(f"Invalid path: {path}")

    def _add_from_url(self, url: str):
        print("Add from URL not implemented yet")
        pass

    def validate_filters(self, filters: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        if not filters:
            return {}, []

        valid_filters = {}
        invalid_keys = []

        # If no metadata filters tracked yet, all keys are considered invalid
        if self.valid_metadata_filters is None:
            invalid_keys = list(filters.keys())
            log_debug(f"No valid metadata filters tracked yet. All filter keys considered invalid: {invalid_keys}")
            return {}, invalid_keys

        for key, value in filters.items():
            # Handle both normal keys and prefixed keys like meta_data.key
            base_key = key.split(".")[-1] if "." in key else key
            if base_key in self.valid_metadata_filters or key in self.valid_metadata_filters:
                valid_filters[key] = value
            else:
                invalid_keys.append(key)
                log_debug(f"Invalid filter key: {key} - not present in knowledge base")

        return valid_filters, invalid_keys


# -- Unused for now. Will revisit when we do async and optimizations ---


#  @property
# def list_documents(self) -> Iterator[List[Document]]:
#     """Iterate over the documents and yield them"""
#     if self.paths:
#         for path in self.paths:
#             self._add_document_by_path(path)
#     if self.urls:
#         for url in self.urls:
#             self.add_document_by_url(url)
#     for document in self.documents:
#         if isinstance(document, Document): # The easy one where we just yield and store this. Figure out vectors later
#             print("document is a Document")
#             yield document

#         elif isinstance(document, dict): # The more complex one where we 1. Determine if path or url. 2. Determine file type and reader. 3. Read it. 4. Yield it.
#             if "source" in document:
#                 result = urlparse(document["source"])
#                 if all([result.scheme, result.netloc]):
#                     print("URL detected")
#                     yield self.url_reader.read(document["source"])
#                 else:
#                     print("File detected")
#                     # TODO: Refactor this to use the add_from_path method instead so we dont duplicate logic
#                     yield self.pdf_reader.read(document["source"], name=document["name"])
#             else:
#                 raise ValueError(f"Invalid document: {document}")

#         else:
#             raise ValueError(f"Invalid document: {document}")
