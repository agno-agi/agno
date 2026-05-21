from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


@dataclass
class ListFilesResult:
    """Result of listing files from a remote source."""

    files: List[dict] = field(default_factory=list)
    folders: List[dict] = field(default_factory=list)
    page: int = 1
    limit: int = 100
    total_count: int = 0
    total_pages: int = 0


class BaseStorageConfig(BaseModel):
    """Base configuration for remote content sources."""

    id: str
    name: str
    metadata: Optional[dict] = None

    model_config = ConfigDict(extra="allow")
