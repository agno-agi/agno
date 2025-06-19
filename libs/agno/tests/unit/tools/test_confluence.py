"""Unit tests for ConfluenceTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest
from atlassian import Confluence

from agno.tools.confluence import ConfluenceTools


@pytest.fixture
def mock_confluence():
    """Create a mock Confluence client."""
    with patch("agno.tools.confluence.Confluence") as mock_confluence_class:
        mock_client = MagicMock(spec=Confluence)
        mock_confluence_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def confluence_tools(mock_confluence):
    """Create ConfluenceTools instance with mocked dependencies."""
    with patch.dict(
        "os.environ",
        {
            "CONFLUENCE_URL": "https://example.atlassian.net",
            "CONFLUENCE_USERNAME": "test_user",
            "CONFLUENCE_API_KEY": "test_api_key",
        },
    ):
        tools = ConfluenceTools()
        tools.confluence = mock_confluence
        return tools


# Initialization Tests
def test_init_with_environment_variables():
    """Test initialization with environment variables."""
    with patch.dict(
        "os.environ",
        {
            "CONFLUENCE_URL": "https://example.atlassian.net",
            "CONFLUENCE_USERNAME": "test_user",
            "CONFLUENCE_API_KEY": "test_api_key",
        },
    ):
        tools = ConfluenceTools()
        assert tools.url == "https://example.atlassian.net"
        assert tools.username == "test_user"
        assert tools.password == "test_api_key"


def test_init_with_constructor_parameters():
    """Test initialization with constructor parameters."""
    tools = ConfluenceTools(
        url="https://custom.atlassian.net",
        username="custom_user",
        api_key="custom_api_key",
    )
    assert tools.url == "https://custom.atlassian.net"
    assert tools.username == "custom_user"
    assert tools.password == "custom_api_key"


def test_init_with_missing_credentials():
    """Test initialization with missing credentials."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            ConfluenceTools()


# Space Tests
def test_get_all_space_detail(confluence_tools, mock_confluence):
    """Test retrieving all space details."""
    mock_spaces = {
        "results": [
            {"key": "SPACE1", "name": "Space One", "type": "global"},
            {"key": "SPACE2", "name": "Space Two", "type": "personal"},
        ]
    }
    mock_confluence.get_all_spaces.return_value = mock_spaces

    result = confluence_tools.get_all_space_detail()
    assert result == str(mock_spaces["results"])
    mock_confluence.get_all_spaces.assert_called_once()


def test_get_space_key_existing(confluence_tools, mock_confluence):
    """Test getting space key for an existing space."""
    mock_spaces = {
        "results": [
            {"key": "SPACE1", "name": "Space One", "type": "global"},
            {"key": "SPACE2", "name": "Space Two", "type": "personal"},
        ]
    }
    mock_confluence.get_all_spaces.return_value = mock_spaces

    result = confluence_tools.get_space_key("Space One")
    assert result == "SPACE1"
    mock_confluence.get_all_spaces.assert_called_once()


def test_get_space_key_not_found(confluence_tools, mock_confluence):
    """Test getting space key for a non-existent space."""
    mock_spaces = {
        "results": [
            {"key": "SPACE1", "name": "Space One", "type": "global"},
            {"key": "SPACE2", "name": "Space Two", "type": "personal"},
        ]
    }
    mock_confluence.get_all_spaces.return_value = mock_spaces

    result = confluence_tools.get_space_key("Non-existent Space")
    assert result == "No space found"
    mock_confluence.get_all_spaces.assert_called_once()


# Page Tests
def test_get_page_content_success(confluence_tools, mock_confluence):
    """Test retrieving page content successfully."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_page = {
            "id": "12345",
            "title": "Test Page",
            "body": {"storage": {"value": "<p>Test content</p>"}},
        }
        mock_confluence.get_page_by_title.return_value = mock_page

        result = confluence_tools.get_page_content("Space One", "Test Page")
        assert json.loads(result) == mock_page
        mock_confluence.get_page_by_title.assert_called_once_with("SPACE1", "Test Page", expand="body.storage")


def test_get_page_content_not_found(confluence_tools, mock_confluence):
    """Test retrieving non-existent page content."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_confluence.get_page_by_title.return_value = None

        result = confluence_tools.get_page_content("Space One", "Non-existent Page")
        assert json.loads(result) == {"error": "Page 'Non-existent Page' not found in space 'Space One'"}
        mock_confluence.get_page_by_title.assert_called_once_with("SPACE1", "Non-existent Page", expand="body.storage")


