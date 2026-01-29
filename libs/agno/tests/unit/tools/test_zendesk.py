"""Unit tests for ZendeskTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.zendesk import ZendeskTools


@pytest.fixture
def mock_requests():
    """Create a mock requests module."""
    with patch("agno.tools.zendesk.requests") as mock_req:
        yield mock_req


@pytest.fixture
def zendesk_tools(mock_requests):
    """Create ZendeskTools instance with mocked dependencies."""
    with patch.dict(
        "os.environ",
        {
            "ZENDESK_USERNAME": "test@example.com/token",
            "ZENDESK_PASSWORD": "test_api_token",
            "ZENDESK_COMPANY_NAME": "testcompany",
        },
    ):
        tools = ZendeskTools(all=True)
        return tools


# Initialization Tests
def test_init_with_environment_variables():
    """Test initialization with environment variables."""
    with patch.dict(
        "os.environ",
        {
            "ZENDESK_USERNAME": "test@example.com/token",
            "ZENDESK_PASSWORD": "test_api_token",
            "ZENDESK_COMPANY_NAME": "testcompany",
        },
    ):
        tools = ZendeskTools()
        assert tools.username == "test@example.com/token"
        assert tools.password == "test_api_token"
        assert tools.company_name == "testcompany"


def test_init_with_direct_parameters():
    """Test initialization with direct parameters."""
    tools = ZendeskTools(
        username="direct@example.com",
        password="direct_token",
        company_name="directcompany",
    )
    assert tools.username == "direct@example.com"
    assert tools.password == "direct_token"
    assert tools.company_name == "directcompany"


def test_init_with_missing_credentials():
    """Test initialization with missing credentials raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="Zendesk credentials required"):
            ZendeskTools()


def test_init_with_partial_credentials():
    """Test initialization with partial credentials raises ValueError."""
    with patch.dict(
        "os.environ",
        {"ZENDESK_USERNAME": "test@example.com"},
        clear=True,
    ):
        with pytest.raises(ValueError, match="Zendesk credentials required"):
            ZendeskTools()


# Helper Method Tests
def test_base_url(zendesk_tools):
    """Test base URL generation."""
    assert zendesk_tools._base_url() == "https://testcompany.zendesk.com/api/v2"


def test_get_auth(zendesk_tools):
    """Test auth tuple generation."""
    auth = zendesk_tools._get_auth()
    assert auth == ("test@example.com/token", "test_api_token")


# _request Helper Tests
def test_request_success(zendesk_tools, mock_requests):
    """Test successful API request."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": "test"}
    mock_requests.request.return_value = mock_response

    result = zendesk_tools._request("GET", "test/endpoint.json")

    assert result == {"data": "test"}
    mock_requests.request.assert_called_once_with(
        "GET",
        "https://testcompany.zendesk.com/api/v2/test/endpoint.json",
        auth=("test@example.com/token", "test_api_token"),
        params=None,
        json=None,
    )


def test_request_with_params(zendesk_tools, mock_requests):
    """Test API request with query parameters."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_requests.request.return_value = mock_response

    result = zendesk_tools._request("GET", "search.json", params={"query": "test"})

    assert result == {"results": []}
    mock_requests.request.assert_called_once_with(
        "GET",
        "https://testcompany.zendesk.com/api/v2/search.json",
        auth=("test@example.com/token", "test_api_token"),
        params={"query": "test"},
        json=None,
    )


def test_request_with_json_data(zendesk_tools, mock_requests):
    """Test API request with JSON body."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ticket": {"id": 123}}
    mock_requests.request.return_value = mock_response

    result = zendesk_tools._request("PUT", "tickets/123.json", json_data={"ticket": {"status": "solved"}})

    assert result == {"ticket": {"id": 123}}
    mock_requests.request.assert_called_once_with(
        "PUT",
        "https://testcompany.zendesk.com/api/v2/tickets/123.json",
        auth=("test@example.com/token", "test_api_token"),
        params=None,
        json={"ticket": {"status": "solved"}},
    )


def test_request_error(zendesk_tools, mock_requests):
    """Test API request error handling."""
    import requests

    mock_requests.RequestException = requests.RequestException
    mock_requests.request.side_effect = requests.RequestException("Connection failed")

    result = zendesk_tools._request("GET", "test.json")

    assert "error" in result
    assert "Connection failed" in result["error"]


# search_zendesk Tests
def test_search_zendesk_success(zendesk_tools, mock_requests):
    """Test searching Zendesk Help Center articles."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Article 1", "body": "<p>Article 1 content</p>", "html_url": "https://test.zendesk.com/1"},
            {"title": "Article 2", "body": "<p>Article 2 content</p>", "html_url": "https://test.zendesk.com/2"},
        ]
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.search_zendesk("password reset")
    parsed = json.loads(result)

    assert len(parsed) == 2
    assert parsed[0]["title"] == "Article 1"
    assert parsed[0]["body"] == "<p>Article 1 content</p>"
    assert parsed[0]["url"] == "https://test.zendesk.com/1"


