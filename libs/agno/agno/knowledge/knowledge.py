import asyncio
import hashlib
import io
import time
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from os.path import basename
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast, overload

from httpx import AsyncClient

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.filters import EQ, FilterExpr
from agno.knowledge.content import Content, ContentAuth, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.reader import Reader, ReaderFactory
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.remote_content import (
    RemoteContent,
)
from agno.knowledge.remote_knowledge import RemoteKnowledge
from agno.knowledge.utils import merge_user_metadata, set_agno_metadata, strip_agno_metadata
from agno.utils.http import async_fetch_with_retry
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

ContentDict = Dict[str, Union[str, Dict[str, str]]]


class KnowledgeContentOrigin(Enum):
    PATH = "path"
    URL = "url"
    TOPIC = "topic"
    CONTENT = "content"


@dataclass
class Knowledge(RemoteKnowledge):
    """Knowledge class"""

    name: Optional[str] = None
    description: Optional[str] = None
    vector_db: Optional[Any] = None
    contents_db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None
    content_sources: Optional[List[BaseStorageConfig]] = None
    # When True, adds linked_to metadata during insert and filters by it during search.
    # This enables isolation when multiple Knowledge instances share the same vector database.
    # Requires re-indexing existing data to add linked_to metadata.
    # Default is False for backwards compatibility with existing data.
    isolate_vector_search: bool = False

    def __post_init__(self):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db and not self.vector_db.exists():
            self.vector_db.create()

        self.construct_readers()

    # ==========================================
    # PUBLIC API - INSERT METHODS
    # ==========================================

    # --- Insert (Single Content) ---
    @overload
    def insert(
        self,
        *,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        reader: Optional[Reader] = None,
        auth: Optional[ContentAuth] = None,
    ) -> None: ...

    @overload
    def insert(self, *args, **kwargs) -> None: ...

    def insert(
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
        skip_if_exists: bool = False,
        auth: Optional[ContentAuth] = None,
    ) -> None:
        """
        Synchronously insert content into the knowledge base.

        Args:
            name: Optional name for the content
            description: Optional description for the content
            path: Optional file path to load content from
            url: Optional URL to load content from
            text_content: Optional text content to insert directly
            metadata: Optional metadata dictionary
            topics: Optional list of topics
            remote_content: Optional cloud storage configuration
            reader: Optional custom reader for processing the content
            include: Optional list of file patterns to include
            exclude: Optional list of file patterns to exclude
            upsert: Whether to update existing content if it already exists (only used when skip_if_exists=False)
            skip_if_exists: Whether to skip inserting content if it already exists (default: False)
        """
        # Validation: At least one of the parameters must be provided
        if all(argument is None for argument in [path, url, text_content, topics, remote_content]):
            log_warning(
                "At least one of 'path', 'url', 'text_content', 'topics', or 'remote_content' must be provided."
            )
            return

        # Strip reserved _agno key from user-provided metadata
        safe_metadata = strip_agno_metadata(metadata)

        content = None
        file_data = None
        if text_content:
            file_data = FileData(content=text_content, type="Text")

        content = Content(
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=file_data if file_data else None,
            metadata=safe_metadata,
            topics=topics,
            remote_content=remote_content,
            reader=reader,
            auth=auth,
        )
        content.content_hash = self._build_content_hash(content)
        content.id = generate_id(content.content_hash)

        self._load_content(content, upsert, skip_if_exists, include, exclude)

    @overload
    async def ainsert(
        self,
        *,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        reader: Optional[Reader] = None,
        auth: Optional[ContentAuth] = None,
    ) -> None: ...

    @overload
    async def ainsert(self, *args, **kwargs) -> None: ...

    async def ainsert(
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
        skip_if_exists: bool = False,
        auth: Optional[ContentAuth] = None,
    ) -> None:
        # Validation: At least one of the parameters must be provided
        if all(argument is None for argument in [path, url, text_content, topics, remote_content]):
            log_warning(
                "At least one of 'path', 'url', 'text_content', 'topics', or 'remote_content' must be provided."
            )
            return

        # Strip reserved _agno key from user-provided metadata
        safe_metadata = strip_agno_metadata(metadata)

        content = None
        file_data = None
        if text_content:
            file_data = FileData(content=text_content, type="Text")

        content = Content(
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=file_data if file_data else None,
            metadata=safe_metadata,
            topics=topics,
            remote_content=remote_content,
            reader=reader,
            auth=auth,
        )
        content.content_hash = self._build_content_hash(content)
        content.id = generate_id(content.content_hash)

        await self._aload_content(content, upsert, skip_if_exists, include, exclude)

    # --- Insert Many ---
    @overload
    async def ainsert_many(self, contents: List[ContentDict]) -> None: ...

    @overload
    async def ainsert_many(
        self,
        *,
        paths: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
        topics: Optional[List[str]] = None,
        text_contents: Optional[List[str]] = None,
        reader: Optional[Reader] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        remote_content: Optional[RemoteContent] = None,
    ) -> None: ...

    async def ainsert_many(self, *args, **kwargs) -> None:
        if args and isinstance(args[0], list):
            arguments = args[0]
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            for argument in arguments:
                await self.ainsert(
                    name=argument.get("name"),
                    description=argument.get("description"),
                    path=argument.get("path"),
                    url=argument.get("url"),
                    metadata=argument.get("metadata"),
                    topics=argument.get("topics"),
                    text_content=argument.get("text_content"),
                    reader=argument.get("reader"),
                    include=argument.get("include"),
                    exclude=argument.get("exclude"),
                    upsert=argument.get("upsert", upsert),
                    skip_if_exists=argument.get("skip_if_exists", skip_if_exists),
                    remote_content=argument.get("remote_content", None),
                    auth=argument.get("auth"),
                )

        elif kwargs:
            name = kwargs.get("name", [])
            metadata = kwargs.get("metadata", {})
            description = kwargs.get("description", [])
            topics = kwargs.get("topics", [])
            reader = kwargs.get("reader", None)
            paths = kwargs.get("paths", [])
            urls = kwargs.get("urls", [])
            text_contents = kwargs.get("text_contents", [])
            include = kwargs.get("include")
            exclude = kwargs.get("exclude")
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            remote_content = kwargs.get("remote_content", None)
            auth = kwargs.get("auth")
            for path in paths:
                await self.ainsert(
                    name=name,
                    description=description,
                    path=path,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            for url in urls:
                await self.ainsert(
                    name=name,
                    description=description,
                    url=url,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            for i, text_content in enumerate(text_contents):
                content_name = f"{name}_{i}" if name else f"text_content_{i}"
                log_debug(f"Adding text content: {content_name}")
                await self.ainsert(
                    name=content_name,
                    description=description,
                    text_content=text_content,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            if topics:
                await self.ainsert(
                    name=name,
                    description=description,
                    topics=topics,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )

            if remote_content:
                await self.ainsert(
                    name=name,
                    metadata=metadata,
                    description=description,
                    remote_content=remote_content,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )

        else:
            raise ValueError("Invalid usage of insert_many.")

    @overload
    def insert_many(self, contents: List[ContentDict]) -> None: ...

    @overload
    def insert_many(
        self,
        *,
        paths: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
        topics: Optional[List[str]] = None,
        text_contents: Optional[List[str]] = None,
        reader: Optional[Reader] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        remote_content: Optional[RemoteContent] = None,
    ) -> None: ...

    def insert_many(self, *args, **kwargs) -> None:
        """
        Synchronously insert multiple content items into the knowledge base.

        Supports two usage patterns:
        1. Pass a list of content dictionaries as first argument
        2. Pass keyword arguments with paths, urls, metadata, etc.

        Args:
            contents: List of content dictionaries (when used as first overload)
            paths: Optional list of file paths to load content from
            urls: Optional list of URLs to load content from
            metadata: Optional metadata dictionary to apply to all content
            topics: Optional list of topics to insert
            text_contents: Optional list of text content strings to insert
            reader: Optional reader to use for processing content
            include: Optional list of file patterns to include
            exclude: Optional list of file patterns to exclude
            upsert: Whether to update existing content if it already exists (only used when skip_if_exists=False)
            skip_if_exists: Whether to skip inserting content if it already exists (default: True)
            remote_content: Optional remote content (S3, GCS, etc.) to insert
        """
        if args and isinstance(args[0], list):
            arguments = args[0]
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            for argument in arguments:
                self.insert(
                    name=argument.get("name"),
                    description=argument.get("description"),
                    path=argument.get("path"),
                    url=argument.get("url"),
                    metadata=argument.get("metadata"),
                    topics=argument.get("topics"),
                    text_content=argument.get("text_content"),
                    reader=argument.get("reader"),
                    include=argument.get("include"),
                    exclude=argument.get("exclude"),
                    upsert=argument.get("upsert", upsert),
                    skip_if_exists=argument.get("skip_if_exists", skip_if_exists),
                    remote_content=argument.get("remote_content", None),
                    auth=argument.get("auth"),
                )

        elif kwargs:
            name = kwargs.get("name", [])
            metadata = kwargs.get("metadata", {})
            description = kwargs.get("description", [])
            topics = kwargs.get("topics", [])
            reader = kwargs.get("reader", None)
            paths = kwargs.get("paths", [])
            urls = kwargs.get("urls", [])
            text_contents = kwargs.get("text_contents", [])
            include = kwargs.get("include")
            exclude = kwargs.get("exclude")
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            remote_content = kwargs.get("remote_content", None)
            auth = kwargs.get("auth")
            for path in paths:
                self.insert(
                    name=name,
                    description=description,
                    path=path,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            for url in urls:
                self.insert(
                    name=name,
                    description=description,
                    url=url,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            for i, text_content in enumerate(text_contents):
                content_name = f"{name}_{i}" if name else f"text_content_{i}"
                log_debug(f"Adding text content: {content_name}")
                self.insert(
                    name=content_name,
                    description=description,
                    text_content=text_content,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )
            if topics:
                self.insert(
                    name=name,
                    description=description,
                    topics=topics,
                    metadata=metadata,
                    include=include,
                    exclude=exclude,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )

            if remote_content:
                self.insert(
                    name=name,
                    metadata=metadata,
                    description=description,
                    remote_content=remote_content,
                    upsert=upsert,
                    skip_if_exists=skip_if_exists,
                    reader=reader,
                    auth=auth,
                )

        else:
            raise ValueError("Invalid usage of insert_many.")

    # ==========================================
    # PUBLIC API - SEARCH METHODS
    # ==========================================

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_type: Optional[str] = None,
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        from agno.vectordb import VectorDb
        from agno.vectordb.search import SearchType

        self.vector_db = cast(VectorDb, self.vector_db)

        if (
            hasattr(self.vector_db, "search_type")
            and isinstance(self.vector_db.search_type, SearchType)
            and search_type
        ):
            self.vector_db.search_type = SearchType(search_type)
        try:
            if self.vector_db is None:
                log_warning("No vector db provided")
                return []

            # Inject linked_to filter when isolate_vector_search is enabled and knowledge has a name
            search_filters = filters
            if self.isolate_vector_search and self.name:
                if search_filters is None:
                    search_filters = {"linked_to": self.name}
                elif isinstance(search_filters, dict):
                    search_filters = {**search_filters, "linked_to": self.name}
                elif isinstance(search_filters, list):
                    search_filters = [EQ("linked_to", self.name), *search_filters]

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            return self.vector_db.search(query=query, limit=_max_results, filters=search_filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    async def asearch(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_type: Optional[str] = None,
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        from agno.vectordb import VectorDb
        from agno.vectordb.search import SearchType

        self.vector_db = cast(VectorDb, self.vector_db)
        if (
            hasattr(self.vector_db, "search_type")
            and isinstance(self.vector_db.search_type, SearchType)
            and search_type
        ):
            self.vector_db.search_type = SearchType(search_type)
        try:
            if self.vector_db is None:
                log_warning("No vector db provided")
                return []

            # Inject linked_to filter when isolate_vector_search is enabled and knowledge has a name
            search_filters = filters
            if self.isolate_vector_search and self.name:
                if search_filters is None:
                    search_filters = {"linked_to": self.name}
                elif isinstance(search_filters, dict):
                    search_filters = {**search_filters, "linked_to": self.name}
                elif isinstance(search_filters, list):
                    search_filters = [EQ("linked_to", self.name), *search_filters]

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            try:
                return await self.vector_db.async_search(query=query, limit=_max_results, filters=search_filters)
            except NotImplementedError:
                log_info("Vector db does not support async search")
                return self.vector_db.search(query=query, limit=_max_results, filters=search_filters)
        except Exception as e:
            log_error(f"Error searching for documents: {e}")
            return []

    # ==========================================
    # PUBLIC API - CONTENT MANAGEMENT METHODS
    # ==========================================

    def get_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError("get_content() is not supported for async databases. Please use aget_content() instead.")

        # Filter by linked_to when knowledge has a name for isolation
        contents, count = self.contents_db.get_knowledge_contents(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.name
        )
        return [self._content_row_to_content(row) for row in contents], count

    async def aget_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        # Filter by linked_to when knowledge has a name for isolation
        if isinstance(self.contents_db, AsyncBaseDb):
            contents, count = await self.contents_db.get_knowledge_contents(
                limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.name
            )
        else:
            contents, count = self.contents_db.get_knowledge_contents(
                limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.name
            )
        return [self._content_row_to_content(row) for row in contents], count

    def get_content_by_id(self, content_id: str) -> Optional[Content]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError(
                "get_content_by_id() is not supported for async databases. Please use aget_content_by_id() instead."
            )

        content_row = self.contents_db.get_knowledge_content(content_id)
        if content_row is None:
            return None
        return self._content_row_to_content(content_row)

    async def aget_content_by_id(self, content_id: str) -> Optional[Content]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            content_row = await self.contents_db.get_knowledge_content(content_id)
        else:
            content_row = self.contents_db.get_knowledge_content(content_id)

        if content_row is None:
            return None
        return self._content_row_to_content(content_row)

    def get_content_status(self, content_id: str) -> Tuple[Optional[ContentStatus], Optional[str]]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError(
                "get_content_status() is not supported for async databases. Please use aget_content_status() instead."
            )

        content_row = self.contents_db.get_knowledge_content(content_id)
        if content_row is None:
            return None, "Content not found"

        return self._parse_content_status(content_row.status), content_row.status_message

    async def aget_content_status(self, content_id: str) -> Tuple[Optional[ContentStatus], Optional[str]]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            content_row = await self.contents_db.get_knowledge_content(content_id)
        else:
            content_row = self.contents_db.get_knowledge_content(content_id)

        if content_row is None:
            return None, "Content not found"

        return self._parse_content_status(content_row.status), content_row.status_message

    def patch_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return self._update_content(content)

    async def apatch_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return await self._aupdate_content(content)

    def remove_content_by_id(self, content_id: str):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db is not None:
            if self.vector_db.__class__.__name__ == "LightRag":
                # For LightRAG, get the content first to find the external_id
                content = self.get_content_by_id(content_id)
                if content and content.external_id:
                    self.vector_db.delete_by_external_id(content.external_id)  # type: ignore
                else:
                    log_warning(f"No external_id found for content {content_id}, cannot delete from LightRAG")
            else:
                self.vector_db.delete_by_content_id(content_id)

        if self.contents_db is not None:
            self.contents_db.delete_knowledge_content(content_id)

    async def aremove_content_by_id(self, content_id: str):
        if self.vector_db is not None:
            if self.vector_db.__class__.__name__ == "LightRag":
                # For LightRAG, get the content first to find the external_id
                content = await self.aget_content_by_id(content_id)
                if content and content.external_id:
                    self.vector_db.delete_by_external_id(content.external_id)  # type: ignore
                else:
                    log_warning(f"No external_id found for content {content_id}, cannot delete from LightRAG")
            else:
                self.vector_db.delete_by_content_id(content_id)

        if self.contents_db is not None:
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.delete_knowledge_content(content_id)
            else:
                self.contents_db.delete_knowledge_content(content_id)

    def remove_all_content(self):
        contents, _ = self.get_content()
        for content in contents:
            if content.id is not None:
                self.remove_content_by_id(content.id)

    async def aremove_all_content(self):
        contents, _ = await self.aget_content()
        for content in contents:
            if content.id is not None:
                await self.aremove_content_by_id(content.id)

    def remove_vector_by_id(self, id: str) -> bool:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return False
        return self.vector_db.delete_by_id(id)

    def remove_vectors_by_name(self, name: str) -> bool:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return False
        return self.vector_db.delete_by_name(name)

    def remove_vectors_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db is None:
            log_warning("No vector DB provided")
            return False
        return self.vector_db.delete_by_metadata(metadata)

    # ==========================================
    # PUBLIC API - FILTER METHODS
    # ==========================================

    def get_valid_filters(self) -> Set[str]:
        if self.contents_db is None:
            log_info("Advanced filtering is not supported without a contents db. All filter keys considered valid.")
            return set()
        contents, _ = self.get_content()
        valid_filters: Set[str] = set()
        for content in contents:
            if content.metadata:
                valid_filters.update(content.metadata.keys())

        return valid_filters

    async def aget_valid_filters(self) -> Set[str]:
        if self.contents_db is None:
            log_info("Advanced filtering is not supported without a contents db. All filter keys considered valid.")
            return set()
        contents, _ = await self.aget_content()
        valid_filters: Set[str] = set()
        for content in contents:
            if content.metadata:
                valid_filters.update(content.metadata.keys())

        return valid_filters

    def validate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        valid_filters_from_db = self.get_valid_filters()

        valid_filters, invalid_keys = self._validate_filters(filters, valid_filters_from_db)

        return valid_filters, invalid_keys

    async def avalidate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        """Return a tuple containing a dict with all valid filters and a list of invalid filter keys"""
        valid_filters_from_db = await self.aget_valid_filters()

        valid_filters, invalid_keys = self._validate_filters(filters, valid_filters_from_db)

        return valid_filters, invalid_keys

    def _validate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]], valid_metadata_filters: Set[str]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        if not filters:
            return {}, []

        valid_filters: Union[Dict[str, Any], List[FilterExpr]] = {}
        invalid_keys = []

        if isinstance(filters, dict):
            # If no metadata filters tracked yet, all keys are considered invalid
            if valid_metadata_filters is None or not valid_metadata_filters:
                invalid_keys = list(filters.keys())
                log_warning(
                    f"No valid metadata filters tracked yet. All filter keys considered invalid: {invalid_keys}"
                )
                return {}, invalid_keys

            for key, value in filters.items():
                # Handle both normal keys and prefixed keys like meta_data.key
                base_key = key.split(".")[-1] if "." in key else key
                if base_key in valid_metadata_filters or key in valid_metadata_filters:
                    valid_filters[key] = value  # type: ignore
                else:
                    invalid_keys.append(key)
                    log_warning(f"Invalid filter key: {key} - not present in knowledge base")

        elif isinstance(filters, List):
            # Validate list filters against known metadata keys
            if valid_metadata_filters is None or not valid_metadata_filters:
                # Can't validate keys without metadata - return original list
                log_warning("No valid metadata filters tracked yet. Cannot validate list filter keys.")
                return filters, []

            valid_list_filters: List[FilterExpr] = []
            for i, filter_item in enumerate(filters):
                if not isinstance(filter_item, FilterExpr):
                    log_warning(
                        f"Invalid filter at index {i}: expected FilterExpr instance, "
                        f"got {type(filter_item).__name__}. "
                        f"Use filter expressions like EQ('key', 'value'), IN('key', [values]), "
                        f"AND(...), OR(...), NOT(...) from agno.filters"
                    )
                    continue

                # Check if filter has a key attribute and validate it
                if hasattr(filter_item, "key"):
                    key = filter_item.key
                    base_key = key.split(".")[-1] if "." in key else key
                    if base_key in valid_metadata_filters or key in valid_metadata_filters:
                        valid_list_filters.append(filter_item)
                    else:
                        invalid_keys.append(key)
                        log_warning(f"Invalid filter key: {key} - not present in knowledge base")
                else:
                    # Complex filters (AND, OR, NOT) - keep them as-is
                    # They contain nested filters that will be validated by the vector DB
                    valid_list_filters.append(filter_item)

            return valid_list_filters, invalid_keys

        return valid_filters, invalid_keys

    # ==========================================
    # PUBLIC API - READER MANAGEMENT METHODS
    # ==========================================

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

    def get_readers(self) -> Dict[str, Reader]:
        """Get all currently loaded readers (only returns readers that have been used)."""
        if self.readers is None:
            self.readers = {}
        elif not isinstance(self.readers, dict):
            # Defensive check: if readers is not a dict (e.g., was set to a list), convert it
            if isinstance(self.readers, list):
                readers_dict: Dict[str, Reader] = {}
                for reader in self.readers:
                    if isinstance(reader, Reader):
                        reader_key = self._generate_reader_key(reader)
                        # Handle potential duplicate keys by appending index if needed
                        original_key = reader_key
                        counter = 1
                        while reader_key in readers_dict:
                            reader_key = f"{original_key}_{counter}"
                            counter += 1
                        readers_dict[reader_key] = reader
                self.readers = readers_dict
            else:
                # For any other unexpected type, reset to empty dict
                self.readers = {}

        return self.readers

    # --- Reader Helper Methods ---

    def _generate_reader_key(self, reader: Reader) -> str:
        """Generate a key for a reader instance."""
        if reader.name:
            return f"{reader.name.lower().replace(' ', '_')}"
        else:
            return f"{reader.__class__.__name__.lower().replace(' ', '_')}"

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

    def _select_reader(self, extension: str) -> Reader:
        """Select the appropriate reader for a file extension."""
        log_info(f"Selecting reader for extension: {extension}")
        return ReaderFactory.get_reader_for_extension(extension)

    def _should_include_file(self, file_path: str, include: Optional[List[str]], exclude: Optional[List[str]]) -> bool:
        """
        Determine if a file should be included based on include/exclude patterns.

        Logic:
        1. If include is specified, file must match at least one include pattern
        2. If exclude is specified, file must not match any exclude pattern
        3. If neither specified, include all files

        Patterns without path separators (e.g. ``*.go``) are matched against
        the filename only so they work when *file_path* is a full or relative
        path that contains directories.

        Args:
            file_path: Path to the file to check
            include: Optional list of include patterns (glob-style)
            exclude: Optional list of exclude patterns (glob-style)

        Returns:
            bool: True if file should be included, False otherwise
        """
        import fnmatch
        import os

        file_name = os.path.basename(file_path)

        def _matches(path: str, name: str, pattern: str) -> bool:
            """Match pattern against both the full path and the basename."""
            return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)

        # If include patterns specified, file must match at least one
        if include:
            if not any(_matches(file_path, file_name, pattern) for pattern in include):
                return False

        # If exclude patterns specified, file must not match any
        if exclude:
            if any(_matches(file_path, file_name, pattern) for pattern in exclude):
                return False

        return True

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

    # --- Reader Properties (Lazy Loading) ---

    @property
    def pdf_reader(self) -> Optional[Reader]:
        """PDF reader - lazy loaded via factory."""
        return self._get_reader("pdf")

    @property
    def csv_reader(self) -> Optional[Reader]:
        """CSV reader - lazy loaded via factory."""
        return self._get_reader("csv")

    @property
    def excel_reader(self) -> Optional[Reader]:
        """Excel reader - lazy loaded via factory."""
        return self._get_reader("excel")

    @property
    def docx_reader(self) -> Optional[Reader]:
        """Docx reader - lazy loaded via factory."""
        return self._get_reader("docx")

    @property
    def pptx_reader(self) -> Optional[Reader]:
        """PPTX reader - lazy loaded via factory."""
        return self._get_reader("pptx")

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
    def youtube_reader(self) -> Optional[Reader]:
        """YouTube reader - lazy loaded via factory."""
        return self._get_reader("youtube")

    # ==========================================
    # PRIVATE - CONTENT LOADING METHODS
    # ==========================================

    def _load_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """Synchronously load content."""
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

    async def _aload_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        if content.path:
            await self._aload_from_path(content, upsert, skip_if_exists, include, exclude)

        if content.url:
            await self._aload_from_url(content, upsert, skip_if_exists)

        if content.file_data:
            await self._aload_from_content(content, upsert, skip_if_exists)

        if content.topics:
            await self._aload_from_topics(content, upsert, skip_if_exists)

        if content.remote_content:
            await self._aload_from_remote_content(content, upsert, skip_if_exists)

    def _should_skip(self, content_hash: str, skip_if_exists: bool) -> bool:
        """
        Handle the skip_if_exists logic for content that already exists in the vector database.

        Args:
            content_hash: The content hash string to check for existence
            skip_if_exists: Whether to skip if content already exists

        Returns:
            bool: True if should skip processing, False if should continue
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db and self.vector_db.content_hash_exists(content_hash) and skip_if_exists:
            log_debug(f"Content already exists: {content_hash}, skipping...")
            return True

        return False

    def _select_reader_by_extension(
        self, file_extension: str, provided_reader: Optional[Reader] = None
    ) -> Tuple[Optional[Reader], str]:
        """
        Select a reader based on file extension.

        Args:
            file_extension: File extension (e.g., '.pdf', '.csv')
            provided_reader: Optional reader already provided

        Returns:
            Tuple of (reader, name) where name may be adjusted based on extension
        """
        if provided_reader:
            return provided_reader, ""

        file_extension = file_extension.lower()
        if file_extension == ".csv":
            return self.csv_reader, "data.csv"
        elif file_extension == ".pdf":
            return self.pdf_reader, ""
        elif file_extension == ".docx":
            return self.docx_reader, ""
        elif file_extension == ".pptx":
            return self.pptx_reader, ""
        elif file_extension == ".json":
            return self.json_reader, ""
        elif file_extension == ".markdown":
            return self.markdown_reader, ""
        elif file_extension in [".xlsx", ".xls"]:
            return self.excel_reader, ""
        else:
            return self.text_reader, ""

    def _select_reader_by_uri(self, uri: str, provided_reader: Optional[Reader] = None) -> Optional[Reader]:
        """
        Select a reader based on URI/file path extension.

        Args:
            uri: URI or file path
            provided_reader: Optional reader already provided

        Returns:
            Selected reader or None
        """
        if provided_reader:
            return provided_reader

        uri_lower = uri.lower()
        if uri_lower.endswith(".pdf"):
            return self.pdf_reader
        elif uri_lower.endswith(".csv"):
            return self.csv_reader
        elif uri_lower.endswith(".docx"):
            return self.docx_reader
        elif uri_lower.endswith(".pptx"):
            return self.pptx_reader
        elif uri_lower.endswith(".json"):
            return self.json_reader
        elif uri_lower.endswith(".markdown"):
            return self.markdown_reader
        elif uri_lower.endswith(".xlsx") or uri_lower.endswith(".xls"):
            return self.excel_reader
        else:
            return self.text_reader

    def _read(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """
        Read content using a reader with optional password handling.

        Args:
            reader: Reader to use
            source: Source to read from (Path, URL string, or BytesIO)
            name: Optional name for the document
            password: Optional password for protected files

        Returns:
            List of documents read
        """
        import inspect

        read_signature = inspect.signature(reader.read)
        if password is not None and "password" in read_signature.parameters:
            if isinstance(source, BytesIO):
                return reader.read(source, name=name, password=password)
            else:
                return reader.read(source, name=name, password=password)
        else:
            if isinstance(source, BytesIO):
                return reader.read(source, name=name)
            else:
                return reader.read(source, name=name)

    async def _aread(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """
        Read content using a reader's async_read method with optional password handling.

        Args:
            reader: Reader to use
            source: Source to read from (Path, URL string, or BytesIO)
            name: Optional name for the document
            password: Optional password for protected files

        Returns:
            List of documents read
        """
        import inspect

        read_signature = inspect.signature(reader.async_read)
        if password is not None and "password" in read_signature.parameters:
            return await reader.async_read(source, name=name, password=password)
        else:
            if isinstance(source, BytesIO):
                return await reader.async_read(source, name=name)
            else:
                return await reader.async_read(source, name=name)

    def _prepare_documents_for_insert(
        self,
        documents: List[Document],
        content_id: str,
        calculate_sizes: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Prepare documents for insertion by assigning content_id and optionally calculating sizes and updating metadata.

        Args:
            documents: List of documents to prepare
            content_id: Content ID to assign to documents
            calculate_sizes: Whether to calculate document sizes
            metadata: Optional metadata to merge into document metadata

        Returns:
            List of prepared documents
        """
        for document in documents:
            document.content_id = content_id
            if calculate_sizes and document.content and not document.size:
                document.size = len(document.content.encode("utf-8"))
            if metadata:
                document.meta_data.update(metadata)
            document.meta_data["linked_to"] = self.name or ""
        return documents

    def _chunk_documents_sync(self, reader: Reader, documents: List[Document]) -> List[Document]:
        """
        Chunk documents synchronously.

        Args:
            reader: Reader with chunking strategy
            documents: Documents to chunk

        Returns:
            List of chunked documents
        """
        if not reader or reader.chunk:
            return documents

        chunked_documents = []
        for doc in documents:
            chunked_documents.extend(reader.chunk_document(doc))
        return chunked_documents

    async def _aload_from_path(
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
            if self._should_include_file(str(path), include, exclude):
                log_debug(f"Adding file {path} due to include/exclude filters")

                # Set name from path if not provided
                if not content.name:
                    content.name = path.name

                await self._ainsert_contents_db(content)
                if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
                    content.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content)
                    return

                # Handle LightRAG special case - read file and upload directly
                if self.vector_db.__class__.__name__ == "LightRag":
                    await self._aprocess_lightrag_content(content, KnowledgeContentOrigin.PATH)
                    return

                if content.reader:
                    reader = content.reader
                else:
                    reader = ReaderFactory.get_reader_for_extension(path.suffix)
                    log_debug(f"Using Reader: {reader.__class__.__name__}")

                if reader:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    read_documents = await self._aread(reader, path, name=content.name or path.name, password=password)
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
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                await self._ahandle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            for file_path in path.iterdir():
                # Apply include/exclude filtering
                if not self._should_include_file(str(file_path), include, exclude):
                    log_debug(f"Skipping file {file_path} due to include/exclude filters")
                    continue

                file_content = Content(
                    name=content.name,
                    path=str(file_path),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                file_content.content_hash = self._build_content_hash(file_content)
                file_content.id = generate_id(file_content.content_hash)

                await self._aload_from_path(file_content, upsert, skip_if_exists, include, exclude)
        else:
            log_warning(f"Invalid path: {path}")

    def _load_from_path(
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
            if self._should_include_file(str(path), include, exclude):
                log_debug(f"Adding file {path} due to include/exclude filters")

                # Set name from path if not provided
                if not content.name:
                    content.name = path.name

                self._insert_contents_db(content)
                if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
                    content.status = ContentStatus.COMPLETED
                    self._update_content(content)
                    return

                # Handle LightRAG special case - read file and upload directly
                if self.vector_db.__class__.__name__ == "LightRag":
                    self._process_lightrag_content(content, KnowledgeContentOrigin.PATH)
                    return

                if content.reader:
                    reader = content.reader
                else:
                    reader = ReaderFactory.get_reader_for_extension(path.suffix)
                    log_debug(f"Using Reader: {reader.__class__.__name__}")

                if reader:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    read_documents = self._read(reader, path, name=content.name or path.name, password=password)
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
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                self._handle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            for file_path in path.iterdir():
                # Apply include/exclude filtering
                if not self._should_include_file(str(file_path), include, exclude):
                    log_debug(f"Skipping file {file_path} due to include/exclude filters")
                    continue

                file_content = Content(
                    name=content.name,
                    path=str(file_path),
                    metadata=content.metadata,
                    description=content.description,
                    reader=content.reader,
                )
                file_content.content_hash = self._build_content_hash(file_content)
                file_content.id = generate_id(file_content.content_hash)

                self._load_from_path(file_content, upsert, skip_if_exists, include, exclude)
        else:
            log_warning(f"Invalid path: {path}")

    async def _aload_from_url(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Load the content in the contextual URL

        1. Set content hash
        2. Validate the URL
        3. Read the content
        4. Prepare and insert the content in the vector database
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from URL {content.url}")
        content.file_type = "url"

        if not content.url:
            raise ValueError("No url provided")

        # Store URL source metadata in _agno for source tracking
        content.metadata = set_agno_metadata(content.metadata, "source_type", "url")
        content.metadata = set_agno_metadata(content.metadata, "source_url", content.url)

        # Set name from URL if not provided
        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        # 1. Add content to contents database
        await self._ainsert_contents_db(content)
        if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            await self._aupdate_content(content)
            return

        if self.vector_db.__class__.__name__ == "LightRag":
            await self._aprocess_lightrag_content(content, KnowledgeContentOrigin.URL)
            return

        # 2. Validate URL
        try:
            from urllib.parse import urlparse

            parsed_url = urlparse(content.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                content.status = ContentStatus.FAILED
                content.status_message = f"Invalid URL format: {content.url}"
                await self._aupdate_content(content)
                log_warning(f"Invalid URL format: {content.url}")
        except Exception as e:
            content.status = ContentStatus.FAILED
            content.status_message = f"Invalid URL: {content.url} - {str(e)}"
            await self._aupdate_content(content)
            log_warning(f"Invalid URL: {content.url} - {str(e)}")
        # 3. Fetch and load content if file has an extension
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        if file_extension:
            async with AsyncClient() as client:
                response = await async_fetch_with_retry(content.url, client=client)
            bytes_content = BytesIO(response.content)

        # 4. Select reader
        name = content.name if content.name else content.url
        if file_extension:
            reader, default_name = self._select_reader_by_extension(file_extension, content.reader)
            if default_name and file_extension == ".csv":
                name = basename(parsed_url.path) or default_name
        else:
            reader = content.reader or self.website_reader
        # 5. Read content
        try:
            read_documents = []
            if reader is not None:
                # Special handling for YouTubeReader
                if reader.__class__.__name__ == "YouTubeReader":
                    read_documents = await reader.async_read(content.url, name=name)
                else:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    source = bytes_content if bytes_content else content.url
                    read_documents = await self._aread(reader, source, name=name, password=password)

        except Exception as e:
            log_error(f"Error reading URL: {content.url} - {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            await self._aupdate_content(content)
            return

        # 6. Chunk documents if needed
        if reader and not reader.chunk:
            read_documents = await reader.chunk_documents_async(read_documents)

        # 7. Group documents by source URL for multi-page readers (like WebsiteReader)
        docs_by_source: Dict[str, List[Document]] = {}
        for doc in read_documents:
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        # 8. Process each source separately if multiple sources exist
        if len(docs_by_source) > 1:
            for source_url, source_docs in docs_by_source.items():
                # Compute per-document hash based on actual source URL
                doc_hash = self._build_document_content_hash(source_docs[0], content)

                # Check skip_if_exists for each source individually
                if self._should_skip(doc_hash, skip_if_exists):
                    log_debug(f"Skipping already indexed: {source_url}")
                    continue

                doc_id = generate_id(doc_hash)
                self._prepare_documents_for_insert(source_docs, doc_id, calculate_sizes=True)

                # Insert with per-document hash
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
            await self._aupdate_content(content)
            return

        # 9. Single source - use existing logic with original content hash
        if not content.id:
            content.id = generate_id(content.content_hash or "")
        self._prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
        await self._ahandle_vector_db_insert(content, read_documents, upsert)

    def _load_from_url(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Synchronous version of _load_from_url.

        Load the content from a URL:
        1. Set content hash
        2. Validate the URL
        3. Read the content
        4. Prepare and insert the content in the vector database
        """
        from agno.utils.http import fetch_with_retry
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        log_info(f"Adding content from URL {content.url}")
        content.file_type = "url"

        if not content.url:
            raise ValueError("No url provided")

        # Store URL source metadata in _agno for source tracking
        content.metadata = set_agno_metadata(content.metadata, "source_type", "url")
        content.metadata = set_agno_metadata(content.metadata, "source_url", content.url)

        # Set name from URL if not provided
        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        # 1. Add content to contents database
        self._insert_contents_db(content)
        if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            self._update_content(content)
            return

        if self.vector_db.__class__.__name__ == "LightRag":
            self._process_lightrag_content(content, KnowledgeContentOrigin.URL)
            return

        # 2. Validate URL
        try:
            from urllib.parse import urlparse

            parsed_url = urlparse(content.url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                content.status = ContentStatus.FAILED
                content.status_message = f"Invalid URL format: {content.url}"
                self._update_content(content)
                log_warning(f"Invalid URL format: {content.url}")
        except Exception as e:
            content.status = ContentStatus.FAILED
            content.status_message = f"Invalid URL: {content.url} - {str(e)}"
            self._update_content(content)
            log_warning(f"Invalid URL: {content.url} - {str(e)}")

        # 3. Fetch and load content if file has an extension
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        if file_extension:
            response = fetch_with_retry(content.url)
            bytes_content = BytesIO(response.content)

        # 4. Select reader
        name = content.name if content.name else content.url
        if file_extension:
            reader, default_name = self._select_reader_by_extension(file_extension, content.reader)
            if default_name and file_extension == ".csv":
                name = basename(parsed_url.path) or default_name
        else:
            reader = content.reader or self.website_reader

        # 5. Read content
        try:
            read_documents = []
            if reader is not None:
                # Special handling for YouTubeReader
                if reader.__class__.__name__ == "YouTubeReader":
                    read_documents = reader.read(content.url, name=name)
                else:
                    password = content.auth.password if content.auth and content.auth.password is not None else None
                    source = bytes_content if bytes_content else content.url
                    read_documents = self._read(reader, source, name=name, password=password)

        except Exception as e:
            log_error(f"Error reading URL: {content.url} - {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            self._update_content(content)
            return

        # 6. Chunk documents if needed (sync version)
        if reader:
            read_documents = self._chunk_documents_sync(reader, read_documents)

        # 7. Group documents by source URL for multi-page readers (like WebsiteReader)
        docs_by_source: Dict[str, List[Document]] = {}
        for doc in read_documents:
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        # 8. Process each source separately if multiple sources exist
        if len(docs_by_source) > 1:
            for source_url, source_docs in docs_by_source.items():
                # Compute per-document hash based on actual source URL
                doc_hash = self._build_document_content_hash(source_docs[0], content)

                # Check skip_if_exists for each source individually
                if self._should_skip(doc_hash, skip_if_exists):
                    log_debug(f"Skipping already indexed: {source_url}")
                    continue

                doc_id = generate_id(doc_hash)
                self._prepare_documents_for_insert(source_docs, doc_id, calculate_sizes=True)

                # Insert with per-document hash
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
            self._update_content(content)
            return

        # 9. Single source - use existing logic with original content hash
        if not content.id:
            content.id = generate_id(content.content_hash or "")
        self._prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
        self._handle_vector_db_insert(content, read_documents, upsert)

    async def _aload_from_content(
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

        await self._ainsert_contents_db(content)
        if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            await self._aupdate_content(content)
            return

        if content.file_data and self.vector_db.__class__.__name__ == "LightRag":
            await self._aprocess_lightrag_content(content, KnowledgeContentOrigin.CONTENT)
            return

        read_documents = []

        if isinstance(content.file_data, str):
            content_bytes = content.file_data.encode("utf-8", errors="replace")
            content_io = io.BytesIO(content_bytes)

            if content.reader:
                log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = await content.reader.async_read(content_io, name=name)
            else:
                text_reader = self.text_reader
                if text_reader:
                    read_documents = await text_reader.async_read(content_io, name=name)
                else:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Text reader not available"
                    await self._aupdate_content(content)
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

                # Respect an explicitly provided reader; otherwise select based on file type
                if content.reader:
                    log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                    reader = content.reader
                else:
                    # Prefer filename extension over MIME type for reader selection
                    # (browsers often send wrong MIME types for Excel files)
                    reader_hint = content.file_data.type
                    if content.file_data.filename:
                        ext = Path(content.file_data.filename).suffix.lower()
                        if ext:
                            reader_hint = ext
                    reader = self._select_reader(reader_hint)
                # Use file_data.filename for reader (preserves extension for format detection)
                reader_name = content.file_data.filename or content.name or f"content_{content.file_data.type}"
                read_documents = await reader.async_read(content_io, name=reader_name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                if len(read_documents) == 0:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Content could not be read"
                    await self._aupdate_content(content)
                    return

        else:
            content.status = ContentStatus.FAILED
            content.status_message = "No content provided"
            await self._aupdate_content(content)
            return

        await self._ahandle_vector_db_insert(content, read_documents, upsert)

    def _load_from_content(
        self,
        content: Content,
        upsert: bool = True,
        skip_if_exists: bool = False,
    ):
        """Synchronous version of _load_from_content."""
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

        self._insert_contents_db(content)
        if self._should_skip(content.content_hash, skip_if_exists):  # type: ignore[arg-type]
            content.status = ContentStatus.COMPLETED
            self._update_content(content)
            return

        if content.file_data and self.vector_db.__class__.__name__ == "LightRag":
            self._process_lightrag_content(content, KnowledgeContentOrigin.CONTENT)
            return

        read_documents = []

        if isinstance(content.file_data, str):
            content_bytes = content.file_data.encode("utf-8", errors="replace")
            content_io = io.BytesIO(content_bytes)

            if content.reader:
                log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                read_documents = content.reader.read(content_io, name=name)
            else:
                text_reader = self.text_reader
                if text_reader:
                    read_documents = text_reader.read(content_io, name=name)
                else:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Text reader not available"
                    self._update_content(content)
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

                # Respect an explicitly provided reader; otherwise select based on file type
                if content.reader:
                    log_debug(f"Using reader: {content.reader.__class__.__name__} to read content")
                    reader = content.reader
                else:
                    # Prefer filename extension over MIME type for reader selection
                    # (browsers often send wrong MIME types for Excel files)
                    reader_hint = content.file_data.type
                    if content.file_data.filename:
                        ext = Path(content.file_data.filename).suffix.lower()
                        if ext:
                            reader_hint = ext
                    reader = self._select_reader(reader_hint)
                # Use file_data.filename for reader (preserves extension for format detection)
                reader_name = content.file_data.filename or content.name or f"content_{content.file_data.type}"
                read_documents = reader.read(content_io, name=reader_name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                if len(read_documents) == 0:
                    content.status = ContentStatus.FAILED
                    content.status_message = "Content could not be read"
                    self._update_content(content)
                    return

        else:
            content.status = ContentStatus.FAILED
            content.status_message = "No content provided"
            self._update_content(content)
            return

        self._handle_vector_db_insert(content, read_documents, upsert)

    async def _aload_from_topics(
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
            content.content_hash = self._build_content_hash(content)
            content.id = generate_id(content.content_hash)

            await self._ainsert_contents_db(content)
            if self._should_skip(content.content_hash, skip_if_exists):
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db.__class__.__name__ == "LightRag":
                await self._aprocess_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db and self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                log_info(f"Content {content.content_hash} already exists, skipping")
                continue

            if content.reader is None:
                log_error(f"No reader available for topic: {topic}")
                content.status = ContentStatus.FAILED
                content.status_message = "No reader available for topic"
                await self._aupdate_content(content)
                continue

            read_documents = await content.reader.async_read(topic)
            if len(read_documents) > 0:
                self._prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
            else:
                content.status = ContentStatus.FAILED
                content.status_message = "No content found for topic"
                await self._aupdate_content(content)

            await self._ahandle_vector_db_insert(content, read_documents, upsert)

    def _load_from_topics(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Synchronous version of _load_from_topics."""
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
            content.content_hash = self._build_content_hash(content)
            content.id = generate_id(content.content_hash)

            self._insert_contents_db(content)
            if self._should_skip(content.content_hash, skip_if_exists):
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db.__class__.__name__ == "LightRag":
                self._process_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db and self.vector_db.content_hash_exists(content.content_hash) and skip_if_exists:
                log_info(f"Content {content.content_hash} already exists, skipping")
                continue

            if content.reader is None:
                log_error(f"No reader available for topic: {topic}")
                content.status = ContentStatus.FAILED
                content.status_message = "No reader available for topic"
                self._update_content(content)
                continue

            read_documents = content.reader.read(topic)
            if len(read_documents) > 0:
                self._prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
            else:
                content.status = ContentStatus.FAILED
                content.status_message = "No content found for topic"
                self._update_content(content)

            self._handle_vector_db_insert(content, read_documents, upsert)

    # ==========================================
    # PRIVATE - CONVERSION & DATA METHODS
    # ==========================================

    def _build_content_hash(self, content: Content) -> str:
        """
        Build the content hash from the content.

        For URLs and paths, includes the name and description in the hash if provided
        to ensure unique content with the same URL/path but different names/descriptions
        get different hashes.

        Hash format:
        - URL with name and description: hash("{name}:{description}:{url}")
        - URL with name only: hash("{name}:{url}")
        - URL with description only: hash("{description}:{url}")
        - URL without name/description: hash("{url}") (backward compatible)
        - Same logic applies to paths
        """
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
            # For file_data, always add filename, type, size, or content for uniqueness
            if content.file_data.filename:
                hash_parts.append(content.file_data.filename)
            elif content.file_data.type:
                hash_parts.append(content.file_data.type)
            elif content.file_data.size is not None:
                hash_parts.append(str(content.file_data.size))
            else:
                # Fallback: use the content for uniqueness
                # Include type information to distinguish str vs bytes
                content_type = "str" if isinstance(content.file_data.content, str) else "bytes"
                content_bytes = (
                    content.file_data.content.encode()
                    if isinstance(content.file_data.content, str)
                    else content.file_data.content
                )
                content_hash = hashlib.sha256(content_bytes).hexdigest()[:16]  # Use first 16 chars
                hash_parts.append(f"{content_type}:{content_hash}")
        elif content.topics and len(content.topics) > 0:
            topic = content.topics[0]
            reader = type(content.reader).__name__ if content.reader else "unknown"
            hash_parts.append(f"{topic}-{reader}")
        else:
            # Fallback for edge cases
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

    def _build_document_content_hash(self, document: Document, content: Content) -> str:
        """
        Build content hash for a specific document.

        Used for multi-page readers (like WebsiteReader) where each crawled page
        should have its own unique content hash based on its actual URL.

        Args:
            document: The document to build the hash for
            content: The original content object (for fallback name/description)

        Returns:
            A unique hash string for this specific document
        """
        hash_parts = []

        if content.name:
            hash_parts.append(content.name)
        if content.description:
            hash_parts.append(content.description)

        # Use document's own URL if available (set by WebsiteReader)
        doc_url = document.meta_data.get("url") if document.meta_data else None
        if doc_url:
            hash_parts.append(str(doc_url))
        elif content.url:
            hash_parts.append(content.url)
        elif content.path:
            hash_parts.append(str(content.path))
        else:
            # Fallback: use content hash for uniqueness
            hash_parts.append(hashlib.sha256(document.content.encode()).hexdigest()[:16])

        hash_input = ":".join(hash_parts)
        return hashlib.sha256(hash_input.encode()).hexdigest()

    def _ensure_string_field(self, value: Any, field_name: str, default: str = "") -> str:
        """
        Safely ensure a field is a string, handling various edge cases.

        Args:
            value: The value to convert to string
            field_name: Name of the field for logging purposes
            default: Default string value if conversion fails

        Returns:
            str: A safe string value
        """
        # Handle None/falsy values
        if value is None or value == "":
            return default

        # Handle unexpected list types (the root cause of our Pydantic warning)
        if isinstance(value, list):
            if len(value) == 0:
                log_debug(f"Empty list found for {field_name}, using default: '{default}'")
                return default
            elif len(value) == 1:
                # Single item list, extract the item
                log_debug(f"Single-item list found for {field_name}, extracting: '{value[0]}'")
                return str(value[0]) if value[0] is not None else default
            else:
                # Multiple items, join them
                log_debug(f"Multi-item list found for {field_name}, joining: {value}")
                return " | ".join(str(item) for item in value if item is not None)

        # Handle other unexpected types
        if not isinstance(value, str):
            log_debug(f"Non-string type {type(value)} found for {field_name}, converting: '{value}'")
            try:
                return str(value)
            except Exception as e:
                log_warning(f"Failed to convert {field_name} to string: {e}, using default")
                return default

        # Already a string, return as-is
        return value

    def _content_row_to_content(self, content_row: KnowledgeRow) -> Content:
        """Convert a KnowledgeRow to a Content object."""
        return Content(
            id=content_row.id,
            name=content_row.name,
            description=content_row.description,
            metadata=content_row.metadata,
            file_type=content_row.type,
            size=content_row.size,
            status=ContentStatus(content_row.status) if content_row.status else None,
            status_message=content_row.status_message,
            created_at=content_row.created_at,
            updated_at=content_row.updated_at if content_row.updated_at else content_row.created_at,
            external_id=content_row.external_id,
        )

    def _build_knowledge_row(self, content: Content) -> KnowledgeRow:
        """Build a KnowledgeRow from a Content object."""
        created_at = content.created_at if content.created_at else int(time.time())
        updated_at = content.updated_at if content.updated_at else int(time.time())
        file_type = (
            content.file_type
            if content.file_type
            else content.file_data.type
            if content.file_data and content.file_data.type
            else None
        )
        return KnowledgeRow(
            id=content.id,
            name=self._ensure_string_field(content.name, "content.name", default=""),
            description=self._ensure_string_field(content.description, "content.description", default=""),
            metadata=content.metadata,
            type=file_type,
            size=content.size
            if content.size
            else len(content.file_data.content)
            if content.file_data and content.file_data.content
            else None,
            linked_to=self.name if self.name else "",
            access_count=0,
            status=content.status if content.status else ContentStatus.PROCESSING,
            status_message=self._ensure_string_field(content.status_message, "content.status_message", default=""),
            created_at=created_at,
            updated_at=updated_at,
        )

    def _parse_content_status(self, status_str: Optional[str]) -> ContentStatus:
        """Parse status string to ContentStatus enum."""
        try:
            return ContentStatus(status_str.lower()) if status_str else ContentStatus.PROCESSING
        except ValueError:
            if status_str and "failed" in status_str.lower():
                return ContentStatus.FAILED
            elif status_str and "completed" in status_str.lower():
                return ContentStatus.COMPLETED
            return ContentStatus.PROCESSING

    # ==========================================
    # PRIVATE - DATABASE METHODS
    # ==========================================

    async def _ainsert_contents_db(self, content: Content):
        if self.contents_db:
            content_row = self._build_knowledge_row(content)
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.upsert_knowledge_content(knowledge_row=content_row)
            else:
                self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    def _insert_contents_db(self, content: Content):
        """Synchronously add content to contents database."""
        if self.contents_db:
            if isinstance(self.contents_db, AsyncBaseDb):
                raise ValueError(
                    "_insert_contents_db() is not supported with an async DB. Please use ainsert() with AsyncDb."
                )
            content_row = self._build_knowledge_row(content)
            self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    # --- Vector DB Insert Helpers ---

    async def _ahandle_vector_db_insert(self, content: Content, read_documents, upsert):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if not self.vector_db:
            log_error("No vector database configured")
            content.status = ContentStatus.FAILED
            content.status_message = "No vector database configured"
            await self._aupdate_content(content)
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                await self.vector_db.async_upsert(content.content_hash, read_documents, content.metadata)  # type: ignore[arg-type]
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not upsert embedding"
                await self._aupdate_content(content)
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
                await self._aupdate_content(content)
                return

        content.status = ContentStatus.COMPLETED
        await self._aupdate_content(content)

    def _handle_vector_db_insert(self, content: Content, read_documents, upsert):
        """Synchronously handle vector database insertion."""
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        if not self.vector_db:
            log_error("No vector database configured")
            content.status = ContentStatus.FAILED
            content.status_message = "No vector database configured"
            self._update_content(content)
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                self.vector_db.upsert(content.content_hash, read_documents, content.metadata)  # type: ignore[arg-type]
            except Exception as e:
                log_error(f"Error upserting document: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not upsert embedding"
                self._update_content(content)
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
                self._update_content(content)
                return

        content.status = ContentStatus.COMPLETED
        self._update_content(content)

    # --- Content Update ---

    def _update_content(self, content: Content) -> Optional[Dict[str, Any]]:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.contents_db:
            if isinstance(self.contents_db, AsyncBaseDb):
                raise ValueError(
                    "update_content() is not supported with an async DB. Please use aupdate_content() instead."
                )

            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            # TODO: we shouldn't check for content here, we should trust the upsert method to handle conflicts
            content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None

            # Apply safe string handling for updates as well
            if content.name is not None:
                content_row.name = self._ensure_string_field(content.name, "content.name", default="")
            if content.description is not None:
                content_row.description = self._ensure_string_field(
                    content.description, "content.description", default=""
                )
            if content.metadata is not None:
                content_row.metadata = merge_user_metadata(content_row.metadata, content.metadata)
            if content.status is not None:
                content_row.status = content.status
            if content.status_message is not None:
                content_row.status_message = self._ensure_string_field(
                    content.status_message, "content.status_message", default=""
                )
            if content.external_id is not None:
                content_row.external_id = self._ensure_string_field(
                    content.external_id, "content.external_id", default=""
                )
            content_row.updated_at = int(time.time())
            self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

            if self.vector_db:
                # Strip _agno from metadata sent to vector_db — only user fields should be searchable
                user_metadata = strip_agno_metadata(content.metadata) or {}
                self.vector_db.update_metadata(content_id=content.id, metadata=user_metadata)

            return content_row.to_dict()

        else:
            return None

    async def _aupdate_content(self, content: Content) -> Optional[Dict[str, Any]]:
        if self.contents_db:
            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            # TODO: we shouldn't check for content here, we should trust the upsert method to handle conflicts
            if isinstance(self.contents_db, AsyncBaseDb):
                content_row = await self.contents_db.get_knowledge_content(content.id)
            else:
                content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None

            # Apply safe string handling for updates
            if content.name is not None:
                content_row.name = self._ensure_string_field(content.name, "content.name", default="")
            if content.description is not None:
                content_row.description = self._ensure_string_field(
                    content.description, "content.description", default=""
                )
            if content.metadata is not None:
                content_row.metadata = merge_user_metadata(content_row.metadata, content.metadata)
            if content.status is not None:
                content_row.status = content.status
            if content.status_message is not None:
                content_row.status_message = self._ensure_string_field(
                    content.status_message, "content.status_message", default=""
                )
            if content.external_id is not None:
                content_row.external_id = self._ensure_string_field(
                    content.external_id, "content.external_id", default=""
                )

            content_row.updated_at = int(time.time())
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.upsert_knowledge_content(knowledge_row=content_row)
            else:
                self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

            if self.vector_db:
                # Strip _agno from metadata sent to vector_db — only user fields should be searchable
                user_metadata = strip_agno_metadata(content.metadata) or {}
                self.vector_db.update_metadata(content_id=content.id, metadata=user_metadata)

            return content_row.to_dict()

        else:
            return None

    # ==========================================
    # PRIVATE - LIGHTRAG PROCESSING METHODS
    # ==========================================

    async def _aprocess_lightrag_content(self, content: Content, content_type: KnowledgeContentOrigin) -> None:
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        await self._ainsert_contents_db(content)
        if content_type == KnowledgeContentOrigin.PATH:
            if content.file_data is None:
                log_warning("No file data provided")

            if content.path is None:
                log_error("No path provided for content")
                return

            path = Path(content.path)

            log_info(f"Uploading file to LightRAG from path: {path}")
            try:
                # Read the file content from path
                with open(path, "rb") as f:
                    file_content = f.read()

                # Get file type from extension or content.file_type
                file_type = content.file_type or path.suffix

                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = await self.vector_db.insert_file_bytes(
                        file_content=file_content,
                        filename=path.name,  # Use the original filename with extension
                        content_type=file_type,
                        send_metadata=True,  # Enable metadata so server knows the file type
                    )

                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                await self._aupdate_content(content)
                return

        elif content_type == KnowledgeContentOrigin.URL:
            log_info(f"Uploading file to LightRAG from URL: {content.url}")
            try:
                reader = content.reader or self.website_reader
                if reader is None:
                    log_error("No URL reader available")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return

                reader.chunk = False
                read_documents = reader.read(content.url, name=content.name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return

                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    result = await self.vector_db.insert_text(
                        file_source=content.url,
                        text=read_documents[0].content,
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return

                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                await self._aupdate_content(content)
                return

        elif content_type == KnowledgeContentOrigin.CONTENT:
            filename = (
                content.file_data.filename if content.file_data and content.file_data.filename else "uploaded_file"
            )
            log_info(f"Uploading file to LightRAG: {filename}")

            # Use the content from file_data
            if content.file_data and content.file_data.content:
                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    result = await self.vector_db.insert_file_bytes(
                        file_content=content.file_data.content,
                        filename=filename,
                        content_type=content.file_data.type,
                        send_metadata=True,  # Enable metadata so server knows the file type
                    )
                else:
                    log_error("Vector database does not support file insertion")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
            else:
                log_warning(f"No file data available for LightRAG upload: {content.name}")
            return

        elif content_type == KnowledgeContentOrigin.TOPIC:
            log_info(f"Uploading file to LightRAG: {content.name}")

            if content.reader is None:
                log_error("No reader available for topic content")
                content.status = ContentStatus.FAILED
                await self._aupdate_content(content)
                return

            if not content.topics:
                log_error("No topics available for content")
                content.status = ContentStatus.FAILED
                await self._aupdate_content(content)
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
                    await self._aupdate_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
                return
            else:
                log_warning(f"No documents found for LightRAG upload: {content.name}")
                return

    def _process_lightrag_content(self, content: Content, content_type: KnowledgeContentOrigin) -> None:
        """Synchronously process LightRAG content. Uses asyncio.run() only for LightRAG-specific async methods."""
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        self._insert_contents_db(content)
        if content_type == KnowledgeContentOrigin.PATH:
            if content.file_data is None:
                log_warning("No file data provided")

            if content.path is None:
                log_error("No path provided for content")
                return

            path = Path(content.path)

            log_info(f"Uploading file to LightRAG from path: {path}")
            try:
                # Read the file content from path
                with open(path, "rb") as f:
                    file_content = f.read()

                # Get file type from extension or content.file_type
                file_type = content.file_type or path.suffix

                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    # LightRAG only has async methods, use asyncio.run() here
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
                    self._update_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                self._update_content(content)
                return

        elif content_type == KnowledgeContentOrigin.URL:
            log_info(f"Uploading file to LightRAG from URL: {content.url}")
            try:
                reader = content.reader or self.website_reader
                if reader is None:
                    log_error("No URL reader available")
                    content.status = ContentStatus.FAILED
                    self._update_content(content)
                    return

                reader.chunk = False
                read_documents = reader.read(content.url, name=content.name)
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    self._update_content(content)
                    return

                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    # LightRAG only has async methods, use asyncio.run() here
                    result = asyncio.run(
                        self.vector_db.insert_text(
                            file_source=content.url,
                            text=read_documents[0].content,
                        )
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    self._update_content(content)
                    return

                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
                return

            except Exception as e:
                log_error(f"Error uploading file to LightRAG: {e}")
                content.status = ContentStatus.FAILED
                content.status_message = f"Could not upload to LightRAG: {str(e)}"
                self._update_content(content)
                return

        elif content_type == KnowledgeContentOrigin.CONTENT:
            filename = (
                content.file_data.filename if content.file_data and content.file_data.filename else "uploaded_file"
            )
            log_info(f"Uploading file to LightRAG: {filename}")

            # Use the content from file_data
            if content.file_data and content.file_data.content:
                if self.vector_db and hasattr(self.vector_db, "insert_file_bytes"):
                    # LightRAG only has async methods, use asyncio.run() here
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
                    self._update_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
            else:
                log_warning(f"No file data available for LightRAG upload: {content.name}")
            return

        elif content_type == KnowledgeContentOrigin.TOPIC:
            log_info(f"Uploading file to LightRAG: {content.name}")

            if content.reader is None:
                log_error("No reader available for topic content")
                content.status = ContentStatus.FAILED
                self._update_content(content)
                return

            if not content.topics:
                log_error("No topics available for content")
                content.status = ContentStatus.FAILED
                self._update_content(content)
                return

            read_documents = content.reader.read(content.topics)
            if len(read_documents) > 0:
                if self.vector_db and hasattr(self.vector_db, "insert_text"):
                    # LightRAG only has async methods, use asyncio.run() here
                    result = asyncio.run(
                        self.vector_db.insert_text(
                            file_source=content.topics[0],
                            text=read_documents[0].content,
                        )
                    )
                else:
                    log_error("Vector database does not support text insertion")
                    content.status = ContentStatus.FAILED
                    self._update_content(content)
                    return
                content.external_id = result
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
                return
            else:
                log_warning(f"No documents found for LightRAG upload: {content.name}")
                return

    # ========================================================================
    # Protocol Implementation (build_context, get_tools, retrieve)
    # ========================================================================

    # Shared context strings
    _SEARCH_KNOWLEDGE_INSTRUCTIONS = (
        "You have a knowledge base you can search using the search_knowledge_base tool. "
        "Search before answering questions—don't assume you know the answer. "
        "For ambiguous questions, search first rather than asking for clarification."
    )

    _AGENTIC_FILTER_INSTRUCTION_TEMPLATE = """
The knowledge base contains documents with these metadata filters: {valid_filters_str}.
Always use filters when the user query indicates specific metadata.

Examples:
1. If the user asks about a specific person like "Jordan Mitchell", you MUST use the search_knowledge_base tool with the filters parameter set to {{'<valid key like user_id>': '<valid value based on the user query>'}}.
2. If the user asks about a specific document type like "contracts", you MUST use the search_knowledge_base tool with the filters parameter set to {{'document_type': 'contract'}}.
3. If the user asks about a specific location like "documents from New York", you MUST use the search_knowledge_base tool with the filters parameter set to {{'<valid key like location>': 'New York'}}.

General Guidelines:
- Always analyze the user query to identify relevant metadata.
- Use the most specific filter(s) possible to narrow down results.
- If multiple filters are relevant, combine them in the filters parameter (e.g., {{'name': 'Jordan Mitchell', 'document_type': 'contract'}}).
- Ensure the filter keys match the valid metadata filters: {valid_filters_str}.

Make sure to pass the filters as [Dict[str: Any]] to the tool. FOLLOW THIS STRUCTURE STRICTLY.
""".strip()

    def _get_agentic_filter_instructions(self, valid_filters: Set[str]) -> str:
        """Generate the agentic filter instructions for the given valid filters."""
        valid_filters_str = ", ".join(valid_filters)
        return self._AGENTIC_FILTER_INSTRUCTION_TEMPLATE.format(valid_filters_str=valid_filters_str)

    def build_context(
        self,
        enable_agentic_filters: bool = False,
        **kwargs,
    ) -> str:
        """Build context string for the agent's system prompt.

        Returns instructions about how to use the search_knowledge_base tool
        and available filters.

        Args:
            enable_agentic_filters: Whether agentic filters are enabled.
            **kwargs: Additional context (unused).

        Returns:
            Context string to add to system prompt.
        """
        context_parts: List[str] = [self._SEARCH_KNOWLEDGE_INSTRUCTIONS]

        # Add filter instructions if agentic filters are enabled
        if enable_agentic_filters:
            valid_filters = self.get_valid_filters()
            if valid_filters:
                context_parts.append(self._get_agentic_filter_instructions(valid_filters))

        return "<knowledge_base>\n" + "\n".join(context_parts) + "\n</knowledge_base>"

    async def abuild_context(
        self,
        enable_agentic_filters: bool = False,
        **kwargs,
    ) -> str:
        """Async version of build_context.

        Returns instructions about how to use the search_knowledge_base tool
        and available filters.

        Args:
            enable_agentic_filters: Whether agentic filters are enabled.
            **kwargs: Additional context (unused).

        Returns:
            Context string to add to system prompt.
        """
        context_parts: List[str] = [self._SEARCH_KNOWLEDGE_INSTRUCTIONS]

        # Add filter instructions if agentic filters are enabled
        if enable_agentic_filters:
            valid_filters = await self.aget_valid_filters()
            if valid_filters:
                context_parts.append(self._get_agentic_filter_instructions(valid_filters))

        return "<knowledge_base>\n" + "\n".join(context_parts) + "\n</knowledge_base>"

    def get_tools(
        self,
        run_response: Optional[Any] = None,
        run_context: Optional[Any] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        async_mode: bool = False,
        enable_agentic_filters: bool = False,
        agent: Optional[Any] = None,
        **kwargs,
    ) -> List[Any]:
        """Get tools to expose to the Agent or Team.

        Returns the search_knowledge_base tool configured for this knowledge base.

        Args:
            run_response: The run response object to add references to.
            run_context: The run context.
            knowledge_filters: Filters to apply to searches.
            async_mode: Whether to return async tools.
            enable_agentic_filters: Whether to enable filter parameter on tool.
            agent: The Agent or Team instance (for document conversion with references_format).
            **kwargs: Additional context.

        Returns:
            List containing the search tool.
        """
        if enable_agentic_filters:
            tool = self._create_search_tool_with_filters(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=knowledge_filters,
                async_mode=async_mode,
                agent=agent,
            )
        else:
            tool = self._create_search_tool(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=knowledge_filters,
                async_mode=async_mode,
                agent=agent,
            )

        return [tool]

    async def aget_tools(
        self,
        run_response: Optional[Any] = None,
        run_context: Optional[Any] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        async_mode: bool = True,
        enable_agentic_filters: bool = False,
        agent: Optional[Any] = None,
        **kwargs,
    ) -> List[Any]:
        """Async version of get_tools."""
        return self.get_tools(
            run_response=run_response,
            run_context=run_context,
            knowledge_filters=knowledge_filters,
            async_mode=async_mode,
            enable_agentic_filters=enable_agentic_filters,
            agent=agent,
            **kwargs,
        )

    def _create_search_tool(
        self,
        run_response: Optional[Any] = None,
        run_context: Optional[Any] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        async_mode: bool = False,
        agent: Optional[Any] = None,
    ) -> Any:
        """Create the search_knowledge_base tool without filter parameter.

        Args:
            agent: Agent or Team instance for custom document conversion.
        """
        from agno.models.message import MessageReferences
        from agno.tools.function import Function
        from agno.utils.timer import Timer

        def search_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()

            try:
                docs = self.search(query=query, filters=knowledge_filters)
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"

            if run_response is not None and docs:
                references = MessageReferences(
                    query=query,
                    references=[doc.to_dict() for doc in docs],
                    time=round(retrieval_timer.elapsed, 4),
                )
                if run_response.references is None:
                    run_response.references = []
                run_response.references.append(references)

            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if not docs:
                return "No documents found"

            return self._convert_documents_to_string(docs, agent)

        async def asearch_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query asynchronously.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()

            try:
                docs = await self.asearch(query=query, filters=knowledge_filters)
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"

            if run_response is not None and docs:
                references = MessageReferences(
                    query=query,
                    references=[doc.to_dict() for doc in docs],
                    time=round(retrieval_timer.elapsed, 4),
                )
                if run_response.references is None:
                    run_response.references = []
                run_response.references.append(references)

            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if not docs:
                return "No documents found"

            return self._convert_documents_to_string(docs, agent)

        if async_mode:
            return Function.from_callable(asearch_knowledge_base, name="search_knowledge_base")
        else:
            return Function.from_callable(search_knowledge_base, name="search_knowledge_base")

    def _create_search_tool_with_filters(
        self,
        run_response: Optional[Any] = None,
        run_context: Optional[Any] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        async_mode: bool = False,
        agent: Optional[Any] = None,
    ) -> Any:
        """Create the search_knowledge_base tool with filter parameter.

        Args:
            agent: Agent or Team instance for custom document conversion.
        """
        from agno.models.message import MessageReferences
        from agno.tools.function import Function
        from agno.utils.timer import Timer

        # Import here to avoid circular imports
        try:
            from agno.utils.knowledge import get_agentic_or_user_search_filters
        except ImportError:
            get_agentic_or_user_search_filters = None  # type: ignore[assignment]

        def search_knowledge_base(query: str, filters: Optional[List[Any]] = None) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            # Merge agentic filters with user-provided filters
            search_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
            if filters and get_agentic_or_user_search_filters is not None:
                # Handle both KnowledgeFilter objects and plain dictionaries
                filters_dict: Dict[str, Any] = {}
                for filt in filters:
                    if isinstance(filt, dict):
                        filters_dict.update(filt)
                    elif hasattr(filt, "key") and hasattr(filt, "value"):
                        filters_dict[filt.key] = filt.value
                search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
            else:
                search_filters = knowledge_filters

            # Validate filters if we have that capability
            if search_filters:
                validated_filters, invalid_keys = self.validate_filters(search_filters)
                if invalid_keys:
                    log_warning(f"Invalid filter keys ignored: {invalid_keys}")
                search_filters = validated_filters if validated_filters else None

            retrieval_timer = Timer()
            retrieval_timer.start()

            try:
                docs = self.search(query=query, filters=search_filters)
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"

            if run_response is not None and docs:
                references = MessageReferences(
                    query=query,
                    references=[doc.to_dict() for doc in docs],
                    time=round(retrieval_timer.elapsed, 4),
                )
                if run_response.references is None:
                    run_response.references = []
                run_response.references.append(references)

            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if not docs:
                return "No documents found"

            return self._convert_documents_to_string(docs, agent)

        async def asearch_knowledge_base(query: str, filters: Optional[List[Any]] = None) -> str:
            """Use this function to search the knowledge base for information about a query asynchronously.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            # Merge agentic filters with user-provided filters
            search_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
            if filters and get_agentic_or_user_search_filters is not None:
                # Handle both KnowledgeFilter objects and plain dictionaries
                filters_dict: Dict[str, Any] = {}
                for filt in filters:
                    if isinstance(filt, dict):
                        filters_dict.update(filt)
                    elif hasattr(filt, "key") and hasattr(filt, "value"):
                        filters_dict[filt.key] = filt.value
                search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
            else:
                search_filters = knowledge_filters

            # Validate filters if we have that capability
            if search_filters:
                validated_filters, invalid_keys = await self.avalidate_filters(search_filters)
                if invalid_keys:
                    log_warning(f"Invalid filter keys ignored: {invalid_keys}")
                search_filters = validated_filters if validated_filters else None

            retrieval_timer = Timer()
            retrieval_timer.start()

            try:
                docs = await self.asearch(query=query, filters=search_filters)
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"

            if run_response is not None and docs:
                references = MessageReferences(
                    query=query,
                    references=[doc.to_dict() for doc in docs],
                    time=round(retrieval_timer.elapsed, 4),
                )
                if run_response.references is None:
                    run_response.references = []
                run_response.references.append(references)

            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if not docs:
                return "No documents found"

            return self._convert_documents_to_string(docs, agent)

        if async_mode:
            func = Function.from_callable(asearch_knowledge_base, name="search_knowledge_base")
        else:
            func = Function.from_callable(search_knowledge_base, name="search_knowledge_base")

        # Opt out of strict mode since filters use dynamic types that are incompatible with strict mode
        func.strict = False
        return func

    def _convert_documents_to_string(
        self,
        docs: List[Document],
        agent: Optional[Any] = None,
    ) -> str:
        """Convert documents to a string representation.

        Args:
            docs: List of documents to convert.
            agent: Optional Agent or Team instance for custom conversion using their references_format.

        Returns:
            String representation of documents.
        """
        # If agent (Agent or Team) has a custom converter, use it for proper YAML/JSON formatting
        if agent is not None and hasattr(agent, "_convert_documents_to_string"):
            return agent._convert_documents_to_string([doc.to_dict() for doc in docs])

        # Default conversion
        if not docs:
            return "No documents found"

        result_parts = []
        for doc in docs:
            if doc.content:
                result_parts.append(doc.content)

        return "\n\n---\n\n".join(result_parts) if result_parts else "No content found"

    def retrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        **kwargs,
    ) -> List[Document]:
        """Retrieve documents for context injection.

        Used by the add_knowledge_to_context feature to pre-fetch
        relevant documents into the user message.

        Args:
            query: The query string.
            max_results: Maximum number of results.
            filters: Filters to apply.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects.
        """
        return self.search(query=query, max_results=max_results, filters=filters)

    async def aretrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        **kwargs,
    ) -> List[Document]:
        """Async version of retrieve.

        Args:
            query: The query string.
            max_results: Maximum number of results.
            filters: Filters to apply.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects.
        """
        return await self.asearch(query=query, max_results=max_results, filters=filters)

    # ========================================================================
    # Deprecated Methods (for backward compatibility)
    # ========================================================================

    @overload
    def add_content(
        self,
        *,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        reader: Optional[Reader] = None,
        auth: Optional[ContentAuth] = None,
    ) -> None: ...

    @overload
    def add_content(self, *args, **kwargs) -> None: ...

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
        skip_if_exists: bool = False,
        auth: Optional[ContentAuth] = None,
    ) -> None:
        """
        DEPRECATED: Use `insert()` instead. This method will be removed in a future version.

        Synchronously insert content into the knowledge base.

        This is a backward-compatible wrapper for the `insert()` method.
        Please migrate your code to use `insert()` instead.
        """
        return self.insert(
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
            auth=auth,
        )

    @overload
    async def add_content_async(
        self,
        *,
        path: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        reader: Optional[Reader] = None,
        auth: Optional[ContentAuth] = None,
    ) -> None: ...

    @overload
    async def add_content_async(self, *args, **kwargs) -> None: ...

    async def add_content_async(
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
        skip_if_exists: bool = False,
        auth: Optional[ContentAuth] = None,
    ) -> None:
        """
        DEPRECATED: Use `ainsert()` instead. This method will be removed in a future version.

        Asynchronously insert content into the knowledge base.

        This is a backward-compatible wrapper for the `ainsert()` method.
        Please migrate your code to use `ainsert()` instead.
        """
        return await self.ainsert(
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
            auth=auth,
        )

    @overload
    async def add_contents_async(self, contents: List[ContentDict]) -> None: ...

    @overload
    async def add_contents_async(
        self,
        *,
        paths: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
        topics: Optional[List[str]] = None,
        text_contents: Optional[List[str]] = None,
        reader: Optional[Reader] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
        remote_content: Optional[RemoteContent] = None,
    ) -> None: ...

    async def add_contents_async(self, *args, **kwargs) -> None:
        """
        DEPRECATED: Use `ainsert_many()` instead. This method will be removed in a future version.

        Asynchronously insert multiple content items into the knowledge base.

        This is a backward-compatible wrapper for the `ainsert_many()` method.
        Please migrate your code to use `ainsert_many()` instead.
        """
        return await self.ainsert_many(*args, **kwargs)
