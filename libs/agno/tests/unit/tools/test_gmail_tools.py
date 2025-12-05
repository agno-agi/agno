"""Unit tests for GmailTools class."""

import base64
from datetime import datetime
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from agno.tools.gmail import GmailTools


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
    mock_service = MagicMock()
    return mock_service


@pytest.fixture
def gmail_tools(mock_credentials, mock_gmail_service):
    """Create GmailTools instance with mocked dependencies."""
    with patch("agno.tools.gmail.build") as mock_build:
        mock_build.return_value = mock_gmail_service
        tools = GmailTools(creds=mock_credentials)
        tools.service = mock_gmail_service
        return tools


def create_mock_message(msg_id: str, subject: str, sender: str, date: str, body: str) -> Dict[str, Any]:
    """Helper function to create mock message data."""
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": date},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


def test_init_with_default_scopes():
    """Test initialization with default scopes."""
    tools = GmailTools()
    assert tools.scopes == GmailTools.DEFAULT_SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in tools.scopes
    assert "https://www.googleapis.com/auth/gmail.compose" in tools.scopes


def test_init_with_custom_scopes():
    """Test initialization with custom scopes."""
    custom_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    tools = GmailTools(
        scopes=custom_scopes,
        include_tools=["get_latest_emails", "create_draft_email", "send_email"],
        exclude_tools=["create_draft_email", "send_email"],
    )
    assert tools.scopes == custom_scopes


def test_init_with_invalid_scopes():
    """Test initialization with invalid scopes for requested operations."""
    custom_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    with pytest.raises(ValueError, match="required for email composition operations"):
        GmailTools(
            scopes=custom_scopes,
        )


def test_init_with_invalid_scopes_include_tools():
    """Test initialization with invalid scopes for requested operations."""
    custom_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    with pytest.raises(ValueError, match="required for email composition operations"):
        GmailTools(
            scopes=custom_scopes,
            include_tools=["create_draft_email", "send_email"],
        )

    # Check that it doesn't raise an error if different tools are included
    GmailTools(
        scopes=custom_scopes,
        include_tools=["get_latest_emails"],
    )


def test_init_with_missing_read_scope():
    """Test initialization with missing read scope."""
    custom_scopes = ["https://www.googleapis.com/auth/gmail.compose"]
    with pytest.raises(ValueError, match="required for email reading operations"):
        GmailTools(
            scopes=custom_scopes,  # This should raise error as readonly scope is missing
        )


def test_authentication_decorator():
    """Test the authentication decorator behavior."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = False

    with patch("agno.tools.gmail.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        tools = GmailTools(creds=mock_creds)

        with patch.object(tools, "_auth") as mock_auth:
            tools.get_latest_emails(count=1)
            mock_auth.assert_called_once()


def test_auth_with_expired_credentials():
    """Test authentication with expired credentials."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = True

    with patch("agno.tools.gmail.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        tools = GmailTools(creds=mock_creds)

        with patch.object(mock_creds, "refresh") as mock_refresh:
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.return_value = False  # Force refresh path
                tools._auth()
                mock_refresh.assert_called_once()


def test_auth_with_custom_paths():
    """Test authentication with custom credential and token paths."""
    custom_creds_path = "custom_creds.json"
    custom_token_path = "custom_token.json"

    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("agno.tools.gmail.Credentials.from_authorized_user_file") as mock_from_file:
            tools = GmailTools(credentials_path=custom_creds_path, token_path=custom_token_path)
            tools._auth()
            mock_from_file.assert_called_once_with(custom_token_path, tools.scopes)


def test_get_latest_emails(gmail_tools, mock_gmail_service):
    """Test getting latest emails."""
    # Mock response data
    mock_messages = {"messages": [{"id": "123"}, {"id": "456"}]}
    mock_message_data = create_mock_message("123", "Test Subject", "sender@test.com", "2024-01-01", "Test body")

    # Set up mock returns
    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_latest_emails(count=2)

    assert "Test Subject" in result
    assert "sender@test.com" in result
    assert "Test body" in result


def test_get_emails_from_user(gmail_tools, mock_gmail_service):
    """Test getting emails from specific user."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message("123", "From User", "specific@test.com", "2024-01-01", "Specific message")

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_emails_from_user("specific@test.com", count=1)

    assert "From User" in result
    assert "specific@test.com" in result


def test_get_unread_emails(gmail_tools, mock_gmail_service):
    """Test getting unread emails."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message("123", "Unread Email", "sender@test.com", "2024-01-01", "Unread content")

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_unread_emails(count=1)

    assert "Unread Email" in result
    assert "Unread content" in result


def test_get_starred_emails(gmail_tools, mock_gmail_service):
    """Test getting starred emails."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message("123", "Starred Email", "sender@test.com", "2024-01-01", "Starred content")

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_starred_emails(count=1)

    assert "Starred Email" in result
    assert "Starred content" in result


def test_get_emails_by_context(gmail_tools, mock_gmail_service):
    """Test getting emails by context."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message(
        "123", "Context Email", "sender@test.com", "2024-01-01", "Contextual content"
    )

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_emails_by_context("test context", count=1)

    assert "Context Email" in result
    assert "Contextual content" in result


