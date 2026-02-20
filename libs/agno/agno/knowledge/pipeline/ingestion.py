"""Ingestion pipeline for Knowledge.

Handles loading content from paths, URLs, text, and topics into the
vector database. Orchestrates reading, chunking, hashing, and insertion.
"""

import asyncio
import hashlib
import io
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from os.path import basename
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.reader import Reader, ReaderFactory
from agno.knowledge.reader_registry import ReaderRegistry
from agno.knowledge.store.content_store import ContentStore
from agno.utils.http import async_fetch_with_retry
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id


class KnowledgeContentOrigin(Enum):
    PATH = "path"
    URL = "url"
    TOPIC = "topic"
    CONTENT = "content"


@dataclass
class IngestionPipeline:
    """Handles loading and indexing content into the vector database."""

    vector_db: Optional[Any] = None
    content_store: Optional[ContentStore] = None
    reader_registry: Optional[ReaderRegistry] = None
    knowledge_name: Optional[str] = None
    isolate_vector_search: bool = False

    # ==========================================
    # MAIN ENTRY POINTS
    # ==========================================

    def load_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """Synchronously load content."""
        if content.path:
            self.load_from_path(content, upsert, skip_if_exists, include, exclude)

        if content.url:
            self.load_from_url(content, upsert, skip_if_exists)

        if content.file_data:
            self.load_from_content(content, upsert, skip_if_exists)

        if content.topics:
            self.load_from_topics(content, upsert, skip_if_exists)

    async def aload_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        if content.path:
            await self.aload_from_path(content, upsert, skip_if_exists, include, exclude)

        if content.url:
            await self.aload_from_url(content, upsert, skip_if_exists)

        if content.file_data:
            await self.aload_from_content(content, upsert, skip_if_exists)

        if content.topics:
            await self.aload_from_topics(content, upsert, skip_if_exists)

    # ==========================================
    # PATH LOADING
    # ==========================================

    def load_from_path(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from path, {content.id}, {content.name}, {content.path}, {content.description}")
        path = Path(content.path)  # type: ignore

        if path.is_file():
            if self.should_include_file(str(path), include, exclude):
                log_debug(f"Adding file {path} due to include/exclude filters")

                if not content.name:
                    content.name = path.name

                self.content_store.insert(content)  # type: ignore[union-attr]
                if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
                    content.status = ContentStatus.COMPLETED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                if self.vector_db.__class__.__name__ == "LightRag":
                    self.process_lightrag_content(content, KnowledgeContentOrigin.PATH)
                    return

                if content.reader:
                    reader = content.reader
                else:
                    reader = ReaderFactory.get_reader_for_extension(path.suffix)
                    log_debug(f"Using Reader: {reader.__class__.__name__}")

                if reader:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    read_documents = self.reader_registry.read(
                        reader, path, name=content.name or path.name, password=password
                    )  # type: ignore[union-attr]
                else:
                    read_documents = []

                if not content.file_type:
                    content.file_type = path.suffix

                if not content.size and content.file_data:
                    content.size = len(content.file_data.content)  # type: ignore
                if not content.size:
                    try:
                        content.size = path.stat().st_size
                    except (OSError, IOError) as e:
                        log_warning(f"Could not get file size for {path}: {e}")
                        content.size = 0

                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                self.handle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            for file_path in path.iterdir():
                if not self.should_include_file(str(file_path), include, exclude):
                    log_debug(f"Skipping file {file_path} due to include/exclude filters")
                    continue

                file_content = Content(
                    name=content.name,
                    path=str(file_path),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                file_content.content_hash = self.build_content_hash(file_content)
                file_content.id = generate_id(file_content.content_hash)

                self.load_from_path(file_content, upsert, skip_if_exists, include, exclude)
        else:
            log_warning(f"Invalid path: {path}")

    async def aload_from_path(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from path, {content.id}, {content.name}, {content.path}, {content.description}")
        path = Path(content.path)  # type: ignore

        if path.is_file():
            if self.should_include_file(str(path), include, exclude):
                log_debug(f"Adding file {path} due to include/exclude filters")

                if not content.name:
                    content.name = path.name

                await self.content_store.ainsert(content)  # type: ignore[union-attr]
                if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
                    content.status = ContentStatus.COMPLETED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                if self.vector_db.__class__.__name__ == "LightRag":
                    await self.aprocess_lightrag_content(content, KnowledgeContentOrigin.PATH)
                    return

                if content.reader:
                    reader = content.reader
                else:
                    reader = ReaderFactory.get_reader_for_extension(path.suffix)
                    log_debug(f"Using Reader: {reader.__class__.__name__}")

                if reader:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    read_documents = await self.reader_registry.aread(
                        reader, path, name=content.name or path.name, password=password
                    )  # type: ignore[union-attr]
                else:
                    read_documents = []

                if not content.file_type:
                    content.file_type = path.suffix

                if not content.size and content.file_data:
                    content.size = len(content.file_data.content)  # type: ignore
                if not content.size:
                    try:
                        content.size = path.stat().st_size
                    except (OSError, IOError) as e:
                        log_warning(f"Could not get file size for {path}: {e}")
                        content.size = 0

                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                await self.ahandle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            for file_path in path.iterdir():
                if not self.should_include_file(str(file_path), include, exclude):
                    log_debug(f"Skipping file {file_path} due to include/exclude filters")
                    continue

                file_content = Content(
                    name=content.name,
                    path=str(file_path),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                file_content.content_hash = self.build_content_hash(file_content)
                file_content.id = generate_id(file_content.content_hash)

                await self.aload_from_path(file_content, upsert, skip_if_exists, include, exclude)
        else:
            log_warning(f"Invalid path: {path}")

    # ==========================================
    # URL LOADING
    # ==========================================

    def load_from_url(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        from agno.utils.http import fetch_with_retry
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from URL {content.url}")
        content.file_type = "url"

        if not content.url:
            raise ValueError("No url provided")

        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        self.content_store.insert(content)  # type: ignore[union-attr]
        if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if self.vector_db.__class__.__name__ == "LightRag":
            self.process_lightrag_content(content, KnowledgeContentOrigin.URL)
            return

        try:
            from urllib.parse import urlparse

            parsed_url = urlparse(content.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                content.status = ContentStatus.FAILED
                content.status_message = f"Invalid URL format: {content.url}"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                log_warning(f"Invalid URL format: {content.url}")
        except Exception as e:
            content.status = ContentStatus.FAILED
            content.status_message = f"Invalid URL: {content.url} - {str(e)}"
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            log_warning(f"Invalid URL: {content.url} - {str(e)}")

        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        if file_extension:
            response = fetch_with_retry(content.url)
            bytes_content = BytesIO(response.content)

        name = content.name if content.name else content.url
        if file_extension:
            reader, default_name = self.reader_registry.select_reader_by_extension(file_extension, content.reader)  # type: ignore[union-attr]
            if default_name and file_extension == ".csv":
                name = basename(parsed_url.path) or default_name
        else:
            reader = content.reader or self.reader_registry.website_reader  # type: ignore[union-attr]

        try:
            read_documents = []
            if reader is not None:
                if reader.__class__.__name__ == "YouTubeReader":
                    read_documents = reader.read(content.url, name=name)
                else:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    source = bytes_content if bytes_content else content.url
                    read_documents = self.reader_registry.read(reader, source, name=name, password=password)  # type: ignore[union-attr]

        except Exception as e:
            log_error(f"Error reading URL: {content.url} - {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if reader:
            read_documents = self.chunk_documents_sync(reader, read_documents)

        docs_by_source: Dict[str, List[Document]] = {}
        for doc in read_documents:
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        if len(docs_by_source) > 1:
            for source_url, source_docs in docs_by_source.items():
                doc_hash = self.build_document_content_hash(source_docs[0], content)

                if self.should_skip(doc_hash, skip_if_exists):
                    log_debug(f"Skipping already indexed: {source_url}")
                    continue

                doc_id = generate_id(doc_hash)
                self.prepare_documents_for_insert(source_docs, doc_id, calculate_sizes=True)

                if self.vector_db.upsert_available() and upsert:
                    try:
                        self.vector_db.upsert(doc_hash, source_docs, content.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document from {source_url}: {e}")
                        continue
                else:
                    try:
                        self.vector_db.insert(doc_hash, documents=source_docs, filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document from {source_url}: {e}")
                        continue

            content.status = ContentStatus.COMPLETED
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if not content.id:
            content.id = generate_id(content.content_hash or "")
        self.prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
        self.handle_vector_db_insert(content, read_documents, upsert)

    async def aload_from_url(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from URL {content.url}")
        content.file_type = "url"

        if not content.url:
            raise ValueError("No url provided")

        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        await self.content_store.ainsert(content)  # type: ignore[union-attr]
        if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if self.vector_db.__class__.__name__ == "LightRag":
            await self.aprocess_lightrag_content(content, KnowledgeContentOrigin.URL)
            return

        try:
            from urllib.parse import urlparse

            parsed_url = urlparse(content.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                content.status = ContentStatus.FAILED
                content.status_message = f"Invalid URL format: {content.url}"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                log_warning(f"Invalid URL format: {content.url}")
        except Exception as e:
            content.status = ContentStatus.FAILED
            content.status_message = f"Invalid URL: {content.url} - {str(e)}"
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            log_warning(f"Invalid URL: {content.url} - {str(e)}")

        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        if file_extension:
            async with AsyncClient() as client:
                response = await async_fetch_with_retry(content.url, client=client)
            bytes_content = BytesIO(response.content)

        name = content.name if content.name else content.url
        if file_extension:
            reader, default_name = self.reader_registry.select_reader_by_extension(file_extension, content.reader)  # type: ignore[union-attr]
            if default_name and file_extension == ".csv":
                name = basename(parsed_url.path) or default_name
        else:
            reader = content.reader or self.reader_registry.website_reader  # type: ignore[union-attr]

        try:
            read_documents = []
            if reader is not None:
                if reader.__class__.__name__ == "YouTubeReader":
                    read_documents = await reader.async_read(content.url, name=name)
                else:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    source = bytes_content if bytes_content else content.url
                    read_documents = await self.reader_registry.aread(reader, source, name=name, password=password)  # type: ignore[union-attr]

        except Exception as e:
            log_error(f"Error reading URL: {content.url} - {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if reader and not reader.chunk:
            read_documents = await reader.chunk_documents_async(read_documents)

        docs_by_source: Dict[str, List[Document]] = {}
        for doc in read_documents:
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        if len(docs_by_source) > 1:
            for source_url, source_docs in docs_by_source.items():
                doc_hash = self.build_document_content_hash(source_docs[0], content)

                if self.should_skip(doc_hash, skip_if_exists):
                    log_debug(f"Skipping already indexed: {source_url}")
                    continue

                doc_id = generate_id(doc_hash)
                self.prepare_documents_for_insert(source_docs, doc_id, calculate_sizes=True)

                if self.vector_db.upsert_available() and upsert:
                    try:
                        await self.vector_db.async_upsert(doc_hash, source_docs, content.metadata)
                    except Exception as e:
                        log_error(f"Error upserting document from {source_url}: {e}")
                        continue
                else:
                    try:
                        await self.vector_db.async_insert(doc_hash, documents=source_docs, filters=content.metadata)
                    except Exception as e:
                        log_error(f"Error inserting document from {source_url}: {e}")
                        continue

            content.status = ContentStatus.COMPLETED
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if not content.id:
            content.id = generate_id(content.content_hash or "")
        self.prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
        await self.ahandle_vector_db_insert(content, read_documents, upsert)

    # ==========================================
    # CONTENT (file_data) LOADING
    # ==========================================

    def load_from_content(
        self,
        content: Content,
        upsert: bool = True,
        skip_if_exists: bool = False,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if content.name:
            name = content.name
        elif content.file_data and content.file_data.filename:
            name = content.file_data.filename
        elif content.file_data and content.file_data.content:
            if isinstance(content.file_data.content, bytes):
                name = content.file_data.content[:10].decode("utf-8", errors="ignore")
            elif isinstance(content.file_data.content, str):
                name = (
                    content.file_data.content[:10]
                    if len(content.file_data.content) >= 10
                    else content.file_data.content
                )
            else:
                name = str(content.file_data.content)[:10]
        else:
            name = None

        if name is not None:
            content.name = name

        log_info(f"Adding content from {content.name}")

        self.content_store.insert(content)  # type: ignore[union-attr]
        if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if content.file_data and self.vector_db.__class__.__name__ == "LightRag":
            self.process_lightrag_content(content, KnowledgeContentOrigin.CONTENT)
            return

        read_documents = []

        if isinstance(content.file_data, str):
            content_bytes = content.file_data.encode("utf-8", errors="replace")
            content_io = io.BytesIO(content_bytes)

            if content.reader:
                log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = content.reader.read(content_io, name=name)
            else:
                text_reader = self.reader_registry.text_reader  # type: ignore[union-attr]
                if text_reader:
                    read_documents = text_reader.read(content_io, name=name)
                else:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Text reader not available"
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

        elif isinstance(content.file_data, FileData):
            if content.file_data.type:
                if isinstance(content.file_data.content, bytes):
                    content_io = io.BytesIO(content.file_data.content)
                elif isinstance(content.file_data.content, str):
                    content_bytes = content.file_data.content.encode("utf-8", errors="replace")
                    content_io = io.BytesIO(content_bytes)
                else:
                    content_io = content.file_data.content  # type: ignore

                if content.reader:
                    log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                    reader = content.reader
                else:
                    reader_hint = content.file_data.type
                    if content.file_data.filename:
                        ext = Path(content.file_data.filename).suffix.lower()
                        if ext:
                            reader_hint = ext
                    reader = self.reader_registry.select_reader(reader_hint)  # type: ignore[union-attr]
                reader_name = content.file_data.filename or content.name or f"content_{content.file_data.type}"
                read_documents = reader.read(content_io, name=reader_name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                if len(read_documents) == 0:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Content could not be read"
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

        else:
            content.status = ContentStatus.FAILED
            content.status_message = "No content provided"
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        self.handle_vector_db_insert(content, read_documents, upsert)

    async def aload_from_content(
        self,
        content: Content,
        upsert: bool = True,
        skip_if_exists: bool = False,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if content.name:
            name = content.name
        elif content.file_data and content.file_data.filename:
            name = content.file_data.filename
        elif content.file_data and content.file_data.content:
            if isinstance(content.file_data.content, bytes):
                name = content.file_data.content[:10].decode("utf-8", errors="ignore")
            elif isinstance(content.file_data.content, str):
                name = (
                    content.file_data.content[:10]
                    if len(content.file_data.content) >= 10
                    else content.file_data.content
                )
            else:
                name = str(content.file_data.content)[:10]
        else:
            name = None

        if name is not None:
            content.name = name

        log_info(f"Adding content from {content.name}")

        await self.content_store.ainsert(content)  # type: ignore[union-attr]
        if self.should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if content.file_data and self.vector_db.__class__.__name__ == "LightRag":
            await self.aprocess_lightrag_content(content, KnowledgeContentOrigin.CONTENT)
            return

        read_documents = []

        if isinstance(content.file_data, str):
            content_bytes = content.file_data.encode("utf-8", errors="replace")
            content_io = io.BytesIO(content_bytes)

            if content.reader:
                log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = await content.reader.async_read(content_io, name=name)
            else:
                text_reader = self.reader_registry.text_reader  # type: ignore[union-attr]
                if text_reader:
                    read_documents = await text_reader.async_read(content_io, name=name)
                else:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Text reader not available"
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

        elif isinstance(content.file_data, FileData):
            if content.file_data.type:
                if isinstance(content.file_data.content, bytes):
                    content_io = io.BytesIO(content.file_data.content)
                elif isinstance(content.file_data.content, str):
                    content_bytes = content.file_data.content.encode("utf-8", errors="replace")
                    content_io = io.BytesIO(content_bytes)
                else:
                    content_io = content.file_data.content  # type: ignore

                if content.reader:
                    log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                    reader = content.reader
                else:
                    reader_hint = content.file_data.type
                    if content.file_data.filename:
                        ext = Path(content.file_data.filename).suffix.lower()
                        if ext:
                            reader_hint = ext
                    reader = self.reader_registry.select_reader(reader_hint)  # type: ignore[union-attr]
                reader_name = content.file_data.filename or content.name or f"content_{content.file_data.type}"
                read_documents = await reader.async_read(content_io, name=reader_name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                if len(read_documents) == 0:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Content could not be read"
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

        else:
            content.status = ContentStatus.FAILED
            content.status_message = "No content provided"
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        await self.ahandle_vector_db_insert(content, read_documents, upsert)

    # ==========================================
    # TOPIC LOADING
    # ==========================================

    def load_from_topics(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        log_info(f"Adding content from topics: {content.topics}")

        if content.topics is None:
            log_warning("No topics provided for content")
            return

        for topic in content.topics:
            content = Content(
                name=topic,
                metadata=content.metadata,
                reader=content.reader,
                status=ContentStatus.PROCESSING if content.reader else ContentStatus.FAILED,
                file_data=FileData(
                    type="Topic",
                ),
                topics=[topic],
            )
            content.content_hash = self.build_content_hash(content)
            content.id = generate_id(content.content_hash)

            self.content_store.insert(content)  # type: ignore[union-attr]
            if self.should_skip(content.content_hash, skip_if_exists):
                content.status = ContentStatus.COMPLETED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                continue

            if self.vector_db.__class__.__name__ == "LightRag":
                self.process_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue

            if self.vector_db and self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                log_info(f"Content {content.content_hash} already exists, skipping")
                continue

            if content.reader is None:
                log_error(f"No reader available for topic: {topic}")
                content.status = ContentStatus.FAILED
                content.status_message = "No reader available for topic"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                continue

            read_documents = content.reader.read(topic)
            if len(read_documents) > 0:
                self.prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
            else:
                content.status = ContentStatus.FAILED
                content.status_message = "No content found for topic"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]

            self.handle_vector_db_insert(content, read_documents, upsert)

    async def aload_from_topics(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        log_info(f"Adding content from topics: {content.topics}")

        if content.topics is None:
            log_warning("No topics provided for content")
            return

        for topic in content.topics:
            content = Content(
                name=topic,
                metadata=content.metadata,
                reader=content.reader,
                status=ContentStatus.PROCESSING if content.reader else ContentStatus.FAILED,
                file_data=FileData(
                    type="Topic",
                ),
                topics=[topic],
            )
            content.content_hash = self.build_content_hash(content)
            content.id = generate_id(content.content_hash)

            await self.content_store.ainsert(content)  # type: ignore[union-attr]
            if self.should_skip(content.content_hash, skip_if_exists):
                content.status = ContentStatus.COMPLETED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                continue

            if self.vector_db.__class__.__name__ == "LightRag":
                await self.aprocess_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue

            if self.vector_db and self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                log_info(f"Content {content.content_hash} already exists, skipping")
                continue

            if content.reader is None:
                log_error(f"No reader available for topic: {topic}")
                content.status = ContentStatus.FAILED
                content.status_message = "No reader available for topic"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                continue

            read_documents = await content.reader.async_read(topic)
            if len(read_documents) > 0:
                self.prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
            else:
                content.status = ContentStatus.FAILED
                content.status_message = "No content found for topic"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]

            await self.ahandle_vector_db_insert(content, read_documents, upsert)

    # ==========================================
    # VECTOR DB INSERT HELPERS
    # ==========================================

    def handle_vector_db_insert(self, content: Content, read_documents: List[Document], upsert: bool) -> None:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if not self.vector_db:
            log_error("No vector database configured")
            content.status = ContentStatus.FAILED
            content.status_message = "No vector database configured"
            self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                self.vector_db.upsert(content.content_hash, read_documents, content.metadata)  # type: ignore[arg-type]
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not upsert embedding"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return
        else:
            try:
                self.vector_db.insert(
                    content.content_hash,  # type: ignore[arg-type]
                    documents=read_documents,
                    filters=content.metadata,  # type: ignore[arg-type]
                )
            except Exception as e:
                log_error(f"Error inserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not insert embedding"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        content.status = ContentStatus.COMPLETED
        self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]

    async def ahandle_vector_db_insert(self, content: Content, read_documents: List[Document], upsert: bool) -> None:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if not self.vector_db:
            log_error("No vector database configured")
            content.status = ContentStatus.FAILED
            content.status_message = "No vector database configured"
            await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                await self.vector_db.async_upsert(content.content_hash, read_documents, content.metadata)  # type: ignore[arg-type]
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not upsert embedding"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return
        else:
            try:
                await self.vector_db.async_insert(
                    content.content_hash,  # type: ignore[arg-type]
                    documents=read_documents,
                    filters=content.metadata,  # type: ignore[arg-type]
                )
            except Exception as e:
                log_error(f"Error inserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not insert embedding"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        content.status = ContentStatus.COMPLETED
        await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]

    # ==========================================
    # HASHING
    # ==========================================

    def build_content_hash(self, content: Content) -> str:
        """Build the content hash from the content."""
        hash_parts = []
        if content.name:
            hash_parts.append(content.name)
        if content.description:
            hash_parts.append(content.description)

        if content.path:
            hash_parts.append(str(content.path))
        elif content.url:
            hash_parts.append(content.url)
        elif content.file_data and content.file_data.content:
            if content.file_data.filename:
                hash_parts.append(content.file_data.filename)
            elif content.file_data.type:
                hash_parts.append(content.file_data.type)
            elif content.file_data.size is not None:
                hash_parts.append(str(content.file_data.size))
            else:
                content_type = "str" if isinstance(content.file_data.content, str) else "bytes"
                content_bytes = (
                    content.file_data.content.encode()
                    if isinstance(content.file_data.content, str)
                    else content.file_data.content
                )
                content_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
                hash_parts.append(f"{content_type}:{content_hash}")
        elif content.topics and len(content.topics) > 0:
            topic = content.topics[0]
            reader = type(content.reader).__name__ if content.reader else "unknown"
            hash_parts.append(f"{topic}-{reader}")
        else:
            import random
            import string

            fallback = (
                content.name
                or content.id
                or ("unknown_content" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6)))
            )
            hash_parts.append(fallback)

        hash_input = ":".join(hash_parts)
        return hashlib.sha256(hash_input.encode()).hexdigest()

    def build_document_content_hash(self, document: Document, content: Content) -> str:
        """Build content hash for a specific document."""
        hash_parts = []

        if content.name:
            hash_parts.append(content.name)
        if content.description:
            hash_parts.append(content.description)

        doc_url = document.meta_data.get("url") if document.meta_data else None
        if doc_url:
            hash_parts.append(str(doc_url))
        elif content.url:
            hash_parts.append(content.url)
        elif content.path:
            hash_parts.append(str(content.path))
        else:
            hash_parts.append(hashlib.sha256(document.content.encode()).hexdigest()[:16])

        hash_input = ":".join(hash_parts)
        return hashlib.sha256(hash_input.encode()).hexdigest()

    # ==========================================
    # UTILITY METHODS
    # ==========================================

    def should_skip(self, content_hash: str, skip_if_exists: bool) -> bool:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db and self.vector_db.content_hash_exists(content_hash) and skip_if_exists:
            log_debug(f"Content already exists: {content_hash}, skipping...")
            return True

        return False

    def should_include_file(self, file_path: str, include: Optional[List[str]], exclude: Optional[List[str]]) -> bool:
        import fnmatch

        if include:
            if not any(fnmatch.fnmatch(file_path, pattern) for pattern in include):
                return False

        if exclude:
            if any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude):
                return False

        return True

    def is_text_mime_type(self, mime_type: str) -> bool:
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

    def prepare_documents_for_insert(
        self,
        documents: List[Document],
        content_id: str,
        calculate_sizes: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        for document in documents:
            document.content_id = content_id
            if calculate_sizes and document.content and not document.size:
                document.size = len(document.content.encode("utf-8"))
            if metadata:
                document.meta_data.update(metadata)
            if self.isolate_vector_search:
                document.meta_data["linked_to"] = self.knowledge_name or ""
        return documents

    def chunk_documents_sync(self, reader: Reader, documents: List[Document]) -> List[Document]:
        if not reader or reader.chunk:
            return documents

        chunked_documents = []
        for doc in documents:
            chunked_documents.extend(reader.chunk_document(doc))
        return chunked_documents

    # ==========================================
    # LIGHTRAG PROCESSING
    # ==========================================

    async def aprocess_lightrag_content(self, content: Content, content_type: KnowledgeContentOrigin) -> None:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        await self.content_store.ainsert(content)  # type: ignore[union-attr]
        if content_type == KnowledgeContentOrigin.PATH:
            if content.file_data is None:
                log_warning("No file data provided")

            if content.path is None:
                log_error("No path provided for content")
                return

            path = Path(content.path)

            log_info(f"Uploading file to LightRAG from path: {path}")
            try:
                with open(path, "rb") as f:
                    file_content = f.read()

                file_type = content.file_type or path.suffix

                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = await self.vector_db.insert_file_bytes(
                        file_content=file_content,
                        filename=path.name,
                        content_type=file_type,
                        send_metadata=True,
                    )

                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        elif content_type == KnowledgeContentOrigin.URL:
            log_info(f"Uploading file to LightRAG from URL: {content.url}")
            try:
                reader = content.reader or self.reader_registry.website_reader  # type: ignore[union-attr]
                if reader is None:
                    log_error("No URL reader available")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                reader.chunk = False
                read_documents = reader.read(content.url, name=content.name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    result = await self.vector_db.insert_text(
                        file_source=content.url,
                        text=read_documents[0].content,
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        elif content_type == KnowledgeContentOrigin.CONTENT:
            filename = (
                content.file_data.filename if content.file_data and content.file_data.filename else "uploaded_file"
            )
            log_info(f"Uploading file to LightRAG: {filename}")

            if content.file_data and content.file_data.content:
                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = await self.vector_db.insert_file_bytes(
                        file_content=content.file_data.content,
                        filename=filename,
                        content_type=content.file_data.type,
                        send_metadata=True,
                    )
                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            else:
                log_warning(f"No file data available for LightRAG upload: {content.name}")
            return

        elif content_type == KnowledgeContentOrigin.TOPIC:
            log_info(f"Uploading file to LightRAG: {content.name}")

            if content.reader is None:
                log_error("No reader available for topic content")
                content.status = ContentStatus.FAILED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            if not content.topics:
                log_error("No topics available for content")
                content.status = ContentStatus.FAILED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            read_documents = content.reader.read(content.topics)
            if len(read_documents) > 0:
                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    result = await self.vector_db.insert_text(
                        file_source=content.topics[0],
                        text=read_documents[0].content,
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self.content_store.aupdate(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return
            else:
                log_warning(f"No documents found for LightRAG upload: {content.name}")
                return

    def process_lightrag_content(self, content: Content, content_type: KnowledgeContentOrigin) -> None:
        """Synchronously process LightRAG content. Uses asyncio.run() only for LightRAG-specific async methods."""
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        self.content_store.insert(content)  # type: ignore[union-attr]
        if content_type == KnowledgeContentOrigin.PATH:
            if content.file_data is None:
                log_warning("No file data provided")

            if content.path is None:
                log_error("No path provided for content")
                return

            path = Path(content.path)

            log_info(f"Uploading file to LightRAG from path: {path}")
            try:
                with open(path, "rb") as f:
                    file_content = f.read()

                file_type = content.file_type or path.suffix

                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = asyncio.run(
                        self.vector_db.insert_file_bytes(
                            file_content=file_content,
                            filename=path.name,
                            content_type=file_type,
                            send_metadata=True,
                        )
                    )
                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        elif content_type == KnowledgeContentOrigin.URL:
            log_info(f"Uploading file to LightRAG from URL: {content.url}")
            try:
                reader = content.reader or self.reader_registry.website_reader  # type: ignore[union-attr]
                if reader is None:
                    log_error("No URL reader available")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                reader.chunk = False
                read_documents = reader.read(content.url, name=content.name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self.prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    result = asyncio.run(
                        self.vector_db.insert_text(
                            file_source=content.url,
                            text=read_documents[0].content,
                        )
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return

                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

        elif content_type == KnowledgeContentOrigin.CONTENT:
            filename = (
                content.file_data.filename if content.file_data and content.file_data.filename else "uploaded_file"
            )
            log_info(f"Uploading file to LightRAG: {filename}")

            if content.file_data and content.file_data.content:
                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = asyncio.run(
                        self.vector_db.insert_file_bytes(
                            file_content=content.file_data.content,
                            filename=filename,
                            content_type=content.file_data.type,
                            send_metadata=True,
                        )
                    )
                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
            else:
                log_warning(f"No file data available for LightRAG upload: {content.name}")
            return

        elif content_type == KnowledgeContentOrigin.TOPIC:
            log_info(f"Uploading file to LightRAG: {content.name}")

            if content.reader is None:
                log_error("No reader available for topic content")
                content.status = ContentStatus.FAILED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            if not content.topics:
                log_error("No topics available for content")
                content.status = ContentStatus.FAILED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return

            read_documents = content.reader.read(content.topics)
            if len(read_documents) > 0:
                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    result = asyncio.run(
                        self.vector_db.insert_text(
                            file_source=content.topics[0],
                            text=read_documents[0].content,
                        )
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self.content_store.update(content, vector_db=self.vector_db)  # type: ignore[union-attr]
                return
            else:
                log_warning(f"No documents found for LightRAG upload: {content.name}")
                return
