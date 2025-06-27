import io
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.document import Document
from agno.document.document_store import DocumentStore
from agno.document.document_v2 import DocumentV2
from agno.document.reader.firecrawl_reader import FirecrawlReader
from agno.document.reader.pdf_reader import PDFReader, PDFUrlReader
from agno.document.reader.url_reader import URLReader
from agno.document.reader.csv_reader import CSVReader
from agno.document.reader.docx_reader import DocxReader
from agno.document.reader.json_reader import JSONReader
from agno.document.reader.markdown_reader import MarkdownReader
from agno.document.reader.text_reader import TextReader
from agno.document.reader.website_reader import WebsiteReader
from agno.document.reader.youtube_reader import YouTubeReader
from agno.document.reader.csv_reader import CSVUrlReader
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb import VectorDb
from agno.document.reader import Reader
from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig


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
    readers: Optional[Dict[str, Reader]] = None

    def __post_init__(self):
        if self.vector_store and not self.vector_store.exists():
            self.vector_store.create()

        if self.document_store is not None:
            self.document_store.read_from_store = True

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
                        self.load_from_document_store(store)
            else:
                log_info(f"Processing single document store: {self.document_store.name}")
                if self.document_store.read_from_store:
                    self.load_from_document_store(self.document_store)

    def load_from_document_store(self, document_store: DocumentStore):
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

    def _load_from_path(
            self,
            document: DocumentV2,
    ):
        log_info("Adding document from path")
        path = Path(document.path)
        if path.is_file():  
            if document.reader:
                read_documents = document.reader.read(path, name=document.name or path.name)
            else:
                reader = self._select_reader(path.suffix)
                print(f"Using Reader: {reader.__class__.__name__}")
                if reader:
                    read_documents = reader.read(path, name=document.name or path.name)
                else:
                    log_info(f"No reader found for path: {path}")
    
            if not document.size and document.content:
                document.size = len(document.content.content)
            if not document.size:
                try:
                    document.size = path.stat().st_size
                except (OSError, IOError) as e:
                    log_warning(f"Could not get file size for {path}: {e}")
                    document.size = 0
            self._add_to_documents_db(document)

            for read_document in read_documents:
                read_document.source_id = document.id
                if self.vector_store.upsert_available():
                    self.vector_store.upsert(documents=[read_document], filters=document.metadata)
                else:
                    self.vector_store.insert(documents=[read_document], filters=document.metadata)
        

        elif path.is_dir():
            for file in path.iterdir():
                id = str(uuid4())
                # Create a new DocumentV2 object for each file in the directory
                file_document = DocumentV2(
                    id=id, name=document.name, path=str(file), metadata=document.metadata, reader=document.reader
                )
                self._load_from_path(file_document)
        else:
            raise ValueError(f"Invalid path: {path}")
            

    def _load_from_url(self, document: DocumentV2):
        log_info("Adding document from URL")
        from urllib.parse import urlparse
        
        # Validate URL
        try:
            parsed_url = urlparse(document.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                raise ValueError(f"Invalid URL format: {document.url}")
        except Exception as e:
            raise ValueError(f"Invalid URL: {document.url} - {str(e)}")
        
        # Determine file type from URL
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()
        
        # Check if it's a file with known extension
        if file_extension and file_extension is not None:
            log_info(f"Detected file type: {file_extension} from URL: {document.url}")
            reader = self._select_url_file_reader(file_extension)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(document.url, document.name)
            else:
                log_info(f"No reader found for file extension: {file_extension}")
        else:
            log_info(f"No file extension found for URL: {document.url}, determining website type")
            reader = self._select_url_reader(document.url)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(document.url, document.name)
            else:
                log_info(f"No reader found for URL: {document.url}")

        file_size = 0
        if read_documents:
            for read_document in read_documents:
                if read_document.size:
                    file_size += read_document.size
                read_document.source_id = document.id
                if self.vector_store.upsert_available():
                    self.vector_store.upsert(documents=[read_document], filters=document.metadata)
                else:
                    self.vector_store.insert(documents=[read_document], filters=document.metadata)
                
        document.size = file_size
        self._add_to_documents_db(document)

    def _load_from_content(self, document: DocumentV2):
        log_info(f"Adding document from content: {document.size}")

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
                    read_document.source_id = document.id

                    # Add to vector store - pass as a list
                    if self.vector_store:
                        self.vector_store.upsert(documents=[read_document], filters=document.metadata)

            self._add_to_documents_db(document)

            # Add to document store if available
            if self.document_store:
                self.document_store.add_document(id, document)

            else:
                # For non-PDF content, log warning for now
                log_warning("Non-PDF content not supported yet")
        else:
            raise ValueError("No content provided")


    def _load_from_topics(self):
        ...

    def _load_from_cloud_storage(self):
        ...


    def _load_document(self, document: DocumentV2) -> None:
        if document.path:
            self._load_from_path(document)

        if document.url:
            self._load_from_url(document)

        if document.content:
            self._load_from_content(document)

        if document.topics:
            if document.reader is None:
                log_warning("No reader provided for topics")
            else:
                self._load_from_topics(id, document)

        if document.config:
            self._load_from_cloud_storage(id, document)

    
    def add_document(
        self,
        document: Optional[DocumentV2] = None,
        name: Optional[str] = None,
        path: Optional[str] = None,
        url: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        topics: Optional[List[str]] = None,
        config: Optional[CloudStorageConfig] = None,
        reader: Optional[Reader] = None,
    ) -> None:
        # Validation: If document is provided, no other parameters should be provided
        if document is not None:
            arguments = [name, path, url, content, metadata, topics, config, reader]
            if any(argument is not None for argument in arguments):
                log_warning("If 'document' is provided, no other parameters should be provided. "
                    "Use either 'document' OR individual parameters, not both.")
      
            # Use the provided document
            if not document.id:
                document.id = str(uuid4())
            log_info(f"Adding document: {document.id}")
            self._load_document(document)
            return
        
        # Validation: If document is not provided, at least one of the other parameters must be provided
        if all(argument is None for argument in [name, path, url, content]):
            log_warning("Either 'document' must be provided, or at least one of 'path', 'url', or 'content' must be provided.")
            
        # Create DocumentV2 from individual parameters
        document = DocumentV2(
            id=str(uuid4()),
            name=name,
            path=path,
            url=url,
            content=content,
            metadata=metadata,
            topics=topics,
            config=config,
            reader=reader,
        )
        self._load_document(document)


    # def add_documents(self, documents: List[DocumentV2]) -> None:
    #     """
    #     Implementation of add_documents that handles both overloads.
    #     """
    #     if isinstance(documents, list):
    #         log_debug(f"Adding {len(documents)} documents")
    #         for document in documents:
    #             self.add_document(document)

    #     elif isinstance(documents, DocumentV2):
    #         self.add_document(documents)

    def get_document(self, document_id: str):
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        document_row = self.documents_db.get_knowledge_document(document_id)
        document = DocumentV2(
            id=document_row.id,
            name=document_row.name,
            description=document_row.description,
            metadata=document_row.metadata,
            size=document_row.size,
        )
        return document

    def get_documents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[DocumentV2], int]:
        if self.documents_db is None:
            raise ValueError("No documents db provided")
        documents, count = self.documents_db.get_knowledge_documents(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order
        )
        # Convert database rows to DocumentV2 objects
        result = []
        for doc_row in documents:
            # Create DocumentV2 from database row
            doc = DocumentV2(
                id=doc_row.id,
                name=doc_row.name,
                description=doc_row.description,
                metadata=doc_row.metadata,
                size=doc_row.size,
            )
            result.append(doc)
        return result, count

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

    def _add_to_documents_db(self, document: DocumentV2):

        if self.documents_db:
            document_row = KnowledgeRow(
                id=document.id,
                name=document.name if document.name else "",
                description=document.description if document.description else "",
                metadata=document.metadata,
                type=document.content.type if document.content else None,
                size=document.size if document.size else len(document.content.content) if document.content else None,
                linked_to=self.name,
                access_count=0,
            )
            self.documents_db.upsert_knowledge_document(knowledge_row=document_row)



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