def test_get_emails_by_date(gmail_tools, mock_gmail_service):
    """Test getting emails by date."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message(
        "123", "Date Email", "sender@test.com", "2024-01-01", "Date-specific content"
    )

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    start_date = int(datetime(2024, 1, 1).timestamp())
    result = gmail_tools.get_emails_by_date(start_date, range_in_days=1)

    assert "Date Email" in result
    assert "Date-specific content" in result


def test_create_draft_email(gmail_tools, mock_gmail_service):
    """Test creating draft email."""
    mock_draft_response = {"id": "draft123", "message": {"id": "msg123"}}

    mock_gmail_service.users().drafts().create().execute.return_value = mock_draft_response

    result = gmail_tools.create_draft_email(
        to="recipient@test.com", subject="Test Draft", body="Draft content", cc="cc@test.com"
    )

    assert "draft123" in result
    assert "msg123" in result


def test_send_email(gmail_tools, mock_gmail_service):
    """Test sending email."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}

    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    result = gmail_tools.send_email(
        to="recipient@test.com", subject="Test Send", body="Email content", cc="cc@test.com"
    )

    assert "msg123" in result


def test_search_emails(gmail_tools, mock_gmail_service):
    """Test searching emails."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = create_mock_message(
        "123", "Search Result", "sender@test.com", "2024-01-01", "Searchable content"
    )

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.search_emails("search query", count=1)

    assert "Search Result" in result
    assert "Searchable content" in result


def test_error_handling(gmail_tools, mock_gmail_service):
    """Test error handling in Gmail tools."""
    from googleapiclient.errors import HttpError

    # Mock an HTTP error
    mock_gmail_service.users().messages().list.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    result = gmail_tools.get_latest_emails(count=1)
    assert "Error retrieving latest emails" in result


def test_message_with_attachments(gmail_tools, mock_gmail_service):
    """Test handling messages with attachments."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = {
        "id": "123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "With Attachment"},
                {"name": "From", "value": "sender@test.com"},
                {"name": "Date", "value": "2024-01-01"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode("Message with attachment".encode()).decode()},
                },
                {"filename": "test.pdf", "mimeType": "application/pdf"},
            ],
        },
    }

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_latest_emails(count=1)

    assert "With Attachment" in result
    assert "Message with attachment" in result
    assert "test.pdf" in result


def test_empty_message_list(gmail_tools, mock_gmail_service):
    """Test handling of empty message list."""
    mock_messages = {"messages": []}
    mock_gmail_service.users().messages().list().execute.return_value = mock_messages

    result = gmail_tools.get_latest_emails(count=1)
    assert "No emails found" in result


