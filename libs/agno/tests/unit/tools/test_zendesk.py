"""Unit tests for ZendeskTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.zendesk import ZendeskTools

# Mock API responses matching Zendesk API format
MOCK_ARTICLES_RESPONSE = {
    "results": [
        {"body": "<p>Article content with <strong>HTML</strong> tags</p>"},
        {"body": "<div>Another article</div>"},
    ]
}

MOCK_TICKETS_RESPONSE = {
    "tickets": [
        {
            "id": 123,
            "subject": "Test ticket",
            "status": "open",
            "priority": "normal",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:00:00Z",
            "requester_id": 456,
            "assignee_id": 789,
            "tags": ["test", "support"],
        },
        {
            "id": 124,
            "subject": "Another ticket",
            "status": "pending",
            "priority": "high",
            "created_at": "2024-01-16T10:00:00Z",
            "updated_at": "2024-01-16T10:00:00Z",
            "requester_id": 457,
            "assignee_id": 790,
            "tags": ["urgent"],
        },
    ],
    "next_page": None,
}

MOCK_TICKET_RESPONSE = {
    "ticket": {
        "id": 123,
        "subject": "Test ticket",
        "description": "This is a test ticket description",
        "status": "open",
        "priority": "normal",
        "type": "question",
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z",
        "requester_id": 456,
        "assignee_id": 789,
        "tags": ["test"],
        "via": {"channel": "email"},
        "custom_fields": [{"id": 1, "value": "custom"}],
    }
}

MOCK_COMMENTS_RESPONSE = {
    "comments": [
        {
            "id": 1,
            "author_id": 456,
            "body": "Original message",
            "created_at": "2024-01-15T10:00:00Z",
            "public": True,
            "type": "Comment",
        },
        {
            "id": 2,
            "author_id": 789,
            "body": "Agent response",
            "created_at": "2024-01-15T11:00:00Z",
            "public": True,
            "type": "Comment",
        },
    ]
}


@pytest.fixture
def mock_response():
    """Create a mock requests.Response object."""
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def zendesk_tools():
    """Create ZendeskTools instance with test credentials."""
    return ZendeskTools(
        username="test@example.com",
        password="test_api_token",
        company_name="testcompany",
        all=True,
    )


@pytest.fixture
def zendesk_tools_default():
    """Create ZendeskTools with default settings (only search enabled)."""
    return ZendeskTools(
        username="test@example.com",
        password="test_api_token",
        company_name="testcompany",
    )


class TestZendeskToolsInitialization:
    """Test ZendeskTools initialization and tool registration."""

    def test_init_with_explicit_credentials(self):
        """Test initialization with explicit credentials."""
        tools = ZendeskTools(
            username="test@example.com",
            password="test_password",
            company_name="mycompany",
        )
        assert tools.username == "test@example.com"
        assert tools.password == "test_password"
        assert tools.company_name == "mycompany"

    def test_init_with_environment_variables(self):
        """Test initialization with environment variables."""
        with patch.dict(
            "os.environ",
            {
                "ZENDESK_USERNAME": "env_user@example.com",
                "ZENDESK_PASSWORD": "env_password",
                "ZENDESK_COMPANY_NAME": "envcompany",
            },
        ):
            tools = ZendeskTools()
            assert tools.username == "env_user@example.com"
            assert tools.password == "env_password"
            assert tools.company_name == "envcompany"

    def test_init_missing_credentials_logs_error(self):
        """Test that missing credentials logs an error."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("agno.tools.zendesk.logger.error") as mock_logger:
                ZendeskTools()
                mock_logger.assert_called_once()
                assert "Username, password, or company name not provided" in str(mock_logger.call_args)

    def test_init_with_all_flag_enables_all_tools(self):
        """Test that all=True enables all methods."""
        tools = ZendeskTools(
            username="test@example.com",
            password="test",
            company_name="test",
            all=True,
        )
        tool_names = list(tools.functions.keys())
        assert "search_zendesk" in tool_names
        assert "get_tickets" in tool_names
        assert "get_ticket" in tool_names
        assert "get_ticket_comments" in tool_names
        assert "create_ticket_comment" in tool_names
        assert "update_ticket" in tool_names

    def test_init_default_only_search_enabled(self):
        """Test that default init only enables search_zendesk."""
        tools = ZendeskTools(
            username="test@example.com",
            password="test",
            company_name="test",
        )
        tool_names = list(tools.functions.keys())
        assert "search_zendesk" in tool_names
        assert "get_tickets" not in tool_names
        assert "get_ticket" not in tool_names

    def test_init_with_individual_enable_flags(self):
        """Test enabling individual methods via flags."""
        tools = ZendeskTools(
            username="test@example.com",
            password="test",
            company_name="test",
            enable_search_zendesk=False,
            enable_get_tickets=True,
            enable_update_ticket=True,
        )
        tool_names = list(tools.functions.keys())
        assert "search_zendesk" not in tool_names
        assert "get_tickets" in tool_names
        assert "update_ticket" in tool_names
        assert "get_ticket" not in tool_names


