from typing import List, Literal, Optional

from pydantic import BaseModel

from agno.os.schema import PaginationInfo


class FileSystemEntry(BaseModel):
    path: str
    type: Literal["file", "directory"]
    size_bytes: Optional[int] = None
    version: Optional[int] = None
    updated_at: Optional[int] = None
    user_id: Optional[str] = None


class FileSystemUsage(BaseModel):
    file_count: int
    total_bytes: int
    bytes_limit: int


class FileSystemListResponse(BaseModel):
    namespace: str
    agent_ids: List[str]
    directory: str
    entries: List[FileSystemEntry]
    usage: FileSystemUsage
    meta: PaginationInfo


class FileSystemContentResponse(BaseModel):
    namespace: str
    agent_ids: List[str]
    path: str
    content: str
    size_bytes: int
    version: Optional[int] = None
    updated_at: Optional[int] = None
    user_id: Optional[str] = None
    line_count: int
    truncated: bool
    offset: int
    limit: int
    next_offset: Optional[int] = None


class FileSystemSearchEntry(BaseModel):
    path: str
    size_bytes: int
    snippet: str
    line: Optional[int] = None
    match_count: int


class FileSystemSearchResponse(BaseModel):
    namespace: str
    agent_ids: List[str]
    query: str
    directory: str
    entries: List[FileSystemSearchEntry]
    meta: PaginationInfo


class FileSystemTableEntry(BaseModel):
    namespace: str
    path: str
    agent_ids: List[str]
    size_bytes: int
    version: Optional[int] = None
    updated_at: Optional[int] = None
    user_id: Optional[str] = None
    snippet: Optional[str] = None
    line: Optional[int] = None
    match_count: Optional[int] = None


class FileSystemTableResponse(BaseModel):
    entries: List[FileSystemTableEntry]
    meta: PaginationInfo