def test_malformed_message(gmail_tools, mock_gmail_service):
    """Test handling of malformed message data."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = {
        "id": "123",
        "payload": {
            "headers": []  # Missing required headers
        },
    }

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_latest_emails(count=1)
    assert result  # Should handle missing headers gracefully


def test_network_error(gmail_tools, mock_gmail_service):
    """Test handling of network errors."""
    mock_gmail_service.users().messages().list.side_effect = ConnectionError("Network unavailable")

    result = gmail_tools.get_latest_emails(count=1)
    assert "Error" in result


def test_html_message_content(gmail_tools, mock_gmail_service):
    """Test handling of HTML message content."""
    mock_messages = {"messages": [{"id": "123"}]}
    html_content = "<p>HTML content</p>"
    mock_message_data = {
        "id": "123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "HTML Email"},
                {"name": "From", "value": "sender@test.com"},
                {"name": "Date", "value": "2024-01-01"},
            ],
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(html_content.encode()).decode()},
        },
    }

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_latest_emails(count=1)

    # Verify email metadata
    assert "HTML Email" in result
    assert "sender@test.com" in result

    # Verify HTML content is included in the result
    assert (
        html_content in result
        or base64.urlsafe_b64decode(mock_message_data["payload"]["body"]["data"]).decode() in result
    )


def test_multiple_recipients(gmail_tools, mock_gmail_service):
    """Test sending email to multiple recipients."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}

    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    result = gmail_tools.send_email(
        to="recipient1@test.com,recipient2@test.com", subject="Multiple Recipients", body="Test content"
    )

    assert "msg123" in result


def test_rate_limit_error(gmail_tools, mock_gmail_service):
    """Test handling of rate limit errors."""
    from googleapiclient.errors import HttpError

    mock_gmail_service.users().messages().list.side_effect = HttpError(
        resp=Mock(status=429), content=b'{"error": {"message": "Rate limit exceeded"}}'
    )

    result = gmail_tools.get_latest_emails(count=1)
    assert "Error retrieving latest emails" in result


def test_multipart_complex_message(gmail_tools, mock_gmail_service):
    """Test handling of complex multipart messages."""
    mock_messages = {"messages": [{"id": "123"}]}
    mock_message_data = {
        "id": "123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Complex Message"},
                {"name": "From", "value": "sender@test.com"},
                {"name": "Date", "value": "2024-01-01"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode("Plain text version".encode()).decode()},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": base64.urlsafe_b64encode("<p>HTML version</p>".encode()).decode()},
                },
                {"filename": "test.pdf", "mimeType": "application/pdf"},
            ],
        },
    }

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages
    mock_gmail_service.users().messages().get().execute.return_value = mock_message_data

    result = gmail_tools.get_latest_emails(count=1)
    assert "Complex Message" in result
    assert "Plain text version" in result
    assert "test.pdf" in result