class TestSearchZendesk:
    """Test search_zendesk method."""

    def test_search_zendesk_success(self, zendesk_tools, mock_response):
        """Test successful article search."""
        mock_response.json.return_value = MOCK_ARTICLES_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            result = zendesk_tools.search_zendesk("billing question")

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "help_center/articles/search.json" in call_args[0][0]
            assert "billing question" in call_args[0][0]

            articles = json.loads(result)
            assert len(articles) == 2
            assert "Article content with HTML tags" in articles[0]
            assert "<strong>" not in articles[0]

    def test_search_zendesk_empty_results(self, zendesk_tools, mock_response):
        """Test search with no results."""
        mock_response.json.return_value = {"results": []}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.search_zendesk("nonexistent topic")

            articles = json.loads(result)
            assert articles == []

    def test_search_zendesk_missing_credentials(self):
        """Test search with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools()
            result = tools.search_zendesk("test")
            assert "Username, password, or company name not provided" in result

    def test_search_zendesk_api_error(self, zendesk_tools):
        """Test search with API connection error."""
        import requests

        with patch(
            "agno.tools.zendesk.requests.get",
            side_effect=requests.RequestException("Network error"),
        ):
            with pytest.raises(ConnectionError, match="API request failed"):
                zendesk_tools.search_zendesk("test")


class TestGetTickets:
    """Test get_tickets method."""

    def test_get_tickets_success(self, zendesk_tools, mock_response):
        """Test successful ticket listing."""
        mock_response.json.return_value = MOCK_TICKETS_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            result = zendesk_tools.get_tickets()

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "tickets.json" in call_args[0][0]
            assert call_args[1]["params"]["page"] == 1
            assert call_args[1]["params"]["per_page"] == 25

            data = json.loads(result)
            assert data["count"] == 2
            assert data["page"] == 1
            assert data["has_more"] is False
            assert len(data["tickets"]) == 2
            assert data["tickets"][0]["id"] == 123

    def test_get_tickets_with_status_filter(self, zendesk_tools, mock_response):
        """Test ticket listing with status filter."""
        mock_response.json.return_value = MOCK_TICKETS_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.get_tickets(status="open")

            data = json.loads(result)
            assert data["count"] == 1
            assert data["tickets"][0]["status"] == "open"

    def test_get_tickets_with_pagination(self, zendesk_tools, mock_response):
        """Test ticket listing with pagination."""
        mock_response.json.return_value = {**MOCK_TICKETS_RESPONSE, "next_page": "https://..."}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            result = zendesk_tools.get_tickets(page=2, per_page=50)

            call_args = mock_get.call_args
            assert call_args[1]["params"]["page"] == 2
            assert call_args[1]["params"]["per_page"] == 50

            data = json.loads(result)
            assert data["has_more"] is True
            assert data["page"] == 2

    def test_get_tickets_per_page_max_100(self, zendesk_tools, mock_response):
        """Test that per_page is capped at 100."""
        mock_response.json.return_value = MOCK_TICKETS_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            zendesk_tools.get_tickets(per_page=200)

            call_args = mock_get.call_args
            assert call_args[1]["params"]["per_page"] == 100

    def test_get_tickets_missing_credentials(self):
        """Test get_tickets with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools(enable_get_tickets=True)
            result = tools.get_tickets()
            assert "Username, password, or company name not provided" in result

    def test_get_tickets_api_error(self, zendesk_tools):
        """Test get_tickets with API error."""
        import requests

        with patch(
            "agno.tools.zendesk.requests.get",
            side_effect=requests.RequestException("Connection refused"),
        ):
            with pytest.raises(ConnectionError, match="API request failed"):
                zendesk_tools.get_tickets()