# --- Readers Setup ---

    # TODO: Rework these into a map we can use for selection, but also return to API.
    def _select_reader(self, extension: str) -> Reader:
        if extension == ".pdf":
            return self.pdf_reader
        elif extension == ".csv":
            return self.csv_reader
        elif extension == ".docx":
            return self.docx_reader
        elif extension == ".json":
            return self.json_reader
        elif extension == ".md":
            return self.markdown_reader
        elif extension == ".txt":
            return self.text_reader
        else:
            return None
        
    def _select_url_reader(self, url: str) -> Reader:
        if any(domain in url for domain in ["youtube.com", "youtu.be"]):
            return self.youtube_reader
        else:
            return self.url_reader
        

    def _select_url_file_reader(self, extension: str) -> Reader:
        if extension == ".pdf":
            return self.pdf_url_reader
        if extension == ".csv":
            return self.csv_url_reader
        else:
            return self.url_reader


    # --- File Readers ---
    @cached_property
    def pdf_reader(self) -> PDFReader:
        """PDF reader - lazy loaded and cached."""
        return PDFReader(chunk=True, chunk_size=100)

    @cached_property
    def csv_reader(self) -> CSVReader:
        """CSV reader - lazy loaded and cached."""
        return CSVReader()
    
    @cached_property
    def docx_reader(self) -> DocxReader:
        """Docx reader - lazy loaded and cached."""
        return DocxReader()
    
    @cached_property
    def json_reader(self) -> JSONReader:
        """JSON reader - lazy loaded and cached."""
        return JSONReader()
    
    @cached_property
    def markdown_reader(self) -> MarkdownReader:
        """Markdown reader - lazy loaded and cached."""
        return MarkdownReader()
    
    @cached_property
    def text_reader(self) -> TextReader:
        """Txt reader - lazy loaded and cached."""
        return TextReader()
        
    # --- URL Readers ---

    @cached_property
    def website_reader(self) -> WebsiteReader:
        """Website reader - lazy loaded and cached."""
        return WebsiteReader()
    
    @cached_property
    def firecrawl_reader(self) -> FirecrawlReader:
        """Firecrawl reader - lazy loaded and cached."""
        return FirecrawlReader(
            api_key=os.getenv("FIRECRAWL_API_KEY"),
            mode="crawl",
        )

    @cached_property
    def url_reader(self) -> URLReader:
        """URL reader - lazy loaded and cached."""
        return URLReader()
    
    @cached_property
    def pdf_url_reader(self) -> PDFUrlReader:
        """PDF URL reader - lazy loaded and cached."""
        return PDFUrlReader()
    
    @cached_property
    def youtube_reader(self) -> YouTubeReader:
        """YouTube reader - lazy loaded and cached."""
        return YouTubeReader()
    
    @cached_property
    def csv_url_reader(self) -> CSVUrlReader:
        """CSV URL reader - lazy loaded and cached."""
        return CSVUrlReader()
    
# -----------------------------
    
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
