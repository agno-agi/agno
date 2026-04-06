from __future__ import annotations

from agno.knowledge.remote_content.base import BaseStorageConfig


class LocalStorageConfig(BaseStorageConfig):
    """Configuration for local filesystem storage (development/testing)."""

    base_path: str
