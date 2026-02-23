"""Remote content loading for Knowledge.

Provides methods for loading content from cloud storage providers:
- S3, GCS, SharePoint, GitHub, Azure Blob Storage

This module contains the RemoteLoader class which composes all loader
instances and dispatches to the appropriate provider.
"""

from typing import Any, List, Optional

from agno.knowledge.content import Content
from agno.knowledge.loaders.azure_blob import AzureBlobLoader
from agno.knowledge.loaders.gcs import GCSLoader
from agno.knowledge.loaders.github import GitHubLoader
from agno.knowledge.loaders.s3 import S3Loader
from agno.knowledge.loaders.sharepoint import SharePointLoader
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.remote_content import (
    AzureBlobContent,
    GCSContent,
    GitHubContent,
    S3Content,
    SharePointContent,
)
from agno.utils.log import log_warning


class RemoteLoader:
    """Manages remote content loading via composed loader instances.

    Each loader receives a pipeline reference (IngestionPipeline) which provides
    direct access to content_store, reader_registry, and vector_db.
    """

    def __init__(self, pipeline: Any, content_sources: Optional[List[BaseStorageConfig]] = None):
        self.content_sources = content_sources
        self._s3_loader = S3Loader(pipeline=pipeline)
        self._gcs_loader = GCSLoader(pipeline=pipeline)
        self._sharepoint_loader = SharePointLoader(pipeline=pipeline)
        self._github_loader = GitHubLoader(pipeline=pipeline)
        self._azure_blob_loader = AzureBlobLoader(pipeline=pipeline)

    # ==========================================
    # REMOTE CONTENT DISPATCHERS
    # ==========================================

    async def aload_from_remote_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Async dispatcher for remote content loading.

        Routes to the appropriate provider-specific loader based on content type.
        """
        if content.remote_content is None:
            log_warning("No remote content provided for content")
            return

        remote_content = content.remote_content

        # Look up config if config_id is provided
        config = None
        if hasattr(remote_content, "config_id") and remote_content.config_id:
            config = self._get_remote_config_by_id(remote_content.config_id)
            if config is None:
                log_warning(f"No config found for config_id: {remote_content.config_id}")

        if isinstance(remote_content, S3Content):
            await self._s3_loader._aload_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            await self._gcs_loader._aload_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            await self._sharepoint_loader._aload_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            await self._github_loader._aload_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            await self._azure_blob_loader._aload_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    def load_from_remote_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Sync dispatcher for remote content loading.

        Routes to the appropriate provider-specific loader based on content type.
        """
        if content.remote_content is None:
            log_warning("No remote content provided for content")
            return

        remote_content = content.remote_content

        # Look up config if config_id is provided
        config = None
        if hasattr(remote_content, "config_id") and remote_content.config_id:
            config = self._get_remote_config_by_id(remote_content.config_id)
            if config is None:
                log_warning(f"No config found for config_id: {remote_content.config_id}")

        if isinstance(remote_content, S3Content):
            self._s3_loader._load_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            self._gcs_loader._load_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            self._sharepoint_loader._load_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            self._github_loader._load_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            self._azure_blob_loader._load_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    # ==========================================
    # REMOTE CONFIG HELPERS
    # ==========================================

    def _get_remote_configs(self) -> List[BaseStorageConfig]:
        """Return configured remote content sources."""
        return self.content_sources or []

    def _get_remote_config_by_id(self, config_id: str) -> Optional[BaseStorageConfig]:
        """Get a remote content config by its ID."""
        if not self.content_sources:
            return None
        return next((c for c in self.content_sources if c.id == config_id), None)
