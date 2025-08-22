from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.remote_content import RemoteContent


class ContentStatus(str, Enum):
    """Enumeration of possible content processing statuses."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FileData:
    content: Optional[Union[str, bytes]] = None
    type: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None


@dataclass
class ContentAuth:
    password: Optional[str] = None


@dataclass
class Content:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    auth: Optional[ContentAuth] = None
    file_data: Optional[FileData] = None
    metadata: Optional[Dict[str, Any]] = None
    topics: Optional[List[str]] = None
    remote_content: Optional[RemoteContent] = None
    reader: Optional[Reader] = None
    size: Optional[int] = None
    file_type: Optional[str] = None
    content_hash: Optional[str] = None
    status: Optional[ContentStatus] = None
    status_message: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    external_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Content":
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            description=data.get("description"),
            path=data.get("path"),
            url=data.get("url"),
            auth=data.get("auth"),
            file_data=data.get("file_data"),
            metadata=data.get("metadata"),
            topics=data.get("topics"),
            remote_content=data.get("remote_content"),
            reader=data.get("reader"),
            size=data.get("size"),
            file_type=data.get("file_type"),
            content_hash=data.get("content_hash"),
            status=data.get("status"),
            status_message=data.get("status_message"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            external_id=data.get("external_id"),
        )
