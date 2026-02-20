from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast, overload

from agno.db.base import AsyncBaseDb, BaseDb
from agno.filters import EQ, FilterExpr
from agno.knowledge.content import Content, ContentAuth, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.pipeline.ingestion import IngestionPipeline
from agno.knowledge.reader import Reader
from agno.knowledge.reader_registry import ReaderRegistry
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.remote_content import (
    RemoteContent,
)
from agno.knowledge.remote_knowledge import RemoteLoader
from agno.knowledge.store.content_store import ContentStore
from agno.utils.log import log_debug, log_info, log_warning
from agno.utils.string import generate_id

ContentDict = Dict[str, Union[str, Dict[str, str]]]


@dataclass
class Knowledge:
    """Knowledge class — orchestrates content store, reader registry, and ingestion pipeline."""

    name: Optional[str] = None
    description: Optional[str] = None
    vector_db: Optional[Any] = None
    contents_db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None
    content_sources: Optional[List[BaseStorageConfig]] = None
    isolate_vector_search: bool = False

    def __post_init__(self):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db and not self.vector_db.exists():
            self.vector_db.create()

        # Initialize components
        self._content_store = ContentStore(
            contents_db=self.contents_db,
            knowledge_name=self.name,
        )
        self._reader_registry = ReaderRegistry(
            readers=self.readers if self.readers is not None else {},
        )
        self._reader_registry.construct_readers()
        # Share the same dict object so self.readers stays in sync
        self.readers = self._reader_registry.readers

        self._pipeline = IngestionPipeline(
            vector_db=self.vector_db,
            content_store=self._content_store,
            reader_registry=self._reader_registry,
            knowledge_name=self.name,
            isolate_vector_search=self.isolate_vector_search,
        )
        self._remote_loader = RemoteLoader(knowledge=self)

    # ==========================================
    # PUBLIC API - INSERT METHODS
    # ==========================================

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
        """Synchronously insert content into the knowledge base."""
        if all(argument is None for argument in [path, url, text_content, topics, remote_content]):
            log_warning(
                "At least one of 'path', 'url', 'text_content', 'topics', or 'remote_content' must be provided."
            )
            return

        file_data = None
        if text_content:
            file_data = FileData(content=text_content, type="Text")

        content = Content(
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=file_data if file_data else None,
            metadata=metadata,
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
        if all(argument is None for argument in [path, url, text_content, topics, remote_content]):
            log_warning(
                "At least one of 'path', 'url', 'text_content', 'topics', or 'remote_content' must be provided."
            )
            return

        file_data = None
        if text_content:
            file_data = FileData(content=text_content, type="Text")

        content = Content(
            name=name,
            description=description,
            path=path,
            url=url,
            file_data=file_data if file_data else None,
            metadata=metadata,
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
        """Synchronously insert multiple content items into the knowledge base."""
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
            from agno.utils.log import log_error

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
            from agno.utils.log import log_error

            log_error(f"Error searching for documents: {e}")
            return []

    # ==========================================
    # PUBLIC API - CONTENT MANAGEMENT (forwarded to ContentStore)
    # ==========================================

    def get_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        return self._content_store.get_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

    async def aget_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Content], int]:
        return await self._content_store.aget_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

    def get_content_by_id(self, content_id: str) -> Optional[Content]:
        return self._content_store.get_content_by_id(content_id)

    async def aget_content_by_id(self, content_id: str) -> Optional[Content]:
        return await self._content_store.aget_content_by_id(content_id)

    def get_content_status(self, content_id: str) -> Tuple[Optional[ContentStatus], Optional[str]]:
        return self._content_store.get_content_status(content_id)

    async def aget_content_status(self, content_id: str) -> Tuple[Optional[ContentStatus], Optional[str]]:
        return await self._content_store.aget_content_status(content_id)

    def patch_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return self._content_store.patch_content(content, vector_db=self.vector_db)

    async def apatch_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return await self._content_store.apatch_content(content, vector_db=self.vector_db)

    def remove_content_by_id(self, content_id: str):
        from agno.vectordb import VectorDb

        self.vector_db = cast(VectorDb, self.vector_db)
        if self.vector_db is not None:
            if self.vector_db.__class__.__name__ == "LightRag":
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
    # PUBLIC API - FILTER METHODS (forwarded to ContentStore)
    # ==========================================

    def get_valid_filters(self) -> Set[str]:
        return self._content_store.get_valid_filters()

    async def aget_valid_filters(self) -> Set[str]:
        return await self._content_store.aget_valid_filters()

    def validate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        return self._content_store.validate_filters(filters)

    async def avalidate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        return await self._content_store.avalidate_filters(filters)

    # ==========================================
    # PUBLIC API - READER MANAGEMENT (forwarded to ReaderRegistry)
    # ==========================================

    def construct_readers(self):
        if not hasattr(self, "_reader_registry"):
            if self.readers is None:
                self.readers = {}
            return
        self._reader_registry.construct_readers()
        self.readers = self._reader_registry.readers

    def add_reader(self, reader: Reader):
        result = self._reader_registry.add_reader(reader)
        self.readers = self._reader_registry.readers
        return result

    def get_readers(self) -> Dict[str, Reader]:
        # Sync: if self.readers was replaced externally, update the registry
        if self.readers is not self._reader_registry.readers:
            self._reader_registry.readers = self.readers
        result = self._reader_registry.get_readers()
        self.readers = self._reader_registry.readers
        return result

    # ==========================================
    # REMOTE CONFIG HELPERS
    # ==========================================

    def _get_remote_configs(self) -> List[BaseStorageConfig]:
        """Return configured remote content sources."""
        return self.content_sources or []

    def _get_remote_config_by_id(self, config_id: str) -> Optional[BaseStorageConfig]:
        """Get a remote content config by its ID."""
        if not self.content_sources:
            return None
        return next((c for c in self.content_sources if c.id == config_id), None)

    # ==========================================
    # FORWARDING METHODS (for loader callback compatibility)
    # ==========================================

    def _build_content_hash(self, content: Content) -> str:
        return self._pipeline.build_content_hash(content)

    def _build_document_content_hash(self, document: Document, content: Content) -> str:
        return self._pipeline.build_document_content_hash(document, content)

    def _should_skip(self, content_hash: str, skip_if_exists: bool) -> bool:
        return self._pipeline.should_skip(content_hash, skip_if_exists)

    def _should_include_file(self, file_path: str, include: Optional[List[str]], exclude: Optional[List[str]]) -> bool:
        return self._pipeline.should_include_file(file_path, include, exclude)

    def _is_text_mime_type(self, mime_type: str) -> bool:
        return self._pipeline.is_text_mime_type(mime_type)

    def _prepare_documents_for_insert(
        self,
        documents: List[Document],
        content_id: str,
        calculate_sizes: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        return self._pipeline.prepare_documents_for_insert(documents, content_id, calculate_sizes, metadata)

    def _handle_vector_db_insert(self, content: Content, read_documents: List[Document], upsert: bool) -> None:
        return self._pipeline.handle_vector_db_insert(content, read_documents, upsert)

    async def _ahandle_vector_db_insert(self, content: Content, read_documents: List[Document], upsert: bool) -> None:
        return await self._pipeline.ahandle_vector_db_insert(content, read_documents, upsert)

    def _insert_contents_db(self, content: Content) -> None:
        self._content_store.insert(content)

    async def _ainsert_contents_db(self, content: Content) -> None:
        await self._content_store.ainsert(content)

    def _update_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return self._content_store.update(content, vector_db=self.vector_db)

    async def _aupdate_content(self, content: Content) -> Optional[Dict[str, Any]]:
        return await self._content_store.aupdate(content, vector_db=self.vector_db)

    def _select_reader_by_uri(self, uri: str, provided_reader: Optional[Reader] = None) -> Optional[Reader]:
        return self._reader_registry.select_reader_by_uri(uri, provided_reader)

    def _select_reader_by_extension(
        self, file_extension: str, provided_reader: Optional[Reader] = None
    ) -> Tuple[Optional[Reader], str]:
        return self._reader_registry.select_reader_by_extension(file_extension, provided_reader)

    def _select_reader(self, extension: str) -> Reader:
        return self._reader_registry.select_reader(extension)

    def _generate_reader_key(self, reader: Reader) -> str:
        return self._reader_registry._generate_reader_key(reader)

    def _get_reader(self, reader_type: str) -> Optional[Reader]:
        return self._reader_registry._get_reader(reader_type)

    def _read(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        return self._reader_registry.read(reader, source, name, password)

    async def _aread(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        return await self._reader_registry.aread(reader, source, name, password)

    def _content_row_to_content(self, content_row: Any) -> Content:
        return self._content_store._content_row_to_content(content_row)

    def _build_knowledge_row(self, content: Content) -> Any:
        return self._content_store._build_knowledge_row(content)

    def _parse_content_status(self, status_str: Optional[str]) -> ContentStatus:
        return self._content_store._parse_content_status(status_str)

    def _ensure_string_field(self, value: Any, field_name: str, default: str = "") -> str:
        return self._content_store._ensure_string_field(value, field_name, default)

    def _validate_filters(
        self, filters: Union[Dict[str, Any], List[FilterExpr]], valid_metadata_filters: Set[str]
    ) -> Tuple[Union[Dict[str, Any], List[FilterExpr]], List[str]]:
        return self._content_store._validate_filters(filters, valid_metadata_filters)

    # Reader properties (forwarded to ReaderRegistry)
    @property
    def pdf_reader(self) -> Optional[Reader]:
        return self._reader_registry.pdf_reader

    @property
    def csv_reader(self) -> Optional[Reader]:
        return self._reader_registry.csv_reader

    @property
    def excel_reader(self) -> Optional[Reader]:
        return self._reader_registry.excel_reader

    @property
    def docx_reader(self) -> Optional[Reader]:
        return self._reader_registry.docx_reader

    @property
    def pptx_reader(self) -> Optional[Reader]:
        return self._reader_registry.pptx_reader

    @property
    def json_reader(self) -> Optional[Reader]:
        return self._reader_registry.json_reader

    @property
    def markdown_reader(self) -> Optional[Reader]:
        return self._reader_registry.markdown_reader

    @property
    def text_reader(self) -> Optional[Reader]:
        return self._reader_registry.text_reader

    @property
    def website_reader(self) -> Optional[Reader]:
        return self._reader_registry.website_reader

    @property
    def firecrawl_reader(self) -> Optional[Reader]:
        return self._reader_registry.firecrawl_reader

    @property
    def youtube_reader(self) -> Optional[Reader]:
        return self._reader_registry.youtube_reader

    # ==========================================
    # PIPELINE LOAD FORWARDING (for backward compatibility / tests)
    # ==========================================

    def _load_from_path(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        self._pipeline.load_from_path(content, upsert, skip_if_exists, include, exclude)

    async def _aload_from_path(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        await self._pipeline.aload_from_path(content, upsert, skip_if_exists, include, exclude)

    def _load_from_url(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        self._pipeline.load_from_url(content, upsert, skip_if_exists)

    async def _aload_from_url(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        await self._pipeline.aload_from_url(content, upsert, skip_if_exists)

    def _load_from_content(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        self._pipeline.load_from_content(content, upsert, skip_if_exists)

    async def _aload_from_content(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        await self._pipeline.aload_from_content(content, upsert, skip_if_exists)

    def _load_from_topics(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        self._pipeline.load_from_topics(content, upsert, skip_if_exists)

    async def _aload_from_topics(self, content: Content, upsert: bool, skip_if_exists: bool) -> None:
        await self._pipeline.aload_from_topics(content, upsert, skip_if_exists)

    # ==========================================
    # PRIVATE - CONTENT LOADING (delegates to pipeline + remote)
    # ==========================================

    def _load_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        self._pipeline.load_content(content, upsert, skip_if_exists, include, exclude)
        if content.remote_content:
            self._remote_loader.load_from_remote_content(content, upsert, skip_if_exists)

    async def _aload_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        await self._pipeline.aload_content(content, upsert, skip_if_exists, include, exclude)
        if content.remote_content:
            await self._remote_loader.aload_from_remote_content(content, upsert, skip_if_exists)

    # ========================================================================
    # Protocol Implementation (build_context, get_tools, retrieve)
    # ========================================================================

    _SEARCH_KNOWLEDGE_INSTRUCTIONS = (
        "You have a knowledge base you can search using the search_knowledge_base tool. "
        "Search before answering questions\u2014don't assume you know the answer. "
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
        valid_filters_str = ", ".join(valid_filters)
        return self._AGENTIC_FILTER_INSTRUCTION_TEMPLATE.format(valid_filters_str=valid_filters_str)

    def build_context(self, enable_agentic_filters: bool = False, **kwargs) -> str:
        context_parts: List[str] = [self._SEARCH_KNOWLEDGE_INSTRUCTIONS]
        if enable_agentic_filters:
            valid_filters = self.get_valid_filters()
            if valid_filters:
                context_parts.append(self._get_agentic_filter_instructions(valid_filters))
        return "<knowledge_base>\n" + "\n".join(context_parts) + "\n</knowledge_base>"

    async def abuild_context(self, enable_agentic_filters: bool = False, **kwargs) -> str:
        context_parts: List[str] = [self._SEARCH_KNOWLEDGE_INSTRUCTIONS]
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
                    query=query, references=[doc.to_dict() for doc in docs], time=round(retrieval_timer.elapsed, 4)
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
                    query=query, references=[doc.to_dict() for doc in docs], time=round(retrieval_timer.elapsed, 4)
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
        from agno.models.message import MessageReferences
        from agno.tools.function import Function
        from agno.utils.timer import Timer

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
            search_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
            if filters and get_agentic_or_user_search_filters is not None:
                filters_dict: Dict[str, Any] = {}
                for filt in filters:
                    if isinstance(filt, dict):
                        filters_dict.update(filt)
                    elif hasattr(filt, "key") and hasattr(filt, "value"):
                        filters_dict[filt.key] = filt.value
                search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
            else:
                search_filters = knowledge_filters
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
                    query=query, references=[doc.to_dict() for doc in docs], time=round(retrieval_timer.elapsed, 4)
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
            search_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
            if filters and get_agentic_or_user_search_filters is not None:
                filters_dict: Dict[str, Any] = {}
                for filt in filters:
                    if isinstance(filt, dict):
                        filters_dict.update(filt)
                    elif hasattr(filt, "key") and hasattr(filt, "value"):
                        filters_dict[filt.key] = filt.value
                search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
            else:
                search_filters = knowledge_filters
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
                    query=query, references=[doc.to_dict() for doc in docs], time=round(retrieval_timer.elapsed, 4)
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
        func.strict = False
        return func

    def _convert_documents_to_string(self, docs: List[Document], agent: Optional[Any] = None) -> str:
        if agent is not None and hasattr(agent, "_convert_documents_to_string"):
            return agent._convert_documents_to_string([doc.to_dict() for doc in docs])
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
        return self.search(query=query, max_results=max_results, filters=filters)

    async def aretrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        **kwargs,
    ) -> List[Document]:
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
        """DEPRECATED: Use `insert()` instead."""
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
        """DEPRECATED: Use `ainsert()` instead."""
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
        """DEPRECATED: Use `ainsert_many()` instead."""
        return await self.ainsert_many(*args, **kwargs)
