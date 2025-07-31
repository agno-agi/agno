from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.remote_content import RemoteContent


@dataclass
class FileData:
    content: Optional[Union[str, bytes]] = None
    type: Optional[str] = None


@dataclass
class Content:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    file_data: Optional[Union[str, FileData]] = None
    metadata: Optional[Dict[str, Any]] = None
    topics: Optional[List[str]] = None
    file_type: Optional[str] = None
    remote_content: Optional[RemoteContent] = None
    reader: Optional[Reader] = None
    size: Optional[int] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    content_hash: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Content":
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            description=data.get("description"),
            path=data.get("path"),
            url=data.get("url"),
            file_data=data.get("file_data"),
            metadata=data.get("metadata"),
            topics=data.get("topics"),
            file_type=data.get("file_type"),
            config=data.get("config"),
            reader=data.get("reader"),
            size=data.get("size"),
            status=data.get("status"),
            status_message=data.get("status_message"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            content_hash=data.get("content_hash"),
        )
