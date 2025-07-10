import io
import os
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.document import Document
from agno.document.reader import Reader
from agno.document.reader.csv_reader import CSVReader, CSVUrlReader
from agno.document.reader.docx_reader import DocxReader
from agno.document.reader.firecrawl_reader import FirecrawlReader
from agno.document.reader.json_reader import JSONReader
from agno.document.reader.markdown_reader import MarkdownReader
from agno.document.reader.pdf_reader import PDFReader, PDFUrlReader
from agno.document.reader.text_reader import TextReader
from agno.document.reader.url_reader import URLReader
from agno.document.reader.website_reader import WebsiteReader
from agno.document.reader.youtube_reader import YouTubeReader
from agno.document.store import Store
from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig
from agno.knowledge.source import Source, SourceContent
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb import VectorDb


@dataclass
class Knowledge:
    """Knowledge class"""

    name: str
    description: Optional[str] = None
    vector_store: Optional[VectorDb] = None
    store: Optional[Union[Store, List[Store]]] = None
    sources_db: Optional[PostgresDb] = None
    sources: Optional[Union[Source, List[Source]]] = None
    paths: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    valid_metadata_filters: Optional[List[str]] = None
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None

    def __post_init__(self):
        if self.vector_store and not self.vector_store.exists():
            self.vector_store.create()

        if self.store is not None:
            self.store.read_from_store = True

        self.construct_readers()

    def search(
        self, query: str, max_results: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_store is None:
                log_warning("No vector db provided")
                return []

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            return self.vector_store.search(query=query, limit=_max_results, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    async def async_search(
        self, query: str, max_results: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_store is None:
                log_warning("No vector db provided")
                return []

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            try:
                return await self.vector_store.async_search(query=query, limit=_max_results, filters=filters)
            except NotImplementedError:
                log_info("Vector db does not support async search")
                return self.search(query=query, max_results=_max_results, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    def load(self):
        log_info("Loading sources into KnowledgeBase")

        if self.sources:
            if isinstance(self.sources, list):
                for source in self.sources:
                    self.add_source(source=source)
            else:
                self.add_source(source=self.sources)

        if self.store is not None:
            if isinstance(self.store, list):
                for store in self.store:
                    # Process each store in the list
                    log_info(f"Processing document store: {store.name}")
                    if store.read_from_store:
                        self.load_from_document_store(store)
            else:
                log_info(f"Processing single document store: {self.store.name}")
                if self.store.read_from_store:
                    self.load_from_document_store(self.store)

    def load_from_document_store(self, store: Store):
        if store.read_from_store:
            for file_content, metadata in store.get_all_documents():
                if metadata["file_type"] == ".pdf":
                    _pdf = io.BytesIO(file_content) if isinstance(file_content, bytes) else file_content
                    document = self.pdf_reader.read(pdf=_pdf, name=metadata["name"])

                    if self.vector_store.upsert_available():
                        self.vector_store.upsert(documents=document, filters=metadata)
                    else:
                        self.vector_store.insert(document)

        if store.copy_to_store:
            # TODO: Need to implement this part. Copy only when the file does not already exist in that store.
            pass

    def _load_from_path(
        self,
        source: Source,
    ):
        log_info("Adding source from path")
        path = Path(source.path)
        if path.is_file():
            if source.reader:
                read_documents = source.reader.read(path, name=source.name or path.name)
            else:
                reader = self._select_reader(path.suffix)
                print(f"Using Reader: {reader.__class__.__name__}")
                if reader:
                    read_documents = reader.read(path, name=source.name or path.name)

            if not source.size and source.content:
                source.size = len(source.content.content)
            if not source.size:
                try:
                    source.size = path.stat().st_size
                except (OSError, IOError) as e:
                    log_warning(f"Could not get file size for {path}: {e}")
                    source.size = 0

            for read_document in read_documents:
                read_document.source_id = source.id
                if self.vector_store.upsert_available():
                    try:
                        self.vector_store.upsert(documents=[read_document], filters=source.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document: {e}")
                        self._update_source_status(source.id, "Failed - Could not upsert embedding")
                else:
                    try:
                        self.vector_store.insert(documents=[read_document], filters=source.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document: {e}")
                        self._update_source_status(source.id, "Failed - Could not insert embedding")

        elif path.is_dir():
            for file in path.iterdir():
                id = str(uuid4())
                # Create a new Source object for each file in the directory
                file_source = Source(
                    id=id, name=source.name, path=str(file), metadata=source.metadata, reader=source.reader
                )
                self._load_from_path(file_source)
        else:
            self._update_source_status(source.id, "Failed")
            log_warning(f"Invalid path: {path}")

        self._update_source_status(source.id, "Completed")

    def _load_from_url(self, source: Source):
        log_info("Adding source from URL")
        from urllib.parse import urlparse

        # Validate URL
        try:
            parsed_url = urlparse(source.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                self._update_source_status(source.id, "Failed - Invalid URL format")
                log_warning(f"Invalid URL format: {source.url}")
        except Exception as e:
            self._update_source_status(source.id, "Failed - Invalid URL")
            log_warning(f"Invalid URL: {source.url} - {str(e)}")

        # Determine file type from URL
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        # Check if it's a file with known extension
        if file_extension and file_extension is not None:
            log_info(f"Detected file type: {file_extension} from URL: {source.url}")
            reader = self._select_url_file_reader(file_extension)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(source.url, source.name)
            else:
                log_info(f"No reader found for file extension: {file_extension}")
        else:
            log_info(f"No file extension found for URL: {source.url}, determining website type")
            reader = self._select_url_reader(source.url)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(source.url, source.name)
            else:
                log_info(f"No reader found for URL: {source.url}")

        file_size = 0
        if read_documents:
            for read_document in read_documents:
                if read_document.size:
                    file_size += read_document.size
                read_document.source_id = source.id
                if self.vector_store.upsert_available():
                    try:
                        self.vector_store.upsert(documents=[read_document], filters=source.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document: {e}")
                        self._update_source_status(source.id, "Failed - Could not upsert embedding")
                else:
                    try:
                        self.vector_store.insert(documents=[read_document], filters=source.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document: {e}")
                        self._update_source_status(source.id, "Failed - Could not insert embedding")

        source.size = file_size
        self._update_source_status(source.id, "Completed")

    def _load_from_content(self, source: Source):
        log_info(f"Adding source from content: {source.size}")

        read_documents = []
        if isinstance(source.content, str):
            if source.name is None:
                source.name = source.content[:10] if len(source.content) >= 10 else source.content
            content_io = io.BytesIO(source.content.encode("utf-8"))
            name = source.name if source.name else source.content[:10] if len(source.content) >= 10 else source.content
            if source.reader:
                read_documents = source.reader.read(content_io, name=name)
            else:
                read_documents = self.text_reader.read(content_io, name=name)

        elif isinstance(source.content, SourceContent):
            if source.content.type:
                log_info(f"Source content type: {source.content.type}")
                if isinstance(source.content.content, bytes):
                    content_io = io.BytesIO(source.content.content)
                elif isinstance(source.content.content, str):
                    content_io = io.BytesIO(source.content.content.encode("utf-8"))
                else:
                    content_io = source.content.content

                reader = self._select_reader(source.content.type)
                name = source.name if source.name else f"content_{source.content.type}"
                read_documents = reader.read(content_io, name=name)

                # Process each document in the list
                for read_document in read_documents:
                    # Add the original metadata to each document
                    if source.metadata:
                        read_document.meta_data.update(source.metadata)
                    read_document.source_id = source.id

                    # Add to vector store - pass as a list
                    if self.vector_store and self.vector_store.upsert_available():
                        try:
                            self.vector_store.upsert(documents=[read_document], filters=source.metadata)
                        except Exception as e:
                            log_error(f"Error upserting document: {e}")
                            self._update_source_status(source.id, "Failed - Could not upsert embedding")
                    else:
                        try:
                            self.vector_store.insert(documents=[read_document], filters=source.metadata)
                        except Exception as e:
                            log_error(f"Error inserting document: {e}")
                            self._update_source_status(source.id, "Failed - Could not insert embedding")

            # Add to document store if available
            if self.store:
                self.store.add_source(id, source)

        else:
            self._update_source_status(source.id, "Failed")
            raise ValueError("No content provided")

        self._update_source_status(source.id, "Completed")

    def _load_from_topics(self, source: Source):
        log_info(f"Adding source from topics: {source.topics}")

        for topic in source.topics:
            id = str(uuid4())
            self._add_to_sources_db(
                Source(
                    id=id,
                    name=topic,
                    metadata=source.metadata,
                    reader=source.reader,
                    status="Processing" if source.reader else "Failed: No reader provided",
                    content=SourceContent(
                        type="Topic",
                    ),
                )
            )

            read_documents = source.reader.read(topic)
            if len(read_documents) > 0:
                for read_document in read_documents:
                    if read_document.content:
                        read_document.size = len(read_document.content.encode("utf-8"))
                    if self.vector_store.upsert_available():
                        self.vector_store.upsert(documents=[read_document], filters=source.metadata)
                    else:
                        self.vector_store.insert(documents=[read_document], filters=source.metadata)
                self._update_source_status(id, "Completed")
            else:
                self._update_source_status(id, "Failed - No content found for topic")

    def _load_from_cloud_storage(self): ...

    def _load_source(self, source: Source) -> None:
        log_info(f"Loading source: {source.id}")
        # Don't add for topics, they need to create their own documents.
        if source.path or source.url or source.content:
            log_info(f"Adding source to sources db: {source.id}")
            self._add_to_sources_db(source)

        if source.path:
            self._load_from_path(source)

        if source.url:
            self._load_from_url(source)

        if source.content:
            self._load_from_content(source)

        if source.topics:
            self._load_from_topics(source)

        # if document.config:
        #     self._load_from_cloud_storage(id, document)

    def patch_source(self, source: Source):
        if self.sources_db is not None:
            source_row = self.sources_db.get_knowledge_source(source.id)
            if source_row is None:
                log_warning(f"Source not found: {source.id}")
                return
            # Only update fields that are not None
            if source.name is not None:
                source_row.name = source.name
            if source.description is not None:
                source_row.description = source.description
            if source.metadata is not None:
                source_row.metadata = source.metadata
            source_row.updated_at = int(time.time())
            self.sources_db.upsert_knowledge_source(knowledge_row=source_row)
        else:
            log_warning("No sources db provided")

    def add_source(
        self,
        name: Optional[str] = None,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        topics: Optional[List[str]] = None,
        config: Optional[CloudStorageConfig] = None,
        reader: Optional[Reader] = None,
    ) -> None:
        # Validation: At least one of the parameters must be provided
        if all(argument is None for argument in [name, path, url, text_content, topics]):
            log_info("At least one of 'path', 'url', 'text_content', or 'topics' must be provided.")
            return

        # Create Source from individual parameters
        content = None
        if text_content:
            content = SourceContent(content=text_content, type="Text")

        source = Source(
            id=str(uuid4()),
            name=name,
            path=path,
            url=url,
            content=content if content else None,
            metadata=metadata,
            topics=topics,
            config=config,
            reader=reader,
        )
        self._load_source(source)

    def _add_source_from_api(
        self,
        source: Source,
    ) -> None:
        # Validation:At least one of the parameters must be provided
        if not source.id:
            source.id = str(uuid4())

        self._load_source(source)

    def get_source(self, source_id: str):
        if self.sources_db is None:
            raise ValueError("No sources db provided")
        source_row = self.sources_db.get_knowledge_source(source_id)
        if source_row is None:
            return None
        source = Source(
            id=source_row.id,
            name=source_row.name,
            description=source_row.description,
            metadata=source_row.metadata,
            size=source_row.size,
            status=source_row.status,
            created_at=source_row.created_at,
            updated_at=source_row.updated_at if source_row.updated_at else source_row.created_at,
        )
        return source

    def get_sources(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Source], int]:
        if self.sources_db is None:
            raise ValueError("No sources db provided")
        sources, count = self.sources_db.get_knowledge_sources(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order
        )
        # Convert database rows to DocumentV2 objects
        result = []
        for source_row in sources:
            # Create Source from database row
            source = Source(
                id=source_row.id,
                name=source_row.name,
                description=source_row.description,
                metadata=source_row.metadata,
                size=source_row.size,
                status=source_row.status,
                created_at=source_row.created_at,
                updated_at=source_row.updated_at if source_row.updated_at else source_row.created_at,
            )
            result.append(source)
        return result, count

    def get_source_status(self, source_id: str) -> Optional[str]:
        if self.sources_db is None:
            raise ValueError("No sources db provided")
        return self.sources_db.get_source_status(source_id)

    def remove_source(self, source_id: str):
        if self.sources_db is not None:
            self.sources_db.delete_knowledge_source(source_id)

        if self.store is not None:
            self.store.delete_source(source_id)

        if self.vector_store is not None:
            self.vector_store.delete_by_source_id(source_id)

    def remove_all_sources(self):
        if self.store is not None:
            self.store.delete_all_sources()
        sources, _ = self.get_sources()
        for source in sources:
            self.remove_source(source.id)

    def _add_to_sources_db(self, source: Source):
        if self.sources_db:
            created_at = source.created_at if source.created_at else int(time.time())
            updated_at = source.updated_at if source.updated_at else int(time.time())

            file_type = source.content.type if source.content and source.content.type else None

            source_row = KnowledgeRow(
                id=source.id,
                name=source.name if source.name else "",
                description=source.description if source.description else "",
                metadata=source.metadata,
                type=file_type,
                size=source.size
                if source.size
                else len(source.content.content)
                if source.content and source.content.content
                else None,
                linked_to=self.name,
                access_count=0,
                status=source.status if source.status else "Processing",
                created_at=created_at,
                updated_at=updated_at,
            )
            self.sources_db.upsert_knowledge_source(knowledge_row=source_row)

    def _update_source_status(self, source_id: str, status: str):
        if self.sources_db:
            source_row = self.sources_db.get_knowledge_source(source_id)
            source_row.status = status
            source_row.updated_at = int(time.time())
            self.sources_db.upsert_knowledge_source(knowledge_row=source_row)

    def _add_from_file(self, file_path: str):
        path = Path(file_path)
        if path.is_file():
            if path.suffix == ".pdf":
                document = self.pdf_reader.read(
                    path, name=path
                )  # TODO: Need to make naming consistent with files and their extensions.
                self.store.add_source(document)
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
    def _generate_reader_key(self, reader: Reader) -> str:
        if reader.name:
            return f"{reader.name.lower().replace(' ', '_')}"
        else:
            return f"{reader.__class__.__name__.lower().replace(' ', '_')}"

    def construct_readers(self):
        self.readers = {
            self._generate_reader_key(self.pdf_reader): self.pdf_reader,
            self._generate_reader_key(self.csv_reader): self.csv_reader,
            self._generate_reader_key(self.docx_reader): self.docx_reader,
            self._generate_reader_key(self.json_reader): self.json_reader,
            self._generate_reader_key(self.markdown_reader): self.markdown_reader,
            self._generate_reader_key(self.text_reader): self.text_reader,
            self._generate_reader_key(self.url_reader): self.url_reader,
            self._generate_reader_key(self.website_reader): self.website_reader,
            self._generate_reader_key(self.firecrawl_reader): self.firecrawl_reader,
            self._generate_reader_key(self.youtube_reader): self.youtube_reader,
            self._generate_reader_key(self.csv_url_reader): self.csv_url_reader,
        }

    def add_reader(self, reader: Reader):
        self.readers[self._generate_reader_key(reader)] = reader
        return reader

    def get_readers(self) -> List[Reader]:
        return self.readers

    def _select_reader(self, extension: str) -> Reader:
        log_info(f"Selecting reader for extension: {extension}")
        extension = extension.lower()
        if "pdf" in extension:
            return self.pdf_reader
        elif "csv" in extension:
            return self.csv_reader
        elif any(ext in extension for ext in ["docx", "doc", "word"]):
            return self.docx_reader
        elif "json" in extension:
            return self.json_reader
        elif any(ext in extension for ext in ["md", "markdown"]):
            return self.markdown_reader
        else:
            return self.text_reader

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

    def get_filters(self) -> List[str]:
        return [
            "filter_tag_1",
            "filter_tag2",
        ]

    # --- File Readers ---
    @cached_property
    def pdf_reader(self) -> PDFReader:
        """PDF reader - lazy loaded and cached."""
        return PDFReader(chunk=True, chunk_size=100)

    @cached_property
    def csv_reader(self) -> CSVReader:
        """CSV reader - lazy loaded and cached."""
        return CSVReader(name="CSV Reader", description="Reads CSV files")

    @cached_property
    def docx_reader(self) -> DocxReader:
        """Docx reader - lazy loaded and cached."""
        return DocxReader(name="Docx Reader", description="Reads Docx files")

    @cached_property
    def json_reader(self) -> JSONReader:
        """JSON reader - lazy loaded and cached."""
        return JSONReader(name="JSON Reader", description="Reads JSON files")

    @cached_property
    def markdown_reader(self) -> MarkdownReader:
        """Markdown reader - lazy loaded and cached."""
        return MarkdownReader(name="Markdown Reader", description="Reads Markdown files")

    @cached_property
    def text_reader(self) -> TextReader:
        """Txt reader - lazy loaded and cached."""
        return TextReader(name="Text Reader", description="Reads Text files")

    # --- URL Readers ---

    @cached_property
    def website_reader(self) -> WebsiteReader:
        """Website reader - lazy loaded and cached."""
        return WebsiteReader(name="Website Reader", description="Reads Website files")

    @cached_property
    def firecrawl_reader(self) -> FirecrawlReader:
        """Firecrawl reader - lazy loaded and cached."""
        return FirecrawlReader(
            api_key=os.getenv("FIRECRAWL_API_KEY"),
            mode="crawl",
            name="Firecrawl Reader",
            description="Crawls websites",
        )

    @cached_property
    def url_reader(self) -> URLReader:
        """URL reader - lazy loaded and cached."""
        return URLReader(name="URL Reader", description="Reads URLs")

    @cached_property
    def pdf_url_reader(self) -> PDFUrlReader:
        """PDF URL reader - lazy loaded and cached."""
        return PDFUrlReader(name="PDF URL Reader", description="Reads PDF URLs")

    @cached_property
    def youtube_reader(self) -> YouTubeReader:
        """YouTube reader - lazy loaded and cached."""
        return YouTubeReader(name="YouTube Reader", description="Reads YouTube videos")

    @cached_property
    def csv_url_reader(self) -> CSVUrlReader:
        """CSV URL reader - lazy loaded and cached."""
        return CSVUrlReader(name="CSV URL Reader", description="Reads CSV URLs")


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
