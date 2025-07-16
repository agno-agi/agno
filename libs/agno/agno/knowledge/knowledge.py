import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, overload
from uuid import uuid4

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.document import Document
from agno.document.reader import Reader, ReaderFactory
from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig
from agno.knowledge.content import Content, FileData
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb import VectorDb

ContentDict = Dict[str, Union[str, Dict[str, str]]]


@dataclass
class Knowledge:
    """Knowledge class"""

    name: str
    description: Optional[str] = None
    vector_store: Optional[VectorDb] = None
    contents_db: Optional[PostgresDb] = None
    valid_metadata_filters: Optional[List[str]] = None
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None

    def __post_init__(self):
        if self.vector_store and not self.vector_store.exists():
            self.vector_store.create()

        self.construct_readers()

    # --- SDK Specific Methods ---

    @overload
    def add_contents(self, contents: List[ContentDict]) -> None: ...

    @overload
    def add_contents(
        self,
        *,
        paths: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None: ...

    def add_contents(self, *args, **kwargs) -> None:
        if args and isinstance(args[0], list):
            contents = args[0]
            print("Case 1: List of content dicts")
            for content in contents:
                print(f"Adding content: {content}")
                self.add_content(
                    name=content.get("name"),
                    description=content.get("description"),
                    path=content.get("path"),
                    url=content.get("url"),
                    metadata=content.get("metadata"),
                    topics=content.get("topics"),
                    reader=content.get("reader"),
                )

        elif kwargs:
            name = kwargs.get("name", [])
            metadata = kwargs.get("metadata", {})
            description = kwargs.get("description", [])
            topics = kwargs.get("topics", [])
            paths = kwargs.get("paths", [])
            urls = kwargs.get("urls", [])

            print("Case 2: Structured inputs with kwargs")
            for path in paths:
                self.add_content(
                    name=name,
                    description=description,
                    path=path,
                    metadata=metadata,
                )
                print(f"Adding path content: {path} with metadata: {metadata}")
            for url in urls:
                self.add_content(
                    name=name,
                    description=description,
                    url=url,
                    metadata=metadata,
                )
                print(f"Adding url content: {url} with metadata: {metadata}")
            if topics:
                self.add_content(
                    name=name,
                    description=description,
                    topics=topics,
                    metadata=metadata,
                )

        else:
            raise ValueError("Invalid usage of add_contents.")

    def add_content(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
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

        content = None
        if text_content:
            content = FileData(content=text_content, type="Text")

        content = Content(
            id=str(uuid4()),
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=content if content else None,
            metadata=metadata,
            topics=topics,
            config=config,
            reader=reader,
        )
        self._load_content(content)

    def _load_from_path(
        self,
        content: Content,
    ):
        log_info(f"Adding content from path, {content.id}, {content.name}, {content.path}, {content.description}")
        path = Path(content.path)
        if path.is_file():
            content.id = str(uuid4())
            self._add_to_contents_db(content)

            if content.reader:
                read_documents = content.reader.read(path, name=content.name or path.name)
            else:
                reader = ReaderFactory.get_reader_for_extension(path.suffix)
                print(f"Using Reader: {reader.__class__.__name__}")
                if reader:
                    read_documents = reader.read(path, name=content.name or path.name)

            if not content.file_type:
                content.file_type = path.suffix

            if not content.size and content.file_data:
                content.size = len(content.file_data.content)
            if not content.size:
                try:
                    content.size = path.stat().st_size
                except (OSError, IOError) as e:
                    log_warning(f"Could not get file size for {path}: {e}")
                    content.size = 0

            completed = True
            for read_document in read_documents:
                read_document.content_id = content.id
                if self.vector_store.upsert_available():
                    try:
                        self.vector_store.upsert(documents=[read_document], filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document: {e}")
                        content.status = "Failed"
                        content.status_message = "Could not upsert embedding"
                        completed = False
                        self._update_content(content)
                else:
                    try:
                        self.vector_store.insert(documents=[read_document], filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document: {e}")
                        content.status = "Failed"
                        content.status_message = "Could not insert embedding"
                        completed = False
                        self._update_content(content)

            if completed:
                content.status = "Completed"
                self._update_content(content)

        elif path.is_dir():
            for file in path.iterdir():
                id = str(uuid4())
                file_content = Content(
                    id=id,
                    name=content.name,
                    path=str(file),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                self._load_from_path(file_content)
        else:
            log_warning(f"Invalid path: {path}")

    def _load_from_url(self, content: Content):
        log_info("Adding content from URL")
        from urllib.parse import urlparse

        content.file_type = "url"
        self._add_to_contents_db(content)

        # Validate URL
        try:
            parsed_url = urlparse(content.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                content.status = "Failed"
                content.status_message = f"Invalid URL format: {content.url}"
                self._update_content(content)
                log_warning(f"Invalid URL format: {content.url}")
        except Exception as e:
            content.status = "Failed"
            content.status_message = f"Invalid URL: {content.url} - {str(e)}"
            self._update_content(content)
            log_warning(f"Invalid URL: {content.url} - {str(e)}")

        # Determine file type from URL
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        # Check if it's a file with known extension
        if file_extension and file_extension is not None:
            log_info(f"Detected file type: {file_extension} from URL: {content.url}")
            reader = self._select_url_file_reader(file_extension)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(content.url, content.name)
            else:
                log_info(f"No reader found for file extension: {file_extension}")
        else:
            log_info(f"No file extension found for URL: {content.url}, determining website type")
            reader = self._select_url_reader(content.url)
            if reader is not None:
                log_info(f"Selected reader: {reader.__class__.__name__}")
                read_documents = reader.read(content.url, content.name)
            else:
                log_info(f"No reader found for URL: {content.url}")

        file_size = 0
        if read_documents:
            for read_document in read_documents:
                if read_document.size:
                    file_size += read_document.size
                read_document.content_id = content.id
                if self.vector_store.upsert_available():
                    try:
                        self.vector_store.upsert(documents=[read_document], filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document: {e}")
                        content.status = "Failed"
                        content.status_message = "Could not upsert embedding"
                        self._update_content(content)
                else:
                    try:
                        self.vector_store.insert(documents=[read_document], filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document: {e}")
                        content.status = "Failed"
                        content.status_message = "Could not insert embedding"
                        self._update_content(content)

        content.size = file_size
        content.status = "Completed"
        self._update_content(content)

    def _load_from_content(self, content: Content):
        log_info(f"Adding content from content: {content.size}")

        completed = True
        read_documents = []
        if isinstance(content.file_data, str):
            if content.name is None:
                content.name = content.file_data[:10] if len(content.file_data) >= 10 else content.file_data
            content_io = io.BytesIO(content.file_data.encode("utf-8"))
            name = (
                content.name
                if content.name
                else content.file_data[:10]
                if len(content.file_data) >= 10
                else content.file_data
            )
            if content.reader:
                log_info(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = content.reader.read(content_io, name=name)
            else:
                read_documents = self.text_reader.read(content_io, name=name)

        elif isinstance(content.file_data, FileData):
            if content.file_data.type:
                log_info(f"Content content type: {content.file_data.type}")
                if isinstance(content.file_data.content, bytes):
                    content_io = io.BytesIO(content.file_data.content)
                elif isinstance(content.file_data.content, str):
                    content_io = io.BytesIO(content.file_data.content.encode("utf-8"))
                else:
                    content_io = content.file_data.content

                reader = self._select_reader(content.file_data.type)
                name = content.name if content.name else f"content_{content.file_data.type}"
                read_documents = reader.read(content_io, name=name)

                # Process each document in the list
                for read_document in read_documents:
                    # Add the original metadata to each document
                    if content.metadata:
                        read_document.meta_data.update(content.metadata)
                    read_document.content_id = content.id

                    # Add to vector store - pass as a list
                    if self.vector_store and self.vector_store.upsert_available():
                        try:
                            self.vector_store.upsert(documents=[read_document], filters=content.metadata)
                        except Exception as e:
                            log_error(f"Error upserting document: {e}")
                            content.status = "Failed"
                            content.status_message = "Could not upsert embedding"
                            completed = False
                            self._update_content(content)
                    else:
                        try:
                            self.vector_store.insert(documents=[read_document], filters=content.metadata)
                        except Exception as e:
                            log_error(f"Error inserting document: {e}")
                            content.status = "Failed"
                            content.status_message = "Could not insert embedding"
                            completed = False
                            self._update_content(content)

                if len(read_documents) == 0:
                    content.status = "Failed"
                    content.status_message = "Content could not be read"
                    completed = False
                    self._update_content(content)

        else:
            content.status = "Failed"
            content.status_message = "No content provided"
            self._update_content(content)
            return

        if completed:
            content.status = "Completed"
            self._update_content(content)

    def _load_from_topics(self, content: Content):
        log_info(f"Adding content from topics: {content.topics}")

        for topic in content.topics:
            id = str(uuid4())
            self._add_to_contents_db(
                Content(
                    id=id,
                    name=topic,
                    metadata=content.metadata,
                    reader=content.reader,
                    status="Processing" if content.reader else "Failed: No reader provided",
                    file_data=FileData(
                        type="Topic",
                    ),
                )
            )

            read_documents = content.reader.read(topic)
            if len(read_documents) > 0:
                for read_document in read_documents:
                    if read_document.content:
                        read_document.size = len(read_document.content.encode("utf-8"))
                    if self.vector_store.upsert_available():
                        self.vector_store.upsert(documents=[read_document], filters=content.metadata)
                    else:
                        self.vector_store.insert(documents=[read_document], filters=content.metadata)
                content.status = "Completed"
                self._update_content(content)
            else:
                content.status = "Failed"
                content.status_message = "No content found for topic"
                self._update_content(content)

    def _load_from_cloud_storage(self): ...

    def _load_content(self, content: Content) -> None:
        log_info(f"Loading content: {content.id}")

        if content.path:
            self._load_from_path(content)

        if content.url:
            self._load_from_url(content)

        if content.file_data:
            self._add_to_contents_db(content)
            self._load_from_content(content)

        if content.topics:
            self._load_from_topics(content)

        # if content.config:
        #     self._load_from_cloud_storage(content)

    def _add_to_contents_db(self, content: Content):
        if self.contents_db:
            created_at = content.created_at if content.created_at else int(time.time())
            updated_at = content.updated_at if content.updated_at else int(time.time())

            file_type = (
                content.file_type
                if content.file_type
                else content.file_data.type
                if content.file_data and content.file_data.type
                else None
            )

            content_row = KnowledgeRow(
                id=content.id,
                name=content.name if content.name else "",
                description=content.description if content.description else "",
                metadata=content.metadata,
                type=file_type,
                size=content.size
                if content.size
                else len(content.file_data.content)
                if content.file_data and content.file_data.content
                else None,
                linked_to=self.name,
                access_count=0,
                status=content.status if content.status else "Processing",
                status_message="",
                created_at=created_at,
                updated_at=updated_at,
            )
            self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    def _update_content(self, content: Content):
        if self.contents_db:
            content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return
            if content.name is not None:
                content_row.name = content.name
            if content.description is not None:
                content_row.description = content.description
            if content.metadata is not None:
                content_row.metadata = content.metadata
            if content.status is not None:
                content_row.status = content.status
            if content.status_message is not None:
                content_row.status_message = content.status_message if content.status_message else ""
            content_row.updated_at = int(time.time())
            self.contents_db.upsert_knowledge_content(knowledge_row=content_row)
        else:
            log_warning(f"Contents DB not found for knowledge base: {self.name}")

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

    def remove_vector_by_id(self, id: str) -> bool:
        if self.vector_store is None:
            log_warning("No vector DB provided")
            return
        return self.vector_store.delete_by_id(id)

    def remove_vector_by_name(self, name: str) -> bool:
        if self.vector_store is None:
            log_warning("No vector DB provided")
            return
        return self.vector_store.delete_by_name(name)

    def remove_vector_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        if self.vector_store is None:
            log_warning("No vector DB provided")
            return
        return self.vector_store.delete_by_metadata(metadata)

    # --- API Only Methods ---

    def process_content(
        self,
        content: Content,
    ) -> None:
        # Validation:At least one of the parameters must be provided
        if not content.id:
            content.id = str(uuid4())

        self._load_content(content)

    def patch_content(self, content: Content):
        self._update_content(content)

    def get_content_by_id(self, content_id: str):
        if self.contents_db is None:
            raise ValueError("No contents db provided")
        content_row = self.contents_db.get_knowledge_content(content_id)
        if content_row is None:
            return None
        content = Content(
            id=content_row.id,
            name=content_row.name,
            description=content_row.description,
            metadata=content_row.metadata,
            size=content_row.size,
            status=content_row.status,
            status_message=content_row.status_message,
            created_at=content_row.created_at,
            updated_at=content_row.updated_at if content_row.updated_at else content_row.created_at,
        )
        return content

    def get_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")
        contents, count = self.contents_db.get_knowledge_contents(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order
        )

        result = []
        for content_row in contents:
            # Create Content from database row
            content = Content(
                id=content_row.id,
                name=content_row.name,
                description=content_row.description,
                metadata=content_row.metadata,
                size=content_row.size,
                status=content_row.status,
                status_message=content_row.status_message,
                created_at=content_row.created_at,
                updated_at=content_row.updated_at if content_row.updated_at else content_row.created_at,
            )
            result.append(content)
        return result, count

    def get_content_status(self, content_id: str) -> Tuple[Optional[str], Optional[str]]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")
        content_row = self.contents_db.get_knowledge_content(content_id)
        if content_row is None:
            return None
        return content_row.status, content_row.status_message

    def remove_content_by_id(self, content_id: str):
        if self.contents_db is not None:
            self.contents_db.delete_knowledge_content(content_id)

        if self.vector_store is not None:
            self.vector_store.delete_by_content_id(content_id)

    def remove_all_content(self):
        contents, _ = self.get_content()
        for content in contents:
            self.remove_content_by_id(content.id)

    # --- Reader Factory Integration ---

    def construct_readers(self):
        """Construct readers using the ReaderFactory."""
        self.readers = ReaderFactory.create_all_readers()

    def add_reader(self, reader: Reader):
        """Add a custom reader to the knowledge base."""
        if self.readers is None:
            self.readers = {}

        # Generate a key for the reader
        reader_key = self._generate_reader_key(reader)
        self.readers[reader_key] = reader
        return reader

    def get_readers(self) -> List[Reader]:
        """Get all available readers."""
        if self.readers is None:
            return []
        return list(self.readers.values())

    def _generate_reader_key(self, reader: Reader) -> str:
        """Generate a key for a reader instance."""
        if reader.name:
            return f"{reader.name.lower().replace(' ', '_')}"
        else:
            return f"{reader.__class__.__name__.lower().replace(' ', '_')}"

    def _select_reader(self, extension: str) -> Reader:
        """Select the appropriate reader for a file extension."""
        log_info(f"Selecting reader for extension: {extension}")
        return ReaderFactory.get_reader_for_extension(extension)

    def _select_url_reader(self, url: str) -> Reader:
        """Select the appropriate reader for a URL."""
        return ReaderFactory.get_reader_for_url(url)

    def _select_url_file_reader(self, extension: str) -> Reader:
        """Select the appropriate reader for a URL file extension."""
        return ReaderFactory.get_reader_for_url_file(extension)

    def get_filters(self) -> List[str]:
        return [
            "filter_tag_1",
            "filter_tag2",
        ]

    # --- Convenience Properties for Backward Compatibility ---

    @property
    def pdf_reader(self) -> Reader:
        """PDF reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("pdf")

    @property
    def csv_reader(self) -> Reader:
        """CSV reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("csv")

    @property
    def docx_reader(self) -> Reader:
        """Docx reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("docx")

    @property
    def json_reader(self) -> Reader:
        """JSON reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("json")

    @property
    def markdown_reader(self) -> Reader:
        """Markdown reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("markdown")

    @property
    def text_reader(self) -> Reader:
        """Text reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("text")

    @property
    def website_reader(self) -> Reader:
        """Website reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("website")

    @property
    def firecrawl_reader(self) -> Reader:
        """Firecrawl reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("firecrawl")

    @property
    def url_reader(self) -> Reader:
        """URL reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("url")

    @property
    def pdf_url_reader(self) -> Reader:
        """PDF URL reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("pdf_url")

    @property
    def youtube_reader(self) -> Reader:
        """YouTube reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("youtube")

    @property
    def csv_url_reader(self) -> Reader:
        """CSV URL reader - lazy loaded via factory."""
        return ReaderFactory.create_reader("csv_url")
