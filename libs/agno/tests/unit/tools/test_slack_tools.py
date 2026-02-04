"""Unit tests for SlackTools class.

Tests cover:
- Initialization (token validation, tool registration, markdown option)
- send_message (success and error handling)
- send_message_thread (success and error handling)
- list_channels (success, empty, and error handling)
- get_channel_history (success, error, subtype handling, missing fields)

All tests mock the slack_sdk.WebClient to avoid real API calls.
"""

import json
import sys
import types
from unittest.mock import Mock, patch

import pytest


def _install_fake_slack_sdk():
    """Install a minimal fake slack_sdk into sys.modules for tests.

    The production code imports `slack_sdk` at module import time and raises
    ImportError if missing. For unit tests, we inject a tiny stub so we can
    validate our wrapper logic without adding external dependencies.
    """

    slack_sdk = types.ModuleType("slack_sdk")
    slack_sdk_errors = types.ModuleType("slack_sdk.errors")

    class SlackApiError(Exception):
        def __init__(self, message="Slack API error", response=None):
            super().__init__(message)
            self.response = response

    class WebClient:
        def __init__(self, token=None):
            self.token = token

    slack_sdk.WebClient = WebClient
    slack_sdk_errors.SlackApiError = SlackApiError

    sys.modules.setdefault("slack_sdk", slack_sdk)
    sys.modules.setdefault("slack_sdk.errors", slack_sdk_errors)


_install_fake_slack_sdk()

from slack_sdk.errors import SlackApiError  # noqa: E402

from agno.tools.slack import SlackTools  # noqa: E402

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def slack_tools():
    """Create SlackTools with a fake token and mocked WebClient."""
    with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
        with patch("agno.tools.slack.WebClient") as mock_web_client:
            mock_client = Mock()
            mock_web_client.return_value = mock_client
            tools = SlackTools()
            tools.client = mock_client
            return tools


# =============================================================================
# Initialization Tests
# =============================================================================


class TestSlackToolsInit:
    """Tests for SlackTools initialization."""

    def test_init_without_token_raises(self):
        """SlackTools should raise if SLACK_TOKEN is missing."""
        with patch.dict("os.environ", clear=True):
            with pytest.raises(ValueError, match="SLACK_TOKEN is not set"):
                SlackTools()

    def test_init_with_empty_token_raises(self):
        """SlackTools should raise if SLACK_TOKEN is empty string."""
        with patch.dict("os.environ", {"SLACK_TOKEN": ""}):
            with pytest.raises(ValueError, match="SLACK_TOKEN is not set"):
                SlackTools()

    def test_init_with_token_parameter(self):
        """SlackTools should accept explicit token parameter."""
        with patch.dict("os.environ", clear=True):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools(token="xoxb-explicit-token")

                assert tools.token == "xoxb-explicit-token"
                mock_web_client.assert_called_once_with(token="xoxb-explicit-token")

    def test_init_with_env_token(self):
        """SlackTools should use SLACK_TOKEN from environment."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-env-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools()

                assert tools.token == "xoxb-env-token"
                mock_web_client.assert_called_once_with(token="xoxb-env-token")

    def test_init_token_parameter_overrides_env(self):
        """Explicit token parameter should override SLACK_TOKEN env var."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-env-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools(token="xoxb-override-token")

                assert tools.token == "xoxb-override-token"

    def test_init_registers_all_tools_by_default(self):
        """All tools should be registered by default."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools()

                tool_names = [f.name for f in tools.functions.values()]
                assert "send_message" in tool_names
                assert "send_message_thread" in tool_names
                assert "list_channels" in tool_names
                assert "get_channel_history" in tool_names
                assert "upload_file" in tool_names
                assert len(tool_names) == 5

    def test_init_with_selective_tools(self):
        """Only enabled tools should be registered."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(
                    enable_send_message=True,
                    enable_send_message_thread=False,
                    enable_list_channels=False,
                    enable_get_channel_history=False,
                    enable_upload_file=False,
                )

                tool_names = [f.name for f in tools.functions.values()]
                assert "send_message" in tool_names
                assert "send_message_thread" not in tool_names
                assert "list_channels" not in tool_names
                assert "get_channel_history" not in tool_names
                assert "upload_file" not in tool_names
                assert len(tool_names) == 1

    def test_init_with_all_flag_enables_all(self):
        """all=True should enable all tools regardless of individual flags."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(
                    enable_send_message=False,
                    enable_send_message_thread=False,
                    enable_list_channels=False,
                    enable_get_channel_history=False,
                    enable_upload_file=False,
                    all=True,
                )

                tool_names = [f.name for f in tools.functions.values()]
                assert len(tool_names) == 5

    def test_init_markdown_default_true(self):
        """Markdown should be enabled by default."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools()
                assert tools.markdown is True

    def test_init_markdown_can_be_disabled(self):
        """Markdown can be disabled via parameter."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(markdown=False)
                assert tools.markdown is False


# =============================================================================
# send_message Tests
# =============================================================================


class TestSendMessage:
    """Tests for send_message method."""

    def test_send_message_success(self, slack_tools):
        """send_message should return JSON of response.data on success."""
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True, "ts": "123.456"})
        result = slack_tools.send_message(channel="#bot-test", text="hello")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["ts"] == "123.456"

    def test_send_message_calls_api_with_correct_params(self, slack_tools):
        """send_message should call chat_postMessage with correct parameters."""
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
        slack_tools.send_message(channel="C12345", text="Hello, world!")

        slack_tools.client.chat_postMessage.assert_called_once_with(channel="C12345", text="Hello, world!", mrkdwn=True)

    def test_send_message_with_markdown_disabled(self):
        """send_message should pass mrkdwn=False when markdown is disabled."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client
                mock_client.chat_postMessage.return_value = Mock(data={"ok": True})

                tools = SlackTools(markdown=False)
                tools.client = mock_client
                tools.send_message(channel="C12345", text="Hello")

                tools.client.chat_postMessage.assert_called_once_with(channel="C12345", text="Hello", mrkdwn=False)

    def test_send_message_error_returns_json(self, slack_tools):
        """send_message should return JSON with error on SlackApiError."""
        slack_tools.client.chat_postMessage.side_effect = SlackApiError(message="channel_not_found", response=Mock())
        result = slack_tools.send_message(channel="#bot-test", text="hello")
        data = json.loads(result)
        assert "error" in data
        assert "channel_not_found" in data["error"]


