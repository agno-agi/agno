import json
from os import getenv
from typing import List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

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
        get_repository: bool = False,
        get_pull_request: bool = False,
        get_pull_request_changes: bool = False,
        create_issue: bool = False,
        create_repository: bool = False,
        delete_repository: bool = False,
        get_repository_languages: bool = False,
        list_branches: bool = False,
        get_pull_request_count: bool = False,
        get_repository_stars: bool = False,
        get_pull_requests: bool = False,
        get_pull_request_comments: bool = False,
        create_pull_request_comment: bool = False,
        edit_pull_request_comment: bool = False,
        get_pull_request_with_details: bool = False,
        get_repository_with_stats: bool = False,
        list_issues: bool = False,
        get_issue: bool = False,
        comment_on_issue: bool = False,
        close_issue: bool = False,
        reopen_issue: bool = False,
        assign_issue: bool = False,
        label_issue: bool = False,
        list_issue_comments: bool = False,
        edit_issue: bool = False,
        create_pull_request: bool = False,
        create_file: bool = False,
        get_file_content: bool = False,
        update_file: bool = True,
        delete_file: bool = False,
        get_directory_content: bool = False,
        get_branch_content: bool = False,
        create_branch: bool = False,
        set_default_branch: bool = False,
        search_code: bool = False,
        search_issues_and_prs: bool = False,
        create_review_request: bool = False,
        **kwargs,
    ):
        super().__init__(name="github", **kwargs)

        self.access_token = access_token or getenv("GITHUB_ACCESS_TOKEN")
        self.base_url = base_url

        self.g = self.authenticate()

        if search_repositories:
            self.register(self.search_repositories)
        if get_repository:
            self.register(self.get_repository)
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
        if get_pull_request_count:
            self.register(self.get_pull_request_count)
        if get_repository_stars:
            self.register(self.get_repository_stars)
        if get_pull_requests:
            self.register(self.get_pull_requests)
        if get_pull_request_comments:
            self.register(self.get_pull_request_comments)
        if create_pull_request_comment:
            self.register(self.create_pull_request_comment)
        if edit_pull_request_comment:
            self.register(self.edit_pull_request_comment)
        if get_pull_request_with_details:
            self.register(self.get_pull_request_with_details)
        if get_repository_with_stats:
            self.register(self.get_repository_with_stats)

        if list_issues:
            self.register(self.list_issues)
        if get_issue:
            self.register(self.get_issue)
        if comment_on_issue:
            self.register(self.comment_on_issue)
        if close_issue:
            self.register(self.close_issue)
        if reopen_issue:
            self.register(self.reopen_issue)
        if assign_issue:
            self.register(self.assign_issue)
        if label_issue:
            self.register(self.label_issue)
        if list_issue_comments:
            self.register(self.list_issue_comments)
        if edit_issue:
            self.register(self.edit_issue)

        if create_pull_request:
            self.register(self.create_pull_request)
        if create_file:
            self.register(self.create_file)
        if get_file_content:
            self.register(self.get_file_content)
        if update_file:
            self.register(self.update_file)
        if delete_file:
            self.register(self.delete_file)
        if get_directory_content:
            self.register(self.get_directory_content)
        if get_branch_content:
            self.register(self.get_branch_content)
        if create_branch:
            self.register(self.create_branch)
        if set_default_branch:
            self.register(self.set_default_branch)
        if search_code:
            self.register(self.search_code)
        if search_issues_and_prs:
            self.register(self.search_issues_and_prs)
        if create_review_request:
            self.register(self.create_review_request)

    def authenticate(self):
        """Authenticate with GitHub using the provided access token."""
        if not self.access_token:  # Fixes lint type error
            raise ValueError("GitHub access token is required")

        auth = Auth.Token(self.access_token)
        if self.base_url:
            log_debug(f"Authenticating with GitHub Enterprise at {self.base_url}")
            return Github(base_url=self.base_url, auth=auth)
        else:
            log_debug("Authenticating with public GitHub")
            return Github(auth=auth)

    def search_repositories(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        page: int = 1,
        per_page: int = 30,
    ) -> str:
        """Search for repositories on GitHub.

        Note: GitHub's Search API has a maximum limit of 1000 results per query.

        Args:
            query (str): The search query keywords.
            sort (str, optional): The field to sort results by. Can be 'stars', 'forks', or 'updated'. Defaults to 'stars'.
            order (str, optional): The order of results. Can be 'asc' or 'desc'. Defaults to 'desc'.
            page (int, optional): Page number of results to return, counting from 1. Defaults to 1.
            per_page (int, optional): Number of results per page. Max 100. Defaults to 30.

        Returns:
            A JSON-formatted string containing a list of repositories matching the search query.
        """
        log_debug(f"Searching repositories with query: '{query}', page: {page}, per_page: {per_page}")
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
        log_debug("Listing repositories")
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
        log_debug(f"Creating repository: {name}")
        try:
            description = description if description is not None else ""

            if organization:
                log_debug(f"Creating in organization: {organization}")
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
        log_debug(f"Getting repository: {repo_name}")
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
        log_debug(f"Getting languages for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            languages = repo.get_languages()
            return json.dumps(languages, indent=2)
        except GithubException as e:
            logger.error(f"Error getting repository languages: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request_count(
        self,
        repo_name: str,
        state: str = "all",
        author: Optional[str] = None,
        base: Optional[str] = None,
        head: Optional[str] = None,
    ) -> str:
        """Get the count of pull requests for a repository based on query parameters.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            state (str, optional): The state of the PRs to count ('open', 'closed', 'all'). Defaults to 'all'.
            author (str, optional): Filter PRs by author username.
            base (str, optional): Filter PRs by base branch name.
            head (str, optional): Filter PRs by head branch name.

        Returns:
            A JSON-formatted string containing the count of pull requests.
        """
        log_debug(f"Counting pull requests for repository: {repo_name} with state: {state}")
        try:
            repo = self.g.get_repo(repo_name)
            pulls = repo.get_pulls(state=state, base=base, head=head)

            # If author is specified, filter the results
            if author:
                # If we need to filter by author and state, make sure both conditions are met
                if state != "all":
                    count = sum(1 for pr in pulls if pr.user.login == author and pr.state == state)
                else:
                    count = sum(1 for pr in pulls if pr.user.login == author)
            else:
                count = pulls.totalCount

            return json.dumps({"count": count}, indent=2)
        except GithubException as e:
            logger.error(f"Error counting pull requests: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request(self, repo_name: str, pr_number: int) -> str:
        """Get details of a specific pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.


        Returns:
            A JSON-formatted string containing pull request details.
        """
        log_debug(f"Getting pull request #{pr_number} for repository: {repo_name}")
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
        log_debug(f"Getting changes for pull request #{pr_number} in repository: {repo_name}")
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
        log_debug(f"Creating issue in repository: {repo_name}")
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

    def list_issues(self, repo_name: str, state: str = "open", limit: int = 20) -> str:
        """List issues for a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            state (str, optional): The state of issues to list ('open', 'closed', 'all'). Defaults to 'open'.
            limit (int, optional): The maximum number of issues to return. Defaults to 20.
        Returns:
            A JSON-formatted string containing a list of issues.
        """
        log_debug(f"Listing issues for repository: {repo_name} with state: {state}")
        try:
            repo = self.g.get_repo(repo_name)
            issues = repo.get_issues(state=state)
            # Filter out pull requests after fetching issues
            logger.info(f"Issues: {issues}")
            filtered_issues = [issue for issue in issues if not issue.pull_request]
            issue_list = []
            for issue in filtered_issues[:limit]:
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
        log_debug(f"Getting issue #{issue_number} for repository: {repo_name}")
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
        log_debug(f"Adding comment to issue #{issue_number} in repository: {repo_name}")
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
        log_debug(f"Closing issue #{issue_number} in repository: {repo_name}")
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
        log_debug(f"Reopening issue #{issue_number} in repository: {repo_name}")
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
        log_debug(f"Assigning users to issue #{issue_number} in repository: {repo_name}")
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
        log_debug(f"Labeling issue #{issue_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            issue.edit(labels=labels)
            return json.dumps(
                {"message": f"Labels {labels} added to issue #{issue_number}."},
                indent=2,
            )
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
        log_debug(f"Listing comments for issue #{issue_number} in repository: {repo_name}")
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
        self,
        repo_name: str,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
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
        log_debug(f"Editing issue #{issue_number} in repository: {repo_name}")
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
        log_debug(f"Deleting repository: {repo_name}")
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

    def get_repository_stars(self, repo_name: str) -> str:
        """Get the number of stars for a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').

        Returns:
            A JSON-formatted string containing the star count.
        """
        log_debug(f"Getting star count for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            return json.dumps({"stars": repo.stargazers_count}, indent=2)
        except GithubException as e:
            logger.error(f"Error getting repository stars: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_requests(
        self,
        repo_name: str,
        state: str = "open",
        sort: str = "created",
        direction: str = "desc",
        limit: int = 50,
    ) -> str:
        """Get pull requests matching query parameters.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            state (str, optional): State of the PRs to retrieve. Can be 'open', 'closed', or 'all'. Defaults to 'open'.
            sort (str, optional): What to sort results by. Can be 'created', 'updated', 'popularity', 'long-running'. Defaults to 'created'.
            direction (str, optional): The direction of the sort. Can be 'asc' or 'desc'. Defaults to 'desc'.
            limit (int, optional): The maximum number of pull requests to return. Defaults to 20.

        Returns:
            A JSON-formatted string containing a list of pull requests.
        """
        try:
            repo = self.g.get_repo(repo_name)
            pulls = repo.get_pulls(state=state, sort=sort, direction=direction)

            pr_list = []
            for pr in pulls[:limit]:
                pr_info = {
                    "number": pr.number,
                    "title": pr.title,
                    "user": pr.user.login,
                    "created_at": pr.created_at.isoformat(),
                    "updated_at": pr.updated_at.isoformat(),
                    "state": pr.state,
                    "url": pr.html_url,
                }
                pr_list.append(pr_info)

            return json.dumps(pr_list, indent=2)
        except GithubException as e:
            logger.error(f"Error getting pull requests by query: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request_comments(self, repo_name: str, pr_number: int, include_issue_comments: bool = True) -> str:
        """Get all comments on a pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.
            include_issue_comments (bool, optional): Whether to include general PR comments. Defaults to True.

        Returns:
            A JSON-formatted string containing a list of pull request comments.
        """
        log_debug(f"Getting comments for pull request #{pr_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            comment_list = []

            # Get review comments (comments on specific lines of code)
            review_comments = pr.get_comments()
            for comment in review_comments:
                comment_info = {
                    "id": comment.id,
                    "body": comment.body,
                    "user": comment.user.login,
                    "created_at": comment.created_at.isoformat(),
                    "updated_at": comment.updated_at.isoformat(),
                    "path": comment.path,
                    "position": comment.position,
                    "commit_id": comment.commit_id,
                    "url": comment.html_url,
                    "type": "review_comment",
                }
                comment_list.append(comment_info)

            # Get general issue comments if requested
            if include_issue_comments:
                issue_comments = pr.get_issue_comments()
                for comment in issue_comments:
                    comment_info = {
                        "id": comment.id,
                        "body": comment.body,
                        "user": comment.user.login,
                        "created_at": comment.created_at.isoformat(),
                        "updated_at": comment.updated_at.isoformat(),
                        "url": comment.html_url,
                        "type": "issue_comment",
                    }
                    comment_list.append(comment_info)

            # Sort all comments by creation date
            comment_list.sort(key=lambda x: x["created_at"], reverse=True)

            return json.dumps(comment_list, indent=2)
        except GithubException as e:
            logger.error(f"Error getting pull request comments: {e}")
            return json.dumps({"error": str(e)})

    def create_pull_request_comment(
        self,
        repo_name: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        position: int,
    ) -> str:
        """Create a comment on a specific line of a specific file in a pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.
            body (str): The text of the comment.
            commit_id (str): The SHA of the commit to comment on.
            path (str): The relative path to the file to comment on.
            position (int): The line index in the diff to comment on.

        Returns:
            A JSON-formatted string containing the created comment details.
        """
        log_debug(f"Creating comment on pull request #{pr_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            commit = repo.get_commit(commit_id)
            comment = pr.create_comment(body, commit, path, position)

            comment_info = {
                "id": comment.id,
                "body": comment.body,
                "user": comment.user.login,
                "created_at": comment.created_at.isoformat(),
                "path": comment.path,
                "position": comment.position,
                "commit_id": comment.commit_id,
                "url": comment.html_url,
            }

            return json.dumps(comment_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating pull request comment: {e}")
            return json.dumps({"error": str(e)})

    def edit_pull_request_comment(self, repo_name: str, comment_id: int, body: str) -> str:
        """Edit an existing pull request comment.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            comment_id (int): The id of the comment to edit.
            body (str): The new text of the comment.

        Returns:
            A JSON-formatted string containing the updated comment details.
        """
        log_debug(f"Editing comment #{comment_id} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            comments = repo.get_pulls_comments()
            comment = None
            for comment in comments:
                if comment.id == comment_id:
                    comment.edit(body)

            if not comment:
                return f"Could not find comment #{comment_id} in repository: {repo_name}"

            comment_info = {
                "id": comment.id,
                "body": comment.body,
                "user": comment.user.login,
                "updated_at": comment.updated_at.isoformat(),
                "path": comment.path,
                "position": comment.position,
                "commit_id": comment.commit_id,
                "url": comment.html_url,
            }

            return json.dumps(comment_info, indent=2)
        except GithubException as e:
            logger.error(f"Error editing pull request comment: {e}")
            return json.dumps({"error": str(e)})

    def get_pull_request_with_details(self, repo_name: str, pr_number: int) -> str:
        """Get comprehensive details of a pull request including comments, labels, and metadata.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.

        Returns:
            A JSON-formatted string containing detailed pull request information.
        """
        log_debug(f"Getting comprehensive details for PR #{pr_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Get review comments
            review_comments = []
            for comment in pr.get_comments():
                review_comments.append(
                    {
                        "id": comment.id,
                        "body": comment.body,
                        "user": comment.user.login,
                        "created_at": comment.created_at.isoformat(),
                        "path": comment.path,
                        "position": comment.position,
                        "commit_id": comment.commit_id,
                        "url": comment.html_url,
                        "type": "review_comment",
                    }
                )

            # Get issue comments
            issue_comments = []
            for comment in pr.get_issue_comments():
                issue_comments.append(
                    {
                        "id": comment.id,
                        "body": comment.body,
                        "user": comment.user.login,
                        "created_at": comment.created_at.isoformat(),
                        "url": comment.html_url,
                        "type": "issue_comment",
                    }
                )

            # Get commit data
            commits = []
            for commit in pr.get_commits():
                commit_info = {
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": (commit.commit.author.name if commit.commit.author else "Unknown"),
                    "date": (commit.commit.author.date.isoformat() if commit.commit.author else None),
                    "url": commit.html_url,
                }
                commits.append(commit_info)

            # Get files changed
            files_changed = []
            for file in pr.get_files():
                file_info = {
                    "filename": file.filename,
                    "status": file.status,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "patch": file.patch,
                }
                files_changed.append(file_info)

            # Combine all comments and sort by creation date
            all_comments = review_comments + issue_comments
            all_comments.sort(key=lambda x: x["created_at"], reverse=True)

            # Get basic PR info
            pr_info = {
                "number": pr.number,
                "title": pr.title,
                "user": pr.user.login,
                "state": pr.state,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "html_url": pr.html_url,
                "body": pr.body,
                "base": pr.base.ref,
                "head": pr.head.ref,
                "merged": pr.is_merged(),
                "mergeable": pr.mergeable,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "labels": [label.name for label in pr.labels],
                "comments_count": {
                    "review_comments": len(review_comments),
                    "issue_comments": len(issue_comments),
                    "total": len(all_comments),
                },
                "comments": all_comments,
                "commits": commits,
                "files_changed": files_changed,
            }

            return json.dumps(pr_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting pull request details: {e}")
            return json.dumps({"error": str(e)})

    def get_repository_with_stats(self, repo_name: str) -> str:
        """Get comprehensive repository information including statistics.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').

        Returns:
            A JSON-formatted string containing detailed repository information and statistics.
        """
        log_debug(f"Getting detailed info for repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Helper function to safely convert values to primitive types
            def safe_value(val):
                if hasattr(val, "isoformat"):
                    return val.isoformat()
                elif isinstance(val, (int, float, bool, str)) or val is None:
                    return val
                else:
                    return str(val)

            # Get basic repo info
            repo_info = {
                "id": int(repo.id),
                "name": str(repo.name),
                "full_name": str(repo.full_name),
                "owner": str(repo.owner.login),
                "description": str(repo.description) if repo.description else None,
                "html_url": str(repo.html_url),
                "homepage": str(repo.homepage) if repo.homepage else None,
                "language": str(repo.language) if repo.language else None,
                "created_at": safe_value(repo.created_at),
                "updated_at": safe_value(repo.updated_at),
                "pushed_at": safe_value(repo.pushed_at),
                "size": int(repo.size),
                "stargazers_count": int(repo.stargazers_count),
                "watchers_count": int(repo.watchers_count),
                "forks_count": int(repo.forks_count),
                "open_issues_count": int(repo.open_issues_count),
                "default_branch": str(repo.default_branch),
                "topics": [str(topic) for topic in repo.get_topics()],
                "license": (str(repo.license.name) if repo.license and hasattr(repo.license, "name") else None),
                "private": bool(repo.private),
                "archived": bool(repo.archived),
            }

            # Get languages
            repo_info["languages"] = {str(lang): int(count) for lang, count in repo.get_languages().items()}

            # Calculate actual open issues (GitHub's count includes PRs)
            try:
                open_issues_count = 0
                for issue in repo.get_issues(state="open"):
                    if not issue.pull_request:
                        open_issues_count += 1
                repo_info["actual_open_issues"] = open_issues_count
            except Exception as e:
                log_debug(f"Error getting actual open issues: {e}")
                repo_info["actual_open_issues"] = None

            # Get open pull requests count
            try:
                open_prs = repo.get_pulls(state="open")
                repo_info["open_pr_count"] = int(open_prs.totalCount)
            except Exception as e:
                log_debug(f"Error getting open PRs count: {e}")
                repo_info["open_pr_count"] = None

            # Get recent open PRs
            try:
                open_prs_list = []
                open_prs = repo.get_pulls(state="open")

                # Use a simple for loop approach instead of trying to slice first
                count = 0
                for pr in open_prs:
                    if count >= 10:
                        break
                    try:
                        # Ensure all fields are primitives, not Mock objects
                        pr_data = {
                            "number": int(pr.number),
                            "title": str(pr.title),
                            "user": str(pr.user.login),
                            "created_at": safe_value(pr.created_at),
                            "updated_at": safe_value(pr.updated_at),
                            "url": str(pr.html_url),
                            "base": str(pr.base.ref),
                            "head": str(pr.head.ref),
                            "comment_count": int(pr.comments),
                        }
                        open_prs_list.append(pr_data)
                        count += 1
                    except Exception as e:
                        log_debug(f"Error processing individual PR: {e}")

                repo_info["recent_open_prs"] = open_prs_list
            except Exception as e:
                log_debug(f"Error getting recent open PRs: {e}")
                repo_info["recent_open_prs"] = []

            # Calculate PR metrics
            try:
                # Get a sample of PRs for statistics
                all_prs_list = []
                all_prs = repo.get_pulls(state="all", sort="created", direction="desc")

                pr_count = 0
                for pr in all_prs:
                    if pr_count >= 100:  # Limit to 100 PRs
                        break
                    all_prs_list.append(pr)
                    pr_count += 1

                # Calculate basic metrics
                merged_prs = []
                for pr in all_prs_list:
                    is_merged = pr.is_merged()
                    if is_merged:
                        merged_prs.append(pr)

                # Compute merge time for merged PRs (in hours)
                merge_times = []
                for pr in merged_prs:
                    if pr.merged_at and pr.created_at:
                        merge_time = (pr.merged_at - pr.created_at).total_seconds() / 3600
                        merge_times.append(merge_time)

                pr_metrics = {
                    "total_prs": len(all_prs_list),
                    "merged_prs": len(merged_prs),
                    "acceptance_rate": ((len(merged_prs) / len(all_prs_list) * 100) if len(all_prs_list) > 0 else 0),
                    "avg_time_to_merge": (sum(merge_times) / len(merge_times) if merge_times else None),
                }
                repo_info["pr_metrics"] = pr_metrics
            except Exception as e:
                log_debug(f"Error calculating PR metrics: {e}")
                repo_info["pr_metrics"] = None

            # Get contributors
            try:
                contributors: list[dict] = []
                for contributor in repo.get_contributors():
                    if len(contributors) >= 20:  # Limit to top 20
                        break
                    contributors.append(
                        {
                            "login": str(contributor.login),
                            "contributions": int(contributor.contributions),
                            "url": str(contributor.html_url),
                        }
                    )
                repo_info["contributors"] = contributors
            except Exception as e:
                log_debug(f"Error getting contributors: {e}")
                repo_info["contributors"] = []

            return json.dumps(repo_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting repository stats: {e}")
            return json.dumps({"error": str(e)})

    def create_pull_request(
        self,
        repo_name: str,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
        maintainer_can_modify: bool = True,
    ) -> str:
        """Create a new pull request in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            title (str): The title of the pull request.
            body (str): The body text of the pull request.
            head (str): The name of the branch where your changes are implemented.
            base (str): The name of the branch you want the changes pulled into.
            draft (bool, optional): Whether the pull request is a draft. Defaults to False.
            maintainer_can_modify (bool, optional): Whether maintainers can modify the PR. Defaults to True.

        Returns:
            A JSON-formatted string containing the created pull request details.
        """
        log_debug(f"Creating pull request in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base,
                draft=draft,
                maintainer_can_modify=maintainer_can_modify,
            )

            pr_info = {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "user": pr.user.login,
                "state": pr.state,
                "created_at": pr.created_at.isoformat(),
                "html_url": pr.html_url,
                "base": pr.base.ref,
                "head": pr.head.ref,
                "mergeable": pr.mergeable,
            }

            return json.dumps(pr_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating pull request: {e}")
            return json.dumps({"error": str(e)})

    def create_review_request(
        self,
        repo_name: str,
        pr_number: int,
        reviewers: List[str],
        team_reviewers: Optional[List[str]] = None,
    ) -> str:
        """Create a review request for a pull request.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            pr_number (int): The number of the pull request.
            reviewers (List[str]): List of user logins that will be requested to review.
            team_reviewers (List[str], optional): List of team slugs that will be requested to review. Defaults to None.

        Returns:
            A JSON-formatted string with the success message or error.
        """
        log_debug(f"Creating review request for PR #{pr_number} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            pr.create_review_request(reviewers=reviewers, team_reviewers=team_reviewers or [])

            return json.dumps(
                {
                    "message": f"Review request created for PR #{pr_number}",
                    "requested_reviewers": reviewers,
                    "requested_team_reviewers": team_reviewers or [],
                },
                indent=2,
            )
        except GithubException as e:
            logger.error(f"Error creating review request: {e}")
            return json.dumps({"error": str(e)})

    def create_file(
        self,
        repo_name: str,
        path: str,
        content: str,
        message: str,
        branch: Optional[str] = None,
    ) -> str:
        """Create a new file in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            path (str): The path to the file in the repository.
            content (str): The content of the file.
            message (str): The commit message.
            branch (str, optional): The branch to commit to. Defaults to repository's default branch.

        Returns:
            A JSON-formatted string containing the file creation result.
        """
        log_debug(f"Creating file {path} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Convert string content to bytes
            content_bytes = content.encode("utf-8")

            # Create the file
            result = repo.create_file(path=path, message=message, content=content_bytes, branch=branch)

            # Extract relevant information
            file_info = {
                "path": result["content"].path,
                "sha": result["content"].sha,
                "url": result["content"].html_url,
                "commit": {
                    "sha": result["commit"].sha,
                    "message": result["commit"].commit.message,
                    "url": result["commit"].html_url,
                },
            }

            return json.dumps(file_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating file: {e}")
            return json.dumps({"error": str(e)})

    def get_file_content(self, repo_name: str, path: str, ref: Optional[str] = None) -> str:
        """Get the content of a file in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            path (str): The path to the file in the repository.
            ref (str, optional): The name of the commit/branch/tag. Defaults to the repository's default branch.

        Returns:
            A JSON-formatted string containing the file content and metadata.
        """
        log_debug(f"Getting content of file {path} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Conditionally call get_contents based on ref
            if ref is not None:
                file_content = repo.get_contents(path, ref=ref)
            else:
                file_content = repo.get_contents(path)

            # If it's a list (directory), raise an error
            if isinstance(file_content, list):
                return json.dumps({"error": f"{path} is a directory, not a file"})

            # Decode content
            try:
                decoded_content = file_content.decoded_content.decode("utf-8")
            except UnicodeDecodeError:
                decoded_content = "Binary file (content not displayed)"
            except Exception as e:
                log_debug(f"Error decoding file content: {e}")
                decoded_content = "Binary file (content not displayed)"

            # Make sure we don't try to display binary content
            if isinstance(decoded_content, str) and (
                "\x00" in decoded_content or sum(1 for c in decoded_content[:1000] if not (32 <= ord(c) <= 126)) > 200
            ):
                decoded_content = "Binary file (content not displayed)"

            # Create response
            content_info = {
                "name": file_content.name,
                "path": file_content.path,
                "sha": file_content.sha,
                "size": file_content.size,
                "type": file_content.type,
                "url": file_content.html_url,
                "content": decoded_content,
            }

            return json.dumps(content_info, indent=2)
        except GithubException as e:
            logger.error(f"Error getting file content: {e}")
            return json.dumps({"error": str(e)})

    def update_file(
        self,
        repo_name: str,
        path: str,
        content: str,
        message: str,
        sha: str,
        branch: Optional[str] = None,
    ) -> str:
        """Update an existing file in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            path (str): The path to the file in the repository.
            content (str): The new content of the file.
            message (str): The commit message.
            sha (str): The blob SHA of the file being replaced.
            branch (str, optional): The branch to commit to. Defaults to repository's default branch.

        Returns:
            A JSON-formatted string containing the file update result.
        """
        log_debug(f"Updating file {path} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Convert string content to bytes
            content_bytes = content.encode("utf-8")

            # Update the file
            result = repo.update_file(
                path=path,
                message=message,
                content=content_bytes,
                sha=sha,
                branch=branch,
            )

            # Extract relevant information
            file_info = {
                "path": result["content"].path,
                "sha": result["content"].sha,
                "url": result["content"].html_url,
                "commit": {
                    "sha": result["commit"].sha,
                    "message": result["commit"].commit.message,
                    "url": result["commit"].html_url,
                },
            }

            return json.dumps(file_info, indent=2)
        except GithubException as e:
            logger.error(f"Error updating file: {e}")
            return json.dumps({"error": str(e)})

    def delete_file(
        self,
        repo_name: str,
        path: str,
        message: str,
        sha: str,
        branch: Optional[str] = None,
    ) -> str:
        """Delete a file from a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            path (str): The path to the file in the repository.
            message (str): The commit message.
            sha (str): The blob SHA of the file being deleted.
            branch (str, optional): The branch to commit to. Defaults to repository's default branch.

        Returns:
            A JSON-formatted string containing the file deletion result.
        """
        log_debug(f"Deleting file {path} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Delete the file
            result = repo.delete_file(path=path, message=message, sha=sha, branch=branch)

            # Extract relevant information
            commit_info = {
                "message": f"File {path} deleted successfully",
                "commit": {
                    "sha": result["commit"].sha,
                    "message": result["commit"].commit.message,
                    "url": result["commit"].html_url,
                },
            }

            return json.dumps(commit_info, indent=2)
        except GithubException as e:
            logger.error(f"Error deleting file: {e}")
            return json.dumps({"error": str(e)})

    def get_directory_content(self, repo_name: str, path: str, ref: Optional[str] = None) -> str:
        """Get the contents of a directory in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            path (str): The path to the directory in the repository. Use empty string for root.
            ref (str, optional): The name of the commit/branch/tag. Defaults to repository's default branch.

        Returns:
            A JSON-formatted string containing a list of directory contents.
        """
        log_debug(f"Getting contents of directory {path} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Conditionally call get_contents based on ref
            if ref is not None:
                contents = repo.get_contents(path, ref=ref)
            else:
                contents = repo.get_contents(path)

            # If it's not a list, it's a file not a directory
            if not isinstance(contents, list):
                return json.dumps({"error": f"{path} is a file, not a directory"})

            # Process directory contents
            items = []
            for content in contents:
                item = {
                    "name": content.name,
                    "path": content.path,
                    "type": content.type,
                    "size": content.size,
                    "sha": content.sha,
                    "url": content.html_url,
                    "download_url": content.download_url,
                }
                items.append(item)

            # Sort by type (directories first) and then by name
            items.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))

            return json.dumps(items, indent=2)
        except GithubException as e:
            logger.error(f"Error getting directory contents: {e}")
            return json.dumps({"error": str(e)})

    def get_branch_content(self, repo_name: str, branch: str = "main") -> str:
        """Get the root directory content of a specific branch.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            branch (str, optional): The branch name. Defaults to "main".

        Returns:
            A JSON-formatted string containing a list of branch contents.
        """
        log_debug(f"Getting contents of branch {branch} in repository: {repo_name}")
        try:
            # This is just a convenience function that uses get_directory_content with empty path
            return self.get_directory_content(repo_name=repo_name, path="", ref=branch)
        except GithubException as e:
            logger.error(f"Error getting branch contents: {e}")
            return json.dumps({"error": str(e)})

    def create_branch(self, repo_name: str, branch_name: str, source_branch: Optional[str] = None) -> str:
        """Create a new branch in a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            branch_name (str): The name of the new branch.
            source_branch (str, optional): The source branch to create from. Defaults to repository's default branch.

        Returns:
            A JSON-formatted string containing information about the created branch.
        """
        log_debug(f"Creating branch {branch_name} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Get the source branch or default branch if not specified
            if source_branch is None:
                source_branch = repo.default_branch

            # Get the SHA of the latest commit on the source branch
            source_branch_ref = repo.get_git_ref(f"heads/{source_branch}")
            sha = source_branch_ref.object.sha

            # Create the new branch
            new_branch = repo.create_git_ref(f"refs/heads/{branch_name}", sha)

            branch_info = {
                "name": branch_name,
                "sha": new_branch.object.sha,
                "url": new_branch.url.replace("api.github.com/repos", "github.com").replace("git/refs/heads", "tree"),
            }

            return json.dumps(branch_info, indent=2)
        except GithubException as e:
            logger.error(f"Error creating branch: {e}")
            return json.dumps({"error": str(e)})

    def set_default_branch(self, repo_name: str, branch_name: str) -> str:
        """Set the default branch for a repository.

        Args:
            repo_name (str): The full name of the repository (e.g., 'owner/repo').
            branch_name (str): The name of the branch to set as default.

        Returns:
            A JSON-formatted string with success message or error.
        """
        log_debug(f"Setting default branch to {branch_name} in repository: {repo_name}")
        try:
            repo = self.g.get_repo(repo_name)

            # Check if the branch exists by looking at all branches
            branches = [branch.name for branch in repo.get_branches()]
            if branch_name not in branches:
                return json.dumps({"error": f"Branch '{branch_name}' does not exist"})

            # Set the default branch
            repo.edit(default_branch=branch_name)

            return json.dumps(
                {
                    "message": f"Default branch changed to {branch_name}",
                    "repository": repo_name,
                    "default_branch": branch_name,
                },
                indent=2,
            )
        except GithubException as e:
            logger.error(f"Error setting default branch: {e}")
            return json.dumps({"error": str(e)})

    def search_code(
        self,
        query: str,
        language: Optional[str] = None,
        repo: Optional[str] = None,
        user: Optional[str] = None,
        path: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> str:
        """Search for code in GitHub repositories.

        Args:
            query (str): The search query.
            language (str, optional): Filter by language. Defaults to None.
            repo (str, optional): Filter by repository (e.g., 'owner/repo'). Defaults to None.
            user (str, optional): Filter by user or organization. Defaults to None.
            path (str, optional): Filter by file path. Defaults to None.
            filename (str, optional): Filter by filename. Defaults to None.

        Returns:
            A JSON-formatted string containing the search results.
        """
        log_debug(f"Searching code with query: {query}")
        try:
            search_query = query

            # Add filters to the query if provided
            if language:
                search_query += f" language:{language}"
            if repo:
                search_query += f" repo:{repo}"
            if user:
                search_query += f" user:{user}"
            if path:
                search_query += f" path:{path}"
            if filename:
                search_query += f" filename:{filename}"

            # Perform the search
            log_debug(f"Final search query: {search_query}")
            code_results = self.g.search_code(search_query)

            # Process results
            results = []
            for code in code_results[:50]:  # Limit to 50 results to prevent timeouts
                code_info = {
                    "repository": code.repository.full_name,
                    "path": code.path,
                    "name": code.name,
                    "sha": code.sha,
                    "html_url": code.html_url,
                    "git_url": code.git_url,
                    "score": code.score,
                }
                results.append(code_info)

            # Return search results
            return json.dumps(
                {
                    "query": search_query,
                    "total_count": code_results.totalCount,
                    "results_count": len(results),
                    "results": results,
                },
                indent=2,
            )
        except GithubException as e:
            logger.error(f"Error searching code: {e}")
            return json.dumps({"error": str(e)})

    def search_issues_and_prs(
        self,
        query: str,
        state: Optional[str] = None,
        type_filter: Optional[str] = None,
        repo: Optional[str] = None,
        user: Optional[str] = None,
        label: Optional[str] = None,
        sort: str = "created",
        order: str = "desc",
        page: int = 1,
        per_page: int = 30,
    ) -> str:
        """Search for issues and pull requests on GitHub.

        Args:
            query (str): The search query.
            state (str, optional): Filter by state ('open', 'closed'). Defaults to None.
            type_filter (str, optional): Filter by type ('issue', 'pr'). Defaults to None.
            repo (str, optional): Filter by repository (e.g., 'owner/repo'). Defaults to None.
            user (str, optional): Filter by user or organization. Defaults to None.
            label (str, optional): Filter by label. Defaults to None.
            sort (str, optional): Sort results by ('created', 'updated', 'comments'). Defaults to "created".
            order (str, optional): Sort order ('asc', 'desc'). Defaults to "desc".
            page (int, optional): Page number for pagination. Defaults to 1.
            per_page (int, optional): Number of results per page. Defaults to 30.

        Returns:
            A JSON-formatted string containing the search results.
        """
        log_debug(f"Searching issues and PRs with query: {query}")
        try:
            search_query = query

            # Add filters to the query if provided
            if state:
                search_query += f" state:{state}"
            if type_filter == "issue":
                search_query += " is:issue"
            elif type_filter == "pr":
                search_query += " is:pr"
            if repo:
                search_query += f" repo:{repo}"
            if user:
                search_query += f" user:{user}"
            if label:
                search_query += f" label:{label}"

            # Perform the search
            log_debug(f"Final search query: {search_query}")
            issue_results = self.g.search_issues(search_query, sort=sort, order=order)

            # Process results
            per_page = min(per_page, 100)  # Ensure per_page doesn't exceed 100
            results = []

            try:
                # Get the specific page of results
                page_items = issue_results.get_page(page - 1)

                for issue in page_items:
                    issue_info = {
                        "number": issue.number,
                        "title": issue.title,
                        "repository": issue.repository.full_name,
                        "state": issue.state,
                        "created_at": issue.created_at.isoformat(),
                        "updated_at": issue.updated_at.isoformat(),
                        "html_url": issue.html_url,
                        "user": issue.user.login,
                        "is_pull_request": hasattr(issue, "pull_request") and issue.pull_request is not None,
                        "comments": issue.comments,
                        "labels": [label.name for label in issue.labels],
                    }
                    results.append(issue_info)

                    if len(results) >= per_page:
                        break
            except IndexError:
                # Page is out of range
                pass

            # Return search results
            return json.dumps(
                {
                    "query": search_query,
                    "total_count": issue_results.totalCount,
                    "page": page,
                    "per_page": per_page,
                    "results_count": len(results),
                    "results": results,
                },
                indent=2,
            )
        except GithubException as e:
            logger.error(f"Error searching issues and PRs: {e}")
            return json.dumps({"error": str(e)})