def test_invalid_email_parameters():
    """Test handling of invalid email parameters."""
    tools = GmailTools(creds=Mock(spec=Credentials, valid=True))

    with patch("agno.tools.gmail.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        tools.service = mock_service  # Set service to avoid authentication

        with pytest.raises(ValueError, match="Invalid recipient email format"):
            tools.send_email(
                to="invalid-email",  # Invalid email format
                subject="Test",
                body="Test body",
            )

        with pytest.raises(ValueError, match="Subject cannot be empty"):
            tools.send_email(
                to="valid@email.com",
                subject="",  # Empty subject
                body="Test body",
            )

        with pytest.raises(ValueError, match="Email body cannot be None"):
            tools.send_email(
                to="valid@email.com",
                subject="Test",
                body=None,  # None body
            )


def test_service_initialization():
    """Test that service is initialized only after successful authentication."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True

    with patch("agno.tools.gmail.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        tools = GmailTools(creds=mock_creds)
        assert tools.service is None  # Service should not be initialized in __init__

        # Call a method that requires authentication
        with patch.object(tools, "_auth"):
            tools.get_latest_emails(count=1)
            mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)


def test_send_email_with_single_attachment(gmail_tools, mock_gmail_service):
    """Test sending email with a single attachment."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("application/pdf", None)):
                result = gmail_tools.send_email(
                    to="recipient@test.com",
                    subject="With Attachment",
                    body="Email with attachment",
                    attachments="test.pdf",
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_send_email_with_multiple_attachments(gmail_tools, mock_gmail_service):
    """Test sending email with multiple attachments."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("application/pdf", None)):
                result = gmail_tools.send_email(
                    to="recipient@test.com",
                    subject="Multiple Attachments",
                    body="Email with multiple attachments",
                    attachments=["test1.pdf", "test2.pdf"],
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_create_draft_with_attachment(gmail_tools, mock_gmail_service):
    """Test creating draft email with attachment."""
    mock_draft_response = {"id": "draft123", "message": {"id": "msg123"}}
    mock_gmail_service.users().drafts().create().execute.return_value = mock_draft_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("text/plain", None)):
                result = gmail_tools.create_draft_email(
                    to="recipient@test.com",
                    subject="Draft with Attachment",
                    body="Draft with attachment",
                    attachments="document.txt",
                )

    assert "draft123" in result
    mock_gmail_service.users().drafts().create.assert_called_once()


def test_send_email_reply_with_attachment(gmail_tools, mock_gmail_service):
    """Test sending email reply with attachment."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("image/jpeg", None)):
                result = gmail_tools.send_email_reply(
                    thread_id="thread123",
                    message_id="msg456",
                    to="recipient@test.com",
                    subject="Reply with Attachment",
                    body="Reply with attachment",
                    attachments="image.jpg",
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_send_email_attachment_file_not_found(gmail_tools, mock_gmail_service):
    """Test error handling when attachment file doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(ValueError, match="Attachment file not found"):
            gmail_tools.send_email(
                to="recipient@test.com", subject="Test", body="Test body", attachments="nonexistent.pdf"
            )


def test_create_draft_attachment_file_not_found(gmail_tools, mock_gmail_service):
    """Test error handling when draft attachment file doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(ValueError, match="Attachment file not found"):
            gmail_tools.create_draft_email(
                to="recipient@test.com", subject="Test", body="Test body", attachments="nonexistent.pdf"
            )


def test_send_reply_attachment_file_not_found(gmail_tools, mock_gmail_service):
    """Test error handling when reply attachment file doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(ValueError, match="Attachment file not found"):
            gmail_tools.send_email_reply(
                thread_id="thread123",
                message_id="msg456",
                to="recipient@test.com",
                subject="Test",
                body="Test body",
                attachments="nonexistent.pdf",
            )


def test_send_email_mixed_attachment_existence(gmail_tools, mock_gmail_service):
    """Test error handling when some attachments exist and others don't."""

    # Create a mock Path class
    class MockPath:
        def __init__(self, path):
            self.path = str(path)

        def exists(self):
            return self.path.endswith("exists.pdf")

    with patch("agno.tools.gmail.Path", MockPath):
        with pytest.raises(ValueError, match="Attachment file not found"):
            gmail_tools.send_email(
                to="recipient@test.com", subject="Test", body="Test body", attachments=["exists.pdf", "missing.pdf"]
            )


def test_attachment_mime_type_guessing(gmail_tools, mock_gmail_service):
    """Test MIME type guessing for different file types."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    # Test with unknown MIME type (should default to application/octet-stream)
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=(None, None)):
                result = gmail_tools.send_email(
                    to="recipient@test.com",
                    subject="Unknown File Type",
                    body="Email with unknown file type",
                    attachments="unknown.xyz",
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_attachment_with_encoding(gmail_tools, mock_gmail_service):
    """Test attachment handling when MIME type has encoding."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    # Test with encoding present (should default to application/octet-stream)
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("text/plain", "gzip")):
                result = gmail_tools.send_email(
                    to="recipient@test.com",
                    subject="Encoded File",
                    body="Email with encoded file",
                    attachments="file.txt.gz",
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_empty_attachments_list(gmail_tools, mock_gmail_service):
    """Test sending email with empty attachments list."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    result = gmail_tools.send_email(
        to="recipient@test.com", subject="No Attachments", body="Email without attachments", attachments=[]
    )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_attachment_filename_extraction(gmail_tools, mock_gmail_service):
    """Test that attachment filenames are properly extracted from paths."""
    mock_send_response = {"id": "msg123", "labelIds": ["SENT"]}
    mock_gmail_service.users().messages().send().execute.return_value = mock_send_response

    # Reset mock to clear any setup calls
    mock_gmail_service.reset_mock()

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            with patch("mimetypes.guess_type", return_value=("application/pdf", None)):
                # Test with full path - should extract just the filename
                result = gmail_tools.send_email(
                    to="recipient@test.com",
                    subject="Path Test",
                    body="Email with full path attachment",
                    attachments="/full/path/to/document.pdf",
                )

    assert "msg123" in result
    mock_gmail_service.users().messages().send.assert_called_once()


def test_list_custom_labels_with_custom_labels(gmail_tools, mock_gmail_service):
    """Test listing custom labels when they exist."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_1", "name": "INBOX", "type": "system"},  # System label
            {"id": "Label_2", "name": "SENT", "type": "system"},  # System label
            {"id": "Label_3", "name": "CustomLabel1", "type": "user"},  # Custom label
            {"id": "Label_4", "name": "Work Projects", "type": "user"},  # Custom label
            {"id": "Label_5", "name": "STARRED", "type": "system"},  # System label
        ]
    }

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.list_custom_labels()

    assert "Your Custom Labels (2 total):" in result
    assert "1. CustomLabel1" in result
    assert "2. Work Projects" in result
    assert "INBOX" not in result
    assert "SENT" not in result


