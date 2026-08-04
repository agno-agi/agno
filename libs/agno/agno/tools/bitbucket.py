import base64
import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Union

import requests

from agno.tools import Toolkit
from agno.utils.log import logger


class BitbucketTools(Toolkit):
    def __init__(
        self,
        server_url: str = "api.bitbucket.org",
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        workspace: Optional[str] = None,
        repo_slug: Optional[str] = None,
        api_version: str = "2.0",
        timeout: int = 30,
        list_repositories: bool = True,
        get_repository_details: bool = True,
        create_repository: bool = False,
        list_repository_commits: bool = True,
        list_all_pull_requests: bool = True,
        get_pull_request_details: bool = True,
        get_pull_request_changes: bool = True,
        list_issues: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize BitbucketTools for Bitbucket Cloud API access.

        Args:
            server_url: Bitbucket API server URL. Defaults to api.bitbucket.org.
            username: Bitbucket username. Falls back to BITBUCKET_USERNAME env var.
            password: Bitbucket app password. Falls back to BITBUCKET_PASSWORD env var.
            token: Bitbucket access token. Falls back to BITBUCKET_TOKEN env var.
            workspace: Bitbucket workspace slug (required).
            repo_slug: Repository slug (required).
            api_version: API version. Defaults to 2.0.
            timeout: Request timeout in seconds. Defaults to 30.
            list_repositories: Enable list_repositories tool. Defaults to True.
            get_repository_details: Enable get_repository_details tool. Defaults to True.
            create_repository: Enable create_repository tool. Defaults to False (creates external resource).
            list_repository_commits: Enable list_repository_commits tool. Defaults to True.
            list_all_pull_requests: Enable list_all_pull_requests tool. Defaults to True.
            get_pull_request_details: Enable get_pull_request_details tool. Defaults to True.
            get_pull_request_changes: Enable get_pull_request_changes tool. Defaults to True.
            list_issues: Enable list_issues tool. Defaults to True.
            all: Enable all tools. Defaults to False.
        """
        self.username = username or getenv("BITBUCKET_USERNAME")
        self.password = password or getenv("BITBUCKET_PASSWORD")
        self.token = token or getenv("BITBUCKET_TOKEN")
        self.auth_password = self.token or self.password
        self.server_url = server_url or "api.bitbucket.org"
        self.api_version = api_version or "2.0"
        self.base_url = (
            f"https://{self.server_url}/{api_version}"
            if not self.server_url.startswith(("http://", "https://"))
            else f"{self.server_url}/{api_version}"
        )
        self.workspace = workspace
        self.repo_slug = repo_slug

        if not (self.username and self.auth_password):
            raise ValueError("Username and password or token are required")

        if not self.workspace:
            raise ValueError("Workspace is required")
        if not self.repo_slug:
            raise ValueError("Repo slug is required")

        self.headers = {"Accept": "application/json", "Authorization": f"Basic {self._generate_access_token()}"}

        tools: List[Callable] = []
        if all or list_repositories:
            tools.append(self.list_repositories)
        if all or get_repository_details:
            tools.append(self.get_repository_details)
        if all or create_repository:
            tools.append(self.create_repository)
        if all or list_repository_commits:
            tools.append(self.list_repository_commits)
        if all or list_all_pull_requests:
            tools.append(self.list_all_pull_requests)
        if all or get_pull_request_details:
            tools.append(self.get_pull_request_details)
        if all or get_pull_request_changes:
            tools.append(self.get_pull_request_changes)
        if all or list_issues:
            tools.append(self.bitbucket_list_issues)

        super().__init__(
            name="bitbucket",
            tools=tools,
            timeout=timeout,
            **kwargs,
        )

    def _generate_access_token(self) -> str:
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
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data, params=params, timeout=self.timeout)
        response.raise_for_status()
        encoding_type = response.headers.get("Content-Type", "application/json")
        if encoding_type.startswith("application/json"):
            return response.json() if response.text else {}
        elif encoding_type == "text/plain":
            return response.text

        logger.warning(f"Unsupported content type: {encoding_type}")
        return {}

    def list_repositories(self, count: int = 10) -> str:
        """
        Get all repositories in the workspace.
        Args:
            count (int, optional): The number of repositories to retrieve

        Returns:
            str: A JSON string containing repository list.
        """
        try:
            # Limit count to maximum of 50
            count = min(count, 50)

            # Use count directly as pagelen for simplicity, max out at 50 per our limit
            pagelen = min(count, 50)
            params = {"page": 1, "pagelen": pagelen}

            repo = self._make_request("GET", f"/repositories/{self.workspace}", params=params)

            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving repository list for workspace {self.workspace}")
            return json.dumps({"error": str(e)})

    def get_repository_details(self) -> str:
        """
        Retrieves repository information.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-repositories/#api-repositories-workspace-repo-slug-get

        Returns:
            str: A JSON string containing repository information.
        """
        try:
            repo = self._make_request("GET", f"/repositories/{self.workspace}/{self.repo_slug}")
            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving repository information for {self.repo_slug}")
            return json.dumps({"error": str(e)})

    def create_repository(
        self,
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

        Args:
            name (str): The name of the new repository.
            project (str, optional): The key of the project to create the repository in.
            is_private (bool, optional): Whether the repository is private.
            description (str, optional): A short description of the repository.
            language (str, optional): The primary language of the repository
            has_issues (bool, optional): Whether the repository has issues enabled.
            has_wiki (bool, optional): Whether the repository has a wiki enabled.

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
            repo = self._make_request("POST", f"/repositories/{self.workspace}/{self.repo_slug}", data=payload)
            return json.dumps(repo, indent=2)
        except Exception as e:
            logger.exception(f"Error creating repository {self.repo_slug} for {self.workspace}")
            return json.dumps({"error": str(e)})

    def list_repository_commits(self, count: int = 10) -> str:
        """
        Retrieves all commits in a repository.

        Args:
            count (int, optional): The number of commits to retrieve. Defaults to 10. Maximum 50.

        Returns:
            str: A JSON string containing all commits.
        """
        try:
            count = min(count, 50)
            params = {"pagelen": count}

            commits = self._make_request(
                "GET", f"/repositories/{self.workspace}/{self.repo_slug}/commits", params=params
            )

            if isinstance(commits, dict) and commits.get("next"):
                collected_commits = commits.get("values", [])

                while len(collected_commits) < count and isinstance(commits, dict) and commits.get("next"):
                    next_url = commits["next"]  # type: ignore
                    query_param = next_url.split("?")[1] if "?" in next_url else ""
                    commits = self._make_request(
                        "GET", f"/repositories/{self.workspace}/{self.repo_slug}/commits?{query_param}"
                    )
                    if isinstance(commits, dict):
                        collected_commits.extend(commits.get("values", []))

                if isinstance(commits, dict):
                    commits["values"] = collected_commits[:count]

            return json.dumps(commits, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving commits for {self.repo_slug}")
            return json.dumps({"error": str(e)})

    def list_all_pull_requests(self, state: str = "OPEN") -> str:
        """
        Retrieves all pull requests for a repository.

        Args:
            state (str, optional): The state of the pull requests to retrieve.

        Returns:
            str: A JSON string containing all pull requests.
        """
        try:
            if state not in ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]:
                logger.debug(f"Invalid pull request state: {state}. Defaulting to OPEN")
                state = "OPEN"

            params = {"state": state}

            pull_requests = self._make_request(
                "GET", f"/repositories/{self.workspace}/{self.repo_slug}/pullrequests", params=params
            )

            return json.dumps(pull_requests, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving pull requests for {self.repo_slug}")
            return json.dumps({"error": str(e)})

    def get_pull_request_details(self, pull_request_id: int) -> str:
        """
        Retrieves a pull request for a repository.
        Args:
            pull_request_id (int): The ID of the pull request to retrieve.

        Returns:
            str: A JSON string containing the pull request.
        """
        try:
            pull_request = self._make_request(
                "GET", f"/repositories/{self.workspace}/{self.repo_slug}/pullrequests/{pull_request_id}"
            )
            return json.dumps(pull_request, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving pull requests for {self.repo_slug}")
            return json.dumps({"error": str(e)})

    def get_pull_request_changes(self, pull_request_id: int) -> str:
        """
        Retrieves changes for a pull request in a repository.

        Args:
            pull_request_id (int): The ID of the pull request to retrieve.

        Returns:
            str: A markdown string containing the pull request diff.
        """
        try:
            diff = self._make_request(
                "GET", f"/repositories/{self.workspace}/{self.repo_slug}/pullrequests/{pull_request_id}/diff"
            )
            if isinstance(diff, dict):
                return json.dumps(diff, indent=2)
            return json.dumps({"diff": diff})
        except Exception as e:
            logger.exception(f"Error retrieving changes for pull request {pull_request_id} in {self.repo_slug}")
            return json.dumps({"error": str(e)})

    def bitbucket_list_issues(self, count: int = 10) -> str:
        """
        Retrieves all issues for a repository.

        Args:
            count (int, optional): The number of issues to retrieve. Defaults to 10. Maximum 50.

        Returns:
            str: A JSON string containing all issues.
        """
        try:
            count = min(count, 50)
            params = {"pagelen": count}

            issues = self._make_request("GET", f"/repositories/{self.workspace}/{self.repo_slug}/issues", params=params)

            return json.dumps(issues, indent=2)
        except Exception as e:
            logger.exception(f"Error retrieving issues for {self.repo_slug}")
            return json.dumps({"error": str(e)})