# =============================================================================
# send_message_thread Tests
# =============================================================================


class TestSendMessageThread:
    """Tests for send_message_thread method."""

    def test_send_message_thread_success(self, slack_tools):
        """send_message_thread should return JSON of response.data on success."""
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True, "thread_ts": "111.222"})
        result = slack_tools.send_message_thread(channel="C123", text="reply", thread_ts="111.222")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["thread_ts"] == "111.222"

    def test_send_message_thread_calls_api_with_correct_params(self, slack_tools):
        """send_message_thread should call chat_postMessage with thread_ts."""
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
        slack_tools.send_message_thread(channel="C12345", text="Reply!", thread_ts="1234567890.123456")

        slack_tools.client.chat_postMessage.assert_called_once_with(
            channel="C12345", text="Reply!", thread_ts="1234567890.123456", mrkdwn=True
        )

    def test_send_message_thread_error_returns_json(self, slack_tools):
        """send_message_thread should return JSON with error on SlackApiError."""
        slack_tools.client.chat_postMessage.side_effect = SlackApiError(message="thread_not_found", response=Mock())
        result = slack_tools.send_message_thread(channel="C123", text="reply", thread_ts="111.222")
        data = json.loads(result)
        assert "error" in data
        assert "thread_not_found" in data["error"]


# =============================================================================
# list_channels Tests
# =============================================================================


class TestListChannels:
    """Tests for list_channels method."""

    def test_list_channels_success(self, slack_tools):
        """list_channels should return JSON list of id/name pairs."""
        slack_tools.client.conversations_list.return_value = {"channels": [{"id": "C1", "name": "general"}]}
        result = slack_tools.list_channels()
        channels = json.loads(result)
        assert channels == [{"id": "C1", "name": "general"}]

    def test_list_channels_multiple(self, slack_tools):
        """list_channels should return all channels."""
        slack_tools.client.conversations_list.return_value = {
            "channels": [
                {"id": "C001", "name": "general", "is_private": False},
                {"id": "C002", "name": "random", "is_private": False},
                {"id": "C003", "name": "engineering", "is_private": True},
            ]
        }
        result = slack_tools.list_channels()
        channels = json.loads(result)

        assert len(channels) == 3
        assert channels[0] == {"id": "C001", "name": "general"}
        assert channels[1] == {"id": "C002", "name": "random"}
        assert channels[2] == {"id": "C003", "name": "engineering"}

    def test_list_channels_empty(self, slack_tools):
        """list_channels should return empty list when no channels."""
        slack_tools.client.conversations_list.return_value = {"channels": []}
        result = slack_tools.list_channels()
        channels = json.loads(result)
        assert channels == []

    def test_list_channels_error_returns_json(self, slack_tools):
        """list_channels should return JSON with error on SlackApiError."""
        slack_tools.client.conversations_list.side_effect = SlackApiError(message="missing_scope", response=Mock())
        result = slack_tools.list_channels()
        data = json.loads(result)
        assert "error" in data
        assert "missing_scope" in data["error"]


