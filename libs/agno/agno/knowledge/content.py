from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig
from agno.knowledge.reader import Reader


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
    config: Optional[CloudStorageConfig] = None
    reader: Optional[Reader] = None
    size: Optional[int] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    content_hash: Optional[str] = None
