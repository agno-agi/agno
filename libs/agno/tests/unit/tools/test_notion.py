import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.notion import NotionTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure NOTION_API_KEY and NOTION_DATABASE_ID are unset unless explicitly needed."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)


@pytest.fixture
def notion_tools():
    """NotionTools with a known API key and database ID for testing."""
    return NotionTools(api_key="secret_test_key_123", database_id="28fee27f-d912-8039-b3f8-f47cb7ade7cb")


@pytest.fixture
def mock_create_page_response():
    """Mock a successful Notion create page response."""
    return {
        "id": "page-123",
        "url": "https://notion.so/page-123",
        "properties": {"Name": {"title": [{"text": {"content": "Test Page"}}]}, "Tag": {"select": {"name": "travel"}}},
    }


@pytest.fixture
def mock_update_page_response():
    """Mock a successful Notion update page response."""
    return {"id": "page-123", "object": "block", "type": "paragraph"}


@pytest.fixture
def mock_search_pages_response():
    """Mock a successful Notion search pages response."""
    return {
        "results": [
            {
                "id": "page-123",
                "url": "https://notion.so/page-123",
                "properties": {
                    "Name": {"title": [{"text": {"content": "Travel Collection"}}]},
                    "Tag": {"select": {"name": "travel"}},
                },
            },
            {
                "id": "page-456",
                "url": "https://notion.so/page-456",
                "properties": {
                    "Name": {"title": [{"text": {"content": "Another Travel Page"}}]},
                    "Tag": {"select": {"name": "travel"}},
                },
            },
        ]
    }


@pytest.fixture
def mock_empty_search_response():
    """Mock an empty search response (no pages found)."""
    return {"results": []}


# Initialization Tests
def test_init_with_api_key_and_database_id():
    """Test initialization with API key and database ID."""
    tools = NotionTools(api_key="secret_key", database_id="db-123")
    assert tools.api_key == "secret_key"
    assert tools.database_id == "db-123"


def test_init_with_env_vars(monkeypatch):
    """Test initialization using environment variables."""
    monkeypatch.setenv("NOTION_API_KEY", "env_key")
    monkeypatch.setenv("NOTION_DATABASE_ID", "env_db_id")

    # When called without params, should use env vars
    tools = NotionTools()
    assert tools.api_key == "env_key"
    assert tools.database_id == "env_db_id"