def test_get_page_content_error(confluence_tools, mock_confluence):
    """Test error handling when retrieving page content."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_confluence.get_page_by_title.side_effect = Exception("API Error")

        result = confluence_tools.get_page_content("Space One", "Test Page")
        assert json.loads(result) == {"error": "API Error"}
        mock_confluence.get_page_by_title.assert_called_once_with("SPACE1", "Test Page", expand="body.storage")


def test_get_all_page_from_space(confluence_tools, mock_confluence):
    """Test retrieving all pages from a space."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_pages = [
            {"id": "12345", "title": "Page One"},
            {"id": "67890", "title": "Page Two"},
        ]
        mock_confluence.get_all_pages_from_space.return_value = mock_pages

        result = confluence_tools.get_all_page_from_space("Space One")
        expected_result = str([{"id": "12345", "title": "Page One"}, {"id": "67890", "title": "Page Two"}])
        assert result == expected_result
        mock_confluence.get_all_pages_from_space.assert_called_once_with(
            "SPACE1", status=None, expand=None, content_type="page"
        )


def test_create_page_success(confluence_tools, mock_confluence):
    """Test creating a page successfully."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_page = {"id": "12345", "title": "New Page"}
        mock_confluence.create_page.return_value = mock_page

        result = confluence_tools.create_page("Space One", "New Page", "<p>Content</p>")
        assert json.loads(result) == {"id": "12345", "title": "New Page"}
        mock_confluence.create_page.assert_called_once_with("SPACE1", "New Page", "<p>Content</p>", parent_id=None)


def test_create_page_with_parent(confluence_tools, mock_confluence):
    """Test creating a page with a parent page."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_page = {"id": "12345", "title": "Child Page"}
        mock_confluence.create_page.return_value = mock_page

        result = confluence_tools.create_page("Space One", "Child Page", "<p>Content</p>", parent_id="67890")
        assert json.loads(result) == {"id": "12345", "title": "Child Page"}
        mock_confluence.create_page.assert_called_once_with("SPACE1", "Child Page", "<p>Content</p>", parent_id="67890")


def test_create_page_error(confluence_tools, mock_confluence):
    """Test error handling when creating a page."""
    # Mock the get_space_key method
    with patch.object(confluence_tools, "get_space_key", return_value="SPACE1"):
        mock_confluence.create_page.side_effect = Exception("API Error")

        result = confluence_tools.create_page("Space One", "New Page", "<p>Content</p>")
        assert json.loads(result) == {"error": "API Error"}
        mock_confluence.create_page.assert_called_once_with("SPACE1", "New Page", "<p>Content</p>", parent_id=None)


def test_update_page_success(confluence_tools, mock_confluence):
    """Test updating a page successfully."""
    mock_page = {"id": "12345", "title": "Updated Page"}
    mock_confluence.update_page.return_value = mock_page

    result = confluence_tools.update_page("12345", "Updated Page", "<p>Updated content</p>")
    assert json.loads(result) == {"status": "success", "id": "12345"}
    mock_confluence.update_page.assert_called_once_with("12345", "Updated Page", "<p>Updated content</p>")


def test_update_page_error(confluence_tools, mock_confluence):
    """Test error handling when updating a page."""
    mock_confluence.update_page.side_effect = Exception("API Error")

    result = confluence_tools.update_page("12345", "Updated Page", "<p>Updated content</p>")
    assert json.loads(result) == {"error": "API Error"}
    mock_confluence.update_page.assert_called_once_with("12345", "Updated Page", "<p>Updated content</p>")