def test_search_zendesk_no_results(zendesk_tools, mock_requests):
    """Test searching with no results."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.search_zendesk("nonexistent topic")
    parsed = json.loads(result)

    assert parsed == []


def test_search_zendesk_error(zendesk_tools, mock_requests):
    """Test search error handling."""
    import requests

    mock_requests.RequestException = requests.RequestException
    mock_requests.request.side_effect = requests.RequestException("API Error")

    result = zendesk_tools.search_zendesk("test")
    parsed = json.loads(result)

    assert "error" in parsed


# get_tickets Tests
def test_get_tickets_success(zendesk_tools, mock_requests):
    """Test listing tickets."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "tickets": [
            {
                "id": 1,
                "subject": "Test ticket",
                "status": "open",
                "priority": "high",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "requester_id": 100,
                "assignee_id": 200,
                "tags": ["billing"],
            }
        ],
        "next_page": None,
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.get_tickets()
    parsed = json.loads(result)

    assert parsed["count"] == 1
    assert parsed["tickets"][0]["id"] == 1
    assert parsed["tickets"][0]["subject"] == "Test ticket"
    assert parsed["has_more"] is False


def test_get_tickets_with_status_filter(zendesk_tools, mock_requests):
    """Test listing tickets with status filter."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "tickets": [
            {"id": 1, "status": "open", "subject": "Open ticket"},
            {"id": 2, "status": "solved", "subject": "Solved ticket"},
        ],
        "next_page": None,
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.get_tickets(status="open")
    parsed = json.loads(result)

    assert parsed["count"] == 1
    assert parsed["tickets"][0]["status"] == "open"


def test_get_tickets_pagination(zendesk_tools, mock_requests):
    """Test ticket pagination."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "tickets": [],
        "next_page": "https://testcompany.zendesk.com/api/v2/tickets.json?page=2",
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.get_tickets(page=1, per_page=25)
    parsed = json.loads(result)

    assert parsed["has_more"] is True
    assert parsed["page"] == 1


# get_ticket Tests
def test_get_ticket_success(zendesk_tools, mock_requests):
    """Test getting a single ticket."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ticket": {
            "id": 123,
            "subject": "Test ticket",
            "description": "Ticket description",
            "status": "open",
            "priority": "high",
            "type": "incident",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "requester_id": 100,
            "assignee_id": 200,
            "tags": ["urgent"],
            "via": {"channel": "email"},
            "custom_fields": [{"id": 1, "value": "test"}],
        }
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.get_ticket(123)
    parsed = json.loads(result)

    assert parsed["id"] == 123
    assert parsed["subject"] == "Test ticket"
    assert parsed["description"] == "Ticket description"
    assert parsed["via"] == "email"


def test_get_ticket_error(zendesk_tools, mock_requests):
    """Test getting a non-existent ticket."""
    import requests

    mock_requests.RequestException = requests.RequestException
    mock_requests.request.side_effect = requests.RequestException("404 Not Found")

    result = zendesk_tools.get_ticket(99999)
    parsed = json.loads(result)

    assert "error" in parsed


# get_ticket_comments Tests
def test_get_ticket_comments_success(zendesk_tools, mock_requests):
    """Test getting ticket comments with attachments."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "comments": [
            {
                "id": 1,
                "author_id": 100,
                "body": "First comment with **markdown**",
                "plain_body": "First comment with markdown",
                "created_at": "2024-01-01T00:00:00Z",
                "public": True,
                "attachments": [
                    {"file_name": "screenshot.png", "content_url": "https://example.com/screenshot.png", "size": 12345}
                ],
            },
            {
                "id": 2,
                "author_id": 200,
                "body": "Second comment",
                "plain_body": "Second comment",
                "created_at": "2024-01-02T00:00:00Z",
                "public": False,
                "attachments": [],
            },
        ]
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.get_ticket_comments(123)
    parsed = json.loads(result)

    assert parsed["ticket_id"] == 123
    assert parsed["count"] == 2
    assert parsed["comments"][0]["body"] == "First comment with markdown"
    assert parsed["comments"][1]["body"] == "Second comment"
    assert parsed["comments"][1]["public"] is False
    assert len(parsed["comments"][0]["attachments"]) == 1
    assert parsed["comments"][0]["attachments"][0]["filename"] == "screenshot.png"
    assert parsed["comments"][1]["attachments"] == []


