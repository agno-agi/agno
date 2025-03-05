import json
import os
from typing import List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from github import Auth, Github, GithubException
except ImportError:
    raise ImportError("`PyGithub` not installed. Please install using `pip install pygithub`")


class GithubTools(Toolkit):
    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        search_repositories: bool = True,
        list_repositories: bool = True,
        get_repository: bool = True,
        list_pull_requests: bool = True,
        get_pull_request: bool = True,
        get_pull_request_changes: bool = True,
        create_issue: bool = True,
        create_repository: bool = True,
        delete_repository: bool = False,
        get_repository_languages: bool = True,
        list_branches: bool = True,
    ):
        super().__init__(name="github")

        self.access_token = access_token or os.getenv("GITHUB_ACCESS_TOKEN")
        self.base_url = base_url

        self.g = self.authenticate()

        if search_repositories:
            self.register(self.search_repositories)
        if list_repositories:
            self.register(self.list_repositories)
        if get_repository:
            self.register(self.get_repository)
        if list_pull_requests:
            self.register(self.list_pull_requests)
        if get_pull_request:
            self.register(self.get_pull_request)
        if get_pull_request_changes:
            self.register(self.get_pull_request_changes)
        if create_issue:
            self.register(self.create_issue)
        if create_repository:
            self.register(self.create_repository)
        if delete_repository:
            self.register(self.delete_repository)
        if list_branches:
            self.register(self.list_branches)
        if get_repository_languages:
            self.register(self.get_repository_languages)

    def authenticate(self):
        """Authenticate with GitHub using the provided access token."""
        if not self.access_token:  # Fixes lint type error
            raise ValueError("GitHub access token is required")

        auth = Auth.Token(self.access_token)
        if self.base_url:
            logger.debug(f"Authenticating with GitHub Enterprise at {self.base_url}")
            return Github(base_url=self.base_url, auth=auth)
        else:
            logger.debug("Authenticating with public GitHub")
            return Github(auth=auth)

    def search_repositories(
        self, query: str, sort: str = "stars", order: str = "desc", page: int = 1, per_page: int = 30
    ) -> str:
        """Search for repositories on GitHub.

        Args:
            query (str): The search query keywords.
            sort (str, optional): The field to sort results by. Can be 'stars', 'forks', or 'updated'. Defaults to 'stars'.
            order (str, optional): The order of results. Can be 'asc' or 'desc'. Defaults to 'desc'.
            page (int, optional): Page number of results to return, counting from 1. Defaults to 1.
            per_page (int, optional): Number of results per page. Max 100. Defaults to 30.
            Note: GitHub's Search API has a maximum limit of 1000 results per query.

        Returns:
            A JSON-formatted string containing a list of repositories matching the search query.
        """
        logger.debug(f"Searching repositories with query: '{query}', page: {page}, per_page: {per_page}")
        try:
            # Ensure per_page doesn't exceed GitHub's max of 100
            per_page = min(per_page, 100)

            repositories = self.g.search_repositories(query=query, sort=sort, order=order)

            # Get the specified page of results
            repo_list = []
            for repo in repositories.get_page(page - 1):
                repo_info = {
                    "full_name": repo.full_name,
                    "description": repo.description,
                    "url": repo.html_url,
                    "stars": repo.stargazers_count,
                    "forks": repo.forks_count,
                    "language": repo.language,
                }
                repo_list.append(repo_info)

                if len(repo_list) >= per_page:
                    break

            return json.dumps(repo_list, indent=2)

        except GithubException as e:
            logger.error(f"Error searching repositories: {e}")
            return json.dumps({"error": str(e)})

    def list_repositories(self) -> str:
        """List all repositories for the authenticated user.

        Returns:
            A JSON-formatted string containing a list of repository names.
        """
        logger.debug("Listing repositories")
        try:
            repos = self.g.get_user().get_repos()
            repo_names = [repo.full_name for repo in repos]
            return json.dumps(repo_names, indent=2)
        except GithubException as e:
            logger.error(f"Error listing repositories: {e}")
            return json.dumps({"error": str(e)})

    def create_repository(
        self,
        name: str,
        private: bool = False,
        description: Optional[str] = None,
        auto_init: bool = False,
        organization: Optional[str] = None,
    ) -> str:
        """Create a new repository on GitHub.

        Args:
            name (str): The name of the repository.
            private (bool, optional): Whether the repository is private. Defaults to False.
            description (str, optional): A short description of the repository.
            auto_init (bool, optional): Whether to initialize the repository with a README. Defaults to False.
            organization (str, optional): Name of organization to create repo in. If None, creates in user account.

        Returns:
            A JSON-formatted string containing the created repository details.
        """
        logger.debug(f"Creating repository: {name}")
        try:
            description = description if description is not None else ""

            if organization:
                logger.debug(f"Creating in organization: {organization}")
                org = self.g.get_organization(organization)
                repo = org.create_repo(
                    name=name,
                    private=private,
                    description=description,
                    auto_init=auto_init,
                )
            else:
                repo = self.g.get_user().create_repo(
                    name=name,
                    private=private,
                    description=description,
                    auto_init=auto_init,
                )

            repo_info = {
                "name": repo.full_name,
                "url": repo.html_url,
                "private": repo.private,
                "description": repo.description,
            }
            return json.dumps(repo_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating repository: {e}")
            return json.dumps({"error": str(e)})

    def get_repository(self, repo_name: str) -> str:
        """Get details of a specific repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').

        Returns:
            A JSON-formatted string containing repository details.
        """
        logger.debug(f"Getting repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            repo_info = {
                "name": repo.full_name,
                "description": repo.description,
                "url": repo.html_url,
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "open_issues": repo.open_issues_count,
                "language": repo.language,
                "license": repo.license.name if repo.license else None,
                "default_branch": repo.default_branch,
            }
            return json.dumps(repo_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting repository: {e}")
            return json.dumps({"error": str(e)})

    def get_repository_languages(self, repo_name: str) -> str:
        """Get the languages used in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').

        Returns:
            A JSON-formatted string containing the list of languages.
        """
        logger.debug(f"Getting languages for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            languages = repo.get_languages()
            return json.dumps(languages, indent=2)
        except GithubException as e:
            logger.error(f"Error getting repository languages: {e}")
            return json.dumps({"error": str(e)})

    def list_pull_requests(self, repo_name: str, state: str = "open") -> str:
        """List pull requests for a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            state (str, optional): The state of the PRs to list ('open', 'closed', 'all'). Defaults to 'open'.

        Returns:
            A JSON-formatted string containing a list of pull requests.
        """
        logger.debug(f"Listing pull requests for repository: {repo_name} with state: {state}")
        try:
            repo = self.g.get_repo(repo_name)
            pulls = repo.get_pulls(state=state)
            pr_list = []
            for pr in pulls:
                pr_info = {
                    "number": pr.number,
                    "title": pr.title,
                    "user": pr.user.login,
                    "created_at": pr.created_at.isoformat(),
                    "state": pr.state,
                    "url": pr.html_url,
                }
                pr_list.append(pr_info)
            return json.dumps(pr_list, indent=2)
        except GithubException as e:
            logger.error(f"Error listing pull requests: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request(self, repo_name: str, pr_number: int) -> str:
        """Get details of a specific pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.

        Returns:
            A JSON-formatted string containing pull request details.
        """
        logger.debug(f"Getting pull request #{pr_number} for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            pr_info = {
                "number": pr.number,
                "title": pr.title,
                "user": pr.user.login,
                "body": pr.body,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "state": pr.state,
                "merged": pr.is_merged(),
                "mergeable": pr.mergeable,
                "url": pr.html_url,
            }
            return json.dumps(pr_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting pull request: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request_changes(self, repo_name: str, pr_number: int) -> str:
        """Get the changes (files modified) in a pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.

        Returns:
            A JSON-formatted string containing the list of changed files.
        """
        logger.debug(f"Getting changes for pull request #{pr_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            files = pr.get_files()
            changes = []
            for file in files:
                file_info = {
                    "filename": file.filename,
                    "status": file.status,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "raw_url": file.raw_url,
                    "blob_url": file.blob_url,
                    "patch": file.patch,
                }
                changes.append(file_info)
            return json.dumps(changes, indent=2)
        except GithubException as e:
            logger.error(f"Error getting pull request changes: {e}")
            return json.dumps({"error": str(e)})

    def create_issue(self, repo_name: str, title: str, body: Optional[str] = None) -> str:
        """Create an issue in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            title (str): The title of the issue.
            body (str, optional): The body content of the issue.

        Returns:
            A JSON-formatted string containing the created issue details.
        """
        logger.debug(f"Creating issue in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.create_issue(title=title, body=body)
            issue_info = {
                "id": issue.id,
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "url": issue.html_url,
                "state": issue.state,
                "created_at": issue.created_at.isoformat(),
                "user": issue.user.login,
            }
            return json.dumps(issue_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating issue: {e}")
            return json.dumps({"error": str(e)})

    def list_issues(self, repo_name: str, state: str = "open") -> str:
        """List issues for a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            state (str, optional): The state of issues to list ('open', 'closed', 'all'). Defaults to 'open'.

        Returns:
            A JSON-formatted string containing a list of issues.
        """
        logger.debug(f"Listing issues for repository: {repo_name} with state: {state}")
        try:
            repo = self.g.get_repo(repo_name)
            issues = repo.get_issues(state=state)
            # Filter out pull requests after fetching issues
            filtered_issues = [issue for issue in issues if not issue.pull_request]
            issue_list = []
            for issue in filtered_issues:
                issue_info = {
                    "number": issue.number,
                    "title": issue.title,
                    "user": issue.user.login,
                    "created_at": issue.created_at.isoformat(),
                    "state": issue.state,
                    "url": issue.html_url,
                }
                issue_list.append(issue_info)
            return json.dumps(issue_list, indent=2)
        except GithubException as e:
            logger.error(f"Error listing issues: {e}")
            return json.dumps({"error": str(e)})

    def get_issue(self, repo_name: str, issue_number: int) -> str:
        """Get details of a specific issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.

        Returns:
            A JSON-formatted string containing issue details.
        """
        logger.debug(f"Getting issue #{issue_number} for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue_info = {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "user": issue.user.login,
                "state": issue.state,
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "url": issue.html_url,
                "assignees": [assignee.login for assignee in issue.assignees],
                "labels": [label.name for label in issue.labels],
            }
            return json.dumps(issue_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting issue: {e}")
            return json.dumps({"error": str(e)})

    def comment_on_issue(self, repo_name: str, issue_number: int, comment_body: str) -> str:
        """Add a comment to an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.
            comment_body (str): The content of the comment.

        Returns:
            A JSON-formatted string containing the comment details.
        """
        logger.debug(f"Adding comment to issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            comment = issue.create_comment(body=comment_body)
            comment_info = {
                "id": comment.id,
                "body": comment.body,
                "user": comment.user.login,
                "created_at": comment.created_at.isoformat(),
                "url": comment.html_url,
            }
            return json.dumps(comment_info, indent=2)
        except GithubException as e:
            logger.error(f"Error commenting on issue: {e}")
            return json.dumps({"error": str(e)})

    def close_issue(self, repo_name: str, issue_number: int) -> str:
        """Close an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.

        Returns:
            A JSON-formatted string confirming the issue is closed.
        """
        logger.debug(f"Closing issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(state="closed")
            return json.dumps({"message": f"Issue #{issue_number} closed."}, indent=2)
        except GithubException as e:
            logger.error(f"Error closing issue: {e}")
            return json.dumps({"error": str(e)})

    def reopen_issue(self, repo_name: str, issue_number: int) -> str:
        """Reopen a closed issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.

        Returns:
            A JSON-formatted string confirming the issue is reopened.
        """
        logger.debug(f"Reopening issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(state="open")
            return json.dumps({"message": f"Issue #{issue_number} reopened."}, indent=2)
        except GithubException as e:
            logger.error(f"Error reopening issue: {e}")
            return json.dumps({"error": str(e)})

    def assign_issue(self, repo_name: str, issue_number: int, assignees: List[str]) -> str:
        """Assign users to an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.
            assignees (List[str]): A list of usernames to assign.

        Returns:
            A JSON-formatted string confirming the assignees.
        """
        logger.debug(f"Assigning users to issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(assignees=assignees)
            return json.dumps({"message": f"Issue #{issue_number} assigned to {assignees}."}, indent=2)
        except GithubException as e:
            logger.error(f"Error assigning issue: {e}")
            return json.dumps({"error": str(e)})

    def label_issue(self, repo_name: str, issue_number: int, labels: List[str]) -> str:
        """Add labels to an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.
            labels (List[str]): A list of label names to add.

        Returns:
            A JSON-formatted string confirming the labels.
        """
        logger.debug(f"Labeling issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(labels=labels)
            return json.dumps({"message": f"Labels {labels} added to issue #{issue_number}."}, indent=2)
        except GithubException as e:
            logger.error(f"Error labeling issue: {e}")
            return json.dumps({"error": str(e)})

    def list_issue_comments(self, repo_name: str, issue_number: int) -> str:
        """List comments on an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.

        Returns:
            A JSON-formatted string containing a list of comments.
        """
        logger.debug(f"Listing comments for issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            comments = issue.get_comments()
            comment_list = []
            for comment in comments:
                comment_info = {
                    "id": comment.id,
                    "user": comment.user.login,
                    "body": comment.body,
                    "created_at": comment.created_at.isoformat(),
                    "url": comment.html_url,
                }
                comment_list.append(comment_info)
            return json.dumps(comment_list, indent=2)
        except GithubException as e:
            logger.error(f"Error listing issue comments: {e}")
            return json.dumps({"error": str(e)})

    def edit_issue(
        self, repo_name: str, issue_number: int, title: Optional[str] = None, body: Optional[str] = None
    ) -> str:
        """Edit the title or body of an issue.

        Args:
            repo_name (str): The full name of the repository.
            issue_number (int): The number of the issue.
            title (str, optional): The new title for the issue.
            body (str, optional): The new body content for the issue.

        Returns:
            A JSON-formatted string confirming the issue has been updated.
        """
        logger.debug(f"Editing issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(title=title, body=body)
            return json.dumps({"message": f"Issue #{issue_number} updated."}, indent=2)
        except GithubException as e:
            logger.error(f"Error editing issue: {e}")
            return json.dumps({"error": str(e)})

    def delete_repository(self, repo_name: str) -> str:
        """Delete a repository (requires admin permissions).

            Args:
                repo_name (str): The full name of the repository to delete (e.g., 'owner/repo').

        Returns:
            A JSON-formatted string with success message or error.
        """
        logger.debug(f"Deleting repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            repo.delete()
            return json.dumps({"message": f"Repository {repo_name} deleted successfully"}, indent=2)
        except GithubException as e:
            logger.error(f"Error deleting repository: {e}")
            return json.dumps({"error": str(e)})

    def list_branches(self, repo_name: str) -> str:
        """List all branches in a repository.

        Args:
            repo_name (str): Full repository name (e.g., 'owner/repo').

        Returns:
            JSON list of branch names.
        """
        try:
            repo = self.g.get_repo(repo_name)
            branches = [branch.name for branch in repo.get_branches()]
            return json.dumps(branches, indent=2)
        except GithubException as e:
            logger.error(f"Error listing branches: {e}")
            return json.dumps({"error": str(e)})