class TestGetTicket:
    """Test get_ticket method."""

    def test_get_ticket_success(self, zendesk_tools, mock_response):
        """Test successful single ticket retrieval."""
        mock_response.json.return_value = MOCK_TICKET_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            result = zendesk_tools.get_ticket(123)

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "tickets/123.json" in call_args[0][0]

            data = json.loads(result)
            assert data["id"] == 123
            assert data["subject"] == "Test ticket"
            assert data["description"] == "This is a test ticket description"
            assert data["status"] == "open"
            assert data["via"] == "email"

    def test_get_ticket_missing_credentials(self):
        """Test get_ticket with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools(enable_get_ticket=True)
            result = tools.get_ticket(123)
            assert "Username, password, or company name not provided" in result

    def test_get_ticket_api_error(self, zendesk_tools):
        """Test get_ticket with API error."""
        import requests

        with patch(
            "agno.tools.zendesk.requests.get",
            side_effect=requests.RequestException("Not found"),
        ):
            with pytest.raises(ConnectionError, match="API request failed"):
                zendesk_tools.get_ticket(999)


class TestGetTicketComments:
    """Test get_ticket_comments method."""

    def test_get_ticket_comments_success(self, zendesk_tools, mock_response):
        """Test successful comment retrieval."""
        mock_response.json.return_value = MOCK_COMMENTS_RESPONSE

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            result = zendesk_tools.get_ticket_comments(123)

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "tickets/123/comments.json" in call_args[0][0]

            data = json.loads(result)
            assert data["ticket_id"] == 123
            assert data["count"] == 2
            assert len(data["comments"]) == 2
            assert data["comments"][0]["body"] == "Original message"
            assert data["comments"][0]["public"] is True

    def test_get_ticket_comments_empty(self, zendesk_tools, mock_response):
        """Test comment retrieval for ticket with no comments."""
        mock_response.json.return_value = {"comments": []}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.get_ticket_comments(123)

            data = json.loads(result)
            assert data["count"] == 0
            assert data["comments"] == []

    def test_get_ticket_comments_html_body_fallback(self, zendesk_tools, mock_response):
        """Test that html_body is used when body is empty."""
        mock_response.json.return_value = {
            "comments": [
                {
                    "id": 1,
                    "author_id": 456,
                    "body": "",
                    "html_body": "<p>HTML body content</p>",
                    "created_at": "2024-01-15T10:00:00Z",
                    "public": True,
                    "type": "Comment",
                }
            ]
        }

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.get_ticket_comments(123)

            data = json.loads(result)
            assert data["comments"][0]["body"] == "HTML body content"
            assert "<p>" not in data["comments"][0]["body"]

    def test_get_ticket_comments_missing_credentials(self):
        """Test get_ticket_comments with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools(enable_get_ticket_comments=True)
            result = tools.get_ticket_comments(123)
            assert "Username, password, or company name not provided" in result