# create_ticket_comment Tests
def test_create_ticket_comment_success(zendesk_tools, mock_requests):
    """Test creating a ticket comment."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ticket": {
            "id": 123,
            "updated_at": "2024-01-02T00:00:00Z",
        }
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.create_ticket_comment(123, "Test comment", public=True)
    parsed = json.loads(result)

    assert parsed["success"] is True
    assert parsed["ticket_id"] == 123
    assert parsed["message"] == "Comment added successfully"

    call_args = mock_requests.request.call_args
    assert call_args[1]["json"] == {"ticket": {"comment": {"body": "Test comment", "public": True}}}


def test_create_ticket_comment_internal_note(zendesk_tools, mock_requests):
    """Test creating an internal note (private comment)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ticket": {"id": 123, "updated_at": "2024-01-02T00:00:00Z"}}
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.create_ticket_comment(123, "Internal note", public=False)
    parsed = json.loads(result)

    assert parsed["success"] is True
    call_args = mock_requests.request.call_args
    assert call_args[1]["json"]["ticket"]["comment"]["public"] is False


# update_ticket Tests
def test_update_ticket_success(zendesk_tools, mock_requests):
    """Test updating a ticket."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ticket": {
            "id": 123,
            "status": "solved",
            "priority": "high",
            "assignee_id": 300,
            "tags": ["resolved"],
            "updated_at": "2024-01-02T00:00:00Z",
        }
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.update_ticket(123, status="solved", priority="high", assignee_id=300, tags=["resolved"])
    parsed = json.loads(result)

    assert parsed["success"] is True
    assert parsed["ticket_id"] == 123
    assert parsed["status"] == "solved"


def test_update_ticket_partial_update(zendesk_tools, mock_requests):
    """Test updating only some ticket fields."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ticket": {
            "id": 123,
            "status": "pending",
            "priority": None,
            "assignee_id": None,
            "tags": [],
            "updated_at": "2024-01-02T00:00:00Z",
        }
    }
    mock_requests.request.return_value = mock_response

    result = zendesk_tools.update_ticket(123, status="pending")
    parsed = json.loads(result)

    assert parsed["success"] is True
    call_args = mock_requests.request.call_args
    assert call_args[1]["json"] == {"ticket": {"status": "pending"}}


def test_update_ticket_no_fields(zendesk_tools, mock_requests):
    """Test updating with no fields returns error."""
    result = zendesk_tools.update_ticket(123)
    parsed = json.loads(result)

    assert parsed["success"] is False
    assert "No fields to update" in parsed["message"]
    mock_requests.request.assert_not_called()


# Tool Registration Tests
def test_default_tools_registered():
    """Test that only search_zendesk is registered by default."""
    with patch.dict(
        "os.environ",
        {
            "ZENDESK_USERNAME": "test@example.com",
            "ZENDESK_PASSWORD": "token",
            "ZENDESK_COMPANY_NAME": "company",
        },
    ):
        tools = ZendeskTools()
        tool_names = [t.__name__ for t in tools.tools]
        assert tool_names == ["search_zendesk"]


def test_all_tools_registered():
    """Test that all tools are registered when all=True."""
    with patch.dict(
        "os.environ",
        {
            "ZENDESK_USERNAME": "test@example.com",
            "ZENDESK_PASSWORD": "token",
            "ZENDESK_COMPANY_NAME": "company",
        },
    ):
        tools = ZendeskTools(all=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "search_zendesk" in tool_names
        assert "get_tickets" in tool_names
        assert "get_ticket" in tool_names
        assert "get_ticket_comments" in tool_names
        assert "create_ticket_comment" in tool_names
        assert "update_ticket" in tool_names


def test_selective_tools_registered():
    """Test selective tool registration."""
    with patch.dict(
        "os.environ",
        {
            "ZENDESK_USERNAME": "test@example.com",
            "ZENDESK_PASSWORD": "token",
            "ZENDESK_COMPANY_NAME": "company",
        },
    ):
        tools = ZendeskTools(
            enable_search_zendesk=False,
            enable_get_ticket=True,
            enable_update_ticket=True,
        )
        tool_names = [t.__name__ for t in tools.tools]
        assert "search_zendesk" not in tool_names
        assert "get_ticket" in tool_names
        assert "update_ticket" in tool_names
        assert "get_tickets" not in tool_names
