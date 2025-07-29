from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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
    def from_dict(cls, content: Dict[str, Any]) -> "ContentResponseSchema":
        return cls(
            id=content.get("id"),  # type: ignore
            name=content.get("name"),
            description=content.get("description"),
            type=content.get("file_type"),
            size=str(content.get("size")) if content.get("size") else "0",
            metadata=content.get("metadata"),
            status=content.get("status"),
            status_message=content.get("status_message"),
            created_at=datetime.fromtimestamp(content["created_at"], tz=timezone.utc)
            if content.get("created_at")
            else None,
            updated_at=datetime.fromtimestamp(content["updated_at"], tz=timezone.utc)
            if content.get("updated_at")
            else None,
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