def test_list_custom_labels_no_custom_labels(gmail_tools, mock_gmail_service):
    """Test listing custom labels when only system labels exist."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_1", "name": "INBOX", "type": "system"},
            {"id": "Label_2", "name": "SENT", "type": "system"},
            {"id": "Label_3", "name": "STARRED", "type": "system"},
        ]
    }

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.list_custom_labels()

    assert "No custom labels found" in result
    assert "Create labels using apply_label function!" in result


def test_list_custom_labels_with_missing_type_field(gmail_tools, mock_gmail_service):
    """Test that labels without type field are treated as system labels."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_1", "name": "INBOX"},  # No type field - should be treated as system
            {"id": "Label_2", "name": "CustomLabel1", "type": "user"},  # User label
            {"id": "Label_3", "name": "SENT"},  # No type field - should be treated as system
        ]
    }

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.list_custom_labels()

    assert "Your Custom Labels (1 total):" in result
    assert "1. CustomLabel1" in result
    assert "INBOX" not in result
    assert "SENT" not in result


def test_list_custom_labels_error_handling(gmail_tools, mock_gmail_service):
    """Test error handling in list_custom_labels."""

    mock_gmail_service.users().labels().list().execute.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    result = gmail_tools.list_custom_labels()
    assert "Error fetching labels" in result


