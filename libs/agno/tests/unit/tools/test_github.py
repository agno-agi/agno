"""Unit tests for GitHub tools."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from github import Github
from github.GithubException import GithubException
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository

from agno.tools.github import GithubTools


@pytest.fixture
def mock_github():
    """Create a mock GitHub client."""
    with patch("agno.tools.github.Github") as mock_github, patch.dict(
        "os.environ", {"GITHUB_ACCESS_TOKEN": "dummy_token"}
    ):
        mock_client = MagicMock(spec=Github)
        mock_github.return_value = mock_client
        mock_repo = MagicMock(spec=Repository)
        mock_repo.full_name = "test-org/test-repo"
        mock_client.get_repo.return_value = mock_repo

        yield mock_client, mock_repo


@pytest.fixture
def mock_search_repos():
    """Create mock repositories for search tests."""
    mock_repo1 = MagicMock(spec=Repository)
    mock_repo1.full_name = "test-org/awesome-project"
    mock_repo1.description = "An awesome project"
    mock_repo1.html_url = "https://github.com/test-org/awesome-project"
    mock_repo1.stargazers_count = 1000
    mock_repo1.forks_count = 100
    mock_repo1.language = "Python"

    mock_repo2 = MagicMock(spec=Repository)
    mock_repo2.full_name = "test-org/another-project"
    mock_repo2.description = "Another cool project"
    mock_repo2.html_url = "https://github.com/test-org/another-project"
    mock_repo2.stargazers_count = 500
    mock_repo2.forks_count = 50
    mock_repo2.language = "JavaScript"

    return [mock_repo1, mock_repo2]


@pytest.fixture
def mock_paginated_list(mock_search_repos):
    """Create a mock paginated list for search results."""
    mock_list = MagicMock()
    mock_list.totalCount = len(mock_search_repos)
    mock_list.__iter__.return_value = mock_search_repos
    mock_list.get_page.return_value = mock_search_repos
    return mock_list


def test_list_pull_requests(mock_github):
    """Test listing pull requests."""
    mock_client, mock_repo = mock_github
    github_tools = GithubTools()

    # Mock PR data
    mock_pr1 = MagicMock(spec=PullRequest)
    mock_pr1.number = 1
    mock_pr1.title = "Feature: Add new functionality"
    mock_pr1.html_url = "https://github.com/test-org/test-repo/pull/1"
    mock_pr1.state = "open"
    mock_pr1.user.login = "test-user"
    mock_pr1.created_at = datetime(2024, 2, 4, 12, 0, 0)

    mock_pr2 = MagicMock(spec=PullRequest)
    mock_pr2.number = 2
    mock_pr2.title = "Fix: Bug fix"
    mock_pr2.html_url = "https://github.com/test-org/test-repo/pull/2"
    mock_pr2.state = "closed"
    mock_pr2.user.login = "another-user"
    mock_pr2.created_at = datetime(2024, 2, 3, 12, 0, 0)

    mock_repo.get_pulls.return_value = [mock_pr1, mock_pr2]

    # Test listing all PRs
    result = github_tools.list_pull_requests("test-org/test-repo")
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["number"] == 1
    assert result_data[0]["state"] == "open"
    assert result_data[1]["number"] == 2
    assert result_data[1]["state"] == "closed"

    # Test listing only open PRs
    mock_repo.get_pulls.return_value = [mock_pr1]
    result = github_tools.list_pull_requests("test-org/test-repo", state="open")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["state"] == "open"


def test_list_issues(mock_github):
    """Test listing issues."""
    mock_client, mock_repo = mock_github
    github_tools = GithubTools()

    # Mock issue data
    mock_issue1 = MagicMock(spec=Issue)
    mock_issue1.number = 1
    mock_issue1.title = "Bug: Something is broken"
    mock_issue1.html_url = "https://github.com/test-org/test-repo/issues/1"
    mock_issue1.state = "open"
    mock_issue1.user.login = "test-user"
    mock_issue1.pull_request = None
    mock_issue1.created_at = datetime(2024, 2, 4, 12, 0, 0)

    mock_issue2 = MagicMock(spec=Issue)
    mock_issue2.number = 2
    mock_issue2.title = "Enhancement: New feature request"
    mock_issue2.html_url = "https://github.com/test-org/test-repo/issues/2"
    mock_issue2.state = "closed"
    mock_issue2.user.login = "another-user"
    mock_issue2.pull_request = None
    mock_issue2.created_at = datetime(2024, 2, 3, 12, 0, 0)

    mock_repo.get_issues.return_value = [mock_issue1, mock_issue2]

    # Test listing all issues
    result = github_tools.list_issues("test-org/test-repo")
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["number"] == 1
    assert result_data[0]["state"] == "open"
    assert result_data[1]["number"] == 2
    assert result_data[1]["state"] == "closed"

    # Test listing only open issues
    mock_repo.get_issues.return_value = [mock_issue1]
    result = github_tools.list_issues("test-org/test-repo", state="open")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["state"] == "open"


def test_create_issue(mock_github):
    """Test creating an issue."""
    mock_client, mock_repo = mock_github
    github_tools = GithubTools()

    mock_issue = MagicMock(spec=Issue)
    mock_issue.id = 123
    mock_issue.number = 1
    mock_issue.title = "New Issue"
    mock_issue.html_url = "https://github.com/test-org/test-repo/issues/1"
    mock_issue.state = "open"
    mock_issue.user.login = "test-user"
    mock_issue.body = "Issue description"
    mock_issue.created_at = datetime(2024, 2, 4, 12, 0, 0)

    mock_repo.create_issue.return_value = mock_issue

    result = github_tools.create_issue("test-org/test-repo", title="New Issue", body="Issue description")
    result_data = json.loads(result)

    mock_repo.create_issue.assert_called_once_with(title="New Issue", body="Issue description")
    assert result_data["id"] == 123
    assert result_data["number"] == 1
    assert result_data["title"] == "New Issue"
    assert result_data["state"] == "open"


def test_get_repository(mock_github):
    """Test getting repository information."""
    mock_client, mock_repo = mock_github
    github_tools = GithubTools()

    # Mock repository data
    mock_repo.full_name = "test-org/test-repo"
    mock_repo.description = "Test repository"
    mock_repo.html_url = "https://github.com/test-org/test-repo"
    mock_repo.stargazers_count = 100
    mock_repo.forks_count = 50
    mock_repo.open_issues_count = 10
    mock_repo.default_branch = "main"
    mock_repo.private = False
    mock_repo.language = "Python"
    mock_repo.license = MagicMock()
    mock_repo.license.name = "MIT"

    result = github_tools.get_repository("test-org/test-repo")
    result_data = json.loads(result)

    assert result_data["name"] == "test-org/test-repo"
    assert result_data["description"] == "Test repository"
    assert result_data["stars"] == 100
    assert result_data["forks"] == 50
    assert result_data["open_issues"] == 10
    assert result_data["language"] == "Python"
    assert result_data["license"] == "MIT"


def test_error_handling(mock_github):
    """Test error handling for various scenarios."""
    mock_client, mock_repo = mock_github
    github_tools = GithubTools()

    # Test repository not found
    mock_client.get_repo.side_effect = GithubException(status=404, data={"message": "Repository not found"})
    result = github_tools.get_repository("invalid/repo")
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Repository not found" in result_data["error"]

    # Reset side effect
    mock_client.get_repo.side_effect = None

    # Test permission error for creating issues
    mock_repo.create_issue.side_effect = GithubException(status=403, data={"message": "Permission denied"})
    result = github_tools.create_issue("test-org/test-repo", title="Test")
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Permission denied" in result_data["error"]


def test_search_repositories_basic(mock_github, mock_paginated_list):
    """Test basic repository search functionality."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    mock_client.search_repositories.return_value = mock_paginated_list

    result = github_tools.search_repositories("awesome python")
    result_data = json.loads(result)

    mock_client.search_repositories.assert_called_once_with(query="awesome python", sort="stars", order="desc")
    assert len(result_data) == 2
    assert "full_name" in result_data[0]
    assert "description" in result_data[0]
    assert "url" in result_data[0]
    assert "stars" in result_data[0]
    assert "forks" in result_data[0]
    assert "language" in result_data[0]


