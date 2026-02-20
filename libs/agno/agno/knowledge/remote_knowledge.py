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

    Each loader receives a reference to the Knowledge instance so it can
    call back into Knowledge for content store, reader, and pipeline operations.
    """

    def __init__(self, knowledge: Any):
        self.knowledge = knowledge
        self._s3_loader = S3Loader(knowledge=knowledge)
        self._gcs_loader = GCSLoader(knowledge=knowledge)
        self._sharepoint_loader = SharePointLoader(knowledge=knowledge)
        self._github_loader = GitHubLoader(knowledge=knowledge)
        self._azure_blob_loader = AzureBlobLoader(knowledge=knowledge)

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
        return self.knowledge.content_sources or []

    def _get_remote_config_by_id(self, config_id: str) -> Optional[BaseStorageConfig]:
        """Get a remote content config by its ID."""
        if not self.knowledge.content_sources:
            return None
        return next((c for c in self.knowledge.content_sources if c.id == config_id), None)
