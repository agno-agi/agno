import asyncio
import hashlib
import io
import json
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
from agno.knowledge.reader.utils.urls import canonical_page_name, is_sitemap_url
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.remote_content import (
    RemoteContent,
)
from agno.knowledge.remote_knowledge import RemoteKnowledge
from agno.knowledge.types import ContentType
from agno.knowledge.utils import get_agno_metadata, merge_user_metadata, set_agno_metadata, strip_agno_metadata
from agno.utils.http import async_fetch_with_retry
from agno.utils.knowledge import strict_user_id_kwarg
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
        user_id: Optional[str] = None,
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
        user_id: Optional[str] = None,
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
            user_id: Owner of this content. ``None`` writes to the shared bucket, which everyone
                can read. A string scopes the content to that user: scoped reads return their own
                rows plus shared ones, and scoped writes and deletes touch only their own.
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
            user_id=user_id,
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
        user_id: Optional[str] = None,
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
        user_id: Optional[str] = None,
    ) -> None:
        """Insert a single piece of content. See ``insert``."""
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
            user_id=user_id,
        )
        content.content_hash = self._build_content_hash(content)
        content.id = generate_id(content.content_hash)

        await self._aload_content(content, upsert, skip_if_exists, include, exclude)

    # --- Insert Many ---
    @overload
    async def ainsert_many(
        self,
        contents: List[ContentDict],
        *,
        upsert: bool = True,
        skip_if_exists: bool = False,
        user_id: Optional[str] = None,
    ) -> None: ...

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
        user_id: Optional[str] = None,
    ) -> None: ...

    async def ainsert_many(self, *args, **kwargs) -> None:
        """Asynchronously insert multiple content items. See ``insert_many``."""
        if args and isinstance(args[0], list):
            arguments = args[0]
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            user_id = kwargs.get("user_id")
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
                    user_id=argument.get("user_id", user_id),
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
            user_id = kwargs.get("user_id")
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
                )

        else:
            raise ValueError("Invalid usage of insert_many.")

    @overload
    def insert_many(
        self,
        contents: List[ContentDict],
        *,
        upsert: bool = True,
        skip_if_exists: bool = False,
        user_id: Optional[str] = None,
    ) -> None: ...

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
        user_id: Optional[str] = None,
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
            user_id: Owner applied to every item in this call. A per-item ``user_id`` in the
                list form takes precedence. See ``insert``.
        """
        if args and isinstance(args[0], list):
            arguments = args[0]
            upsert = kwargs.get("upsert", True)
            skip_if_exists = kwargs.get("skip_if_exists", False)
            user_id = kwargs.get("user_id")
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
                    user_id=argument.get("user_id", user_id),
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
            user_id = kwargs.get("user_id")
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
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
                    user_id=user_id,
                )

        else:
            raise ValueError("Invalid usage of insert_many.")

    # ==========================================
    # PUBLIC API - SEARCH METHODS
    # ==========================================

    def _inject_instance_scope_filter(
        self,
        search_filters: Optional[Union[Dict[str, Any], List["FilterExpr"]]],
    ) -> Optional[Union[Dict[str, Any], List["FilterExpr"]]]:
        """Add the ``linked_to`` instance scope to the caller's filters when isolation is on.

        Returns a new filter object. ``user_id`` is not part of the filter DSL — it travels
        separately to ``vector_db.search()``, where each backend applies its own primitive.
        """
        if not (self.isolate_vector_search and self.name):
            return search_filters

        if search_filters is None:
            return {"linked_to": self.name}
        if isinstance(search_filters, dict):
            return {**search_filters, "linked_to": self.name}
        if isinstance(search_filters, list):
            return [EQ("linked_to", self.name), *search_filters]
        return search_filters

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Returns relevant documents matching a query.

        Args:
            user_id: Owner scope forwarded to ``vector_db.search()``. ``None`` searches everything.
        """
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

            search_filters = self._inject_instance_scope_filter(filters)

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            return self.vector_db.search(
                query=query,
                limit=_max_results,
                filters=search_filters,
                **strict_user_id_kwarg(self.vector_db.search, user_id),
            )
        except ValueError:
            # The adapters raise these outside their own catch-alls on purpose.
            raise
        except Exception as e:
            log_error(f"Error searching for documents: {str(e)}")
            return []

    async def asearch(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        search_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Returns relevant documents matching a query. See ``search``."""
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

            search_filters = self._inject_instance_scope_filter(filters)

            _max_results = max_results or self.max_results
            log_debug(f"Getting {_max_results} relevant documents for query: {query}")
            try:
                return await self.vector_db.async_search(
                    query=query,
                    limit=_max_results,
                    filters=search_filters,
                    **strict_user_id_kwarg(self.vector_db.async_search, user_id),
                )
            except NotImplementedError:
                log_info("Vector db does not support async search")
                return self.vector_db.search(
                    query=query,
                    limit=_max_results,
                    filters=search_filters,
                    **strict_user_id_kwarg(self.vector_db.search, user_id),
                )
        except ValueError:
            # See the matching comment in ``search``.
            raise
        except Exception as e:
            log_error(f"Error searching for documents: {str(e)}")
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
        user_id: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError("get_content() is not supported for async databases. Please use aget_content() instead.")

        # A scoped read returns the caller's rows plus shared ones (user_id IS NULL)
        contents, count = self.contents_db.get_knowledge_contents(
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
            linked_to=self.name,
            user_id=user_id,
        )
        return [self._content_row_to_content(row) for row in contents], count

    async def aget_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            contents, count = await self.contents_db.get_knowledge_contents(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                linked_to=self.name,
                user_id=user_id,
            )
        else:
            contents, count = self.contents_db.get_knowledge_contents(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                linked_to=self.name,
                user_id=user_id,
            )
        return [self._content_row_to_content(row) for row in contents], count

    def get_content_by_id(self, content_id: str, user_id: Optional[str] = None) -> Optional[Content]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError(
                "get_content_by_id() is not supported for async databases. Please use aget_content_by_id() instead."
            )

        content_row = self.contents_db.get_knowledge_content(content_id, user_id=user_id)
        if content_row is None:
            return None
        return self._content_row_to_content(content_row)

    async def aget_content_by_id(self, content_id: str, user_id: Optional[str] = None) -> Optional[Content]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            content_row = await self.contents_db.get_knowledge_content(content_id, user_id=user_id)
        else:
            content_row = self.contents_db.get_knowledge_content(content_id, user_id=user_id)

        if content_row is None:
            return None
        return self._content_row_to_content(content_row)

    def get_content_status(
        self, content_id: str, user_id: Optional[str] = None
    ) -> Tuple[Optional[ContentStatus], Optional[str]]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            raise ValueError(
                "get_content_status() is not supported for async databases. Please use aget_content_status() instead."
            )

        content_row = self.contents_db.get_knowledge_content(content_id, user_id=user_id)
        if content_row is None:
            return None, "Content not found"

        return self._parse_content_status(content_row.status), content_row.status_message

    async def aget_content_status(
        self, content_id: str, user_id: Optional[str] = None
    ) -> Tuple[Optional[ContentStatus], Optional[str]]:
        if self.contents_db is None:
            raise ValueError("No contents db provided")

        if isinstance(self.contents_db, AsyncBaseDb):
            content_row = await self.contents_db.get_knowledge_content(content_id, user_id=user_id)
        else:
            content_row = self.contents_db.get_knowledge_content(content_id, user_id=user_id)

        if content_row is None:
            return None, "Content not found"

        return self._parse_content_status(content_row.status), content_row.status_message

    def patch_content(self, content: Content, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._update_content(content, user_id=user_id)

    async def apatch_content(self, content: Content, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return await self._aupdate_content(content, user_id=user_id)

    def remove_content_by_id(
        self, content_id: str, user_id: Optional[str] = None, _seen: Optional[Set[str]] = None
    ) -> bool:
        """Remove one content row and its vectors; cascades through a site row's pages.

        Returns False when nothing was removed (ownership refused it), when the vector
        store reported a failed delete for a row that records indexed content, or when
        part of a site's cascade failed — the affected rows and their place in the
        parent's cascade record are kept, so a later attempt can still reach the
        vectors instead of orphaning them. A False from the vector store for a row with
        no recorded indexed content (site parents, legacy rows) is a zero-match no-op,
        not a failure — several adapters answer False for both.
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        # Ownership lives on the contents row, so a vector-only knowledge base has nothing to check
        scoped = user_id is not None and self.contents_db is not None
        content = self.get_content_by_id(content_id, user_id=user_id) if scoped else None
        if scoped and (content is None or self._content_is_shared(content, user_id)):
            # ``delete_by_content_id`` takes no owner, so going ahead would strip another
            # owner's vectors and leave their row behind pointing at nothing
            log_debug(f"Skipping delete of content {content_id}: not owned by {user_id}")
            return False

        if content is None and self.contents_db is not None:
            content = self.get_content_by_id(content_id, user_id=user_id)

        # A site row owns its page rows: deleting it deletes them and their vectors.
        # ``_seen`` guards against a metadata cycle and marks the cascade for the
        # parent-list maintenance below.
        seen = _seen if _seen is not None else set()
        seen.add(content_id)
        surviving_children: List[str] = []
        children = get_agno_metadata(content.metadata, "children") if content else None
        if isinstance(children, list):
            for child_id in children:
                if isinstance(child_id, str) and child_id not in seen:
                    if not self.remove_content_by_id(child_id, user_id=user_id, _seen=seen):
                        surviving_children.append(child_id)
        if surviving_children and content is not None:
            # Some pages could not be removed: the parent stays as the retry anchor,
            # its cascade record narrowed to what actually survives.
            self._stamp_row_children(content, surviving_children)
            return False

        if self.vector_db is not None:
            if self.vector_db.__class__.__name__ == "LightRag":
                # For LightRAG, delete by the external_id on the row
                if content is None and self.contents_db is not None:
                    content = self.get_content_by_id(content_id, user_id=user_id)
                if content and content.external_id:
                    lightrag_deleted = self.vector_db.delete_by_external_id(content.external_id)  # type: ignore
                    if lightrag_deleted is False:
                        log_debug(f"LightRAG delete failed for content {content_id}; keeping the row for retry")
                        return False
                else:
                    log_warning(f"No external_id found for content {content_id}, cannot delete from LightRAG")
            else:
                # Backends without per-user isolation accept ``user_id`` as a no-op.
                deleted = self.vector_db.delete_by_content_id(
                    content_id, **strict_user_id_kwarg(self.vector_db.delete_by_content_id, user_id)
                )
                if deleted is False and self._false_delete_is_failure(content):
                    log_debug(f"Vector delete failed for content {content_id}; keeping the row for retry")
                    return False

        if self.contents_db is not None:
            self.contents_db.delete_knowledge_content(content_id, user_id=user_id)
            self._drop_from_parent_children(content, content_id, user_id, seen)
        return True

    def _drop_from_parent_children(
        self, content: Optional[Content], content_id: str, user_id: Optional[str], seen: Set[str]
    ) -> None:
        """After a page row is deleted on its own, take its id off the site row's list."""
        parent_id = get_agno_metadata(content.metadata, "parent_id") if content else None
        if not isinstance(parent_id, str) or parent_id in seen or self.contents_db is None:
            return
        if isinstance(self.contents_db, AsyncBaseDb):
            return
        parent_row = self.contents_db.get_knowledge_content(parent_id, user_id=user_id)
        if parent_row is None:
            return
        siblings = get_agno_metadata(parent_row.metadata, "children")
        if not isinstance(siblings, list) or content_id not in siblings:
            return
        update = Content(id=parent_id, user_id=parent_row.user_id)
        update.metadata = set_agno_metadata(None, "children", [child for child in siblings if child != content_id])
        self._update_content(update)

    async def _adrop_from_parent_children(
        self, content: Optional[Content], content_id: str, user_id: Optional[str], seen: Set[str]
    ) -> None:
        """Async version of _drop_from_parent_children."""
        parent_id = get_agno_metadata(content.metadata, "parent_id") if content else None
        if not isinstance(parent_id, str) or parent_id in seen or self.contents_db is None:
            return
        if isinstance(self.contents_db, AsyncBaseDb):
            parent_row = await self.contents_db.get_knowledge_content(parent_id, user_id=user_id)
        else:
            parent_row = self.contents_db.get_knowledge_content(parent_id, user_id=user_id)
        if parent_row is None:
            return
        siblings = get_agno_metadata(parent_row.metadata, "children")
        if not isinstance(siblings, list) or content_id not in siblings:
            return
        update = Content(id=parent_id, user_id=parent_row.user_id)
        update.metadata = set_agno_metadata(None, "children", [child for child in siblings if child != content_id])
        await self._aupdate_content(update)

    async def aremove_content_by_id(
        self, content_id: str, user_id: Optional[str] = None, _seen: Optional[Set[str]] = None
    ) -> bool:
        """Async version of :meth:`remove_content_by_id` (see there for the return contract)."""
        scoped = user_id is not None and self.contents_db is not None
        content = await self.aget_content_by_id(content_id, user_id=user_id) if scoped else None
        if scoped and (content is None or self._content_is_shared(content, user_id)):
            # See the matching guard in ``remove_content_by_id``.
            log_debug(f"Skipping delete of content {content_id}: not owned by {user_id}")
            return False

        if content is None and self.contents_db is not None:
            content = await self.aget_content_by_id(content_id, user_id=user_id)

        # See the matching cascade in ``remove_content_by_id``.
        seen = _seen if _seen is not None else set()
        seen.add(content_id)
        surviving_children: List[str] = []
        children = get_agno_metadata(content.metadata, "children") if content else None
        if isinstance(children, list):
            for child_id in children:
                if isinstance(child_id, str) and child_id not in seen:
                    if not await self.aremove_content_by_id(child_id, user_id=user_id, _seen=seen):
                        surviving_children.append(child_id)
        if surviving_children and content is not None:
            # See the matching branch in ``remove_content_by_id``.
            await self._astamp_row_children(content, surviving_children)
            return False

        if self.vector_db is not None:
            if self.vector_db.__class__.__name__ == "LightRag":
                # For LightRAG, delete by the external_id on the row
                if content is None and self.contents_db is not None:
                    content = await self.aget_content_by_id(content_id, user_id=user_id)
                if content and content.external_id:
                    # The sync wrapper runs asyncio.run and cannot be called from a
                    # running event loop (e.g. under the REST server)
                    lightrag_deleted = await self.vector_db.async_delete_by_external_id(content.external_id)  # type: ignore
                    if lightrag_deleted is False:
                        log_debug(f"LightRAG delete failed for content {content_id}; keeping the row for retry")
                        return False
                else:
                    log_warning(f"No external_id found for content {content_id}, cannot delete from LightRAG")
            else:
                # See the matching comment in ``remove_content_by_id``.
                deleted = self.vector_db.delete_by_content_id(
                    content_id, **strict_user_id_kwarg(self.vector_db.delete_by_content_id, user_id)
                )
                if deleted is False and self._false_delete_is_failure(content):
                    log_debug(f"Vector delete failed for content {content_id}; keeping the row for retry")
                    return False

        if self.contents_db is not None:
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.delete_knowledge_content(content_id, user_id=user_id)
            else:
                self.contents_db.delete_knowledge_content(content_id, user_id=user_id)
            await self._adrop_from_parent_children(content, content_id, user_id, seen)
        return True

    def remove_all_content(self, user_id: Optional[str] = None) -> bool:
        """Remove every deletable row. Returns False when any removal failed (see
        ``remove_content_by_id``); the failed rows are kept for retry."""
        contents, _ = self.get_content(user_id=user_id)
        all_removed = True
        for content in contents:
            if content.id is not None and not self._content_is_shared(content, user_id):
                if self.get_content_by_id(content.id, user_id=user_id) is None:
                    continue  # already removed by an earlier row's cascade
                if not self.remove_content_by_id(content.id, user_id=user_id):
                    all_removed = False
        return all_removed

    async def aremove_all_content(self, user_id: Optional[str] = None) -> bool:
        """Async version of :meth:`remove_all_content`."""
        contents, _ = await self.aget_content(user_id=user_id)
        all_removed = True
        for content in contents:
            if content.id is not None and not self._content_is_shared(content, user_id):
                if await self.aget_content_by_id(content.id, user_id=user_id) is None:
                    continue  # already removed by an earlier row's cascade
                if not await self.aremove_content_by_id(content.id, user_id=user_id):
                    all_removed = False
        return all_removed

    @staticmethod
    def _row_owns_vectors(content: Optional[Content]) -> bool:
        """Whether this row is recorded as owning indexed vectors.

        ``_agno.vectors_indexed`` is written at every successful vector insert (text,
        file, single-page, and per-page rows alike); ``_agno.content_digest`` is the
        page-row form of the same evidence and is stripped when an embed fails.
        """
        if content is None:
            return False
        if get_agno_metadata(content.metadata, "vectors_indexed") is True:
            return True
        return isinstance(get_agno_metadata(content.metadata, "content_digest"), str)

    @classmethod
    def _false_delete_is_failure(cls, content: Optional[Content]) -> bool:
        """Whether a False from ``delete_by_content_id`` means the delete failed.

        Adapter return semantics are mixed: some return False on operational failure,
        others (Chroma, LanceDB, Weaviate) on a zero-match no-op. The two are told
        apart by what this side persisted: a row recorded as owning vectors treats
        False as a failure and is kept for retry; a row with no such record — a site
        parent, or a row whose indexing never succeeded — treats False as the no-op
        it usually is.
        """
        return cls._row_owns_vectors(content)

    @staticmethod
    def _content_is_shared(content: Content, user_id: Optional[str]) -> bool:
        """Whether ``content`` is shared (unowned) content the caller may read but not delete.

        Scoped reads surface unowned rows too, so a bulk delete must skip them. An unscoped
        caller still deletes everything.
        """
        return user_id is not None and content.user_id is None

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

    def get_valid_filters(self, user_id: Optional[str] = None) -> Set[str]:
        # Filter key names are content, so only return keys from documents the caller can retrieve
        if self.contents_db is None:
            log_info("No contents db configured; returning an empty filter validation key set.")
            return set()
        contents, _ = self.get_content(user_id=user_id)
        valid_filters: Set[str] = set()
        for content in contents:
            if content.metadata:
                valid_filters.update(content.metadata.keys())

        return valid_filters

    async def aget_valid_filters(self, user_id: Optional[str] = None) -> Set[str]:
        """Async version of get_valid_filters."""
        if self.contents_db is None:
            log_info("No contents db configured; returning an empty filter validation key set.")
            return set()
        contents, _ = await self.aget_content(user_id=user_id)
        valid_filters: Set[str] = set()
        for content in contents:
            if content.metadata:
                valid_filters.update(content.metadata.keys())

        return valid_filters

    def validate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]], user_id: Optional[str] = None
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        if self.contents_db is None:
            log_info("No contents db configured; skipping filter key validation and preserving filters.")
            return filters, []

        valid_filters_from_db = self.get_valid_filters(user_id=user_id)

        valid_filters, invalid_keys = self._validate_filters(filters, valid_filters_from_db)

        return valid_filters, invalid_keys

    async def avalidate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]], user_id: Optional[str] = None
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        """Return a tuple containing a dict with all valid filters and a list of invalid filter keys"""
        if self.contents_db is None:
            log_info("No contents db configured; skipping filter key validation and preserving filters.")
            return filters, []

        valid_filters_from_db = await self.aget_valid_filters(user_id=user_id)

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
                log_warning(f"Cannot create {reader_type} reader: {str(e)}")
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
    def sitemap_reader(self) -> Optional[Reader]:
        """Sitemap reader - lazy loaded via factory."""
        return self._get_reader("sitemap")

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
        try:
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
        except Exception as e:
            # The loaders write the contents-db row before the vector work, so a failure
            # here would otherwise strand the row in 'processing' forever
            self._mark_content_failed(content, str(e))
            raise

    async def _aload_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        try:
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
        except Exception as e:
            # See ``_load_content`` — never strand the row in 'processing'.
            await self._amark_content_failed(content, str(e))
            raise

    def _mark_content_failed(self, content: Content, reason: str) -> None:
        """Best-effort record of a terminal 'failed' status and reason on the contents-db row."""
        try:
            content.status = ContentStatus.FAILED
            content.status_message = reason
            self.patch_content(content)
        except Exception:
            # Never let status bookkeeping mask the original error.
            pass

    async def _amark_content_failed(self, content: Content, reason: str) -> None:
        """Async version of _mark_content_failed."""
        try:
            content.status = ContentStatus.FAILED
            content.status_message = reason
            if self.contents_db is not None and isinstance(self.contents_db, AsyncBaseDb):
                await self.apatch_content(content)
            else:
                self.patch_content(content)
        except Exception:
            # Never let status bookkeeping mask the original error.
            pass

    def _should_skip(self, content_hash: str, skip_if_exists: bool, user_id: Optional[str] = None) -> bool:
        """
        Handle the skip_if_exists logic for content that already exists in the vector database.

        Args:
            content_hash: The content hash string to check for existence
            skip_if_exists: Whether to skip if content already exists
            user_id: Owner of the content being loaded. The existence check is scoped to that
                owner, so ``None`` matches the shared bucket alone.

        Returns:
            bool: True if should skip processing, False if should continue
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if (
            self.vector_db
            and self.vector_db.content_hash_exists(
                content_hash, **strict_user_id_kwarg(self.vector_db.content_hash_exists, user_id)
            )
            and skip_if_exists
        ):
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
        Prepare documents for insertion by assigning content_id and optionally
        calculating sizes and updating metadata.

        Note: ``user_id`` is not written into ``meta_data``. It flows as an explicit parameter
        on the ``vector_db.insert`` / ``async_insert`` calls instead.

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
                if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
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
                        log_warning(f"Could not get file size for {path}: {str(e)}")
                        content.size = 0

                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                await self._ahandle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            await self._aload_dir_as_folder(content, path, upsert, skip_if_exists, include, exclude)
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
                if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
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
                        log_warning(f"Could not get file size for {path}: {str(e)}")
                        content.size = 0

                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id, metadata=content.metadata)

                self._handle_vector_db_insert(content, read_documents, upsert)

        elif path.is_dir():
            self._load_dir_as_folder(content, path, upsert, skip_if_exists, include, exclude)
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

        # Set name from URL if not provided. Whether it was caller-provided decides the
        # site row's display name for multi-page reads (see _aload_url_page_groups).
        name_was_auto = not content.name
        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        # A multi-page re-ingest needs the previous run's child-row ids to delete pages that
        # left the site; the upsert below overwrites them, so capture first.
        previous_children, previous_row_owned_vectors = await self._aget_previous_children(content)

        # 1. Add content to contents database
        if previous_row_owned_vectors:
            await self._ainsert_contents_db(content, vectors_indexed=True)
        else:
            await self._ainsert_contents_db(content)
        if previous_children:
            # The upsert above replaced the row's metadata wholesale. Until this read
            # finalizes, the row must keep its cascade record: a failed read that lost
            # the children list would strand every page row on a later site delete.
            # The ROW is patched, never content.metadata — that is a hash input.
            await self._astamp_row_children(content, previous_children)
        elif previous_row_owned_vectors:
            # Same wholesale-upsert hazard for the ownership marker: an aborted legacy
            # promotion must still be recognized as one on the retry, or the retry runs
            # unguarded and lands COMPLETED beside stale searchable vectors.
            marker = Content(id=content.id, user_id=content.user_id)
            marker.metadata = set_agno_metadata(None, "vectors_indexed", True)
            await self._aupdate_content(marker)
        if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
            content.metadata = set_agno_metadata(content.metadata, "vectors_indexed", True)
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
            log_warning(f"Invalid URL: {content.url}: {str(e)}")
        # 3. Fetch and load content if file has an extension
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        # A bare sitemap URL routes to the sitemap reader, which owns the URL end to end
        auto_sitemap = content.reader is None and is_sitemap_url(content.url)
        # Skip pre-download when a custom URL-based reader is provided —
        # it handles the URL directly (e.g. LLMsTxtReader fetches linked pages)
        skip_download = auto_sitemap or (
            content.reader is not None
            and hasattr(content.reader, "get_supported_content_types")
            and ContentType.URL in content.reader.get_supported_content_types()
        )
        if file_extension and not skip_download:
            async with AsyncClient() as client:
                response = await async_fetch_with_retry(content.url, client=client)
            bytes_content = BytesIO(response.content)

        # 4. Select reader
        name = content.name if content.name else content.url
        if auto_sitemap:
            reader = self.sitemap_reader
        elif file_extension:
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
            log_error(f"Error reading URL: {content.url}: {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            await self._aupdate_content(content)
            return

        # A reader that returned nothing read nothing: report the failure and leave every
        # previously loaded page (and its row ownership) untouched. Landing this as
        # COMPLETED-with-no-vectors — or worse, reconciling it against previous children —
        # would turn an outage into a site wipe.
        if not read_documents:
            content.status = ContentStatus.FAILED
            content.status_message = "Reader returned no documents"
            await self._aupdate_content(content)
            return

        # 6. Group documents by source URL for multi-page readers (like WebsiteReader)
        docs_by_source: Dict[str, List[Document]] = {}
        discovery_incomplete = False
        for doc in read_documents:
            # Transport-level flag from the reader; consumed here, never embedded
            if doc.meta_data and doc.meta_data.pop("discovery_incomplete", None):
                discovery_incomplete = True
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        # 8. Multi-page reads land one content row per page, owned by the site row.
        # A row that is already a site row stays one even when the site shrank to one page.
        if len(docs_by_source) > 1 or previous_children:
            await self._aload_url_page_groups(
                content,
                docs_by_source,
                upsert,
                skip_if_exists,
                previous_children,
                name_was_auto,
                discovery_incomplete=discovery_incomplete,
                legacy_promotion=previous_row_owned_vectors and not previous_children,
            )
            return

        # 9. Single source - use existing logic with original content hash
        if read_documents and all((doc.meta_data or {}).get("error") for doc in read_documents):
            # The reader reported every document as a failed fetch; embedding empty
            # text and reporting COMPLETED would hide the failure from status polls.
            content.status = ContentStatus.FAILED
            content.status_message = str((read_documents[0].meta_data or {}).get("error"))
            await self._aupdate_content(content)
            return
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

        # Set name from URL if not provided. Whether it was caller-provided decides the
        # site row's display name for multi-page reads (see _load_url_page_groups).
        name_was_auto = not content.name
        if not content.name and content.url:
            from urllib.parse import urlparse

            parsed = urlparse(content.url)
            url_path = Path(parsed.path)
            content.name = url_path.name if url_path.name else content.url

        # A multi-page re-ingest needs the previous run's child-row ids to delete pages that
        # left the site; the upsert below overwrites them, so capture first.
        previous_children, previous_row_owned_vectors = self._get_previous_children(content)

        # 1. Add content to contents database
        if previous_row_owned_vectors:
            self._insert_contents_db(content, vectors_indexed=True)
        else:
            self._insert_contents_db(content)
        if previous_children:
            # See the matching re-stamp in _aload_from_url.
            self._stamp_row_children(content, previous_children)
        elif previous_row_owned_vectors:
            # See the matching marker re-stamp in _aload_from_url.
            marker = Content(id=content.id, user_id=content.user_id)
            marker.metadata = set_agno_metadata(None, "vectors_indexed", True)
            self._update_content(marker)
        if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
            content.metadata = set_agno_metadata(content.metadata, "vectors_indexed", True)
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
            log_warning(f"Invalid URL: {content.url}: {str(e)}")

        # 3. Fetch and load content if file has an extension
        url_path = Path(parsed_url.path)
        file_extension = url_path.suffix.lower()

        bytes_content = None
        # A bare sitemap URL routes to the sitemap reader, which owns the URL end to end
        auto_sitemap = content.reader is None and is_sitemap_url(content.url)
        # Skip pre-download when a custom URL-based reader is provided —
        # it handles the URL directly (e.g. LLMsTxtReader fetches linked pages)
        skip_download = auto_sitemap or (
            content.reader is not None
            and hasattr(content.reader, "get_supported_content_types")
            and ContentType.URL in content.reader.get_supported_content_types()
        )
        if file_extension and not skip_download:
            response = fetch_with_retry(content.url)
            bytes_content = BytesIO(response.content)

        # 4. Select reader
        name = content.name if content.name else content.url
        if auto_sitemap:
            reader = self.sitemap_reader
        elif file_extension:
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
            log_error(f"Error reading URL: {content.url}: {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = f"Error reading URL: {content.url} - {str(e)}"
            self._update_content(content)
            return

        # See the matching guard in _aload_from_url: an empty read never prunes.
        if not read_documents:
            content.status = ContentStatus.FAILED
            content.status_message = "Reader returned no documents"
            self._update_content(content)
            return

        # 6. Group documents by source URL for multi-page readers (like WebsiteReader)
        docs_by_source: Dict[str, List[Document]] = {}
        discovery_incomplete = False
        for doc in read_documents:
            # Transport-level flag from the reader; consumed here, never embedded
            if doc.meta_data and doc.meta_data.pop("discovery_incomplete", None):
                discovery_incomplete = True
            source_url = doc.meta_data.get("url", content.url) if doc.meta_data else content.url
            source_url = source_url or "unknown"
            if source_url not in docs_by_source:
                docs_by_source[source_url] = []
            docs_by_source[source_url].append(doc)

        # 8. Multi-page reads land one content row per page, owned by the site row.
        # A row that is already a site row stays one even when the site shrank to one page.
        if len(docs_by_source) > 1 or previous_children:
            self._load_url_page_groups(
                content,
                docs_by_source,
                upsert,
                skip_if_exists,
                previous_children,
                name_was_auto,
                discovery_incomplete=discovery_incomplete,
                legacy_promotion=previous_row_owned_vectors and not previous_children,
            )
            return

        # 9. Single source - use existing logic with original content hash
        if read_documents and all((doc.meta_data or {}).get("error") for doc in read_documents):
            # See the matching guard in _aload_from_url.
            content.status = ContentStatus.FAILED
            content.status_message = str((read_documents[0].meta_data or {}).get("error"))
            self._update_content(content)
            return
        if not content.id:
            content.id = generate_id(content.content_hash or "")
        self._prepare_documents_for_insert(read_documents, content.id, calculate_sizes=True)
        self._handle_vector_db_insert(content, read_documents, upsert)

    # --- Per-file rows for folder loads ---

    @staticmethod
    def _file_digest(file_path) -> Optional[str]:
        """sha256 of a file's bytes, streamed; None when the file cannot be read."""
        digest = hashlib.sha256()
        try:
            with open(file_path, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
        except OSError:
            return None
        return digest.hexdigest()

    def _prepare_folder_file_content(self, content: Content, file_path) -> Content:
        """The child Content for one file of a folder load.

        Hash inputs are exactly what the per-file recursion has always used (the
        caller's name/metadata and the file path), so ids match rows written by
        earlier releases; display name and ``_agno`` bookkeeping land after the id
        is fixed, mirroring the page-row ordering rule.
        """
        file_content = Content(
            name=content.name,
            path=str(file_path),
            metadata=dict(strip_agno_metadata(content.metadata) or {}) or None,
            description=content.description,
            reader=content.reader,
            user_id=content.user_id,
        )
        file_content.content_hash = self._build_content_hash(file_content)
        file_content.id = generate_id(file_content.content_hash)
        file_content.name = file_path.name
        file_content.metadata = set_agno_metadata(file_content.metadata, "source_type", "folder")
        file_content.metadata = set_agno_metadata(file_content.metadata, "source_path", str(file_path))
        file_content.metadata = set_agno_metadata(file_content.metadata, "parent_id", content.id)
        digest = self._file_digest(file_path)
        if digest:
            file_content.metadata = set_agno_metadata(file_content.metadata, "content_digest", digest)
        return file_content

    def _folder_files(self, path, include, exclude) -> Tuple[List, bool]:
        """``(files, enumeration_failed)`` — every readable file under ``path``, sorted.

        An enumeration failure is indistinguishable from an empty folder, so it is
        reported and the caller must not prune previously loaded files.
        """
        try:
            files = sorted(entry for entry in Path(path).rglob("*") if entry.is_file())
        except OSError as e:
            log_debug(f"Could not enumerate folder {path}: {e}")
            return [], True
        return [entry for entry in files if self._should_include_file(str(entry), include, exclude)], False

    async def _aload_dir_as_folder(
        self,
        content: Content,
        path,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> None:
        """Land a directory as a folder row owning one child row per file.

        The file twin of ``_aload_url_page_groups``: unchanged files (by byte digest)
        refresh their row without re-reading or re-embedding, a file that fails to
        read gets a FAILED child row without aborting the folder, files that left
        the folder are pruned under the same bool-honoring rules, and deleting the
        folder row cascades. The folder row owns no vectors.
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        content.file_type = "folder"
        content.metadata = set_agno_metadata(content.metadata, "source_type", "folder")
        content.metadata = set_agno_metadata(content.metadata, "source_path", str(path))
        if not content.name:
            content.name = Path(path).name or str(path)

        previous_children, _ = await self._aget_previous_children(content)
        await self._ainsert_contents_db(content)
        if previous_children:
            # See the matching re-stamp in _aload_from_url.
            await self._astamp_row_children(content, previous_children)

        files, enumeration_failed = self._folder_files(path, include, exclude)
        if enumeration_failed or (not files and previous_children):
            # An unreadable or suddenly empty folder must not read as "all files removed"
            content.status = ContentStatus.FAILED
            content.status_message = (
                "Could not enumerate folder" if enumeration_failed else "Folder is empty; previous files kept"
            )
            await self._aupdate_content(content)
            return

        child_ids: List[str] = []
        failed: List[Dict[str, str]] = []
        files_loaded = 0
        for file_path in files:
            file_content = self._prepare_folder_file_content(content, file_path)
            child_ids.append(file_content.id)  # type: ignore[arg-type]

            digest = get_agno_metadata(file_content.metadata, "content_digest")
            if digest is None:
                # The bytes could not be read; ingesting nothing as COMPLETED would hide it
                file_content.status = ContentStatus.FAILED
                file_content.status_message = "File could not be read"
                await self._ainsert_contents_db(file_content)
                failed.append({"path": str(file_path), "error": "File could not be read"})
                continue
            if self.contents_db is not None:
                previous_digest = await self._aget_child_digest(file_content.id, content.user_id)
                if previous_digest is not None and previous_digest == digest:
                    file_content.status = ContentStatus.COMPLETED
                    file_content.metadata = set_agno_metadata(file_content.metadata, "vectors_indexed", True)
                    await self._ainsert_contents_db(file_content)
                    files_loaded += 1
                    log_debug(f"File unchanged, embedding skipped: {file_path}")
                    continue
                if previous_digest is not None:
                    # Changed file: replace its chunks wholesale, as the page path does,
                    # so refresh works without adapter upsert support and never stacks
                    try:
                        clear_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
                        self.vector_db.delete_by_content_id(file_content.id, **clear_kwargs)  # type: ignore[arg-type, union-attr]
                    except Exception as e:
                        log_debug(f"Could not clear previous chunks for {file_path}: {e}")

            try:
                await self._aload_from_path(file_content, upsert, skip_if_exists, include, exclude)
            except Exception as e:
                log_error(f"Error reading file {file_path}: {str(e)}")
                file_content.status = ContentStatus.FAILED
                file_content.status_message = f"{type(e).__name__}: {e}"[:300]
                if file_content.metadata and isinstance(file_content.metadata.get("_agno"), dict):
                    # A digest asserts indexed content; a failed read must not leave one
                    file_content.metadata["_agno"].pop("content_digest", None)
                await self._ainsert_contents_db(file_content)
                failed.append({"path": str(file_path), "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            if self.contents_db is None:
                # Vector-only base: no row to read back; the load not raising is the signal
                files_loaded += 1
                continue
            row = await self.aget_content_by_id(file_content.id, user_id=content.user_id)  # type: ignore[arg-type]
            if row is not None and self._parse_content_status(row.status) == ContentStatus.COMPLETED:
                files_loaded += 1
            else:
                failed.append({"path": str(file_path), "error": (row.status_message if row else None) or "failed"})

        current_ids = set(child_ids)
        if content.id:
            current_ids.add(content.id)
        for stale_id in previous_children:
            if stale_id not in current_ids:
                try:
                    removed = await self.aremove_content_by_id(stale_id, user_id=content.user_id)
                except Exception as e:
                    log_debug(f"Could not remove departed file row {stale_id}: {e}")
                    removed = False
                if not removed:
                    child_ids.append(stale_id)

        self._finalize_site_row_content(
            content,
            len(files),
            files_loaded,
            child_ids,
            failed,
            {},
            "folder",
            name_was_auto=False,
            unit="files",
        )
        await self._aupdate_content(content)

    def _load_dir_as_folder(
        self,
        content: Content,
        path,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> None:
        """Synchronous version of _aload_dir_as_folder."""
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        content.file_type = "folder"
        content.metadata = set_agno_metadata(content.metadata, "source_type", "folder")
        content.metadata = set_agno_metadata(content.metadata, "source_path", str(path))
        if not content.name:
            content.name = Path(path).name or str(path)

        previous_children, _ = self._get_previous_children(content)
        self._insert_contents_db(content)
        if previous_children:
            self._stamp_row_children(content, previous_children)

        files, enumeration_failed = self._folder_files(path, include, exclude)
        if enumeration_failed or (not files and previous_children):
            content.status = ContentStatus.FAILED
            content.status_message = (
                "Could not enumerate folder" if enumeration_failed else "Folder is empty; previous files kept"
            )
            self._update_content(content)
            return

        child_ids: List[str] = []
        failed: List[Dict[str, str]] = []
        files_loaded = 0
        for file_path in files:
            file_content = self._prepare_folder_file_content(content, file_path)
            child_ids.append(file_content.id)  # type: ignore[arg-type]

            digest = get_agno_metadata(file_content.metadata, "content_digest")
            if digest is None:
                # See the matching guard in _aload_dir_as_folder
                file_content.status = ContentStatus.FAILED
                file_content.status_message = "File could not be read"
                self._insert_contents_db(file_content)
                failed.append({"path": str(file_path), "error": "File could not be read"})
                continue
            if self.contents_db is not None:
                previous_digest = self._get_child_digest(file_content.id, content.user_id)
                if previous_digest is not None and previous_digest == digest:
                    file_content.status = ContentStatus.COMPLETED
                    file_content.metadata = set_agno_metadata(file_content.metadata, "vectors_indexed", True)
                    self._insert_contents_db(file_content)
                    files_loaded += 1
                    log_debug(f"File unchanged, embedding skipped: {file_path}")
                    continue
                if previous_digest is not None:
                    # See the matching clear in _aload_dir_as_folder
                    try:
                        clear_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
                        self.vector_db.delete_by_content_id(file_content.id, **clear_kwargs)  # type: ignore[arg-type, union-attr]
                    except Exception as e:
                        log_debug(f"Could not clear previous chunks for {file_path}: {e}")

            try:
                self._load_from_path(file_content, upsert, skip_if_exists, include, exclude)
            except Exception as e:
                log_error(f"Error reading file {file_path}: {str(e)}")
                file_content.status = ContentStatus.FAILED
                file_content.status_message = f"{type(e).__name__}: {e}"[:300]
                if file_content.metadata and isinstance(file_content.metadata.get("_agno"), dict):
                    file_content.metadata["_agno"].pop("content_digest", None)
                self._insert_contents_db(file_content)
                failed.append({"path": str(file_path), "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            if self.contents_db is None:
                # See the matching guard in _aload_dir_as_folder
                files_loaded += 1
                continue
            row = self.get_content_by_id(file_content.id, user_id=content.user_id)  # type: ignore[arg-type]
            if row is not None and self._parse_content_status(row.status) == ContentStatus.COMPLETED:
                files_loaded += 1
            else:
                failed.append({"path": str(file_path), "error": (row.status_message if row else None) or "failed"})

        current_ids = set(child_ids)
        if content.id:
            current_ids.add(content.id)
        for stale_id in previous_children:
            if stale_id not in current_ids:
                try:
                    removed = self.remove_content_by_id(stale_id, user_id=content.user_id)
                except Exception as e:
                    log_debug(f"Could not remove departed file row {stale_id}: {e}")
                    removed = False
                if not removed:
                    child_ids.append(stale_id)

        self._finalize_site_row_content(
            content,
            len(files),
            files_loaded,
            child_ids,
            failed,
            {},
            "folder",
            name_was_auto=False,
            unit="files",
        )
        self._update_content(content)

    # --- Per-page rows for multi-page URL reads ---

    async def _astamp_row_children(self, content: Content, children: List[str]) -> None:
        """Write a children list onto the site ROW without touching content.metadata."""
        update = Content(id=content.id, user_id=content.user_id)
        update.metadata = set_agno_metadata(None, "children", children)
        await self._aupdate_content(update)

    def _stamp_row_children(self, content: Content, children: List[str]) -> None:
        """Synchronous version of _astamp_row_children."""
        update = Content(id=content.id, user_id=content.user_id)
        update.metadata = set_agno_metadata(None, "children", children)
        self._update_content(update)

    _MULTI_PAGE_READER_IDS = {"SitemapReader": "sitemap", "LLMsTxtReader": "llms_txt", "WebsiteReader": "website"}

    @staticmethod
    def _parse_previous_row(row) -> Tuple[List[str], bool]:
        """``(children, owned_vectors)`` from a previous run's row.

        A row that owned vectors and has no children is a legacy single row about to
        be promoted to a site row — its vectors live under its own id and must be
        cleared first. A row without that positive evidence (for example a FAILED
        first ingest) is not a promotion, so a later healthy run can proceed.
        """
        children = get_agno_metadata(row.metadata, "children")
        parsed = [child for child in children if isinstance(child, str)] if isinstance(children, list) else []
        owned = get_agno_metadata(row.metadata, "vectors_indexed") is True or isinstance(
            get_agno_metadata(row.metadata, "content_digest"), str
        )
        return parsed, owned

    async def _aget_previous_children(self, content: Content) -> Tuple[List[str], bool]:
        """``(previous child ids, previous row owned vectors)`` — see _parse_previous_row."""
        if self.contents_db is None or not content.id:
            return [], False
        if isinstance(self.contents_db, AsyncBaseDb):
            row = await self.contents_db.get_knowledge_content(content.id, user_id=content.user_id)
        else:
            row = self.contents_db.get_knowledge_content(content.id, user_id=content.user_id)
        if row is None:
            return [], False
        return self._parse_previous_row(row)

    def _get_previous_children(self, content: Content) -> Tuple[List[str], bool]:
        """Synchronous version of _aget_previous_children."""
        if self.contents_db is None or not content.id or isinstance(self.contents_db, AsyncBaseDb):
            return [], False
        row = self.contents_db.get_knowledge_content(content.id, user_id=content.user_id)
        if row is None:
            return [], False
        return self._parse_previous_row(row)

    async def _aget_child_digest(self, child_id: Optional[str], user_id: Optional[str]) -> Optional[str]:
        """The stored page-text digest of a child row, or None when the row does not exist."""
        if self.contents_db is None or not child_id:
            return None
        if isinstance(self.contents_db, AsyncBaseDb):
            row = await self.contents_db.get_knowledge_content(child_id, user_id=user_id)
        else:
            row = self.contents_db.get_knowledge_content(child_id, user_id=user_id)
        if row is None:
            return None
        digest = get_agno_metadata(row.metadata, "content_digest")
        return digest if isinstance(digest, str) else None

    def _get_child_digest(self, child_id: Optional[str], user_id: Optional[str]) -> Optional[str]:
        """Synchronous version of _aget_child_digest."""
        if self.contents_db is None or not child_id or isinstance(self.contents_db, AsyncBaseDb):
            return None
        row = self.contents_db.get_knowledge_content(child_id, user_id=user_id)
        if row is None:
            return None
        digest = get_agno_metadata(row.metadata, "content_digest")
        return digest if isinstance(digest, str) else None

    def _prepare_page_child(
        self, content: Content, source_url: str, source_docs: List[Document]
    ) -> Tuple[Content, Optional[str], Optional[str], str, Optional[str]]:
        """Build the child Content for one page's URL group.

        Returns ``(child, digest, error, extractor, source_kind)``. The child's id equals the
        ``content_id`` its vectors carry (both derive from the per-URL document hash), which
        is what makes per-page delete reach the vectors. The digest is over the page text
        before any header injection, so provenance decoration never forces a re-embed.
        """
        doc_hash = self._build_document_content_hash(source_docs[0], content)
        first = source_docs[0]
        meta = first.meta_data or {}
        error = meta.get("error")
        page_text = "".join(doc.content or "" for doc in source_docs)
        if not error and not page_text:
            error = "empty"
        digest = hashlib.sha256(page_text.encode("utf-8", errors="replace")).hexdigest() if not error else None

        # Readers that name pages per page keep their names; a reader that stamped every
        # document with the read-level name gets a canonical per-page one instead.
        if first.name and first.name not in (content.name, content.url):
            child_name = first.name
        else:
            child_name = canonical_page_name(source_url)

        user_metadata = strip_agno_metadata(content.metadata)
        child = Content(
            id=generate_id(doc_hash),
            name=child_name,
            description=content.description,
            url=source_url,
            metadata=dict(user_metadata) if user_metadata else None,
            user_id=content.user_id,
            content_hash=doc_hash,
            file_type="url",
            size=len(page_text.encode("utf-8", errors="replace")) if page_text else None,
        )
        source_kind = meta.get("source")
        extractor = meta.get("extractor") or "unknown"
        child.metadata = set_agno_metadata(child.metadata, "source_type", source_kind or "url")
        child.metadata = set_agno_metadata(child.metadata, "source_url", source_url)
        child.metadata = set_agno_metadata(child.metadata, "parent_id", content.id)
        child.metadata = set_agno_metadata(child.metadata, "fetched_at", int(time.time()))
        if meta.get("title"):
            child.metadata = set_agno_metadata(child.metadata, "title", meta["title"])
        if meta.get("extractor"):
            child.metadata = set_agno_metadata(child.metadata, "extractor", meta["extractor"])
        if meta.get("attempts"):
            child.metadata = set_agno_metadata(child.metadata, "attempts", meta["attempts"])
        if digest:
            child.metadata = set_agno_metadata(child.metadata, "content_digest", digest)
        return child, digest, (str(error) if error else None), extractor, source_kind

    def _finalize_site_row_content(
        self,
        content: Content,
        total_pages: int,
        pages_loaded: int,
        child_ids: List[str],
        failed: List[Dict[str, str]],
        extractor_counts: Dict[str, int],
        source_kind: Optional[str],
        name_was_auto: bool,
        reader_id: Optional[str] = None,
        discovery_incomplete: bool = False,
        site_owns_vectors: bool = False,
        unit: str = "pages",
    ) -> None:
        """Turn the parent row into the site row: aggregate status, children, provenance."""
        if name_was_auto and content.url:
            from urllib.parse import urlparse

            host = urlparse(content.url).netloc
            if host:
                content.name = host
        content.metadata = set_agno_metadata(content.metadata, "source_type", source_kind or "url")
        content.metadata = set_agno_metadata(content.metadata, "children", child_ids)
        content.metadata = set_agno_metadata(content.metadata, "page_count", pages_loaded)
        content.metadata = set_agno_metadata(content.metadata, "auto_named", name_was_auto)
        if site_owns_vectors:
            content.metadata = set_agno_metadata(content.metadata, "vectors_indexed", True)
        if reader_id:
            # A refresh must re-run the reader that built this site, never a guessed one
            content.metadata = set_agno_metadata(content.metadata, "reader_id", reader_id)
        if extractor_counts:
            content.metadata = set_agno_metadata(content.metadata, "extractor_counts", extractor_counts)
        if failed:
            content.metadata = set_agno_metadata(content.metadata, "failed", failed[:25])

        message = f"{pages_loaded} of {total_pages} {unit} loaded"
        if discovery_incomplete:
            message += "; sitemap discovery incomplete, previous pages kept"
        if failed:
            sample = ", ".join(str(entry.get("url") or entry.get("path")) for entry in failed[:5])
            message += f"; failed: {sample}"
            if len(failed) > 5:
                message += f" and {len(failed) - 5} more"
        content.status = ContentStatus.COMPLETED if pages_loaded > 0 else ContentStatus.FAILED
        content.status_message = message

    async def _aload_url_page_groups(
        self,
        content: Content,
        docs_by_source: Dict[str, List[Document]],
        upsert: bool,
        skip_if_exists: bool,
        previous_children: List[str],
        name_was_auto: bool,
        discovery_incomplete: bool = False,
        legacy_promotion: bool = False,
    ) -> None:
        """Land a multi-page read as one content row per page under the site row.

        Each page row's id equals its vectors' ``content_id``. A page whose stored text
        digest is unchanged refreshes its row without re-embedding; a changed page replaces
        its vectors wholesale (works without adapter upsert support, so the REST route's
        ``upsert=False`` still refreshes); a page that left the site since the previous run
        is deleted; a page that failed to fetch gets a FAILED row and is retried next run.
        ``skip_if_exists`` for page rows therefore means "same URL and same text".
        """
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        # The site row owns no page vectors. Clearing its content_id first makes the
        # 1-to-N transition drop the legacy single-row vectors, and lets the overview
        # branch below re-insert without stacking chunks run over run. On an ordinary
        # re-ingest there is nothing to clear, so a False is a zero-match no-op; during
        # a promotion (a legacy row growing into a site) the legacy vectors are real,
        # and inserting page rows beside them would leave stale content searchable —
        # a failed clear aborts the promotion for a later retry.
        try:
            clear_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
            cleared = self.vector_db.delete_by_content_id(content.id, **clear_kwargs)  # type: ignore[arg-type]
            clear_failed = cleared is False and legacy_promotion
        except Exception as e:
            log_debug(f"Could not clear site-row vectors before per-page load: {e}")
            clear_failed = legacy_promotion
        if clear_failed:
            content.status = ContentStatus.FAILED
            content.status_message = "Could not clear the row's previous vectors; re-run to retry"
            await self._aupdate_content(content)
            return
        if legacy_promotion:
            ownership = Content(id=content.id, user_id=content.user_id)
            ownership.metadata = set_agno_metadata(None, "vectors_indexed", False)
            await self._aupdate_content(ownership)

        reader_id = self._MULTI_PAGE_READER_IDS.get(type(content.reader).__name__) if content.reader else None

        child_ids: List[str] = []
        failed: List[Dict[str, str]] = []
        extractor_counts: Dict[str, int] = {}
        pages_loaded = 0
        source_kind: Optional[str] = None
        site_owns_vectors = False

        for source_url, source_docs in docs_by_source.items():
            child, digest, error, extractor, doc_source = self._prepare_page_child(content, source_url, source_docs)
            if child.id == content.id:
                # A document whose URL is the insert URL itself (e.g. an llms.txt overview)
                # hashes to the site row's own id. Its vectors stay under the site hash as
                # before; it must not become a child row or the prune pass would eat the site.
                if error is None:
                    self._prepare_documents_for_insert(source_docs, content.id, calculate_sizes=True)  # type: ignore[arg-type]
                    try:
                        owner_kwargs = strict_user_id_kwarg(self.vector_db.async_insert, content.user_id)
                        await self.vector_db.async_insert(
                            content.content_hash,  # type: ignore[arg-type]
                            documents=source_docs,
                            filters=strip_agno_metadata(content.metadata),
                            **owner_kwargs,
                        )
                        site_owns_vectors = True
                    except Exception as e:
                        log_error(f"Error inserting overview document from {source_url}: {str(e)}")
                continue
            child_ids.append(child.id)  # type: ignore[arg-type]
            if source_kind is None and doc_source:
                source_kind = doc_source

            previous_digest: Optional[str] = None
            if self.contents_db is not None:
                previous_digest = await self._aget_child_digest(child.id, content.user_id)

            if error is not None:
                # A page that was loaded before keeps its row and vectors: a transient
                # fetch failure must not demote good, searchable content. The failure is
                # still surfaced on the site row.
                if previous_digest is not None:
                    failed.append({"url": source_url, "error": error, "stale_kept": "true"})
                    pages_loaded += 1
                    continue
                child.status = ContentStatus.FAILED
                child.status_message = error
                await self._ainsert_contents_db(child)
                failed.append({"url": source_url, "error": error})
                continue

            if self.contents_db is not None:
                if previous_digest is not None and previous_digest == digest:
                    child.status = ContentStatus.COMPLETED
                    child.metadata = set_agno_metadata(child.metadata, "vectors_indexed", True)
                    await self._ainsert_contents_db(child)
                    extractor_counts[extractor] = extractor_counts.get(extractor, 0) + 1
                    pages_loaded += 1
                    log_debug(f"Page unchanged, embedding skipped: {source_url}")
                    continue
            elif self._should_skip(child.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
                # Vector-only knowledge base: no digest to compare, keep the legacy check
                log_debug(f"Skipping already indexed: {source_url}")
                continue

            self._prepare_documents_for_insert(source_docs, child.id, calculate_sizes=True)  # type: ignore[arg-type]
            vector_metadata = strip_agno_metadata(content.metadata)

            # Resolve the owner scope OUTSIDE the try: a scoped write against a legacy
            # adapter must fail the ingest (marked FAILED by _aload_content), not be
            # swallowed per-page and reported COMPLETED.
            use_upsert = self.vector_db.upsert_available() and upsert
            owner_kwargs = strict_user_id_kwarg(
                self.vector_db.async_upsert if use_upsert else self.vector_db.async_insert, content.user_id
            )
            try:
                if use_upsert:
                    await self.vector_db.async_upsert(
                        child.content_hash,  # type: ignore[arg-type]
                        source_docs,
                        vector_metadata,
                        **owner_kwargs,
                    )
                else:
                    # Replace wholesale: a changed page refreshes without adapter upsert
                    # support, and a row-less vector group (pre-existing orphans) is
                    # adopted without duplicating its chunks.
                    deleted = None
                    try:
                        delete_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
                        deleted = self.vector_db.delete_by_content_id(child.id, **delete_kwargs)  # type: ignore[arg-type]
                    except NotImplementedError:
                        log_debug(f"Vector db cannot clear previous chunks for {source_url}")
                    if deleted is False and previous_digest is not None:
                        failed.append(
                            {
                                "url": source_url,
                                "error": "Could not replace previous page vectors",
                                "stale_kept": "true",
                            }
                        )
                        pages_loaded += 1
                        log_debug(f"Keeping previous page vectors for retry: {source_url}")
                        continue
                    await self.vector_db.async_insert(
                        child.content_hash,  # type: ignore[arg-type]
                        documents=source_docs,
                        filters=vector_metadata,
                        **owner_kwargs,
                    )
            except Exception as e:
                log_error(f"Error inserting document from {source_url}: {str(e)}")
                child.status = ContentStatus.FAILED
                child.status_message = "Could not embed page"
                # The digest asserts "this text is indexed" — it must not survive an
                # embed failure, or the next identical run would skip the embed and
                # mark the page COMPLETED with no vectors behind it.
                if child.metadata and isinstance(child.metadata.get("_agno"), dict):
                    child.metadata["_agno"].pop("content_digest", None)
                await self._ainsert_contents_db(child)
                failed.append({"url": source_url, "error": "Could not embed page"})
                continue

            child.status = ContentStatus.COMPLETED
            child.metadata = set_agno_metadata(child.metadata, "vectors_indexed", True)
            await self._ainsert_contents_db(child)
            extractor_counts[extractor] = extractor_counts.get(extractor, 0) + 1
            pages_loaded += 1

        # Pages that left the site since the previous run disappear with it — but only
        # when discovery saw the whole site, and a page whose delete failed keeps its
        # place in the children list so a later run can still reach it.
        current_ids = set(child_ids)
        if content.id:
            current_ids.add(content.id)  # never prune the site row itself
        if not discovery_incomplete:
            for stale_id in previous_children:
                if stale_id not in current_ids:
                    try:
                        removed = await self.aremove_content_by_id(stale_id, user_id=content.user_id)
                    except Exception as e:
                        log_debug(f"Could not remove stale page row {stale_id}: {e}")
                        removed = False
                    if not removed:
                        child_ids.append(stale_id)
        else:
            for stale_id in previous_children:
                if stale_id not in current_ids:
                    child_ids.append(stale_id)

        self._finalize_site_row_content(
            content,
            len(docs_by_source),
            pages_loaded,
            child_ids,
            failed,
            extractor_counts,
            source_kind,
            name_was_auto,
            reader_id=reader_id,
            discovery_incomplete=discovery_incomplete,
            site_owns_vectors=site_owns_vectors,
        )
        await self._aupdate_content(content)

    def _load_url_page_groups(
        self,
        content: Content,
        docs_by_source: Dict[str, List[Document]],
        upsert: bool,
        skip_if_exists: bool,
        previous_children: List[str],
        name_was_auto: bool,
        discovery_incomplete: bool = False,
        legacy_promotion: bool = False,
    ) -> None:
        """Synchronous version of _aload_url_page_groups."""
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)

        # See the matching clear-and-abort in _aload_url_page_groups.
        try:
            clear_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
            cleared = self.vector_db.delete_by_content_id(content.id, **clear_kwargs)  # type: ignore[arg-type]
            clear_failed = cleared is False and legacy_promotion
        except Exception as e:
            log_debug(f"Could not clear site-row vectors before per-page load: {e}")
            clear_failed = legacy_promotion
        if clear_failed:
            content.status = ContentStatus.FAILED
            content.status_message = "Could not clear the row's previous vectors; re-run to retry"
            self._update_content(content)
            return
        if legacy_promotion:
            ownership = Content(id=content.id, user_id=content.user_id)
            ownership.metadata = set_agno_metadata(None, "vectors_indexed", False)
            self._update_content(ownership)

        reader_id = self._MULTI_PAGE_READER_IDS.get(type(content.reader).__name__) if content.reader else None

        child_ids: List[str] = []
        failed: List[Dict[str, str]] = []
        extractor_counts: Dict[str, int] = {}
        pages_loaded = 0
        source_kind: Optional[str] = None
        site_owns_vectors = False

        for source_url, source_docs in docs_by_source.items():
            child, digest, error, extractor, doc_source = self._prepare_page_child(content, source_url, source_docs)
            if child.id == content.id:
                # See the matching branch in _aload_url_page_groups.
                if error is None:
                    self._prepare_documents_for_insert(source_docs, content.id, calculate_sizes=True)  # type: ignore[arg-type]
                    try:
                        owner_kwargs = strict_user_id_kwarg(self.vector_db.insert, content.user_id)
                        self.vector_db.insert(
                            content.content_hash,  # type: ignore[arg-type]
                            documents=source_docs,
                            filters=strip_agno_metadata(content.metadata),
                            **owner_kwargs,
                        )
                        site_owns_vectors = True
                    except Exception as e:
                        log_error(f"Error inserting overview document from {source_url}: {str(e)}")
                continue
            child_ids.append(child.id)  # type: ignore[arg-type]
            if source_kind is None and doc_source:
                source_kind = doc_source

            previous_digest: Optional[str] = None
            if self.contents_db is not None:
                previous_digest = self._get_child_digest(child.id, content.user_id)

            if error is not None:
                # See the matching last-known-good branch in _aload_url_page_groups.
                if previous_digest is not None:
                    failed.append({"url": source_url, "error": error, "stale_kept": "true"})
                    pages_loaded += 1
                    continue
                child.status = ContentStatus.FAILED
                child.status_message = error
                self._insert_contents_db(child)
                failed.append({"url": source_url, "error": error})
                continue

            if self.contents_db is not None:
                if previous_digest is not None and previous_digest == digest:
                    child.status = ContentStatus.COMPLETED
                    child.metadata = set_agno_metadata(child.metadata, "vectors_indexed", True)
                    self._insert_contents_db(child)
                    extractor_counts[extractor] = extractor_counts.get(extractor, 0) + 1
                    pages_loaded += 1
                    log_debug(f"Page unchanged, embedding skipped: {source_url}")
                    continue
            elif self._should_skip(child.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
                # Vector-only knowledge base: no digest to compare, keep the legacy check
                log_debug(f"Skipping already indexed: {source_url}")
                continue

            self._prepare_documents_for_insert(source_docs, child.id, calculate_sizes=True)  # type: ignore[arg-type]
            vector_metadata = strip_agno_metadata(content.metadata)

            # Resolve the owner scope OUTSIDE the try: a scoped write against a legacy
            # adapter must fail the ingest (marked FAILED by _load_content), not be
            # swallowed per-page and reported COMPLETED.
            use_upsert = self.vector_db.upsert_available() and upsert
            owner_kwargs = strict_user_id_kwarg(
                self.vector_db.upsert if use_upsert else self.vector_db.insert, content.user_id
            )
            try:
                if use_upsert:
                    self.vector_db.upsert(
                        child.content_hash,  # type: ignore[arg-type]
                        source_docs,
                        vector_metadata,
                        **owner_kwargs,
                    )
                else:
                    # Replace wholesale: a changed page refreshes without adapter upsert
                    # support, and a row-less vector group (pre-existing orphans) is
                    # adopted without duplicating its chunks.
                    deleted = None
                    try:
                        delete_kwargs = strict_user_id_kwarg(self.vector_db.delete_by_content_id, content.user_id)
                        deleted = self.vector_db.delete_by_content_id(child.id, **delete_kwargs)  # type: ignore[arg-type]
                    except NotImplementedError:
                        log_debug(f"Vector db cannot clear previous chunks for {source_url}")
                    if deleted is False and previous_digest is not None:
                        failed.append(
                            {
                                "url": source_url,
                                "error": "Could not replace previous page vectors",
                                "stale_kept": "true",
                            }
                        )
                        pages_loaded += 1
                        log_debug(f"Keeping previous page vectors for retry: {source_url}")
                        continue
                    self.vector_db.insert(
                        child.content_hash,  # type: ignore[arg-type]
                        documents=source_docs,
                        filters=vector_metadata,
                        **owner_kwargs,
                    )
            except Exception as e:
                log_error(f"Error inserting document from {source_url}: {str(e)}")
                child.status = ContentStatus.FAILED
                child.status_message = "Could not embed page"
                # See the matching digest strip in _aload_url_page_groups.
                if child.metadata and isinstance(child.metadata.get("_agno"), dict):
                    child.metadata["_agno"].pop("content_digest", None)
                self._insert_contents_db(child)
                failed.append({"url": source_url, "error": "Could not embed page"})
                continue

            child.status = ContentStatus.COMPLETED
            child.metadata = set_agno_metadata(child.metadata, "vectors_indexed", True)
            self._insert_contents_db(child)
            extractor_counts[extractor] = extractor_counts.get(extractor, 0) + 1
            pages_loaded += 1

        # See the matching prune guard in _aload_url_page_groups.
        current_ids = set(child_ids)
        if content.id:
            current_ids.add(content.id)  # never prune the site row itself
        if not discovery_incomplete:
            for stale_id in previous_children:
                if stale_id not in current_ids:
                    try:
                        removed = self.remove_content_by_id(stale_id, user_id=content.user_id)
                    except Exception as e:
                        log_debug(f"Could not remove stale page row {stale_id}: {e}")
                        removed = False
                    if not removed:
                        child_ids.append(stale_id)
        else:
            for stale_id in previous_children:
                if stale_id not in current_ids:
                    child_ids.append(stale_id)

        self._finalize_site_row_content(
            content,
            len(docs_by_source),
            pages_loaded,
            child_ids,
            failed,
            extractor_counts,
            source_kind,
            name_was_auto,
            reader_id=reader_id,
            discovery_incomplete=discovery_incomplete,
            site_owns_vectors=site_owns_vectors,
        )
        self._update_content(content)

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
        if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
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
        if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):  # type: ignore[arg-type]
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
                user_id=content.user_id,
            )
            content.content_hash = self._build_content_hash(content)
            content.id = generate_id(content.content_hash)

            await self._ainsert_contents_db(content)
            if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):
                content.status = ContentStatus.COMPLETED
                await self._aupdate_content(content)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db.__class__.__name__ == "LightRag":
                await self._aprocess_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue  # Skip to next topic, don't exit loop

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
                user_id=content.user_id,
            )
            content.content_hash = self._build_content_hash(content)
            content.id = generate_id(content.content_hash)

            self._insert_contents_db(content)
            if self._should_skip(content.content_hash, skip_if_exists, user_id=content.user_id):
                content.status = ContentStatus.COMPLETED
                self._update_content(content)
                continue  # Skip to next topic, don't exit loop

            if self.vector_db.__class__.__name__ == "LightRag":
                self._process_lightrag_content(content, KnowledgeContentOrigin.TOPIC)
                continue  # Skip to next topic, don't exit loop

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

    @staticmethod
    def _build_remote_content_identity(remote_content: Optional["RemoteContent"]) -> Optional[str]:
        """Return a stable identity string for a remote content reference.

        The reference's source scope (bucket, repo, site, container) plus its
        in-scope path must be included in the content hash so that the same
        filename pulled from two different sources does not collide.
        """
        if remote_content is None:
            return None

        from agno.knowledge.remote_content.remote_content import (
            AzureBlobContent,
            GCSContent,
            GitHubContent,
            S3Content,
            SharePointContent,
        )

        if isinstance(remote_content, GitHubContent):
            scope = remote_content.repo or ""
            in_scope = remote_content.file_path or remote_content.folder_path or ""
            branch = remote_content.branch or ""
            return f"github:{scope}@{branch}:{in_scope}"

        elif isinstance(remote_content, S3Content):
            scope = remote_content.bucket_name or (
                remote_content.bucket.name if remote_content.bucket is not None else ""
            )
            in_scope = (
                remote_content.key
                or remote_content.prefix
                or (remote_content.object.name if remote_content.object is not None else "")
            )
            return f"s3:{scope}:{in_scope}"

        elif isinstance(remote_content, GCSContent):
            scope = remote_content.bucket_name or (
                remote_content.bucket.name if remote_content.bucket is not None else ""
            )
            in_scope = remote_content.blob_name or remote_content.prefix or ""
            return f"gcs:{scope}:{in_scope}"

        elif isinstance(remote_content, SharePointContent):
            scope = f"{remote_content.site_path or ''}/{remote_content.drive_id or ''}"
            in_scope = remote_content.file_path or remote_content.folder_path or ""
            return f"sharepoint:{remote_content.config_id}:{scope}:{in_scope}"

        elif isinstance(remote_content, AzureBlobContent):
            in_scope = remote_content.blob_name or remote_content.prefix or ""
            return f"azureblob:{remote_content.config_id}:{in_scope}"

        return None

    def _build_content_hash(self, content: Content) -> str:
        """
        Build the content hash from the content.

        For URLs and paths, includes the name, description and metadata in the hash if
        provided to ensure unique content with the same URL/path but different
        names/descriptions/metadata get different hashes.

        Hash format:
        - URL with name and description: hash("{name}:{description}:{url}")
        - URL with name only: hash("{name}:{url}")
        - URL with description only: hash("{description}:{url}")
        - URL without name/description: hash("{url}") (backward compatible)
        - Same logic applies to paths
        - When metadata is provided, a deterministic representation of it is appended
          so the same content inserted with different metadata produces distinct hashes
          (this allows `upsert=False` inserts of the same document with different
          metadata to coexist instead of collapsing onto each other).
        - When the content carries an owner, the owner leads the hash so two users uploading
          the same file name get distinct rows instead of colliding
        """
        hash_parts = []
        # Digest the owner, don't raw-join it: a namespaced owner could otherwise collide onto another's id
        if content.user_id is not None:
            hash_parts.append(hashlib.sha256(content.user_id.encode()).hexdigest()[:16])
        if content.name:
            hash_parts.append(content.name)
        if content.description:
            hash_parts.append(content.description)
        if content.metadata:
            hash_parts.append(json.dumps(content.metadata, sort_keys=True, default=str))

        remote_identity = self._build_remote_content_identity(content.remote_content)
        if remote_identity:
            hash_parts.append(remote_identity)

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

        # Digest the owner, as in _build_content_hash: no cross-owner dedup, no forgeable id
        if content.user_id is not None:
            hash_parts.append(hashlib.sha256(content.user_id.encode()).hexdigest()[:16])
        if content.name:
            hash_parts.append(content.name)
        if content.description:
            hash_parts.append(content.description)
        if content.metadata:
            hash_parts.append(json.dumps(content.metadata, sort_keys=True, default=str))

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
                log_warning(f"Failed to convert {field_name} to string, using default: {str(e)}")
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
            user_id=content_row.user_id,
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
            user_id=content.user_id,
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

    async def _ainsert_contents_db(self, content: Content, vectors_indexed: Optional[bool] = None):
        if self.contents_db:
            content_row = self._build_knowledge_row(content)
            if vectors_indexed is not None:
                content_row.metadata = merge_user_metadata(
                    content_row.metadata, set_agno_metadata(None, "vectors_indexed", vectors_indexed)
                )
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.upsert_knowledge_content(knowledge_row=content_row)
            else:
                self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    def _insert_contents_db(self, content: Content, vectors_indexed: Optional[bool] = None):
        """Synchronously add content to contents database."""
        if self.contents_db:
            if isinstance(self.contents_db, AsyncBaseDb):
                raise ValueError(
                    "_insert_contents_db() is not supported with an async DB. Please use ainsert() with AsyncDb."
                )
            content_row = self._build_knowledge_row(content)
            if vectors_indexed is not None:
                content_row.metadata = merge_user_metadata(
                    content_row.metadata, set_agno_metadata(None, "vectors_indexed", vectors_indexed)
                )
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

        # Resolve the owner scope OUTSIDE the try: a scoped write against a legacy
        # adapter must surface its ValueError (marked FAILED with the real reason),
        # not be relabelled as a generic "could not embed" failure.
        try:
            owner_kwargs = strict_user_id_kwarg(
                self.vector_db.async_upsert
                if (self.vector_db.upsert_available() and upsert)
                else self.vector_db.async_insert,
                content.user_id,
            )
        except ValueError as e:
            log_error(f"Error inserting document: {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = str(e)
            await self._aupdate_content(content)
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                await self.vector_db.async_upsert(
                    content.content_hash,  # type: ignore[arg-type]
                    read_documents,
                    content.metadata,
                    **owner_kwargs,
                )
            except Exception as e:
                log_error(f"Error upserting document: {str(e)}")
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
                    **owner_kwargs,
                )
            except Exception as e:
                log_error(f"Error inserting document: {str(e)}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not insert embedding"
                await self._aupdate_content(content)
                return

        # The row now provably owns vectors; deletion reads this marker to tell an
        # operational False apart from a zero-match no-op.
        content.metadata = set_agno_metadata(content.metadata, "vectors_indexed", True)
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

        # Resolve the owner scope OUTSIDE the try (see the async twin for rationale).
        try:
            owner_kwargs = strict_user_id_kwarg(
                self.vector_db.upsert if (self.vector_db.upsert_available() and upsert) else self.vector_db.insert,
                content.user_id,
            )
        except ValueError as e:
            log_error(f"Error inserting document: {str(e)}")
            content.status = ContentStatus.FAILED
            content.status_message = str(e)
            self._update_content(content)
            return

        if self.vector_db.upsert_available() and upsert:
            try:
                self.vector_db.upsert(
                    content.content_hash,  # type: ignore[arg-type]
                    read_documents,
                    content.metadata,
                    **owner_kwargs,
                )
            except Exception as e:
                log_error(f"Error upserting document: {str(e)}")
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
                    **owner_kwargs,
                )
            except Exception as e:
                log_error(f"Error inserting document: {str(e)}")
                content.status = ContentStatus.FAILED
                content.status_message = "Could not insert embedding"
                self._update_content(content)
                return

        # See the matching marker in _ahandle_vector_db_insert.
        content.metadata = set_agno_metadata(content.metadata, "vectors_indexed", True)
        content.status = ContentStatus.COMPLETED
        self._update_content(content)

    # --- Content Update ---

    def _update_content(self, content: Content, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        from agno.vectordb import VectorDb

        # No scope passed: default it to the content's owner so the re-read can't reach another's row
        if user_id is None:
            user_id = content.user_id

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
            content_row = self.contents_db.get_knowledge_content(content.id, user_id=user_id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None
            if user_id is not None and content_row.user_id is None:
                # Shared content is readable by a scoped caller but not theirs to change
                log_debug(f"Skipping update of content {content.id}: shared content is not owned by {user_id}")
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

    async def _aupdate_content(self, content: Content, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # No scope passed: default it to the content's owner so the re-read can't reach another's row
        if user_id is None:
            user_id = content.user_id

        if self.contents_db:
            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            # TODO: we shouldn't check for content here, we should trust the upsert method to handle conflicts
            if isinstance(self.contents_db, AsyncBaseDb):
                content_row = await self.contents_db.get_knowledge_content(content.id, user_id=user_id)
            else:
                content_row = self.contents_db.get_knowledge_content(content.id, user_id=user_id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None
            if user_id is not None and content_row.user_id is None:
                # See the matching guard in ``_update_content``.
                log_debug(f"Skipping update of content {content.id}: shared content is not owned by {user_id}")
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
                log_error(f"Error uploading file to LightRAG: {str(e)}")
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

                # The reader is a shared instance; restore its chunking preference after the
                # unchunked read this store needs.
                previous_chunk = reader.chunk
                reader.chunk = False
                try:
                    read_documents = reader.read(content.url, name=content.name)
                finally:
                    reader.chunk = previous_chunk
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    await self._aupdate_content(content)
                    return

                # Only the first document would land below; refusing beats silently
                # ingesting one page of a multi-page read.
                page_urls = {doc.meta_data.get("url") for doc in read_documents if doc.meta_data} - {None}
                if len(page_urls) > 1:
                    content.status = ContentStatus.FAILED
                    content.status_message = "LightRag does not support multi-page readers"
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
                log_error(f"Error uploading file to LightRAG: {str(e)}")
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
                log_error(f"Error uploading file to LightRAG: {str(e)}")
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

                # The reader is a shared instance; restore its chunking preference after the
                # unchunked read this store needs.
                previous_chunk = reader.chunk
                reader.chunk = False
                try:
                    read_documents = reader.read(content.url, name=content.name)
                finally:
                    reader.chunk = previous_chunk
                if not content.id:
                    content.id = generate_id(content.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content.id)

                if not read_documents:
                    log_error("No documents read from URL")
                    content.status = ContentStatus.FAILED
                    self._update_content(content)
                    return

                # Only the first document would land below; refusing beats silently
                # ingesting one page of a multi-page read.
                page_urls = {doc.meta_data.get("url") for doc in read_documents if doc.meta_data} - {None}
                if len(page_urls) > 1:
                    content.status = ContentStatus.FAILED
                    content.status_message = "LightRag does not support multi-page readers"
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
                log_error(f"Error uploading file to LightRAG: {str(e)}")
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
        user_id: Optional[str] = None,
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
            valid_filters = self.get_valid_filters(user_id=user_id)
            if valid_filters:
                context_parts.append(self._get_agentic_filter_instructions(valid_filters))

        return "<knowledge_base>\n" + "\n".join(context_parts) + "\n</knowledge_base>"

    async def abuild_context(
        self,
        enable_agentic_filters: bool = False,
        user_id: Optional[str] = None,
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
            valid_filters = await self.aget_valid_filters(user_id=user_id)
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

    # The tools these factories build carry the run's owner
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
                docs = self.search(
                    query=query, filters=knowledge_filters, user_id=getattr(run_context, "user_id", None)
                )
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {str(e)}")
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
                docs = await self.asearch(
                    query=query, filters=knowledge_filters, user_id=getattr(run_context, "user_id", None)
                )
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {str(e)}")
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
                docs = self.search(query=query, filters=search_filters, user_id=getattr(run_context, "user_id", None))
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {str(e)}")
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
                docs = await self.asearch(
                    query=query, filters=search_filters, user_id=getattr(run_context, "user_id", None)
                )
            except Exception as e:
                retrieval_timer.stop()
                log_warning(f"Knowledge search failed: {str(e)}")
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
        user_id: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        """Retrieve documents for context injection.

        Used by the add_knowledge_to_context feature to pre-fetch
        relevant documents into the user message.

        Args:
            query: The query string.
            max_results: Maximum number of results.
            filters: Filters to apply.
            user_id: Owner scope forwarded to ``search``. ``None`` returns everything.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects.
        """
        return self.search(query=query, max_results=max_results, filters=filters, user_id=user_id)

    async def aretrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        """Async version of retrieve."""
        return await self.asearch(query=query, max_results=max_results, filters=filters, user_id=user_id)
