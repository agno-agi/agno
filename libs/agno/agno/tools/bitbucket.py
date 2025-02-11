import json
import os
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from atlassian.bitbucket import Cloud
    from atlassian import Bitbucket
except ImportError:
    raise ImportError("`atlassian-python-api` not installed. Please install using `pip install atlassian-python-api`")


class BitbucketTools(Toolkit):
    def __init__(self,
        cloud: Optional[bool] = False,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ):
        super().__init__(name="bitbucket_tools")

        self.server_url = server_url or os.getenv("BITBUCKET_SERVER_URL")
        self.username = username or os.getenv("BITBUCKET_USERNAME")
        self.password = password or os.getenv("BITBUCKET_PASSWORD")
        self.token = token or os.getenv("BITBUCKET_TOKEN")

        # For cloud instance, server_url is not needed
        if cloud and not (self.username and (self.password or self.token)):
            raise ValueError("Bitbucket Cloud requires username and either password or token.")
        # For server instance, we need server_url
        elif not cloud and not self.server_url:
            raise ValueError("Bitbucket server URL not provided.")

        # Use token as password if provided
        auth_password = self.token or self.password

        if cloud:
            self.bitbucket = Cloud(
                username=self.username,
                password=auth_password,
                cloud=True,
            )
        else:
            self.bitbucket = Bitbucket(
                url=self.server_url,
                username=self.username,
                password=auth_password,
            )
        # Register methods
        self.register(self.get_repo_info)
        self.register(self.get_repo_branches)
        self.register(self.get_repo_commits)
        self.register(self.get_repo_pull_requests)
        self.register(self.get_repo_issues)
        self.register(self.get_repo_pipelines)
        self.register(self.get_repo_pipeline_runs)
        self.register(self.get_repo_pipeline_steps)

    def get_repo_info(self, repo_slug: str) -> str:
        """
        Retrieves repository information.

        :param repo_slug: The slug of the repository to retrieve information for.
        :return: A JSON string containing repository information.
        """
        try:
            repo = self.bitbucket.get_repo(repo_slug)
            logger.debug(f"Repository information: {repo}")
            return json.dumps(repo)
        except Exception as e:
            logger.error(f"Error retrieving repository information: {str(e)}")
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
