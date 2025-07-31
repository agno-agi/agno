import asyncio
import hashlib
import io
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List, Optional, Tuple, Union, overload
from uuid import uuid4

from agno.db.base import BaseDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.knowledge.content import Content, FileData
from agno.knowledge.document import Document
from agno.knowledge.reader import Reader, ReaderFactory
from agno.knowledge.remote_content.remote_content import GCSContent, RemoteContent, S3Content
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb import VectorDb

ContentDict = Dict[str, Union[str, Dict[str, str]]]


@dataclass
class Knowledge:
    """Knowledge class"""

    name: Optional[str] = None
    description: Optional[str] = None
    vector_db: Optional[VectorDb] = None
    contents_db: Optional[BaseDb] = None
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None

    def __post_init__(self):
        if self.vector_db and not self.vector_db.exists():
            self.vector_db.create()

        self.construct_readers()
        self.valid_metadata_filters = set()

    def _is_text_mime_type(self, mime_type: str) -> bool:
        """
        Check if a MIME type represents text content that can be safely encoded as UTF-8.

        Args:
            mime_type: The MIME type to check

        Returns:
            bool: True if it's a text type, False if binary
        """
        if not mime_type:
            return False

        text_types = [
            "text/",
            "application/json",
            "application/xml",
            "application/javascript",
            "application/csv",
            "application/sql",
        ]

        return any(mime_type.startswith(t) for t in text_types)

    def _should_include_file(self, file_path: str, include: Optional[List[str]], exclude: Optional[List[str]]) -> bool:
        """
        Determine if a file should be included based on include/exclude patterns.

        Logic:
        1. If include is specified, file must match at least one include pattern
        2. If exclude is specified, file must not match any exclude pattern
        3. If neither specified, include all files

        Args:
            file_path: Path to the file to check
            include: Optional list of include patterns (glob-style)
            exclude: Optional list of exclude patterns (glob-style)

        Returns:
            bool: True if file should be included, False otherwise
        """
        import fnmatch

        # If include patterns specified, file must match at least one
        if include:
            if not any(fnmatch.fnmatch(file_path, pattern) for pattern in include):
                return False

        # If exclude patterns specified, file must not match any
        if exclude:
            if any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude):
                return False

        return True

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
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = False,
        skip_if_exists: bool = False,
        remote_content: Optional[RemoteContent] = None,
    ) -> None: ...

    def add_contents(self, *args, **kwargs) -> None:
        if args and isinstance(args[0], list):
            arguments = args[0]
            for argument in arguments:
                self.add_content(
                    name=argument.get("name"),
                    description=argument.get("description"),
                    path=argument.get("path"),
                    url=argument.get("url"),
                    metadata=argument.get("metadata"),
                    topics=argument.get("topics"),
                    reader=argument.get("reader"),
                    include=argument.get("include"),
                    exclude=argument.get("exclude"),
                    upsert=argument.get("upsert", False),
                    skip_if_exists=argument.get("skip_if_exists", False),
                    remote_content=argument.get("remote_content", None),
                )

        elif kwargs:
            name = kwargs.get("name", [])
            metadata = kwargs.get("metadata", {})
            description = kwargs.get("description", [])
            topics = kwargs.get("topics", [])
            paths = kwargs.get("paths", [])
            urls = kwargs.get("urls", [])
            include = kwargs.get("include")
            exclude = kwargs.get("exclude")
            upsert = kwargs.get("upsert", False)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            remote_content = kwargs.get("remote_content", None)

            for path in paths:
                self.add_content(
                    name=name,
                    description=description,
                    path=path,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                )
            for url in urls:
                self.add_content(
                    name=name,
                    description=description,
                    url=url,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                )
            if topics:
                self.add_content(
                    name=name,
                    description=description,
                    topics=topics,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                )

            if remote_content:
                self.add_content(
                    name=name,
                    metadata=metadata,
                    description=description,
                    remote_content=remote_content,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                )

        else:
            raise ValueError("Invalid usage of add_contents.")

    @overload
    async def async_add_contents(self, contents: List[ContentDict]) -> None: ...

    @overload
    async def async_add_contents(
        self,
        *,
        paths: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = False,
        skip_if_exists: bool = False,
    ) -> None: ...

    async def async_add_contents(self, *args, **kwargs) -> None:
        """
        Asynchronously add multiple content items to the knowledge base.

        This method wraps the synchronous add_contents method and runs it in a thread pool
        to avoid blocking the event loop.

        Supports two usage patterns:
        1. Pass a list of content dictionaries as first argument
        2. Pass keyword arguments with paths, urls, metadata, etc.

        Args:
            contents: List of content dictionaries (when used as first overload)
            paths: Optional list of file paths to load content from
            urls: Optional list of URLs to load content from
            metadata: Optional metadata dictionary to apply to all content
            include: Optional list of file patterns to include
            exclude: Optional list of file patterns to exclude
            upsert: Whether to update existing content if it already exists
            skip_if_exists: Whether to skip adding content if it already exists
        """
        await asyncio.to_thread(self.add_contents, *args, **kwargs)

    def add_content(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        topics: Optional[List[str]] = None,
        remote_content: Optional[RemoteContent] = None,
        reader: Optional[Reader] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = True,
    ) -> None:
        # Validation: At least one of the parameters must be provided
        if all(argument is None for argument in [path, url, text_content, topics, remote_content]):
            log_info("At least one of 'path', 'url', 'text_content', 'topics', or 'remote_content' must be provided.")
            return

        if not skip_if_exists:
            log_info("skip_if_exists is disabled, disabling upsert")
            upsert = False

        content = None
        file_data = None
        if text_content:
            file_data = FileData(content=text_content, type="Text")

        content = Content(
            id=str(uuid4()),
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=file_data if file_data else None,
            metadata=metadata,
            topics=topics,
            remote_content=remote_content,
            reader=reader,
        )

        self._load_content(content, upsert, skip_if_exists, include, exclude)

    async def async_add_content(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        topics: Optional[List[str]] = None,
        remote_content: Optional[RemoteContent] = None,
        reader: Optional[Reader] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = True,
    ) -> None:
        """
        Asynchronously add content to the knowledge base.

        This method wraps the synchronous add_content method and runs it in a thread pool
        to avoid blocking the event loop.

        Args:
            name: Optional name for the content
            description: Optional description for the content
            path: Optional file path to load content from
            url: Optional URL to load content from
            text_content: Optional text content to add directly
            metadata: Optional metadata dictionary
            topics: Optional list of topics
            config: Optional cloud storage configuration
            reader: Optional custom reader for processing the content
            include: Optional list of file patterns to include
            exclude: Optional list of file patterns to exclude
            upsert: Whether to update existing content if it already exists
            skip_if_exists: Whether to skip adding content if it already exists
        """
        await asyncio.to_thread(
            self.add_content,
            name=name,
            description=description,
            path=path,
            url=url,
            text_content=text_content,
            metadata=metadata,
            topics=topics,
            remote_content=remote_content,
            reader=reader,
            include=include,
            exclude=exclude,
            upsert=upsert,
            skip_if_exists=skip_if_exists,
        )

    def _load_from_path(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        log_info(f"Adding content from path, {content.id}, {content.name}, {content.path}, {content.description}")
        path = Path(content.path)
        if path.is_file():
            if self._should_include_file(str(path), include, exclude):
                log_info(f"Adding file {path} due to include/exclude filters")

                self._add_to_contents_db(content)
                content.content_hash = self._build_content_hash(content)
                if self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                    log_info(f"Content {content.content_hash} already exists, skipping")
                    content.status = "Completed"
                    self._update_content(content)
                    return

                if content.reader:
                    read_documents = content.reader.read(path, name=content.name or path.name)
                else:
                    reader = ReaderFactory.get_reader_for_extension(path.suffix)
                    log_info(f"Using Reader: {reader.__class__.__name__}")
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

                if upsert:
                    try:
                        self.vector_db.upsert(content.content_hash, read_documents, content.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document: {e}")
                        content.status = "Failed"
                        content.status_message = "Could not upsert embedding"
                        completed = False
                        self._update_content(content)
                else:
                    try:
                        self.vector_db.insert(content.content_hash, documents=read_documents, filters=content.metadata)
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
            for file_path in path.iterdir():
                # Apply include/exclude filtering
                if not self._should_include_file(str(file_path), include, exclude):
                    log_debug(f"Skipping file {file_path} due to include/exclude filters")
                    continue

                id = str(uuid4())
                file_content = Content(
                    id=id,
                    name=content.name,
                    path=str(file_path),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                self._load_from_path(file_content, upsert, skip_if_exists, include, exclude)
        else:
            log_warning(f"Invalid path: {path}")

    def _load_from_url(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        log_info(f"Adding content from URL {content.name}")
        self._add_to_contents_db(content)

        content.content_hash = self._build_content_hash(content)
        if self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
            log_info(f"Content {content.content_hash} already exists, skipping")
            content.status = "Completed"
            self._update_content(content)

            return

        content.file_type = "url"

        # Validate URL
        try:
            from urllib.parse import urlparse

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

        if content.url.endswith("llms-full.txt") or content.url.endswith("llms.txt"):
            log_info(f"Detected llms, using url reader")
            reader = self.url_reader
            read_documents = reader.read(content.url, content.name)

        elif file_extension and file_extension is not None:
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

        if self.vector_db.upsert_available() and upsert:
            try:
                self.vector_db.upsert(content.content_hash, documents=read_documents, filters=content.metadata)
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = "Failed"
                content.status_message = "Could not upsert embedding"
                self._update_content(content)
        else:
            try:
                self.vector_db.insert(content.content_hash, documents=read_documents, filters=content.metadata)
            except Exception as e:
                log_error(f"Error inserting document: {e}")
                content.status = "Failed"
                content.status_message = "Could not insert embedding"
                self._update_content(content)

        content.size = file_size
        content.status = "Completed"
        self._update_content(content)

    def _load_from_content(
        self,
        content: Content,
        upsert: bool = True,
        skip_if_exists: bool = True,
    ):
        name = (
            content.name
            if content.name
            else content.file_data.content[:10]
            if len(content.file_data.content) >= 10
            else content.file_data.content
        )
        content.name = name

        log_info(f"Adding content from {content.name}")
        self._add_to_contents_db(content)

        content.content_hash = self._build_content_hash(content)
        if self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
            log_info(f"Content {content.content_hash} already exists, skipping")
            content.status = "Completed"
            self._update_content(content)
            return

        completed = True
        read_documents = []

        if isinstance(content.file_data, str):
            try:
                content_bytes = content.file_data.encode("utf-8")
            except UnicodeEncodeError:
                content_bytes = content.file_data.encode("latin-1")
            content_io = io.BytesIO(content_bytes)

            if content.reader:
                log_info(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = content.reader.read(content_io, name=name)
            else:
                text_reader = self.text_reader
                if text_reader:
                    read_documents = text_reader.read(content_io, name=name)
                else:
                    content.status = "Failed"
                    content.status_message = "Text reader not available"
                    completed = False
                    self._update_content(content)
                    return

        elif isinstance(content.file_data, FileData):
            if content.file_data.type:
                if isinstance(content.file_data.content, bytes):
                    content_io = io.BytesIO(content.file_data.content)
                elif isinstance(content.file_data.content, str):
                    if self._is_text_mime_type(content.file_data.type):
                        try:
                            content_bytes = content.file_data.content.encode("utf-8")
                        except UnicodeEncodeError:
                            log_debug(f"UTF-8 encoding failed for {content.file_data.type}, using latin-1")
                            content_bytes = content.file_data.content.encode("latin-1")
                    else:
                        content_bytes = content.file_data.content.encode("latin-1")
                    content_io = io.BytesIO(content_bytes)
                else:
                    content_io = content.file_data.content

                reader = self._select_reader(content.file_data.type)
                name = content.name if content.name else f"content_{content.file_data.type}"
                read_documents = reader.read(content_io, name=name)

                for read_document in read_documents:
                    if content.metadata:
                        read_document.meta_data.update(content.metadata)
                    read_document.content_id = content.id

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

        # Add to vector store - pass as a list
        if self.vector_db and self.vector_db.upsert_available() and upsert:
            try:
                self.vector_db.upsert(content.content_hash, documents=read_documents, filters=content.metadata)
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = "Failed"
                content.status_message = "Could not upsert embedding"
                completed = False
                self._update_content(content)
        else:
            try:
                self.vector_db.insert(content.content_hash, documents=read_documents, filters=content.metadata)
            except Exception as e:
                log_error(f"Error inserting document: {e}")
                content.status = "Failed"
                content.status_message = "Could not insert embedding"
                completed = False
                self._update_content(content)

        if completed:
            content.status = "Completed"
            self._update_content(content)

    def _load_from_topics(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        log_info(f"Adding content from topics: {content.topics}")

        for topic in content.topics:
            id = str(uuid4())
            content = Content(
                id=id,
                name=topic,
                metadata=content.metadata,
                reader=content.reader,
                status="Processing" if content.reader else "Failed: No reader provided",
                file_data=FileData(
                    type="Topic",
                ),
                topics=[topic],
            )
            self._add_to_contents_db(content)

            content.content_hash = self._build_content_hash(content)
            if self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                log_info(f"Content {content.content_hash} already exists, skipping")
                continue

            read_documents = content.reader.read(topic)
            if len(read_documents) > 0:
                for read_document in read_documents:
                    read_document.content_id = id
                    if read_document.content:
                        read_document.size = len(read_document.content.encode("utf-8"))
            else:
                content.status = "Failed"
                content.status_message = "No content found for topic"
                self._update_content(content)

            if self.vector_db.upsert_available() and upsert:
                self.vector_db.upsert(content.content_hash, documents=read_documents, filters=content.metadata)
            else:
                self.vector_db.insert(content.content_hash, documents=read_documents, filters=content.metadata)
            content.status = "Completed"
            self._update_content(content)

    def _load_from_remote_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        log_info(f"Loading content from cloud storage")

        if content.remote_content is None:
            log_warning("No remote content provided for content")
            return

        remote_content = content.remote_content

        if isinstance(remote_content, S3Content):
            self._load_from_s3(content, upsert, skip_if_exists)

        elif isinstance(remote_content, GCSContent):
            self._load_from_gcs(content, upsert, skip_if_exists)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    def _load_from_s3(self, content: Content, upsert: bool, skip_if_exists: bool):
        from agno.aws.resource.s3.object import S3Object  # type: ignore

        log_info(f"Loading content from S3")
        if content.reader is None:
            reader = self.s3_reader
        else:
            reader = content.reader

        if reader is None:
            log_warning("No reader provided for content")
            return

        remote_content: S3Content = content.remote_content

        objects_to_read: List[S3Object] = []

        if remote_content.bucket is not None:
            if remote_content.key is not None:
                _object = S3Object(bucket_name=remote_content.bucket.name, name=remote_content.key)
                objects_to_read.append(_object)
            elif remote_content.object is not None:
                objects_to_read.append(remote_content.object)
            elif remote_content.prefix is not None:
                objects_to_read.extend(remote_content.bucket.get_objects(prefix=remote_content.prefix))
            else:
                objects_to_read.extend(remote_content.bucket.get_objects())

        for object in objects_to_read:
            id = str(uuid4())
            content_entry = Content(
                id=id,
                name=content.name + "_" + object.name,
                description=content.description,
                status="Processing",
                metadata=content.metadata,
                file_type="s3",
            )

            content_hash = self._build_content_hash(content_entry)
            if self.vector_db.content_hash_exists(content_hash) and skip_if_exists:
                log_info(f"Content {content_hash} already exists, skipping")
                continue

            self._add_to_contents_db(content_entry)

            read_documents = reader.read(content_entry.name, object)

            for read_document in read_documents:
                read_document.content_id = content.id

            completed = True
            if upsert:
                try:
                    self.vector_db.upsert(content_hash, read_documents, content.metadata)
                except Exception as e:
                    log_error(f"Error upserting document: {e}")
                    content_entry.status = "Failed"
                    content_entry.status_message = "Could not upsert embedding"
                    completed = False
                    self._update_content(content_entry)
            else:
                try:
                    self.vector_db.insert(content_hash, documents=read_documents, filters=content.metadata)
                except Exception as e:
                    log_error(f"Error inserting document: {e}")
                    content_entry.status = "Failed"
                    content_entry.status_message = "Could not insert embedding"
                    completed = False
                    self._update_content(content_entry)

            if completed:
                content_entry.status = "Completed"
                self._update_content(content_entry)

    def _load_from_gcs(self, content: Content, upsert: bool, skip_if_exists: bool):
        log_info(f"Loading content from GCS")

        if content.reader is None:
            reader = self.gcs_reader
        else:
            reader = content.reader

        if reader is None:
            log_warning("No reader provided for content")
            return

        remote_content: GCSContent = content.remote_content
        objects_to_read = []

        if remote_content.blob_name is not None:
            objects_to_read.append(remote_content.bucket.blob(remote_content.blob_name))
        elif remote_content.prefix is not None:
            objects_to_read.extend(remote_content.bucket.list_blobs(prefix=remote_content.prefix))
        else:
            objects_to_read.extend(remote_content.bucket.list_blobs())

        for object in objects_to_read:
            id = str(uuid4())
            content_entry = Content(
                id=id,
                name=content.name + "_" + object.name,
                description=content.description,
                status="Processing",
                metadata=content.metadata,
                file_type="gcs",
            )

            content_hash = self._build_content_hash(content_entry)
            if self.vector_db.content_hash_exists(content_hash) and skip_if_exists:
                log_info(f"Content {content_hash} already exists, skipping")
                continue

            self._add_to_contents_db(content_entry)

            read_documents = reader.read(content_entry.name, object)

            for read_document in read_documents:
                read_document.content_id = content.id

            completed = True

            if upsert:
                try:
                    self.vector_db.upsert(content_hash, read_documents, content.metadata)
                except Exception as e:
                    log_error(f"Error upserting document: {e}")
                    content_entry.status = "Failed"
                    content_entry.status_message = "Could not upsert embedding"
                    completed = False
                    self._update_content(content_entry)
            else:
                try:
                    self.vector_db.insert(content_hash, documents=read_documents, filters=content.metadata)
                except Exception as e:
                    log_error(f"Error inserting document: {e}")
                    content_entry.status = "Failed"
                    content_entry.status_message = "Could not insert embedding"
                    completed = False
                    self._update_content(content_entry)

            if completed:
                content_entry.status = "Completed"
                self._update_content(content_entry)

    def _load_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        log_info(f"Loading content: {content.id}")

        if content.metadata:
            self.add_filters(content.metadata)

        if content.path:
            self._load_from_path(content, upsert, skip_if_exists, include, exclude)

        if content.url:
            self._load_from_url(content, upsert, skip_if_exists)

        if content.file_data:
            self._load_from_content(content, upsert, skip_if_exists)

        if content.topics:
            self._load_from_topics(content, upsert, skip_if_exists)

        if content.remote_content:
            self._load_from_remote_content(content, upsert, skip_if_exists)

    def _build_content_hash(self, content: Content) -> str:
        """
        Build the content hash from the content.
        """
        if content.path:
            return hashlib.sha256(str(content.path).encode()).hexdigest()
        elif content.url:
            return hashlib.sha256(content.url.encode()).hexdigest()
        elif content.file_data and content.file_data.content:
            name = content.name or "content"
            return hashlib.sha256(name.encode()).hexdigest()
        elif content.topics and len(content.topics) > 0:
            topic = content.topics[0]
            reader = type(content.reader).__name__ if content.reader else "unknown"
            return hashlib.sha256(f"{topic}-{reader}".encode()).hexdigest()
        else:
            # Fallback for edge cases
            import random
            import string

            fallback = (
                content.name
                or content.id
                or ("unknown_content" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6)))
            )
            return hashlib.sha256(fallback.encode()).hexdigest()

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

    def _update_content(self, content: Content) -> Optional[Dict[str, Any]]:
        if self.contents_db:
            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            # TODO: we shouldn't check for content here, we should trust the upsert method to handle conflicts
            content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None

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

            return content_row.to_dict()

        else:
            log_warning(f"Contents DB not found for knowledge base: {self.name}")

    def search(
        self, query: str, max_results: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""

        try:
            if self.vector_db is None:
                log_warning("No vector db provided")
                return []

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            return self.vector_db.search(query=query, limit=_max_results, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    async def async_search(
        self, query: str, max_results: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""

        try:
            if self.vector_db is None:
                log_warning("No vector db provided")
                return []

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            try:
                return await self.vector_db.async_search(query=query, limit=_max_results, filters=filters)
            except NotImplementedError:
                log_info("Vector db does not support async search")
                return self.search(query=query, max_results=_max_results, filters=filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    def validate_filters(self, filters: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        if self.valid_metadata_filters is None:
            self.valid_metadata_filters = set()
        self.valid_metadata_filters.update(self._get_filters_from_db)

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

    def add_filters(self, metadata: Dict[str, Any]) -> None:
        if self.valid_metadata_filters is None:
            self.valid_metadata_filters = set()

        for key in metadata.keys():
            self.valid_metadata_filters.add(key)

    @cached_property
    def _get_filters_from_db(self) -> set:
        if self.contents_db is None:
            return set()
        contents, _ = self.get_content()
        valid_filters = set()
        for content in contents:
            if content.metadata:
                valid_filters.update(content.metadata.keys())
        return valid_filters

    def remove_vector_by_id(self, id: str) -> bool:
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return
        return self.vector_db.delete_by_id(id)

    def remove_vectors_by_name(self, name: str) -> bool:
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return
        return self.vector_db.delete_by_name(name)

    def remove_vectors_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return
        return self.vector_db.delete_by_metadata(metadata)

    # --- API Only Methods ---

    def process_content(
        self,
        content: Content,
    ) -> None:
        # Validation:At least one of the parameters must be provided
        if not content.id:
            content.id = str(uuid4())
        print("PROCESSING", content.name)
        pprint(content)
        self._load_content(content, upsert=False, skip_if_exists=True)

    def patch_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return self._update_content(content)

    def get_content_by_id(self, content_id: str) -> Optional[Content]:
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
            file_type=content_row.type,
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
                file_type=content_row.type,
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

        if self.vector_db is not None:
            self.vector_db.delete_by_content_id(content_id)

    def remove_all_content(self):
        contents, _ = self.get_content()
        for content in contents:
            self.remove_content_by_id(content.id)

    # --- Reader Factory Integration ---

    def construct_readers(self):
        """Initialize readers dictionary for lazy loading."""
        # Initialize empty readers dict - readers will be created on-demand
        if self.readers is None:
            self.readers = {}

    def add_reader(self, reader: Reader):
        """Add a custom reader to the knowledge base."""
        if self.readers is None:
            self.readers = {}

        # Generate a key for the reader
        reader_key = self._generate_reader_key(reader)
        self.readers[reader_key] = reader
        return reader

    def get_readers(self) -> List[Reader]:
        """Get all currently loaded readers (only returns readers that have been used)."""
        if self.readers is None:
            self.readers = {}

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

    def _get_reader(self, reader_type: str) -> Optional[Reader]:
        """Get a cached reader or create it if not cached, handling missing dependencies gracefully."""
        if self.readers is None:
            self.readers = {}

        if reader_type not in self.readers:
            try:
                reader = ReaderFactory.create_reader(reader_type)
                if reader:
                    self.readers[reader_type] = reader
                else:
                    return None

            except Exception as e:
                log_warning(f"Cannot create {reader_type} reader {e}")
                return None

        return self.readers.get(reader_type)

    @property
    def pdf_reader(self) -> Optional[Reader]:
        """PDF reader - lazy loaded via factory."""
        return self._get_reader("pdf")

    @property
    def csv_reader(self) -> Optional[Reader]:
        """CSV reader - lazy loaded via factory."""
        return self._get_reader("csv")

    @property
    def docx_reader(self) -> Optional[Reader]:
        """Docx reader - lazy loaded via factory."""
        return self._get_reader("docx")

    @property
    def json_reader(self) -> Optional[Reader]:
        """JSON reader - lazy loaded via factory."""
        return self._get_reader("json")

    @property
    def markdown_reader(self) -> Optional[Reader]:
        """Markdown reader - lazy loaded via factory."""
        return self._get_reader("markdown")

    @property
    def text_reader(self) -> Optional[Reader]:
        """Text reader - lazy loaded via factory."""
        return self._get_reader("text")

    @property
    def website_reader(self) -> Optional[Reader]:
        """Website reader - lazy loaded via factory."""
        return self._get_reader("website")

    @property
    def firecrawl_reader(self) -> Optional[Reader]:
        """Firecrawl reader - lazy loaded via factory."""
        return self._get_reader("firecrawl")

    @property
    def url_reader(self) -> Optional[Reader]:
        """URL reader - lazy loaded via factory."""
        return self._get_reader("url")

    @property
    def pdf_url_reader(self) -> Optional[Reader]:
        """PDF URL reader - lazy loaded via factory."""
        return self._get_reader("pdf_url")

    @property
    def youtube_reader(self) -> Optional[Reader]:
        """YouTube reader - lazy loaded via factory."""
        return self._get_reader("youtube")

    @property
    def csv_url_reader(self) -> Optional[Reader]:
        """CSV URL reader - lazy loaded via factory."""
        return self._get_reader("csv_url")

    @property
    def s3_reader(self) -> Optional[Reader]:
        """S3 reader - lazy loaded via factory."""
        return self._get_reader("s3")

    @property
    def gcs_reader(self) -> Optional[Reader]:
        """GCS reader - lazy loaded via factory."""
        return self._get_reader("gcs")
