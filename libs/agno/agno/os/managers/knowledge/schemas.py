from typing import Optional

from fastapi import UploadFile
from pydantic import BaseModel


class DocumentResponseSchema(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    size: Optional[str] = None
    linked_to: Optional[str] = None
    metadata: Optional[dict] = None
    access_count: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
