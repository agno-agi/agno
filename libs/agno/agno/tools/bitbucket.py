import base64
import json
import os
from typing import Any, Dict, Optional, Union

import requests

from agno.tools import Toolkit
from agno.utils.log import logger


class BitbucketTools(Toolkit):
    """A class that provides tools for interacting with the Bitbucket API."""

    def __init__(
        self,
        server_url: Optional[str] = "api.bitbucket.org",
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        api_version: Optional[str] = "2.0",
        list_repositories: bool = True,
        get_repository: bool = True,
        create_repository: bool = True,
        list_repository_commits: bool = True,
        list_pull_requests: bool = True,
        get_pull_request: bool = True,
        get_pull_request_changes: bool = True,
        list_issues: bool = True,
        list_repository_pipelines: bool = True,
    ):
        """Initializes Bitbucket Tools.

        Args:
            server_url (str, optional): The Bitbucket server URL. Defaults to "api.bitbucket.org".
            username (str, optional): The username to authenticate with. If not provided, it will take the value of `BITBUCKET_USERNAME` env variable.
            password (str, optional): The password to authenticate with. If not provided, it will take the value of `BITBUCKET_PASSWORD` env variable.
            token (str, optional): The token to authenticate with. If not provided, it will take the value of `BITBUCKET_TOKEN` env variable.
            api_version (str, optional): The version of the Bitbucket API to use. Defaults to "2.0".
            list_repositories (bool, optional): Whether to register the `list_repositories` method. Defaults to True.
            get_repository (bool, optional): Whether to register the `get_repository` method. Defaults to True.
            create_repository (bool, optional): Whether to register the `create_repository` method. Defaults to True.
            list_repository_commits (bool, optional): Whether to register the `list_repository_commits` method. Defaults to True.
            list_pull_requests (bool, optional): Whether to register the `list_pull_requests` method. Defaults to True.
            get_pull_request (bool, optional): Whether to register the `get_pull_request` method. Defaults to True.
            get_pull_request_changes (bool, optional): Whether to register the `get_pull_request_changes` method. Defaults to True.
            list_issues (bool, optional): Whether to register the `list_issues` method. Defaults to True.
            list_repository_pipelines (bool, optional): Whether to register the `list_repository_pipelines` method. Defaults to True.

        Raises:
            ValueError: If username and password or token are not provided.

        Example:
            ```python
            bitbucket = BitbucketTools(
                username="your-username",
                password="your-password",
                server_url="your-server-url",
                api_version="2.0"
            )
            ```
        """
        super().__init__(name="bitbucket")

        self.server_url = server_url or os.getenv("BITBUCKET_SERVER_URL")
        self.username = username or os.getenv("BITBUCKET_USERNAME")
        self.password = password or os.getenv("BITBUCKET_PASSWORD")
        self.token = token or os.getenv("BITBUCKET_TOKEN")
        self.auth_password = self.token or self.password
        self.base_url = f"https://{self.server_url}/{api_version}"

        if not (self.username and self.auth_password):
            logger.error("Username and password or token are required")
            raise ValueError("Username and password or token are required")

        self.headers = {"Accept": "application/json", "Authorization": f"Basic {self._generate_access_token()}"}

        # Register methods
        if list_repositories:
            self.register(self.list_repositories)
        if get_repository:
            self.register(self.get_repository)
        if create_repository:
            self.register(self.create_repository)
        if list_repository_commits:
            self.register(self.list_repository_commits)
        if list_pull_requests:
            self.register(self.list_pull_requests)
        if get_pull_request:
            self.register(self.get_pull_request)
        if get_pull_request_changes:
            self.register(self.get_pull_request_changes)
        if list_issues:
            self.register(self.list_issues)
        if list_repository_pipelines:
            self.register(self.list_repository_pipelines)

    def _generate_access_token(self) -> str:
        """Generate an access token for Bitbucket API using Basic Auth.

        Returns:
            str: The access token.
        """
        auth_str = f"{self.username}:{self.auth_password}"
        auth_bytes = auth_str.encode("ascii")
        auth_base64 = base64.b64encode(auth_bytes).decode("ascii")
        return auth_base64

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Make a request to Bitbucket API.

        Args:
            method (str): The HTTP method to use for the request.
            endpoint (str): The API endpoint to make the request to.
            params (Dict[str, Any], optional): Query parameters to include in the request. Defaults to None.
            data (Dict[str, Any], optional): The payload to send with the request. Defaults to None.

        Returns:
            Union[str, Dict[str, Any]]: The response from the API as a string or a dictionary.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data, params=params)
        response.raise_for_status()
        encoding_type = response.headers.get("Content-Type", "application/json")
        if encoding_type.startswith("application/json"):
            return response.json() if response.text else {}
        elif encoding_type == "text/plain":
            return response.text

        logger.warning(f"Unsupported content type: {encoding_type}")
        return {}

    def list_repositories(self, workspace: str, page: int = 1, pagelen: int = 10) -> str:
        """
        List repository info for a given workspace.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-repositories/#api-repositories-workspace-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            page (int, optional): The page number to retrieve. Defaults to 1.
            pagelen (int, optional): The number of repositories to retrieve per page. Defaults to 10.

        Returns:
            str: A JSON string containing repository list.
        """
        try:
            params = {"page": page, "pagelen": pagelen}
            repo = self._make_request("GET", f"/repositories/{workspace}", params=params)
            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving repository list for workspace {workspace}: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repository(self, workspace: str, repo_slug: str) -> str:
        """
        Retrieves repository information.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-repositories/#api-repositories-workspace-repo-slug-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve information for.

        Returns:
            str: A JSON string containing repository information.
        """
        try:
            repo = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}")
            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving repository information for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def create_repository(
        self,
        workspace: str,
        repo_slug: str,
        name: str,
        project: Optional[str] = None,
        is_private: bool = False,
        description: Optional[str] = None,
        language: Optional[str] = None,
        has_issues: bool = False,
        has_wiki: bool = False,
    ) -> str:
        """
        Creates a new repository in Bitbucket for the given workspace.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-repositories/#api-repositories-workspace-repo-slug-post

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the new repository.
            name (str): The name of the new repository.
            project (str, optional): The key of the project to create the repository in. Defaults to None. If not provided, the repository will be created in the oldest project in the workspace.
            is_private (bool, optional): Whether the repository is private. Defaults to False.
            description (str, optional): A short description of the repository. Defaults to None.
            language (str, optional): The primary language of the repository. Defaults to None.
            has_issues (bool, optional): Whether the repository has issues enabled. Defaults to False.
            has_wiki (bool, optional): Whether the repository has a wiki enabled. Defaults to False.

        Returns:
            str: A JSON string containing repository information.
        """
        try:
            payload: Dict[str, Any] = {
                "name": name,
                "scm": "git",
                "is_private": is_private,
                "description": description,
                "language": language,
                "has_issues": has_issues,
                "has_wiki": has_wiki,
            }
            if project:
                payload["project"] = {"key": project}
            repo = self._make_request("POST", f"/repositories/{workspace}/{repo_slug}", data=payload)
            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.error(f"Error creating repository {repo_slug} for {workspace}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_repository_commits(
        self, workspace: str, repo_slug: str, ctx: Optional[str] = None, page: int = 1, pagelen: int = 10
    ) -> str:
        """
        Retrieves all commits in a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-commits/#api-repositories-workspace-repo-slug-commits-get

        Note: The underlying API uses cursor based pagination, so refrain from using the page parameter. Multiple API calls need to be made to retrieve commits of next pages.

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve commits for.
            ctx (str, optional): The cursor to navigate between pages. Provided by Bitbucket API. Defaults to None.
            page (int, optional): The page number to retrieve. Defaults to 1.
            pagelen (int, optional): The number of commits to retrieve per page. Defaults to 10.

        Returns:
            str: A JSON string containing all commits.
        """
        try:
            if ctx:
                commits = self._make_request(
                    "GET", f"/repositories/{workspace}/{repo_slug}/commits?ctx={ctx}&page={page}&pagelen={pagelen}"
                )
            else:
                commits = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}/commits?pagelen={pagelen}")
                for i in range(2, page + 1):
                    next_url = commits["next"]  # type: ignore
                    query_param = next_url.split("?")[1]
                    commits = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}/commits?{query_param}")
            return json.dumps(commits, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving commits for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_pull_requests(
        self, workspace: str, repo_slug: str, state: str = "OPEN", page: int = 1, pagelen: int = 10
    ) -> str:
        """
        Retrieves all pull requests for a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/#api-repositories-workspace-repo-slug-pullrequests-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve pull requests for.
            state (str, optional): The state of the pull requests to retrieve. Defaults to "OPEN". Possible values: "OPEN", "MERGED", "DECLINED", "SUPERSEDED".
            page (int, optional): The page number to retrieve. Defaults to 1.
            pagelen (int, optional): The number of pull requests to retrieve per page. Defaults to 10.

        Returns:
            str: A JSON string containing all pull requests.
        """
        try:
            VALID_STATES = ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
            if state not in VALID_STATES:
                raise ValueError(f"Invalid state: {state}. Valid states are: {', '.join(VALID_STATES)}")

            params = {"state": state, "page": page, "pagelen": pagelen}
            pull_requests = self._make_request(
                "GET", f"/repositories/{workspace}/{repo_slug}/pullrequests", params=params
            )
            return json.dumps(pull_requests, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving pull requests for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_pull_request(self, workspace: str, repo_slug: str, pull_request_id: int) -> str:
        """
        Retrieves a pull request for a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/#api-repositories-workspace-repo-slug-pullrequests-pull-request-id-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve pull requests for.
            pull_request_id (int): The ID of the pull request to retrieve.

        Returns:
            str: A JSON string containing the pull request.
        """
        try:
            pull_requests = self._make_request(
                "GET", f"/repositories/{workspace}/{repo_slug}/pullrequests/{pull_request_id}"
            )
            return json.dumps(pull_requests, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving pull requests for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_pull_request_changes(self, workspace: str, repo_slug: str, pull_request_id: int) -> str:
        """
        Retrieves changes for a pull request in a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/#api-repositories-workspace-repo-slug-pullrequests-pull-request-id-diff-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve pull requests for.
            pull_request_id (int): The ID of the pull request to retrieve.

        Returns:
            str: A markdown string containing the pull request diff.
        """
        try:
            diff = self._make_request(
                "GET", f"/repositories/{workspace}/{repo_slug}/pullrequests/{pull_request_id}/diff"
            )
            return f"```\n{diff}\n```"
        except Exception as e:
            logger.error(f"Error retrieving changes for pull request {pull_request_id} in {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_issues(self, workspace: str, repo_slug: str, page: int = 1, pagelen: int = 10) -> str:
        """
        Retrieves all issues for a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-issue-tracker/#api-repositories-workspace-repo-slug-issues-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve issues for.
            page (int, optional): The page number to retrieve. Defaults to 1.
            pagelen (int, optional): The number of issues to retrieve per page. Defaults to 10.

        Returns:
            str: A JSON string containing all issues.
        """
        try:
            params = {"page": page, "pagelen": pagelen}
            issues = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}/issues", params=params)
            return json.dumps(issues, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving issues for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_repository_pipelines(self, workspace: str, repo_slug: str, page: int = 1, pagelen: int = 10) -> str:
        """
        Retrieves all pipelines for a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pipelines/#api-repositories-workspace-repo-slug-pipelines-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve pipelines for.
            page (int, optional): The page number to retrieve. Defaults to 1.
            pagelen (int, optional): The number of pipelines to retrieve per page. Defaults to 10.

        Returns:
            str: A JSON string containing all pipelines.
        """
        try:
            pipelines = self._make_request(
                "GET", f"/repositories/{workspace}/{repo_slug}/pipelines?page={page}&pagelen={pagelen}"
            )
            return json.dumps(pipelines, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving pipelines for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})
