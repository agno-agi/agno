from datetime import datetime
from typing import List, Optional

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


class ReaderSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None


class ConfigResponseSchema(BaseModel):
    readers: Optional[List[ReaderSchema]] = None
    filters: Optional[List[str]] = None
