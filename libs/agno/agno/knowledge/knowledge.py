from dataclasses import dataclass, field
from agno.document.document_store import DocumentStore
from typing import Any, Optional, List, Iterator, Tuple, overload
from agno.document import Document
from agno.utils.log import log_info, log_debug, log_error, log_warning
from urllib.parse import urlparse
import os
from pathlib import Path
from agno.vectordb import VectorDb
from functools import cached_property
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.url_reader import URLReader
from typing import Union, Dict
import io
from agno.document.document_v2 import DocumentV2
from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
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
    num_documents: int = 5

    def __post_init__(self):
        if self.vector_store and not self.vector_store.exists():
            self.vector_store.create()

        if self.document_store is not None:
            self.document_store.read_from_store = True

    @property
    def list_documents(self) -> Iterator[List[Document]]:
        """Iterate over the documents and yield them"""
        if self.paths:
            for path in self.paths:
                self._add_document_by_path(path)
        if self.urls:
            for url in self.urls:
                self.add_document_by_url(url)
        for document in self.documents:
            if isinstance(document, Document): # The easy one where we just yield and store this. Figure out vectors later
                print("document is a Document")
                yield document

            elif isinstance(document, dict): # The more complex one where we 1. Determine if path or url. 2. Determine file type and reader. 3. Read it. 4. Yield it.
                if "source" in document:
                    result = urlparse(document["source"])
                    if all([result.scheme, result.netloc]):
                        print("URL detected")
                        yield self.url_reader.read(document["source"])
                    else:
                        print("File detected")
                        # TODO: Refactor this to use the add_from_path method instead so we dont duplicate logic
                        yield self.pdf_reader.read(document["source"], name=document["name"])
                else:
                    raise ValueError(f"Invalid document: {document}")

            else:
                raise ValueError(f"Invalid document: {document}")


    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        print("Searching for documents")
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
        # num_documents = 0
        # for document_list in self.list_documents:
        #    for doc in document_list:
        #        if self.vector_store.upsert_available(): # Need to add logic here for vector stores that dont support upsert.In that case, do a manual existings files check.
        #          self.vector_store.upsert(documents=[doc], filters= doc.meta_data)
        # log_info(f"Loaded {num_documents} documents")
 


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
                    print(f"Processing document store: {store.name}")
                    if store.read_from_store:
                        self.load_documents_from_store(store)
            else:
                print(f"Processing single document store: {self.document_store.name}")
                if self.document_store.read_from_store:
                  self.load_documents_from_store(self.document_store)
                        
                           

    def load_documents_from_store(self, document_store: DocumentStore):

        if document_store.read_from_store:
            for file_content, metadata in document_store.get_all_documents():
                print("Document found in store")
                print(metadata)
                if metadata["file_type"] == ".pdf":
                    print("PDF file detected")
                    _pdf = io.BytesIO(file_content) if isinstance(file_content, bytes) else file_content
                    document = self.pdf_reader.read(pdf=_pdf, name=metadata["name"])
                    
                    if self.vector_store.upsert_available():
                        self.vector_store.upsert(documents = document, filters=metadata)
                    else:
                      self.vector_store.insert(document)

        if document_store.copy_to_store:
            #Need to figure this part out. Copy only when the file does not already exist in that store.
            pass

    def _add_document_by_path(self, document: DocumentV2):
        path = document.paths
        if isinstance(path, str):
            path = [path]
        for path in path:
            path = Path(path)
            if path.is_file():
                if path.suffix in [".pdf", ".csv"]:
                    print(f"{path.suffix} file detected, trying to process", path)
                    if document.reader:
                        read_document = document.reader.read(path)
                    else:
                        read_document = self.pdf_reader.read(path, name=path.name)
                    # self.document_store.add_document(document)
                    self._add_to_documents_db(document)

                    # self.vector_store.insert(documents=read_document, filters=document.metadata)
                else:
                    print(f"File is not a supported file type: {path}.")
            elif path.is_dir():
                for file in path.iterdir():
                    self._add_document_by_path(document)
            else:
                raise ValueError(f"Invalid path: {path}")



    def add_document(self, document: Union[str, DocumentV2]) -> None:
        if isinstance(document, DocumentV2):
            if document.paths:
                self._add_document_by_path(document)
            elif document.urls:
                self._add_from_url(document)
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
                self._add_document_by_path(document)
        else:
            raise ValueError("No document provided")
        # elif isinstance(document, str):
        #     self._add_from_file(document)
        # else:
        #     raise ValueError("No document provided")
        
        
    def add_documents(self, documents: Union[List[str], List[DocumentV2]]) -> None:
        """
        Implementation of add_documents that handles both overloads.
        """
        for document in documents:
            self.add_document(document)


        # if isinstance(documents, list[str]):
        #     for document in documents:
        #         self._add_from_file(document)
        # else:
        #     if documents.paths:
        #         self._add_document_by_path(documents)
        #     elif documents.urls:
        #         self._add_from_url(documents)
        #     else:
        #         raise ValueError("No document provided")

  
    def get_document(self, document_id: str):
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        document_row = self.documents_db.get_knowledge_document(document_id)
        return document_row

    def get_documents(self):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.get_all_documents()

    def remove_document(self, document_id: str):
        if self.document_store is None:
            ...
            #remove from document store


        if self.vector_store is not None:
            self.vector_store.delete_by_id(document_id)


    def remove_all_documents(self):
        if self.document_store is None:
            raise ValueError("No document store provided")
        return self.document_store.delete_all_documents()


    
    def _add_to_documents_db(self, document: DocumentV2):
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        document_row = KnowledgeRow(
            description="HELLO",
            content="HELLO",
            metadata={"user_tag": "Engineering candidates"},
            name=document.name
        )
        self.documents_db.upsert_knowledge_document(document_row)

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

                print("PDF file detected")
                document = self.pdf_reader.read(path, name=path) #TODO: Need to make naming consistent with files and their extensions.
                print(document)
                # self.document_store.add_document(document)
                self.vector_store.insert(document)
        elif path.is_dir():
            pass
        else:
            raise ValueError(f"Invalid path: {path}")
       
        
    def _add_from_url(self, url: str):
        document = self.url_reader.read(url)
        print(document)
        # self.document_store.add_document(document)
        self.vector_store.insert(document)

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
