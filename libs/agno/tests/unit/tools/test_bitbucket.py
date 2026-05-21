import json
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from agno.tools.bitbucket import BitbucketTools


class TestBitbucketTools:
    """Test suite for BitbucketTools class."""

    @pytest.fixture
    def mock_env_vars(self):
        """Mock environment variables for testing."""
        with patch.dict(
            os.environ,
            {
                "BITBUCKET_USERNAME": "test_user",
                "BITBUCKET_PASSWORD": "test_password",
            },
        ):
            yield

    @pytest.fixture
    def bitbucket_tools(self, mock_env_vars):
        """Create BitbucketTools instance for testing."""
        return BitbucketTools(workspace="test_workspace", repo_slug="test_repo")

    @pytest.fixture
    def bitbucket_tools_with_token(self, mock_env_vars):
        """Create BitbucketTools instance with token for testing."""
        with patch.dict(os.environ, {"BITBUCKET_TOKEN": "test_token"}):
            return BitbucketTools(workspace="test_workspace", repo_slug="test_repo")

    def test_init_with_required_params(self, mock_env_vars):
        """Test successful initialization with required parameters."""
        tools = BitbucketTools(workspace="test_workspace", repo_slug="test_repo")

        assert tools.workspace == "test_workspace"
        assert tools.repo_slug == "test_repo"
        assert tools.username == "test_user"
        assert tools.auth_password == "test_password"
        assert tools.server_url == "api.bitbucket.org"
        assert tools.api_version == "2.0"
        assert "Basic" in tools.headers["Authorization"]

    def test_init_with_custom_params(self, mock_env_vars):
        """Test initialization with custom parameters."""
        tools = BitbucketTools(
            workspace="custom_workspace",
            repo_slug="custom_repo",
            server_url="custom.bitbucket.com",
            username="custom_user",
            password="custom_password",
            api_version="2.1",
        )

        assert tools.workspace == "custom_workspace"
        assert tools.repo_slug == "custom_repo"
        assert tools.username == "custom_user"
        assert tools.auth_password == "custom_password"
        assert tools.server_url == "custom.bitbucket.com"
        assert tools.api_version == "2.1"

    def test_init_with_token_priority(self, mock_env_vars):
        """Test that token takes priority over password."""
        tools = BitbucketTools(
            workspace="test_workspace", repo_slug="test_repo", token="test_token", password="test_password"
        )

        assert tools.auth_password == "test_token"
        assert tools.token == "test_token"
        assert tools.password == "test_password"

    def test_init_missing_credentials(self):
        """Test initialization fails without credentials."""
        with patch.dict(os.environ, {}, clear=True):  # Clear all environment variables
            with pytest.raises(ValueError, match="Username and password or token are required"):
                BitbucketTools(workspace="test_workspace", repo_slug="test_repo")

    def test_init_missing_workspace(self, mock_env_vars):
        """Test initialization fails without workspace."""
        with pytest.raises(ValueError, match="Workspace is required"):
            BitbucketTools(repo_slug="test_repo")

    def test_init_missing_repo_slug(self, mock_env_vars):
        """Test initialization fails without repo_slug."""
        with pytest.raises(ValueError, match="Repo slug is required"):
            BitbucketTools(workspace="test_workspace")

    def test_generate_access_token(self, bitbucket_tools):
        """Test access token generation."""
        token = bitbucket_tools._generate_access_token()
        assert isinstance(token, str)
        assert len(token) > 0

    @patch("requests.request")
    def test_make_request_json_response(self, mock_request, bitbucket_tools):
        """Test _make_request with JSON response."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"test": "data"}
        mock_response.text = '{"test": "data"}'
        mock_request.return_value = mock_response

        result = bitbucket_tools._make_request("GET", "/test")

        assert result == {"test": "data"}
        mock_request.assert_called_once()

    @patch("requests.request")
    def test_make_request_text_response(self, mock_request, bitbucket_tools):
        """Test _make_request with text response."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "text/plain"}
        mock_response.text = "test data"
        mock_request.return_value = mock_response

        result = bitbucket_tools._make_request("GET", "/test")

        assert result == "test data"

    @patch("requests.request")
    def test_make_request_empty_json_response(self, mock_request, bitbucket_tools):
        """Test _make_request with empty JSON response."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = ""
        mock_request.return_value = mock_response

        result = bitbucket_tools._make_request("GET", "/test")

        assert result == {}

    @patch("requests.request")
    def test_make_request_unsupported_content_type(self, mock_request, bitbucket_tools):
        """Test _make_request with unsupported content type."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/xml"}
        mock_request.return_value = mock_response

        with patch("agno.tools.bitbucket.logger.warning") as mock_logger:
            result = bitbucket_tools._make_request("GET", "/test")

            assert result == {}
            mock_logger.assert_called_once()

    @patch("requests.request")
    def test_make_request_http_error(self, mock_request, bitbucket_tools):
        """Test _make_request with HTTP error."""
        mock_request.side_effect = requests.exceptions.HTTPError("HTTP Error")

        with pytest.raises(requests.exceptions.HTTPError):
            bitbucket_tools._make_request("GET", "/test")

    @patch.object(BitbucketTools, "_make_request")
    def test_list_repositories_success(self, mock_request, bitbucket_tools):
        """Test list_repositories method success."""
        mock_response = {"values": [{"name": "repo1"}, {"name": "repo2"}], "page": 1, "size": 2}
        mock_request.return_value = mock_response

        result = bitbucket_tools.list_repositories(count=5)

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with("GET", "/repositories/test_workspace", params={"page": 1, "pagelen": 5})

    @patch.object(BitbucketTools, "_make_request")
    def test_list_repositories_max_count(self, mock_request, bitbucket_tools):
        """Test list_repositories respects maximum count of 50."""
        mock_response = {"values": []}
        mock_request.return_value = mock_response

        bitbucket_tools.list_repositories(count=100)

        # Should be limited to 50
        mock_request.assert_called_once_with("GET", "/repositories/test_workspace", params={"page": 1, "pagelen": 50})

    @patch.object(BitbucketTools, "_make_request")
    def test_list_repositories_error(self, mock_request, bitbucket_tools):
        """Test list_repositories error handling."""
        mock_request.side_effect = Exception("API Error")

        with patch("agno.tools.bitbucket.logger.error") as mock_logger:
            result = bitbucket_tools.list_repositories()

            result_data = json.loads(result)
            assert "error" in result_data
            mock_logger.assert_called_once()

    @patch.object(BitbucketTools, "_make_request")
    def test_get_repository_details_success(self, mock_request, bitbucket_tools):
        """Test get_repository_details method success."""
        mock_response = {"name": "test_repo", "full_name": "test_workspace/test_repo"}
        mock_request.return_value = mock_response

        result = bitbucket_tools.get_repository_details()

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with("GET", "/repositories/test_workspace/test_repo")

    @patch.object(BitbucketTools, "_make_request")
    def test_create_repository_success(self, mock_request, bitbucket_tools):
        """Test create_repository method success."""
        mock_response = {"name": "new_repo", "is_private": False}
        mock_request.return_value = mock_response

        result = bitbucket_tools.create_repository(name="new_repo", description="Test repository", is_private=False)

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response

        expected_payload = {
            "name": "new_repo",
            "scm": "git",
            "is_private": False,
            "description": "Test repository",
            "language": None,
            "has_issues": False,
            "has_wiki": False,
        }
        mock_request.assert_called_once_with("POST", "/repositories/test_workspace/test_repo", data=expected_payload)

    @patch.object(BitbucketTools, "_make_request")
    def test_create_repository_with_project(self, mock_request, bitbucket_tools):
        """Test create_repository with project parameter."""
        mock_response = {"name": "new_repo"}
        mock_request.return_value = mock_response

        bitbucket_tools.create_repository(name="new_repo", project="TEST")

        call_args = mock_request.call_args
        payload = call_args[1]["data"]
        assert payload["project"] == {"key": "TEST"}

    @patch.object(BitbucketTools, "_make_request")
    def test_list_repository_commits_success(self, mock_request, bitbucket_tools):
        """Test list_repository_commits method success."""
        mock_response = {"values": [{"hash": "abc123"}, {"hash": "def456"}], "next": None}
        mock_request.return_value = mock_response

        result = bitbucket_tools.list_repository_commits(count=10)

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with(
            "GET", "/repositories/test_workspace/test_repo/commits", params={"pagelen": 10}
        )

    @patch.object(BitbucketTools, "_make_request")
    def test_list_repository_commits_with_pagination(self, mock_request, bitbucket_tools):
        """Test list_repository_commits with pagination."""
        # First response with next page
        first_response = {
            "values": [{"hash": "abc123"}],
            "next": "https://api.bitbucket.org/repositories/test_workspace/test_repo/commits?page=2",
        }
        # Second response
        second_response = {"values": [{"hash": "def456"}], "next": None}

        mock_request.side_effect = [first_response, second_response]

        result = bitbucket_tools.list_repository_commits(count=10)

        result_data = json.loads(result)
        assert len(result_data["values"]) == 2
        assert result_data["values"][0]["hash"] == "abc123"
        assert result_data["values"][1]["hash"] == "def456"
        assert mock_request.call_count == 2

    @patch.object(BitbucketTools, "_make_request")
    def test_list_all_pull_requests_success(self, mock_request, bitbucket_tools):
        """Test list_all_pull_requests method success."""
        mock_response = {"values": [{"id": 1, "title": "PR 1"}, {"id": 2, "title": "PR 2"}]}
        mock_request.return_value = mock_response

        result = bitbucket_tools.list_all_pull_requests(state="OPEN")

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with(
            "GET", "/repositories/test_workspace/test_repo/pullrequests", params={"state": "OPEN"}
        )

    @patch.object(BitbucketTools, "_make_request")
    def test_list_all_pull_requests_invalid_state(self, mock_request, bitbucket_tools):
        """Test list_all_pull_requests with invalid state defaults to OPEN."""
        mock_response = {"values": []}
        mock_request.return_value = mock_response

        with patch("agno.tools.bitbucket.logger.debug") as mock_logger:
            bitbucket_tools.list_all_pull_requests(state="INVALID")

            mock_logger.assert_called_once()
            # Should default to OPEN state
            mock_request.assert_called_once_with(
                "GET", "/repositories/test_workspace/test_repo/pullrequests", params={"state": "OPEN"}
            )

    @patch.object(BitbucketTools, "_make_request")
    def test_get_pull_request_details_success(self, mock_request, bitbucket_tools):
        """Test get_pull_request_details method success."""
        mock_response = {"id": 123, "title": "Test PR"}
        mock_request.return_value = mock_response

        result = bitbucket_tools.get_pull_request_details(pull_request_id=123)

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with("GET", "/repositories/test_workspace/test_repo/pullrequests/123")

    @patch.object(BitbucketTools, "_make_request")
    def test_get_pull_request_changes_success(self, mock_request, bitbucket_tools):
        """Test get_pull_request_changes method success."""
        mock_diff = "diff --git a/file.txt b/file.txt\n+added line"
        mock_request.return_value = mock_diff

        result = bitbucket_tools.get_pull_request_changes(pull_request_id=123)

        assert result == mock_diff
        mock_request.assert_called_once_with("GET", "/repositories/test_workspace/test_repo/pullrequests/123/diff")

    @patch.object(BitbucketTools, "_make_request")
    def test_list_issues_success(self, mock_request, bitbucket_tools):
        """Test list_issues method success."""
        mock_response = {"values": [{"id": 1, "title": "Issue 1"}, {"id": 2, "title": "Issue 2"}]}
        mock_request.return_value = mock_response

        result = bitbucket_tools.list_issues(count=10)

        assert isinstance(result, str)
        result_data = json.loads(result)
        assert result_data == mock_response
        mock_request.assert_called_once_with(
            "GET", "/repositories/test_workspace/test_repo/issues", params={"pagelen": 10}
        )

    @patch.object(BitbucketTools, "_make_request")
    def test_list_issues_max_count(self, mock_request, bitbucket_tools):
        """Test list_issues respects maximum count of 50."""
        mock_response = {"values": []}
        mock_request.return_value = mock_response

        bitbucket_tools.list_issues(count=100)

        # Should be limited to 50
        mock_request.assert_called_once_with(
            "GET", "/repositories/test_workspace/test_repo/issues", params={"pagelen": 50}
        )

    def test_base_url_construction_with_protocol(self, mock_env_vars):
        """Test base URL construction when server_url already has protocol."""
        tools = BitbucketTools(
            workspace="test_workspace", repo_slug="test_repo", server_url="https://custom.bitbucket.com"
        )

        assert tools.base_url == "https://custom.bitbucket.com/2.0"

    def test_base_url_construction_without_protocol(self, mock_env_vars):
        """Test base URL construction when server_url doesn't have protocol."""
        tools = BitbucketTools(workspace="test_workspace", repo_slug="test_repo", server_url="custom.bitbucket.com")

        assert tools.base_url == "https://custom.bitbucket.com/2.0"

    def test_tools_registration(self, bitbucket_tools):
        """Test that all expected tools are registered."""
        # Check that the tools list contains the expected methods
        assert hasattr(bitbucket_tools, "list_repositories")
        assert hasattr(bitbucket_tools, "get_repository_details")
        assert hasattr(bitbucket_tools, "create_repository")
        assert hasattr(bitbucket_tools, "list_repository_commits")
        assert hasattr(bitbucket_tools, "list_all_pull_requests")
        assert hasattr(bitbucket_tools, "get_pull_request_details")
        assert hasattr(bitbucket_tools, "get_pull_request_changes")
        assert hasattr(bitbucket_tools, "list_issues")

    @patch.object(BitbucketTools, "_make_request")
    def test_error_handling_returns_json_error(self, mock_request, bitbucket_tools):
        """Test that errors are properly formatted as JSON."""
        mock_request.side_effect = Exception("Test error")

        with patch("agno.tools.bitbucket.logger.error"):
            result = bitbucket_tools.list_repositories()

            result_data = json.loads(result)
            assert "error" in result_data
            assert "Test error" in result_data["error"]

    def test_env_var_fallbacks(self):
        """Test environment variable fallbacks work correctly."""
        with patch.dict(
            os.environ,
            {"BITBUCKET_USERNAME": "env_user", "BITBUCKET_PASSWORD": "env_password", "BITBUCKET_TOKEN": "env_token"},
        ):
            tools = BitbucketTools(workspace="test_workspace", repo_slug="test_repo")

            assert tools.username == "env_user"
            assert tools.password == "env_password"
            assert tools.token == "env_token"
            assert tools.auth_password == "env_token"  # Token takes priority