# =============================================================================
# get_channel_history Tests
# =============================================================================


class TestGetChannelHistory:
    """Tests for get_channel_history method."""

    def test_get_channel_history_success(self, slack_tools):
        """get_channel_history should normalize messages into a consistent JSON shape."""
        slack_tools.client.conversations_history.return_value = {
            "messages": [
                {"text": "hi", "user": "U1", "ts": "1.0"},
                {
                    "text": "bot",
                    "subtype": "bot_message",
                    "ts": "2.0",
                    "attachments": [{"text": "a"}],
                },
            ]
        }
        result = slack_tools.get_channel_history(channel="C1", limit=2)
        messages = json.loads(result)
        assert len(messages) == 2
        assert messages[0]["text"] == "hi"
        assert messages[0]["user"] == "U1"
        assert messages[0]["ts"] == "1.0"
        assert messages[1]["user"] == "webhook"
        assert messages[1]["sub_type"] == "bot_message"
        assert isinstance(messages[1]["attachments"], list)

    def test_get_channel_history_calls_api_with_limit(self, slack_tools):
        """get_channel_history should pass limit to API."""
        slack_tools.client.conversations_history.return_value = {"messages": []}
        slack_tools.get_channel_history(channel="C12345", limit=50)

        slack_tools.client.conversations_history.assert_called_once_with(channel="C12345", limit=50)

    def test_get_channel_history_default_limit(self, slack_tools):
        """get_channel_history should use default limit of 100."""
        slack_tools.client.conversations_history.return_value = {"messages": []}
        slack_tools.get_channel_history(channel="C12345")

        slack_tools.client.conversations_history.assert_called_once_with(channel="C12345", limit=100)

    def test_get_channel_history_bot_message_handling(self, slack_tools):
        """get_channel_history should mark bot messages with 'webhook' user."""
        slack_tools.client.conversations_history.return_value = {
            "messages": [
                {
                    "text": "Bot says hello",
                    "subtype": "bot_message",
                    "ts": "1234567890.333333",
                    "attachments": [{"text": "Attachment content"}],
                },
            ]
        }
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)

        assert len(messages) == 1
        assert messages[0]["user"] == "webhook"
        assert messages[0]["sub_type"] == "bot_message"
        assert messages[0]["attachments"] == [{"text": "Attachment content"}]

    def test_get_channel_history_regular_message_attachments_na(self, slack_tools):
        """Regular messages should have 'n/a' for attachments."""
        slack_tools.client.conversations_history.return_value = {
            "messages": [
                {"text": "Hello!", "user": "U001", "ts": "1234567890.111111"},
            ]
        }
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)

        assert messages[0]["attachments"] == "n/a"

    def test_get_channel_history_empty(self, slack_tools):
        """get_channel_history should return empty list when no messages."""
        slack_tools.client.conversations_history.return_value = {"messages": []}
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)
        assert messages == []

    def test_get_channel_history_missing_fields(self, slack_tools):
        """get_channel_history should handle missing message fields gracefully."""
        slack_tools.client.conversations_history.return_value = {
            "messages": [
                {"ts": "1234567890.444444"},
            ]
        }
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)

        assert len(messages) == 1
        assert messages[0]["text"] == ""
        assert messages[0]["user"] == "unknown"
        assert messages[0]["ts"] == "1234567890.444444"
        assert messages[0]["sub_type"] == "unknown"

    def test_get_channel_history_error_returns_json(self, slack_tools):
        """get_channel_history should return JSON with error on SlackApiError."""
        slack_tools.client.conversations_history.side_effect = SlackApiError(
            message="channel_not_found", response=Mock()
        )
        result = slack_tools.get_channel_history(channel="C1", limit=1)
        data = json.loads(result)
        assert "error" in data
        assert "channel_not_found" in data["error"]


# =============================================================================
# upload_file Tests
# =============================================================================


