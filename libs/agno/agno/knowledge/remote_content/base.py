from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ListFilesResult:
    """Result of listing files from a remote source."""

    def __init__(
        self,
        files: list,
        folders: list,
        page: int = 1,
        limit: int = 100,
        total_count: int = 0,
        total_pages: int = 0,
    ):
        self.files = files
        self.folders = folders
        self.page = page
        self.limit = limit
        self.total_count = total_count
        self.total_pages = total_pages


class BaseStorageConfig(BaseModel):
    """Base configuration for remote content sources."""

    id: str
    name: str
    metadata: Optional[dict] = None

    model_config = ConfigDict(extra="allow")