def test_search_repositories_empty_results(mock_github):
    """Test repository search with no results."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    mock_empty_list = MagicMock()
    mock_empty_list.totalCount = 0
    mock_empty_list.__iter__.return_value = []
    mock_empty_list.get_page.return_value = []
    mock_client.search_repositories.return_value = mock_empty_list

    result = github_tools.search_repositories("nonexistent-repo-name")
    result_data = json.loads(result)
    assert len(result_data) == 0


def test_search_repositories_with_sorting(mock_github, mock_paginated_list):
    """Test repository search with sorting parameters."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    mock_client.search_repositories.return_value = mock_paginated_list

    result = github_tools.search_repositories("python", sort="stars", order="desc")
    result_data = json.loads(result)

    mock_client.search_repositories.assert_called_with(query="python", sort="stars", order="desc")
    assert len(result_data) == 2
    assert result_data[0]["stars"] == 1000
    assert result_data[1]["stars"] == 500


def test_search_repositories_with_language_filter(mock_github, mock_paginated_list):
    """Test repository search with language filter."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    mock_client.search_repositories.return_value = mock_paginated_list

    result = github_tools.search_repositories("project language:python")
    result_data = json.loads(result)

    mock_client.search_repositories.assert_called_with(query="project language:python", sort="stars", order="desc")
    assert len(result_data) == 2


def test_search_repositories_rate_limit_error(mock_github):
    """Test repository search with rate limit error."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    mock_client.search_repositories.side_effect = GithubException(
        status=403, data={"message": "API rate limit exceeded"}
    )

    result = github_tools.search_repositories("python")
    result_data = json.loads(result)
    assert "error" in result_data
    assert "API rate limit exceeded" in result_data["error"]


