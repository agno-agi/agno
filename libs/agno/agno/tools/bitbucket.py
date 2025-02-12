import json
import os
from typing import Optional, Dict, Any

import requests
import base64

from agno.tools import Toolkit
from agno.utils.log import logger


class BitbucketTools(Toolkit):
    def __init__(
        self,
        server_url: Optional[str] = "api.bitbucket.org",
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        api_version: Optional[str] = "2.0",
    ):
        """Initializes Bitbucket Tools."""
        super().__init__(name="bitbucket")

        self.server_url = server_url or os.getenv("BITBUCKET_SERVER_URL")
        self.username = username or os.getenv("BITBUCKET_USERNAME")
        self.password = password or os.getenv("BITBUCKET_PASSWORD")
        self.token = token or os.getenv("BITBUCKET_TOKEN")
        self.auth_password = self.token or self.password
        self.base_url = f"https://{self.server_url}/{api_version}"

        if not (self.username and self.auth_password):
            logger.error("Username and assword or token are required")
            raise ValueError("Username and assword or token are required")

        self.headers = {"Accept": "application/json", "Authorization": f"Basic {self._generate_access_token()}"}

        # Register methods
        self.register(self.list_repositories)
        self.register(self.get_repository)
        self.register(self.create_repository)
        self.register(self.list_repository_commits)
        self.register(self.list_pull_requests)
        self.register(self.get_pull_request)
        self.register(self.get_pull_request_changes)
        self.register(self.get_repo_issues)
        self.register(self.get_repo_pipelines)
        self.register(self.get_repo_pipeline_runs)
        self.register(self.get_repo_pipeline_steps)

    def _generate_access_token(self) -> str:
        """Generate an access token for Bitbucket API using Basic Auth."""
        auth_str = f"{self.username}:{self.auth_password}"
        auth_bytes = auth_str.encode("ascii")
        auth_base64 = base64.b64encode(auth_bytes).decode("ascii")
        return auth_base64

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Union[str, Dict[str, Any]]:
        """Make a request to Bitbucket API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        encoding_type = response.headers.get("Content-Type")
        if encoding_type == "application/json":
            return response.json() if response.text else {}
        elif encoding_type == "text/plain":
            return response.text

        logger.warning(f"Unsupported content type: {encoding_type}")
        return {}

    def list_repositories(self, workspace: str) -> str:
        """
        TODO: Add optional pagination query parameters. Also only selectively return fields from response to save tokens.

        List repository info for a given workspace.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-repositories/#api-repositories-workspace-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.

        Returns:
            str: A JSON string containing repository list.
        """
        try:
            repo = self._make_request("GET", f"/repositories/{workspace}")
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

    def list_repository_commits(self, workspace: str, repo_slug: str, ctx: Optional[str] = None, page: int = 1) -> str:
        """
        Retrieves all commits in a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-commits/#api-repositories-workspace-repo-slug-commits-get

        Note: The underlying API uses cursor based pagination, so refrain from using the page parameter. Multiple API calls need to be made to retrieve commits of next pages.

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve commits for.
            ctx (str, optional): The cursor to navigate between pages. Provided by Bitbucket API. Defaults to None.
            page (int, optional): The page number to retrieve. Defaults to 1.

        Returns:
            str: A JSON string containing all commits.
        """
        try:
            if ctx:
                commits = self._make_request(
                    "GET", f"/repositories/{workspace}/{repo_slug}/commits?ctx={ctx}&page={page}"
                )
            else:
                commits = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}/commits")
                for i in range(2, page + 1):
                    next_url = commits["next"]
                    query_param = next_url.split("?")[1]
                    commits = self._make_request("GET", f"/repositories/{workspace}/{repo_slug}/commits?{query_param}")
            return json.dumps(commits, indent=2)
        except Exception as e:
            logger.error(f"Error retrieving commits for {repo_slug}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_pull_requests(self, workspace: str, repo_slug: str, state: str = "OPEN", page: int = 1) -> str:
        """
        Retrieves all pull requests for a repository.
        API Docs: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/#api-repositories-workspace-repo-slug-pullrequests-get

        Args:
            workspace (str): The slug of the workspace where the repository exists.
            repo_slug (str): The slug of the repository to retrieve pull requests for.
            state (str, optional): The state of the pull requests to retrieve. Defaults to "OPEN". Possible values: "OPEN", "MERGED", "DECLINED", "SUPERSEDED".
            page (int, optional): The page number to retrieve. Defaults to 1.

        Returns:
            str: A JSON string containing all pull requests.
        """
        try:
            VALID_STATES = ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
            if state not in VALID_STATES:
                raise ValueError(f"Invalid state: {state}. Valid states are: {', '.join(VALID_STATES)}")

            pull_requests = self._make_request(
                "GET", f"/repositories/{workspace}/{repo_slug}/pullrequests?state={state}&page={page}"
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

    def get_repo_issues(self, workspace: str, repo_slug: str) -> str:
        """
        Retrieves all issues for a repository.

        :param repo_slug: The slug of the repository to retrieve issues for.
        :return: A JSON string containing all issues.
        """
        try:
            issues = self.bitbucket.get_issues(repo_slug)
            logger.debug(f"Issues: {issues}")
            return json.dumps(issues)
        except Exception as e:
            logger.error(f"Error retrieving issues: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_pipelines(self, repo_slug: str) -> str:
        """
        Retrieves all pipelines for a repository.

        :param repo_slug: The slug of the repository to retrieve pipelines for.
        :return: A JSON string containing all pipelines.
        """
        try:
            pipelines = self.bitbucket.get_pipelines(repo_slug)
            logger.debug(f"Pipelines: {pipelines}")
            return json.dumps(pipelines)
        except Exception as e:
            logger.error(f"Error retrieving pipelines: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_pipeline_runs(self, repo_slug: str) -> str:
        """
        Retrieves all pipeline runs for a repository.

        :param repo_slug: The slug of the repository to retrieve pipeline runs for.
        :return: A JSON string containing all pipeline runs.
        """
        try:
            pipeline_runs = self.bitbucket.get_pipeline_runs(repo_slug)
            logger.debug(f"Pipeline runs: {pipeline_runs}")
            return json.dumps(pipeline_runs)
        except Exception as e:
            logger.error(f"Error retrieving pipeline runs: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_pipeline_steps(self, repo_slug: str) -> str:
        """
        Retrieves all pipeline steps for a repository.

        :param repo_slug: The slug of the repository to retrieve pipeline steps for.
        :return: A JSON string containing all pipeline steps.
        """
        try:
            pipeline_steps = self.bitbucket.get_pipeline_steps(repo_slug)
            logger.debug(f"Pipeline steps: {pipeline_steps}")
            return json.dumps(pipeline_steps)
        except Exception as e:
            logger.error(f"Error retrieving pipeline steps: {str(e)}")
            return json.dumps({"error": str(e)})
