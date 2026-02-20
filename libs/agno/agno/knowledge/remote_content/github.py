from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agno.knowledge.remote_content.base import BaseStorageConfig

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import GitHubContent


class GitHubConfig(BaseStorageConfig):
    """Configuration for GitHub content source."""

    repo: str
    token: Optional[str] = None
    branch: Optional[str] = None
    path: Optional[str] = None

    def file(self, file_path: str, branch: Optional[str] = None) -> "GitHubContent":
        """Create a content reference for a specific file.

        Args:
            file_path: Path to the file in the repository.
            branch: Optional branch override.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            file_path=file_path,
            branch=branch or self.branch,
        )

    def folder(self, folder_path: str, branch: Optional[str] = None) -> "GitHubContent":
        """Create a content reference for a folder.

        Args:
            folder_path: Path to the folder in the repository.
            branch: Optional branch override.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            folder_path=folder_path,
            branch=branch or self.branch,
        )
