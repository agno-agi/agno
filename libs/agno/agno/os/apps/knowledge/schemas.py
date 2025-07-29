from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel

from agno.knowledge.content import Content


class ContentResponseSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    size: Optional[str] = None
    linked_to: Optional[str] = None
    metadata: Optional[dict] = None
    access_count: Optional[int] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_content(cls, content: Content) -> "ContentResponseSchema":
        content_id = content.id if hasattr(content, "id") else None
        created_at = content.created_at if hasattr(content, "created_at") else None
        updated_at = content.updated_at if hasattr(content, "updated_at") else None

        return cls(
            id=content_id,  # type: ignore
            name=content.name,
            description=content.description,
            type=content.file_type,
            size=str(content.size) if content.size else "0",
            metadata=content.metadata,
            status=content.status,
            status_message=content.status_message,
            created_at=datetime.fromtimestamp(created_at, tz=timezone.utc) if created_at else None,
            updated_at=datetime.fromtimestamp(updated_at, tz=timezone.utc) if updated_at else None,
            # TODO: These fields are not available in the Content class. Fix the inconsistency
            access_count=None,
            linked_to=None,
        )


class ReaderSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None


class ConfigResponseSchema(BaseModel):
    readers: Optional[List[ReaderSchema]] = None
    filters: Optional[List[str]] = None