def test_init_without_api_key_raises_error(monkeypatch):
    """Test initialization without API key raises ValueError."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.setenv("NOTION_DATABASE_ID", "db-123")

    with pytest.raises(ValueError, match="Notion API key is required"):
        NotionTools()


def test_init_without_database_id_raises_error(monkeypatch):
    """Test initialization without database ID raises ValueError."""
    monkeypatch.setenv("NOTION_API_KEY", "secret_key")
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)

    with pytest.raises(ValueError, match="Notion database ID is required"):
        NotionTools()


def test_init_with_tool_selection():
    """Test initialization with selective tool enabling."""
    tools = NotionTools(
        api_key="test_key",
        database_id="test_db",
        enable_create_page=True,
        enable_update_page=False,
        enable_search_pages=False,
    )
    # Should only have create_page in functions
    assert "create_page" in tools.functions
    assert "update_page" not in tools.functions
    assert "search_pages" not in tools.functions


def test_init_with_all_flag():
    """Test initialization with all=True enables all tools."""
    tools = NotionTools(api_key="test_key", database_id="test_db", all=True)
    assert "create_page" in tools.functions
    assert "update_page" in tools.functions
    assert "search_pages" in tools.functions


# Create Page Tests
def test_create_page_success(notion_tools, mock_create_page_response):
    """Test successful page creation."""
    with patch.object(notion_tools.client.pages, "create", return_value=mock_create_page_response):
        result = notion_tools.create_page(title="Test Page", tag="travel", content="This is test content")

        result_json = json.loads(result)
        assert result_json["success"] is True
        assert result_json["page_id"] == "page-123"
        assert result_json["url"] == "https://notion.so/page-123"
        assert result_json["title"] == "Test Page"
        assert result_json["tag"] == "travel"


def test_create_page_with_empty_title(notion_tools, mock_create_page_response):
    """Test page creation with empty title still works."""
    with patch.object(notion_tools.client.pages, "create", return_value=mock_create_page_response):
        result = notion_tools.create_page(title="", tag="tech", content="Some content")

        result_json = json.loads(result)
        assert result_json["success"] is True


def test_create_page_exception_handling(notion_tools):
    """Test error handling when page creation fails."""
    with patch.object(notion_tools.client.pages, "create", side_effect=Exception("API Error")):
        result = notion_tools.create_page(title="Test", tag="tech", content="Content")

        result_json = json.loads(result)
        assert result_json["success"] is False
        assert "error" in result_json
        assert "API Error" in result_json["error"]


def test_create_page_with_special_characters(notion_tools, mock_create_page_response):
    """Test page creation with special characters in content."""
    with patch.object(notion_tools.client.pages, "create", return_value=mock_create_page_response):
        result = notion_tools.create_page(
            title="Test & Special < Characters >",
            tag="general-blogs",
            content="Content with 'quotes' and \"double quotes\" and new\nlines",
        )

        result_json = json.loads(result)
        assert result_json["success"] is True


# Update Page Tests
def test_update_page_success(notion_tools, mock_update_page_response):
    """Test successful page update."""
    with patch.object(notion_tools.client.blocks.children, "append", return_value=mock_update_page_response):
        result = notion_tools.update_page(page_id="page-123", content="Updated content")

        result_json = json.loads(result)
        assert result_json["success"] is True
        assert result_json["page_id"] == "page-123"
        assert "Content added successfully" in result_json["message"]


def test_update_page_with_empty_content(notion_tools, mock_update_page_response):
    """Test updating page with empty content."""
    with patch.object(notion_tools.client.blocks.children, "append", return_value=mock_update_page_response):
        result = notion_tools.update_page(page_id="page-123", content="")

        result_json = json.loads(result)
        assert result_json["success"] is True


def test_update_page_exception_handling(notion_tools):
    """Test error handling when page update fails."""
    with patch.object(notion_tools.client.blocks.children, "append", side_effect=Exception("Update failed")):
        result = notion_tools.update_page(page_id="invalid-id", content="Some content")

        result_json = json.loads(result)
        assert result_json["success"] is False
        assert "error" in result_json
        assert "Update failed" in result_json["error"]


def test_update_page_with_long_content(notion_tools, mock_update_page_response):
    """Test updating page with very long content."""
    long_content = "A" * 10000  # 10,000 characters
    with patch.object(notion_tools.client.blocks.children, "append", return_value=mock_update_page_response):
        result = notion_tools.update_page(page_id="page-123", content=long_content)

        result_json = json.loads(result)
        assert result_json["success"] is True


# Search Pages Tests
def test_search_pages_success(notion_tools, mock_search_pages_response):
    """Test successful search for pages by tag."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_search_pages_response

    with patch("httpx.post", return_value=mock_response):
        result = notion_tools.search_pages(tag="travel")

        result_json = json.loads(result)
        assert result_json["success"] is True
        assert result_json["count"] == 2
        assert len(result_json["pages"]) == 2
        assert result_json["pages"][0]["tag"] == "travel"
        assert result_json["pages"][0]["title"] == "Travel Collection"


def test_search_pages_empty_results(notion_tools, mock_empty_search_response):
    """Test search when no pages match the tag."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_empty_search_response

    with patch("httpx.post", return_value=mock_response):
        result = notion_tools.search_pages(tag="nonexistent")

        result_json = json.loads(result)
        assert result_json["success"] is True
        assert result_json["count"] == 0
        assert len(result_json["pages"]) == 0


def test_search_pages_api_error(notion_tools):
    """Test search when API returns an error."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.text = "Invalid database ID"

    with patch("httpx.post", return_value=mock_response):
        result = notion_tools.search_pages(tag="tech")

        result_json = json.loads(result)
        assert result_json["success"] is False
        assert "error" in result_json
        assert "400" in result_json["error"]


