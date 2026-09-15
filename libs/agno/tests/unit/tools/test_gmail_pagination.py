"""Tests for Gmail pagination support."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google.gmail import GmailTools


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth2 credentials."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    return mock_creds


@pytest.fixture
def mock_gmail_service():
    """Mock Gmail API service."""
    return MagicMock()


@pytest.fixture
def gmail_tools(mock_credentials, mock_gmail_service):
    """Create GmailTools with mocked dependencies and max_results=5."""
    with patch("googleapiclient.discovery.build") as mock_build:
        mock_build.return_value = mock_gmail_service
        tools = GmailTools(creds=mock_credentials, max_results=5)
        tools._service = mock_gmail_service
        return tools


class TestGmailPagination:
    def test_max_results_caps_count(self, gmail_tools):
        """Count is capped to max_results."""
        gmail_tools._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        gmail_tools.get_latest_emails(count=100)

        call_kwargs = gmail_tools._service.users().messages().list.call_args[1]
        assert call_kwargs["maxResults"] == 5

    def test_page_token_passed_to_api(self, gmail_tools):
        """page_token is forwarded to API as pageToken."""
        gmail_tools._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        gmail_tools.get_latest_emails(count=5, page_token="abc123")

        call_kwargs = gmail_tools._service.users().messages().list.call_args[1]
        assert call_kwargs["pageToken"] == "abc123"

    def test_page_token_returned_in_response(self, gmail_tools):
        """page_token from API is included in response."""
        gmail_tools._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
            "nextPageToken": "next_page_xyz",
        }

        result = gmail_tools.get_latest_emails(count=5)
        parsed = json.loads(result)

        assert "nextPageToken" in parsed
        assert parsed["nextPageToken"] == "next_page_xyz"

    def test_no_token_when_no_more_pages(self, gmail_tools):
        """page_token is absent when API doesn't return one."""
        gmail_tools._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        result = gmail_tools.get_latest_emails(count=5)
        parsed = json.loads(result)

        assert "nextPageToken" not in parsed

    def test_search_threads_pagination(self, gmail_tools):
        """search_threads supports pagination."""
        gmail_tools._service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "t1"}],
            "nextPageToken": "thread_next",
        }

        result = gmail_tools.search_threads(query="is:unread", page_token="prev_token")
        parsed = json.loads(result)

        assert parsed["nextPageToken"] == "thread_next"
        call_kwargs = gmail_tools._service.users().threads().list.call_args[1]
        assert call_kwargs["pageToken"] == "prev_token"

    def test_list_drafts_pagination(self, gmail_tools):
        """list_drafts supports pagination."""
        gmail_tools._service.users.return_value.drafts.return_value.list.return_value.execute.return_value = {
            "drafts": [{"id": "d1"}],
            "nextPageToken": "draft_next",
        }

        result = gmail_tools.list_drafts(count=5, page_token="prev_token")
        parsed = json.loads(result)

        assert parsed["nextPageToken"] == "draft_next"
        call_kwargs = gmail_tools._service.users().drafts().list.call_args[1]
        assert call_kwargs["pageToken"] == "prev_token"
