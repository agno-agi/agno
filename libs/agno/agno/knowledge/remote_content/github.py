from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from pydantic import model_validator

from agno.knowledge.remote_content.base import BaseStorageConfig

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import GitHubContent


class GitHubConfig(BaseStorageConfig):
    """Configuration for GitHub content source.

    Supports two authentication methods:
    - Personal Access Token: set ``token`` to a fine-grained PAT
    - GitHub App: set ``app_id``, ``installation_id``, and ``private_key``

    For GitHub App auth, the loader generates a JWT and exchanges it for an
    installation access token automatically.  Requires ``PyJWT[crypto]``.
    """

    repo: Optional[str] = None
    token: Optional[str] = None
    branch: Optional[str] = None
    path: Optional[str] = None

    # GitHub App authentication (alternative to token)
    app_id: Optional[Union[str, int]] = None
    installation_id: Optional[Union[str, int]] = None
    private_key: Optional[str] = None

    @model_validator(mode="after")
    def _validate_app_auth_fields(self) -> "GitHubConfig":
        """Ensure all three GitHub App fields are set together and private_key is PEM-formatted."""
        app_fields = [self.app_id, self.installation_id, self.private_key]
        provided = [f for f in app_fields if f is not None]
        if 0 < len(provided) < 3:
            missing = []
            if self.app_id is None:
                missing.append("app_id")
            if self.installation_id is None:
                missing.append("installation_id")
            if self.private_key is None:
                missing.append("private_key")
            raise ValueError(
                f"GitHub App authentication requires all three fields: app_id, installation_id, private_key. "
                f"Missing: {', '.join(missing)}"
            )
        if self.private_key is not None and not self.private_key.strip().startswith("-----BEGIN"):
            raise ValueError(
                "private_key must be a PEM-formatted RSA private key "
                "(starting with '-----BEGIN RSA PRIVATE KEY-----' or '-----BEGIN PRIVATE KEY-----')"
            )
        return self

    def file(
        self,
        file_path: str,
        branch: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> "GitHubContent":
        """Create a content reference for a specific file.

        Args:
            file_path: Path to the file in the repository.
            branch: Optional branch override.
            repo: Optional ``owner/repo`` override. When omitted, the config's
                ``repo`` is used. Allows reusing the same auth credentials
                across multiple repositories.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            file_path=file_path,
            branch=branch or self.branch,
            repo=repo,
        )

    def folder(
        self,
        folder_path: str,
        branch: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> "GitHubContent":
        """Create a content reference for a folder.

        Args:
            folder_path: Path to the folder in the repository.
            branch: Optional branch override.
            repo: Optional ``owner/repo`` override. When omitted, the config's
                ``repo`` is used. Allows reusing the same auth credentials
                across multiple repositories.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            folder_path=folder_path,
            branch=branch or self.branch,
            repo=repo,
        )
