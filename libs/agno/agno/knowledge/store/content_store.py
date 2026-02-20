"""Content store for Knowledge.

Manages content CRUD operations against the contents database,
including insert, update, get, patch, and filter validation.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.filters import FilterExpr
from agno.knowledge.content import Content, ContentStatus
from agno.utils.log import log_debug, log_info, log_warning


@dataclass
class ContentStore:
    """Handles content persistence in the contents database."""

    contents_db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    knowledge_name: Optional[str] = None

    # ==========================================
    # INSERT
    # ==========================================

    def insert(self, content: Content) -> None:
        """Synchronously upsert content into the contents database."""
        if self.contents_db:
            if isinstance(self.contents_db, AsyncBaseDb):
                raise ValueError(
                    "_insert_contents_db() is not supported with an async DB. Please use ainsert() with AsyncDb."
                )
            content_row = self._build_knowledge_row(content)
            self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    async def ainsert(self, content: Content) -> None:
        """Asynchronously upsert content into the contents database."""
        if self.contents_db:
            content_row = self._build_knowledge_row(content)
            if isinstance(self.contents_db, AsyncBaseDb):
                await self.contents_db.upsert_knowledge_content(knowledge_row=content_row)
            else:
                self.contents_db.upsert_knowledge_content(knowledge_row=content_row)

    # ==========================================
    # UPDATE
    # ==========================================

    def update(self, content: Content, vector_db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Synchronously update content in the contents database."""
        if self.contents_db:
            if isinstance(self.contents_db, AsyncBaseDb):
                raise ValueError(
                    "update_content() is not supported with an async DB. Please use aupdate_content() instead."
                )

            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None

            if content.name is not None:
                content_row.name = self._ensure_string_field(content.name, "content.name", default="")
            if content.description is not None:
                content_row.description = self._ensure_string_field(
                    content.description, "content.description", default=""
                )
            if content.metadata is not None:
                content_row.metadata = content.metadata
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

            if vector_db:
                vector_db.update_metadata(content_id=content.id, metadata=content.metadata or {})

            return content_row.to_dict()

        else:
            return None

    async def aupdate(self, content: Content, vector_db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Asynchronously update content in the contents database."""
        if self.contents_db:
            if not content.id:
                log_warning("Content id is required to update Knowledge content")
                return None

            if isinstance(self.contents_db, AsyncBaseDb):
                content_row = await self.contents_db.get_knowledge_content(content.id)
            else:
                content_row = self.contents_db.get_knowledge_content(content.id)
            if content_row is None:
                log_warning(f"Content row not found for id: {content.id}, cannot update status")
                return None

            if content.name is not None:
                content_row.name = self._ensure_string_field(content.name, "content.name", default="")
            if content.description is not None:
                content_row.description = self._ensure_string_field(
                    content.description, "content.description", default=""
                )
            if content.metadata is not None:
                content_row.metadata = content.metadata
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

            if vector_db:
                vector_db.update_metadata(content_id=content.id, metadata=content.metadata or {})

            return content_row.to_dict()

        else:
            return None

    # ==========================================
    # GET
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

        contents, count = self.contents_db.get_knowledge_contents(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.knowledge_name
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

        if isinstance(self.contents_db, AsyncBaseDb):
            contents, count = await self.contents_db.get_knowledge_contents(
                limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.knowledge_name
            )
        else:
            contents, count = self.contents_db.get_knowledge_contents(
                limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, linked_to=self.knowledge_name
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

    def patch_content(self, content: Content, vector_db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        return self.update(content, vector_db=vector_db)

    async def apatch_content(self, content: Content, vector_db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        return await self.aupdate(content, vector_db=vector_db)

    # ==========================================
    # FILTERS
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
            if valid_metadata_filters is None or not valid_metadata_filters:
                invalid_keys = list(filters.keys())
                log_warning(
                    f"No valid metadata filters tracked yet. All filter keys considered invalid: {invalid_keys}"
                )
                return {}, invalid_keys

            for key, value in filters.items():
                base_key = key.split(".")[-1] if "." in key else key
                if base_key in valid_metadata_filters or key in valid_metadata_filters:
                    valid_filters[key] = value  # type: ignore
                else:
                    invalid_keys.append(key)
                    log_warning(f"Invalid filter key: {key} - not present in knowledge base")

        elif isinstance(filters, List):
            if valid_metadata_filters is None or not valid_metadata_filters:
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

                if hasattr(filter_item, "key"):
                    key = filter_item.key
                    base_key = key.split(".")[-1] if "." in key else key
                    if base_key in valid_metadata_filters or key in valid_metadata_filters:
                        valid_list_filters.append(filter_item)
                    else:
                        invalid_keys.append(key)
                        log_warning(f"Invalid filter key: {key} - not present in knowledge base")
                else:
                    valid_list_filters.append(filter_item)

            return valid_list_filters, invalid_keys

        return valid_filters, invalid_keys

    # ==========================================
    # CONVERSION HELPERS
    # ==========================================

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
            linked_to=self.knowledge_name if self.knowledge_name else "",
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

    def _ensure_string_field(self, value: Any, field_name: str, default: str = "") -> str:
        """Safely ensure a field is a string, handling various edge cases."""
        if value is None or value == "":
            return default

        if isinstance(value, list):
            if len(value) == 0:
                log_debug(f"Empty list found for {field_name}, using default: '{default}'")
                return default
            elif len(value) == 1:
                log_debug(f"Single-item list found for {field_name}, extracting: '{value[0]}'")
                return str(value[0]) if value[0] is not None else default
            else:
                log_debug(f"Multi-item list found for {field_name}, joining: {value}")
                return " | ".join(str(item) for item in value if item is not None)

        if not isinstance(value, str):
            log_debug(f"Non-string type {type(value)} found for {field_name}, converting: '{value}'")
            try:
                return str(value)
            except Exception as e:
                log_warning(f"Failed to convert {field_name} to string: {e}, using default")
                return default

        return value
