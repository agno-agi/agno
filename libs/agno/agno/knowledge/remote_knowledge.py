"""Remote content loading for Knowledge.

Provides methods for loading content from cloud storage providers:
- S3, GCS, SharePoint, GitHub, Azure Blob Storage

This module contains the RemoteKnowledge class which combines all loader
capabilities through inheritance. The Knowledge class inherits from this
to gain remote content loading capabilities.
"""

from typing import List, Optional

from agno.knowledge.content import Content
from agno.knowledge.loaders.azure_blob import AzureBlobLoader
from agno.knowledge.loaders.gcs import GCSLoader
from agno.knowledge.loaders.github import GitHubLoader
from agno.knowledge.loaders.s3 import S3Loader
from agno.knowledge.loaders.sharepoint import SharePointLoader
from agno.knowledge.remote_content.config import RemoteContentConfig
from agno.knowledge.remote_content.remote_content import (
    AzureBlobContent,
    GCSContent,
    GitHubContent,
    S3Content,
    SharePointContent,
)
from agno.utils.log import log_warning


class RemoteKnowledge(S3Loader, GCSLoader, SharePointLoader, GitHubLoader, AzureBlobLoader):
    """Base class providing remote content loading capabilities.

    Inherits from all provider-specific loaders:
    - S3Loader: AWS S3 content loading
    - GCSLoader: Google Cloud Storage content loading
    - SharePointLoader: Microsoft SharePoint content loading
    - GitHubLoader: GitHub repository content loading
    - AzureBlobLoader: Azure Blob Storage content loading

    Knowledge inherits from this class and provides:
    - content_sources: List[RemoteContentConfig]
    - vector_db, contents_db attributes
    - _should_skip(), _select_reader_by_uri(), _prepare_documents_for_insert() methods
    - _ahandle_vector_db_insert(), _handle_vector_db_insert() methods
    - _ainsert_contents_db(), _insert_contents_db() methods
    - _aupdate_content(), _update_content() methods
    - _build_content_hash() method
    """

    # These attributes are provided by the Knowledge subclass
    content_sources: Optional[List[RemoteContentConfig]]

    # ==========================================
    # REMOTE CONTENT DISPATCHERS
    # ==========================================

    async def _aload_from_remote_content(
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
            await self._aload_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            await self._aload_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            await self._aload_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            await self._aload_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            await self._aload_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    def _load_from_remote_content(
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
            self._load_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            self._load_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            self._load_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            self._load_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            self._load_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    # ==========================================
    # REMOTE CONFIG HELPERS
    # ==========================================

    def _get_remote_configs(self) -> List[RemoteContentConfig]:
        """Return configured remote content sources."""
        return self.content_sources or []

    def _get_remote_config_by_id(self, config_id: str) -> Optional[RemoteContentConfig]:
        """Get a remote content config by its ID."""
        if not self.content_sources:
            return None
        return next((c for c in self.content_sources if c.id == config_id), None)
