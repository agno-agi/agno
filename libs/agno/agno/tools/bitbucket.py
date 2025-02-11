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
        super().__init__(name="bitbucket_tools")

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
        self.register(self.list_repos)
        self.register(self.get_repo_info)
        self.register(self.get_repo_branches)
        self.register(self.get_repo_commits)
        self.register(self.get_repo_pull_requests)
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

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to Bitbucket API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json() if response.text else {}

    def list_repos(self, workspace: str) -> str:
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

    def get_repo_info(self, workspace: str, repo_slug: str) -> str:
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

    def get_repo_branches(self, repo_slug: str) -> str:
        """
        Retrieves all branches for a repository.

        :param repo_slug: The slug of the repository to retrieve branches for.
        :return: A JSON string containing all branches.
        """
        try:
            branches = self.bitbucket.get_branches(repo_slug)
            logger.debug(f"Branches: {branches}")
            return json.dumps(branches)
        except Exception as e:
            logger.error(f"Error retrieving branches: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_commits(self, repo_slug: str, branch: str) -> str:
        """
        Retrieves all commits for a specific branch in a repository.

        :param repo_slug: The slug of the repository to retrieve commits for.
        :param branch: The branch to retrieve commits for.
        :return: A JSON string containing all commits.
        """
        try:
            commits = self.bitbucket.get_commits(repo_slug, branch)
            logger.debug(f"Commits: {commits}")
            return json.dumps(commits)
        except Exception as e:
            logger.error(f"Error retrieving commits: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_pull_requests(self, repo_slug: str) -> str:
        """
        Retrieves all pull requests for a repository.

        :param repo_slug: The slug of the repository to retrieve pull requests for.
        :return: A JSON string containing all pull requests.
        """
        try:
            pull_requests = self.bitbucket.get_pull_requests(repo_slug)
            logger.debug(f"Pull requests: {pull_requests}")
            return json.dumps(pull_requests)
        except Exception as e:
            logger.error(f"Error retrieving pull requests: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_repo_issues(self, repo_slug: str) -> str:
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