def test_search_pages_network_exception(notion_tools):
    """Test search when network request fails."""
    with patch("httpx.post", side_effect=Exception("Network timeout")):
        result = notion_tools.search_pages(tag="fashion")

        result_json = json.loads(result)
        assert result_json["success"] is False
        assert "error" in result_json
        assert "Network timeout" in result_json["error"]


def test_search_pages_with_missing_properties(notion_tools):
    """Test search with pages that have missing properties."""
    mock_response_data = {
        "results": [
            {
                "id": "page-789",
                "url": "https://notion.so/page-789",
                "properties": {
                    "Name": {"title": []},  # Empty title
                    "Tag": {"select": None},  # Missing tag
                },
            }
        ]
    }

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_response_data

    with patch("httpx.post", return_value=mock_response):
        result = notion_tools.search_pages(tag="tech")

        result_json = json.loads(result)
        assert result_json["success"] is True
        assert result_json["count"] == 1
        assert result_json["pages"][0]["title"] == "Untitled"
        assert result_json["pages"][0]["tag"] is None


def test_search_pages_with_various_tags(notion_tools, mock_search_pages_response):
    """Test search with different tag values."""
    tags_to_test = ["travel", "tech", "general-blogs", "fashion", "documents"]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_search_pages_response

    for tag in tags_to_test:
        with patch("httpx.post", return_value=mock_response):
            result = notion_tools.search_pages(tag=tag)
            result_json = json.loads(result)
            assert result_json["success"] is True


# Edge Cases and Integration Tests
def test_notion_tools_with_all_methods(
    notion_tools, mock_create_page_response, mock_update_page_response, mock_search_pages_response
):
    """Test all methods work together in sequence."""
    # Create a page
    with patch.object(notion_tools.client.pages, "create", return_value=mock_create_page_response):
        create_result = notion_tools.create_page("Test", "travel", "Content")
        create_json = json.loads(create_result)
        assert create_json["success"] is True
        page_id = create_json["page_id"]

    # Update the page
    with patch.object(notion_tools.client.blocks.children, "append", return_value=mock_update_page_response):
        update_result = notion_tools.update_page(page_id, "More content")
        update_json = json.loads(update_result)
        assert update_json["success"] is True

    # Search for pages
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_search_pages_response

    with patch("httpx.post", return_value=mock_response):
        search_result = notion_tools.search_pages("travel")
        search_json = json.loads(search_result)
        assert search_json["success"] is True


def test_database_id_formatting():
    """Test that database IDs are stored as-is (no formatting applied)."""
    # Test with UUID format (with hyphens)
    tools1 = NotionTools(api_key="test_key", database_id="28fee27f-d912-8039-b3f8-f47cb7ade7cb")
    assert tools1.database_id == "28fee27f-d912-8039-b3f8-f47cb7ade7cb"

    # Test without hyphens
    tools2 = NotionTools(api_key="test_key", database_id="28fee27fd9128039b3f8f47cb7ade7cb")
    assert tools2.database_id == "28fee27fd9128039b3f8f47cb7ade7cb"


def test_json_serialization_of_responses(notion_tools, mock_create_page_response):
    """Test that all responses are valid JSON."""
    with patch.object(notion_tools.client.pages, "create", return_value=mock_create_page_response):
        result = notion_tools.create_page("Test", "tech", "Content")

        # Should not raise JSONDecodeError
        result_json = json.loads(result)
        assert isinstance(result_json, dict)

        # Should be able to serialize back to JSON
        re_serialized = json.dumps(result_json)
        assert isinstance(re_serialized, str)


def test_toolkit_name():
    """Test that the toolkit has the correct name."""
    tools = NotionTools(api_key="test", database_id="test")
    assert tools.name == "notion_tools"


def test_all_functions_registered():
    """Test that all expected functions are registered when all=True."""
    tools = NotionTools(api_key="test", database_id="test", all=True)

    expected_functions = ["create_page", "update_page", "search_pages"]
    for func_name in expected_functions:
        assert func_name in tools.functions
        assert callable(tools.functions[func_name].entrypoint)