class TestUploadFile:
    """Tests for upload_file method."""

    def test_upload_file_success(self, slack_tools):
        """upload_file should return JSON of response.data on success."""
        slack_tools.client.files_upload_v2.return_value = Mock(
            data={"ok": True, "file": {"id": "F12345", "name": "test.csv"}}
        )
        result = slack_tools.upload_file(
            channel="C12345",
            content=b"col1,col2\nval1,val2",
            filename="test.csv",
        )
        data = json.loads(result)
        assert data["ok"] is True
        assert data["file"]["id"] == "F12345"

    def test_upload_file_calls_api_with_correct_params(self, slack_tools):
        """upload_file should call files_upload_v2 with correct parameters."""
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
        slack_tools.upload_file(
            channel="C12345",
            content=b"test content",
            filename="report.csv",
            title="Sales Report",
            initial_comment="Here's the data you requested",
            thread_ts="1234567890.123456",
        )

        slack_tools.client.files_upload_v2.assert_called_once_with(
            channel="C12345",
            content=b"test content",
            filename="report.csv",
            title="Sales Report",
            initial_comment="Here's the data you requested",
            thread_ts="1234567890.123456",
        )

    def test_upload_file_minimal_params(self, slack_tools):
        """upload_file should work with only required parameters."""
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
        slack_tools.upload_file(
            channel="C12345",
            content=b"data",
            filename="file.txt",
        )

        slack_tools.client.files_upload_v2.assert_called_once_with(
            channel="C12345",
            content=b"data",
            filename="file.txt",
            title=None,
            initial_comment=None,
            thread_ts=None,
        )

    def test_upload_file_error_returns_json(self, slack_tools):
        """upload_file should return JSON with error on SlackApiError."""
        slack_tools.client.files_upload_v2.side_effect = SlackApiError(message="file_upload_failed", response=Mock())
        result = slack_tools.upload_file(
            channel="C12345",
            content=b"data",
            filename="file.txt",
        )
        data = json.loads(result)
        assert "error" in data
        assert "file_upload_failed" in data["error"]

    def test_upload_file_with_binary_content(self, slack_tools):
        """upload_file should handle binary content (e.g., images, PDFs)."""
        binary_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
        slack_tools.client.files_upload_v2.return_value = Mock(
            data={"ok": True, "file": {"id": "F12345", "mimetype": "image/png"}}
        )
        result = slack_tools.upload_file(
            channel="C12345",
            content=binary_content,
            filename="chart.png",
        )
        data = json.loads(result)
        assert data["ok"] is True

        slack_tools.client.files_upload_v2.assert_called_once_with(
            channel="C12345",
            content=binary_content,
            filename="chart.png",
            title=None,
            initial_comment=None,
            thread_ts=None,
        )

    def test_upload_file_with_output_directory(self, tmp_path):
        """upload_file should save file to disk when output_directory is set."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client
                mock_client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})

                tools = SlackTools(output_directory=str(tmp_path))
                tools.client = mock_client

                content = b"col1,col2\nval1,val2"
                result = tools.upload_file(
                    channel="C12345",
                    content=content,
                    filename="test.csv",
                )

                data = json.loads(result)
                assert data["ok"] is True
                assert "local_path" in data
                assert data["local_path"] == str(tmp_path / "test.csv")

                saved_file = tmp_path / "test.csv"
                assert saved_file.exists()
                assert saved_file.read_bytes() == content

    def test_upload_file_without_output_directory_no_local_path(self, slack_tools):
        """upload_file should not include local_path when output_directory is not set."""
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})
        slack_tools.output_directory = None

        result = slack_tools.upload_file(
            channel="C12345",
            content=b"data",
            filename="file.txt",
        )

        data = json.loads(result)
        assert data["ok"] is True
        assert "local_path" not in data

    def test_upload_file_disk_write_failure_still_uploads(self, tmp_path):
        """upload_file should still upload to Slack even if local save fails."""
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client
                mock_client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})

                # Create a read-only directory to force write failure
                readonly_dir = tmp_path / "readonly"
                readonly_dir.mkdir()
                readonly_dir.chmod(0o444)

                try:
                    tools = SlackTools(output_directory=str(readonly_dir))
                    tools.client = mock_client

                    result = tools.upload_file(
                        channel="C12345",
                        content=b"data",
                        filename="test.txt",
                    )

                    data = json.loads(result)
                    # Upload should still succeed
                    assert data["ok"] is True
                    # But local_path should not be present (save failed)
                    assert "local_path" not in data
                finally:
                    # Restore permissions for cleanup
                    readonly_dir.chmod(0o755)