class TestCreateTicketComment:
    """Test create_ticket_comment method."""

    def test_create_ticket_comment_public(self, zendesk_tools, mock_response):
        """Test creating a public comment."""
        mock_response.json.return_value = {
            "ticket": {
                "id": 123,
                "status": "open",
                "updated_at": "2024-01-15T12:00:00Z",
            }
        }

        with patch("agno.tools.zendesk.requests.put", return_value=mock_response) as mock_put:
            result = zendesk_tools.create_ticket_comment(
                ticket_id=123,
                body="This is a public response",
                public=True,
            )

            mock_put.assert_called_once()
            call_args = mock_put.call_args
            assert "tickets/123.json" in call_args[0][0]

            payload = call_args[1]["json"]
            assert payload["ticket"]["comment"]["body"] == "This is a public response"
            assert payload["ticket"]["comment"]["public"] is True

            data = json.loads(result)
            assert data["success"] is True
            assert data["ticket_id"] == 123
            assert "Comment added" in data["message"]

    def test_create_ticket_comment_internal(self, zendesk_tools, mock_response):
        """Test creating an internal note (private comment)."""
        mock_response.json.return_value = {
            "ticket": {
                "id": 123,
                "status": "open",
                "updated_at": "2024-01-15T12:00:00Z",
            }
        }

        with patch("agno.tools.zendesk.requests.put", return_value=mock_response) as mock_put:
            result = zendesk_tools.create_ticket_comment(
                ticket_id=123,
                body="This is an internal note",
                public=False,
            )

            payload = mock_put.call_args[1]["json"]
            assert payload["ticket"]["comment"]["public"] is False

            data = json.loads(result)
            assert data["success"] is True

    def test_create_ticket_comment_missing_credentials(self):
        """Test create_ticket_comment with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools(enable_create_ticket_comment=True)
            result = tools.create_ticket_comment(123, "test")
            assert "Username, password, or company name not provided" in result

    def test_create_ticket_comment_api_error(self, zendesk_tools):
        """Test create_ticket_comment with API error."""
        import requests

        with patch(
            "agno.tools.zendesk.requests.put",
            side_effect=requests.RequestException("Server error"),
        ):
            with pytest.raises(ConnectionError, match="API request failed"):
                zendesk_tools.create_ticket_comment(123, "test comment")


class TestUpdateTicket:
    """Test update_ticket method."""

    def test_update_ticket_status(self, zendesk_tools, mock_response):
        """Test updating ticket status."""
        mock_response.json.return_value = {
            "ticket": {
                "id": 123,
                "status": "solved",
                "priority": "normal",
                "assignee_id": 789,
                "tags": ["test"],
                "updated_at": "2024-01-15T12:00:00Z",
            }
        }

        with patch("agno.tools.zendesk.requests.put", return_value=mock_response) as mock_put:
            result = zendesk_tools.update_ticket(ticket_id=123, status="solved")

            mock_put.assert_called_once()
            call_args = mock_put.call_args
            assert "tickets/123.json" in call_args[0][0]

            payload = call_args[1]["json"]
            assert payload["ticket"]["status"] == "solved"

            data = json.loads(result)
            assert data["success"] is True
            assert data["status"] == "solved"

    def test_update_ticket_priority(self, zendesk_tools, mock_response):
        """Test updating ticket priority."""
        mock_response.json.return_value = {
            "ticket": {
                "id": 123,
                "status": "open",
                "priority": "urgent",
                "assignee_id": 789,
                "tags": [],
                "updated_at": "2024-01-15T12:00:00Z",
            }
        }

        with patch("agno.tools.zendesk.requests.put", return_value=mock_response) as mock_put:
            result = zendesk_tools.update_ticket(ticket_id=123, priority="urgent")

            payload = mock_put.call_args[1]["json"]
            assert payload["ticket"]["priority"] == "urgent"

            data = json.loads(result)
            assert data["priority"] == "urgent"

    def test_update_ticket_multiple_fields(self, zendesk_tools, mock_response):
        """Test updating multiple ticket fields at once."""
        mock_response.json.return_value = {
            "ticket": {
                "id": 123,
                "status": "pending",
                "priority": "high",
                "assignee_id": 999,
                "tags": ["escalated", "vip"],
                "updated_at": "2024-01-15T12:00:00Z",
            }
        }

        with patch("agno.tools.zendesk.requests.put", return_value=mock_response) as mock_put:
            result = zendesk_tools.update_ticket(
                ticket_id=123,
                status="pending",
                priority="high",
                assignee_id=999,
                tags=["escalated", "vip"],
            )

            payload = mock_put.call_args[1]["json"]
            assert payload["ticket"]["status"] == "pending"
            assert payload["ticket"]["priority"] == "high"
            assert payload["ticket"]["assignee_id"] == 999
            assert payload["ticket"]["tags"] == ["escalated", "vip"]

            data = json.loads(result)
            assert data["success"] is True

    def test_update_ticket_no_fields_error(self, zendesk_tools):
        """Test update_ticket with no fields returns error."""
        result = zendesk_tools.update_ticket(ticket_id=123)

        data = json.loads(result)
        assert data["success"] is False
        assert "No fields to update" in data["message"]

    def test_update_ticket_missing_credentials(self):
        """Test update_ticket with missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            tools = ZendeskTools(enable_update_ticket=True)
            result = tools.update_ticket(123, status="open")
            assert "Username, password, or company name not provided" in result

    def test_update_ticket_api_error(self, zendesk_tools):
        """Test update_ticket with API error."""
        import requests

        with patch(
            "agno.tools.zendesk.requests.put",
            side_effect=requests.RequestException("Unauthorized"),
        ):
            with pytest.raises(ConnectionError, match="API request failed"):
                zendesk_tools.update_ticket(123, status="solved")