def test_apply_label_new_label(gmail_tools, mock_gmail_service):
    """Test applying a new label to emails."""
    # Mock messages search response
    mock_messages_response = {"messages": [{"id": "msg1"}, {"id": "msg2"}]}

    # Mock labels list response (no existing label)
    mock_labels_response = {
        "labels": [
            {"id": "Label_1", "name": "INBOX", "type": "system"},
            {"id": "Label_2", "name": "SENT", "type": "system"},
        ]
    }

    # Mock label creation response
    mock_create_label_response = {"id": "Label_new", "name": "NewLabel", "type": "user"}

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response
    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response
    mock_gmail_service.users().labels().create().execute.return_value = mock_create_label_response

    result = gmail_tools.apply_label("is:unread", "NewLabel", count=2)

    assert "Applied label 'NewLabel' to 2 emails matching 'is:unread'" in result
    # Check that create was called with the correct parameters
    mock_gmail_service.users().labels().create.assert_called_with(
        userId="me", body={"name": "NewLabel", "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    )
    assert mock_gmail_service.users().messages().modify.call_count == 2


def test_apply_label_existing_label(gmail_tools, mock_gmail_service):
    """Test applying an existing label to emails."""
    # Mock messages search response
    mock_messages_response = {"messages": [{"id": "msg1"}, {"id": "msg2"}]}

    # Mock labels list response (with existing label)
    mock_labels_response = {
        "labels": [
            {"id": "Label_1", "name": "INBOX", "type": "system"},
            {"id": "Label_existing", "name": "ExistingLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response
    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.apply_label("is:unread", "ExistingLabel", count=2)

    assert "Applied label 'ExistingLabel' to 2 emails matching 'is:unread'" in result
    mock_gmail_service.users().labels().create.assert_not_called()
    assert mock_gmail_service.users().messages().modify.call_count == 2


def test_apply_label_no_messages_found(gmail_tools, mock_gmail_service):
    """Test applying label when no messages match the context."""
    mock_messages_response = {"messages": []}

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response

    result = gmail_tools.apply_label("from:nonexistent@example.com", "TestLabel")

    assert "No emails found matching: 'from:nonexistent@example.com'" in result
    mock_gmail_service.users().labels().create.assert_not_called()


def test_apply_label_case_insensitive(gmail_tools, mock_gmail_service):
    """Test that label matching is case insensitive."""
    mock_messages_response = {"messages": [{"id": "msg1"}]}

    mock_labels_response = {
        "labels": [
            {"id": "Label_existing", "name": "TestLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response
    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.apply_label("is:unread", "testlabel", count=1)  # lowercase

    assert "Applied label 'testlabel' to 1 emails matching 'is:unread'" in result
    mock_gmail_service.users().labels().create.assert_not_called()


def test_apply_label_error_handling(gmail_tools, mock_gmail_service):
    """Test error handling in apply_label."""
    from googleapiclient.errors import HttpError

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().messages().list().execute.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    result = gmail_tools.apply_label("is:unread", "TestLabel")
    assert "Error applying label 'TestLabel'" in result


def test_remove_label_success(gmail_tools, mock_gmail_service):
    """Test successfully removing a label from emails."""
    # Mock labels list response
    mock_labels_response = {
        "labels": [
            {"id": "Label_target", "name": "TargetLabel", "type": "user"},
            {"id": "Label_other", "name": "OtherLabel", "type": "user"},
        ]
    }

    # Mock messages search response
    mock_messages_response = {"messages": [{"id": "msg1"}, {"id": "msg2"}]}

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response
    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response

    result = gmail_tools.remove_label("is:unread", "TargetLabel", count=2)

    assert "Removed label 'TargetLabel' from 2 emails matching 'is:unread'" in result
    assert mock_gmail_service.users().messages().modify.call_count == 2


def test_remove_label_not_found(gmail_tools, mock_gmail_service):
    """Test removing a label that doesn't exist."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_other", "name": "OtherLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.remove_label("is:unread", "NonexistentLabel")

    assert "Label 'NonexistentLabel' not found" in result
    mock_gmail_service.users().messages().modify.assert_not_called()


def test_remove_label_no_messages_found(gmail_tools, mock_gmail_service):
    """Test removing label when no messages match the context."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_target", "name": "TargetLabel", "type": "user"},
        ]
    }

    mock_messages_response = {"messages": []}

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response
    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response

    result = gmail_tools.remove_label("from:nonexistent@example.com", "TargetLabel")

    assert "No emails found matching: 'from:nonexistent@example.com' with label 'TargetLabel'" in result
    mock_gmail_service.users().messages().modify.assert_not_called()


def test_remove_label_case_insensitive(gmail_tools, mock_gmail_service):
    """Test that label removal is case insensitive."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_target", "name": "TestLabel", "type": "user"},
        ]
    }

    mock_messages_response = {"messages": [{"id": "msg1"}]}

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response
    mock_gmail_service.users().messages().list().execute.return_value = mock_messages_response

    result = gmail_tools.remove_label("is:unread", "testlabel")  # lowercase

    assert "Removed label 'testlabel' from 1 emails matching 'is:unread'" in result


def test_remove_label_error_handling(gmail_tools, mock_gmail_service):
    """Test error handling in remove_label."""
    from googleapiclient.errors import HttpError

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    result = gmail_tools.remove_label("is:unread", "TestLabel")
    assert "Error removing label 'TestLabel'" in result


def test_delete_custom_label_without_confirmation(gmail_tools, mock_gmail_service):
    """Test delete label without confirmation returns warning."""
    result = gmail_tools.delete_custom_label("TestLabel")

    assert "LABEL DELETION REQUIRES CONFIRMATION" in result
    assert "Set confirm=True to proceed" in result
    mock_gmail_service.users().labels().delete.assert_not_called()


def test_delete_custom_label_success(gmail_tools, mock_gmail_service):
    """Test successfully deleting a custom label."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_target", "name": "CustomLabel", "type": "user"},
            {"id": "Label_other", "name": "OtherLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.delete_custom_label("CustomLabel", confirm=True)

    assert "Successfully deleted label 'CustomLabel'" in result
    assert "This label has been removed from all emails" in result
    mock_gmail_service.users().labels().delete.assert_called_with(userId="me", id="Label_target")


def test_delete_custom_label_not_found(gmail_tools, mock_gmail_service):
    """Test deleting a label that doesn't exist."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_other", "name": "OtherLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.delete_custom_label("NonexistentLabel", confirm=True)

    assert "Label 'NonexistentLabel' not found" in result
    mock_gmail_service.users().labels().delete.assert_not_called()


def test_delete_custom_label_system_label(gmail_tools, mock_gmail_service):
    """Test attempting to delete a system label."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_inbox", "name": "INBOX", "type": "system"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.delete_custom_label("INBOX", confirm=True)

    assert "Cannot delete system label 'INBOX'. Only user-created labels can be deleted." in result
    mock_gmail_service.users().labels().delete.assert_not_called()


def test_delete_custom_label_missing_type_field(gmail_tools, mock_gmail_service):
    """Test that labels without type field cannot be deleted."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_inbox", "name": "INBOX"},  # No type field - should be treated as system
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.delete_custom_label("INBOX", confirm=True)

    assert "Cannot delete system label 'INBOX'" in result
    mock_gmail_service.users().labels().delete.assert_not_called()


def test_delete_custom_label_case_insensitive(gmail_tools, mock_gmail_service):
    """Test that label deletion is case insensitive."""
    mock_labels_response = {
        "labels": [
            {"id": "Label_target", "name": "TestLabel", "type": "user"},
        ]
    }

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.return_value = mock_labels_response

    result = gmail_tools.delete_custom_label("testlabel", confirm=True)  # lowercase

    assert "Successfully deleted label 'testlabel'" in result
    mock_gmail_service.users().labels().delete.assert_called_with(userId="me", id="Label_target")


def test_delete_custom_label_error_handling(gmail_tools, mock_gmail_service):
    """Test error handling in delete_custom_label."""
    from googleapiclient.errors import HttpError

    # Reset the mock to clear any previous calls
    mock_gmail_service.reset_mock()

    mock_gmail_service.users().labels().list().execute.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    result = gmail_tools.delete_custom_label("TestLabel", confirm=True)
    assert "Error deleting label 'TestLabel'" in result