def test_search_repositories_pagination(mock_github):
    """Test repository search with pagination."""
    mock_client, _ = mock_github
    github_tools = GithubTools()

    # Create mock repos for different pages
    mock_repos_page1 = [
        MagicMock(
            full_name="test-org/repo1",
            description="First repo",
            html_url="https://github.com/test-org/repo1",
            stargazers_count=1000,
            forks_count=100,
            language="Python",
        ),
        MagicMock(
            full_name="test-org/repo2",
            description="Second repo",
            html_url="https://github.com/test-org/repo2",
            stargazers_count=900,
            forks_count=90,
            language="Python",
        ),
    ]

    mock_repos_page2 = [
        MagicMock(
            full_name="test-org/repo3",
            description="Third repo",
            html_url="https://github.com/test-org/repo3",
            stargazers_count=800,
            forks_count=80,
            language="Python",
        )
    ]

    # Mock paginated list
    mock_paginated = MagicMock()
    mock_paginated.totalCount = 3

    # Test first page
    mock_paginated.get_page.return_value = mock_repos_page1
    mock_client.search_repositories.return_value = mock_paginated

    result = github_tools.search_repositories("python", page=1, per_page=2)
    result_data = json.loads(result)

    mock_paginated.get_page.assert_called_with(0)  # GitHub API uses 0-based indexing
    assert len(result_data) == 2
    assert result_data[0]["full_name"] == "test-org/repo1"
    assert result_data[1]["full_name"] == "test-org/repo2"

    # Test second page
    mock_paginated.get_page.return_value = mock_repos_page2
    mock_client.search_repositories.return_value = mock_paginated

    result = github_tools.search_repositories("python", page=2, per_page=2)
    result_data = json.loads(result)

    mock_paginated.get_page.assert_called_with(1)  # GitHub API uses 0-based indexing
    assert len(result_data) == 1
    assert result_data[0]["full_name"] == "test-org/repo3"

    # Test with custom per_page
    mock_paginated.get_page.return_value = mock_repos_page1[:1]
    result = github_tools.search_repositories("python", page=1, per_page=1)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["full_name"] == "test-org/repo1"

    # Test with per_page exceeding GitHub's max (100)
    result = github_tools.search_repositories("python", per_page=150)
    result_data = json.loads(result)

    # Should be limited to 100
    mock_client.search_repositories.assert_called_with(query="python", sort="stars", order="desc")
