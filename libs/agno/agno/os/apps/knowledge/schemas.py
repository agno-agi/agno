from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContentStatus(str, Enum):
    """Enumeration of possible content processing statuses."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentStatusResponse(BaseModel):
    """Response model for content status endpoint."""

    status: ContentStatus
    status_message: str = ""


class ContentResponseSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    size: Optional[str] = None
    linked_to: Optional[str] = None
    metadata: Optional[dict] = None
    access_count: Optional[int] = None
    status: Optional[ContentStatus] = None
    status_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, content: Dict[str, Any]) -> "ContentResponseSchema":
        status = content.get("status")
        if isinstance(status, str):
            try:
                status = ContentStatus(status.lower())
            except ValueError:
                # Handle legacy or unknown statuses gracefully
                if "failed" in status.lower():
                    status = ContentStatus.FAILED
                elif "completed" in status.lower():
                    status = ContentStatus.COMPLETED
                else:
                    status = ContentStatus.PROCESSING
        elif status is None:
            status = ContentStatus.PROCESSING  # Default for None values

        return cls(
            id=content.get("id"),  # type: ignore
            name=content.get("name"),
            description=content.get("description"),
            type=content.get("file_type"),
            size=str(content.get("size")) if content.get("size") else "0",
            metadata=content.get("metadata"),
            status=status,
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


class ContentUpdateSchema(BaseModel):
    """Schema for updating content."""

    name: Optional[str] = Field(None, description="Content name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Content description", max_length=1000)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Content metadata as key-value pairs")
    reader_id: Optional[str] = Field(None, description="ID of the reader to use for processing", min_length=1)


class ReaderSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None


class ConfigResponseSchema(BaseModel):
    readers: Optional[List[ReaderSchema]] = None
    filters: Optional[List[str]] = None