class TestAPIUrlConstruction:
    """Test that API URLs are constructed correctly."""

    def test_search_url_construction(self, zendesk_tools, mock_response):
        """Test search API URL is correct."""
        mock_response.json.return_value = {"results": []}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            zendesk_tools.search_zendesk("test query")

            call_url = mock_get.call_args[0][0]
            assert (
                call_url == "https://testcompany.zendesk.com/api/v2/help_center/articles/search.json?query=test query"
            )

    def test_tickets_url_construction(self, zendesk_tools, mock_response):
        """Test tickets API URL is correct."""
        mock_response.json.return_value = {"tickets": [], "next_page": None}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            zendesk_tools.get_tickets()

            call_url = mock_get.call_args[0][0]
            assert call_url == "https://testcompany.zendesk.com/api/v2/tickets.json"

    def test_auth_headers(self, zendesk_tools, mock_response):
        """Test that auth is passed correctly."""
        mock_response.json.return_value = {"results": []}

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response) as mock_get:
            zendesk_tools.search_zendesk("test")

            auth = mock_get.call_args[1]["auth"]
            assert auth == ("test@example.com", "test_api_token")


class TestHTMLStripping:
    """Test HTML tag stripping functionality."""

    def test_search_strips_html_tags(self, zendesk_tools, mock_response):
        """Test that HTML tags are stripped from search results."""
        mock_response.json.return_value = {
            "results": [{"body": "<div class='test'><p>Content with <a href='#'>link</a></p></div>"}]
        }

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.search_zendesk("test")

            articles = json.loads(result)
            assert "<" not in articles[0]
            assert ">" not in articles[0]
            assert "Content with link" in articles[0]

    def test_comments_strips_html_from_html_body(self, zendesk_tools, mock_response):
        """Test that HTML tags are stripped from comment html_body."""
        mock_response.json.return_value = {
            "comments": [
                {
                    "id": 1,
                    "author_id": 456,
                    "body": "",
                    "html_body": "<p>Formatted <strong>comment</strong></p>",
                    "created_at": "2024-01-15T10:00:00Z",
                    "public": True,
                    "type": "Comment",
                }
            ]
        }

        with patch("agno.tools.zendesk.requests.get", return_value=mock_response):
            result = zendesk_tools.get_ticket_comments(123)

            data = json.loads(result)
            body = data["comments"][0]["body"]
            assert "<" not in body
            assert ">" not in body
            assert "Formatted comment" in body
