import asyncio
import json
from typing import Any, List, Optional

from agno.tools.azure_devops.base import AzureDevOpsBaseTools
from agno.utils.log import log_debug, log_error


class AzureDevOpsReposTools(AzureDevOpsBaseTools):
    """Toolkit for Azure DevOps Git repositories."""

    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        enable_list_repos: bool = True,
        enable_read_repository_file: bool = True,
        enable_get_repo_file_tree: bool = True,
        **kwargs: Any,
    ):
        tools: List[Any] = []
        async_tools: List[tuple[Any, str]] = []

        if enable_list_repos:
            tools.append(self.list_repos)
            async_tools.append((self.alist_repos, "list_repos"))
        if enable_read_repository_file:
            tools.append(self.read_repository_file)
            async_tools.append((self.aread_repository_file, "read_repository_file"))
        if enable_get_repo_file_tree:
            tools.append(self.get_repo_file_tree)
            async_tools.append((self.aget_repo_file_tree, "get_repo_file_tree"))

        super().__init__(
            organization_url=organization_url,
            personal_access_token=personal_access_token,
            project=project,
            name="azure_devops_repos",
            tools=tools,
            async_tools=async_tools,
            **kwargs,
        )

    def list_repos(self, project: Optional[str] = None) -> str:
        """List all Git repositories in an Azure DevOps project.

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of repositories (id, name, is_disabled).
        """
        try:
            git_client = self._get_git_client()
            repos = git_client.get_repositories(project=self._resolve_project(project))
            data = [{"id": repo.id, "name": repo.name, "is_disabled": repo.is_disabled} for repo in repos]
            log_debug(f"Listed {len(data)} Azure DevOps repositories")
            return json.dumps({"repos": data})
        except Exception as e:
            log_error(f"Error listing Azure DevOps repositories: {e}")
            return json.dumps({"error": str(e)})

    async def alist_repos(self, project: Optional[str] = None) -> str:
        """List all Git repositories in an Azure DevOps project (async).

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of repositories (id, name, is_disabled).
        """
        return await asyncio.to_thread(self.list_repos, project)

    def read_repository_file(
        self,
        repository_id: str,
        path: str = "/README.md",
        project: Optional[str] = None,
    ) -> str:
        """Read the content of a specific file from an Azure DevOps Git repository.

        Args:
            repository_id: The repository ID or name.
            path: Path to the file inside the repository. Defaults to "/README.md".
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the file path and its content.
        """
        try:
            git_client = self._get_git_client()
            item = git_client.get_item(
                repository_id=repository_id,
                path=path,
                project=self._resolve_project(project),
                include_content=True,
            )
            return json.dumps({"path": path, "content": item.content})
        except Exception as e:
            log_error(f"Error reading Azure DevOps repository file: {e}")
            return json.dumps({"error": str(e)})

    async def aread_repository_file(
        self,
        repository_id: str,
        path: str = "/README.md",
        project: Optional[str] = None,
    ) -> str:
        """Read the content of a specific file from an Azure DevOps Git repository (async).

        Args:
            repository_id: The repository ID or name.
            path: Path to the file inside the repository. Defaults to "/README.md".
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the file path and its content.
        """
        return await asyncio.to_thread(self.read_repository_file, repository_id, path, project)

    def get_repo_file_tree(
        self,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """List the full directory tree of an Azure DevOps Git repository.

        Args:
            repository_id: The repository ID or name.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of paths, each marked as DIR or FILE.
        """
        try:
            git_client = self._get_git_client()
            items = git_client.get_items(
                repository_id=repository_id,
                project=self._resolve_project(project),
                scope_path="/",
                recursion_level="full",
                include_content_metadata=True,
            )
            paths = [f"{item.path} - {'DIR' if item.is_folder else 'FILE'}" for item in items]
            return json.dumps({"files": paths})
        except Exception as e:
            log_error(f"Error getting Azure DevOps repository file tree: {e}")
            return json.dumps({"error": str(e)})

    async def aget_repo_file_tree(
        self,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """List the full directory tree of an Azure DevOps Git repository (async).

        Args:
            repository_id: The repository ID or name.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of paths, each marked as DIR or FILE.
        """
        return await asyncio.to_thread(self.get_repo_file_tree, repository_id, project)
