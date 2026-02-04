import json
import sys
import types
from unittest.mock import Mock, patch

import pytest


def _install_fake_slack_sdk():
    # Stub slack_sdk so tests run without the dependency
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


@pytest.fixture
def slack_tools():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
        with patch("agno.tools.slack.WebClient") as mock_web_client:
            mock_client = Mock()
            mock_web_client.return_value = mock_client
            tools = SlackTools()
            tools.client = mock_client
            return tools


class TestSlackToolsInit:
    def test_init_without_token_raises(self):
        with patch.dict("os.environ", clear=True):
            with pytest.raises(ValueError, match="SLACK_TOKEN is not set"):
                SlackTools()

    def test_init_with_empty_token_raises(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": ""}):
            with pytest.raises(ValueError, match="SLACK_TOKEN is not set"):
                SlackTools()

    def test_init_with_token_parameter(self):
        with patch.dict("os.environ", clear=True):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools(token="xoxb-explicit-token")

                assert tools.token == "xoxb-explicit-token"
                mock_web_client.assert_called_once_with(token="xoxb-explicit-token")

    def test_init_with_env_token(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-env-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools()

                assert tools.token == "xoxb-env-token"
                mock_web_client.assert_called_once_with(token="xoxb-env-token")

    def test_init_token_parameter_overrides_env(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-env-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client

                tools = SlackTools(token="xoxb-override-token")

                assert tools.token == "xoxb-override-token"

    def test_init_registers_all_tools_by_default(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools()

                tool_names = [f.name for f in tools.functions.values()]
                assert "send_message" in tool_names
                assert "send_message_thread" in tool_names
                assert "list_channels" in tool_names
                assert "get_channel_history" in tool_names
                assert "upload_file" in tool_names
                assert "download_file" in tool_names
                assert len(tool_names) == 6

    def test_init_with_selective_tools(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(
                    enable_send_message=True,
                    enable_send_message_thread=False,
                    enable_list_channels=False,
                    enable_get_channel_history=False,
                    enable_upload_file=False,
                    enable_download_file=False,
                )

                tool_names = [f.name for f in tools.functions.values()]
                assert "send_message" in tool_names
                assert "send_message_thread" not in tool_names
                assert "list_channels" not in tool_names
                assert "get_channel_history" not in tool_names
                assert "upload_file" not in tool_names
                assert "download_file" not in tool_names
                assert len(tool_names) == 1

    def test_init_with_all_flag_enables_all(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(
                    enable_send_message=False,
                    enable_send_message_thread=False,
                    enable_list_channels=False,
                    enable_get_channel_history=False,
                    enable_upload_file=False,
                    enable_download_file=False,
                    all=True,
                )

                tool_names = [f.name for f in tools.functions.values()]
                assert len(tool_names) == 10

    def test_init_markdown_default_true(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools()
                assert tools.markdown is True

    def test_init_markdown_can_be_disabled(self):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient"):
                tools = SlackTools(markdown=False)
                assert tools.markdown is False


class TestSendMessage:
    def test_send_message_success(self, slack_tools):
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True, "ts": "123.456"})
        result = slack_tools.send_message(channel="#bot-test", text="hello")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["ts"] == "123.456"

    def test_send_message_calls_api_with_correct_params(self, slack_tools):
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
        slack_tools.send_message(channel="C12345", text="Hello, world!")

        slack_tools.client.chat_postMessage.assert_called_once_with(channel="C12345", text="Hello, world!", mrkdwn=True)

    def test_send_message_with_markdown_disabled(self):
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
        slack_tools.client.chat_postMessage.side_effect = SlackApiError(message="channel_not_found", response=Mock())
        result = slack_tools.send_message(channel="#bot-test", text="hello")
        data = json.loads(result)
        assert "error" in data
        assert "channel_not_found" in data["error"]


class TestSendMessageThread:
    def test_send_message_thread_success(self, slack_tools):
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True, "thread_ts": "111.222"})
        result = slack_tools.send_message_thread(channel="C123", text="reply", thread_ts="111.222")
        data = json.loads(result)
        assert data["ok"] is True
        assert data["thread_ts"] == "111.222"

    def test_send_message_thread_calls_api_with_correct_params(self, slack_tools):
        slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
        slack_tools.send_message_thread(channel="C12345", text="Reply!", thread_ts="1234567890.123456")

        slack_tools.client.chat_postMessage.assert_called_once_with(
            channel="C12345", text="Reply!", thread_ts="1234567890.123456", mrkdwn=True
        )

    def test_send_message_thread_error_returns_json(self, slack_tools):
        slack_tools.client.chat_postMessage.side_effect = SlackApiError(message="thread_not_found", response=Mock())
        result = slack_tools.send_message_thread(channel="C123", text="reply", thread_ts="111.222")
        data = json.loads(result)
        assert "error" in data
        assert "thread_not_found" in data["error"]


class TestListChannels:
    def test_list_channels_success(self, slack_tools):
        slack_tools.client.conversations_list.return_value = {"channels": [{"id": "C1", "name": "general"}]}
        result = slack_tools.list_channels()
        channels = json.loads(result)
        assert channels == [{"id": "C1", "name": "general"}]

    def test_list_channels_multiple(self, slack_tools):
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
        slack_tools.client.conversations_list.return_value = {"channels": []}
        result = slack_tools.list_channels()
        channels = json.loads(result)
        assert channels == []

    def test_list_channels_error_returns_json(self, slack_tools):
        slack_tools.client.conversations_list.side_effect = SlackApiError(message="missing_scope", response=Mock())
        result = slack_tools.list_channels()
        data = json.loads(result)
        assert "error" in data
        assert "missing_scope" in data["error"]


class TestGetChannelHistory:
    def test_get_channel_history_success(self, slack_tools):
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
        slack_tools.client.conversations_history.return_value = {"messages": []}
        slack_tools.get_channel_history(channel="C12345", limit=50)

        slack_tools.client.conversations_history.assert_called_once_with(channel="C12345", limit=50)

    def test_get_channel_history_default_limit(self, slack_tools):
        slack_tools.client.conversations_history.return_value = {"messages": []}
        slack_tools.get_channel_history(channel="C12345")

        slack_tools.client.conversations_history.assert_called_once_with(channel="C12345", limit=100)

    def test_get_channel_history_bot_message_handling(self, slack_tools):
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
        slack_tools.client.conversations_history.return_value = {
            "messages": [
                {"text": "Hello!", "user": "U001", "ts": "1234567890.111111"},
            ]
        }
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)

        assert messages[0]["attachments"] == "n/a"

    def test_get_channel_history_empty(self, slack_tools):
        slack_tools.client.conversations_history.return_value = {"messages": []}
        result = slack_tools.get_channel_history(channel="C12345")
        messages = json.loads(result)
        assert messages == []

    def test_get_channel_history_missing_fields(self, slack_tools):
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
        slack_tools.client.conversations_history.side_effect = SlackApiError(
            message="channel_not_found", response=Mock()
        )
        result = slack_tools.get_channel_history(channel="C1", limit=1)
        data = json.loads(result)
        assert "error" in data
        assert "channel_not_found" in data["error"]


class TestUploadFile:
    def test_upload_file_success(self, slack_tools):
        slack_tools.client.files_upload_v2.return_value = Mock(
            data={"ok": True, "file": {"id": "F12345", "name": "test.csv"}}
        )
        result = slack_tools.upload_file(
            channel="C12345",
            content="col1,col2\nval1,val2",
            filename="test.csv",
        )
        data = json.loads(result)
        assert data["ok"] is True
        assert data["file"]["id"] == "F12345"

    def test_upload_file_calls_api_with_correct_params(self, slack_tools):
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
        slack_tools.upload_file(
            channel="C12345",
            content="test content",
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
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
        slack_tools.upload_file(
            channel="C12345",
            content="data",
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
        slack_tools.client.files_upload_v2.side_effect = SlackApiError(message="file_upload_failed", response=Mock())
        result = slack_tools.upload_file(
            channel="C12345",
            content="data",
            filename="file.txt",
        )
        data = json.loads(result)
        assert "error" in data
        assert "file_upload_failed" in data["error"]

    def test_upload_file_with_output_directory(self, tmp_path):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client
                mock_client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})

                tools = SlackTools(output_directory=str(tmp_path))
                tools.client = mock_client

                content = "col1,col2\nval1,val2"
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
                assert saved_file.read_bytes() == content.encode("utf-8")

    def test_upload_file_without_output_directory_no_local_path(self, slack_tools):
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})
        slack_tools.output_directory = None

        result = slack_tools.upload_file(
            channel="C12345",
            content="data",
            filename="file.txt",
        )

        data = json.loads(result)
        assert data["ok"] is True
        assert "local_path" not in data

    def test_upload_file_with_bytes_content(self, slack_tools):
        slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True, "file": {"id": "F12345"}})
        content_bytes = b"col1,col2\nval1,val2"
        slack_tools.upload_file(
            channel="C12345",
            content=content_bytes,
            filename="data.csv",
        )

        slack_tools.client.files_upload_v2.assert_called_once_with(
            channel="C12345",
            content=content_bytes,
            filename="data.csv",
            title=None,
            initial_comment=None,
            thread_ts=None,
        )

    def test_upload_file_disk_write_failure_still_uploads(self, tmp_path):
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
                        content="data",
                        filename="test.txt",
                    )

                    data = json.loads(result)
                    assert data["ok"] is True
                    assert "local_path" not in data
                finally:
                    # Restore permissions for cleanup
                    readonly_dir.chmod(0o755)


class TestDownloadFile:
    def test_download_file_with_dest_path(self, slack_tools, tmp_path):
        slack_tools.client.files_info.return_value = {
            "file": {
                "id": "F12345",
                "name": "report.csv",
                "size": 1024,
                "url_private": "https://files.slack.com/files-pri/T123/F12345/report.csv",
            }
        }

        with patch("agno.tools.slack.requests.get") as mock_get:
            mock_get.return_value.content = b"col1,col2\nval1,val2"
            mock_get.return_value.raise_for_status = Mock()

            dest_path = tmp_path / "download" / "report.csv"
            result = slack_tools.download_file(file_id="F12345", dest_path=str(dest_path))

            data = json.loads(result)
            assert data["file_id"] == "F12345"
            assert data["filename"] == "report.csv"
            assert data["size"] == 1024
            assert data["path"] == str(dest_path)
            assert dest_path.exists()
            assert dest_path.read_bytes() == b"col1,col2\nval1,val2"

    def test_download_file_with_output_directory(self, tmp_path):
        with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
            with patch("agno.tools.slack.WebClient") as mock_web_client:
                mock_client = Mock()
                mock_web_client.return_value = mock_client
                mock_client.files_info.return_value = {
                    "file": {
                        "id": "F12345",
                        "name": "data.json",
                        "size": 512,
                        "url_private": "https://files.slack.com/files-pri/T123/F12345/data.json",
                    }
                }

                tools = SlackTools(output_directory=str(tmp_path))
                tools.client = mock_client

                with patch("agno.tools.slack.requests.get") as mock_get:
                    mock_get.return_value.content = b'{"key": "value"}'
                    mock_get.return_value.raise_for_status = Mock()

                    result = tools.download_file(file_id="F12345")

                    data = json.loads(result)
                    assert data["path"] == str(tmp_path / "data.json")
                    assert (tmp_path / "data.json").exists()

    def test_download_file_returns_base64_when_no_dest(self, slack_tools):
        import base64

        slack_tools.output_directory = None
        slack_tools.client.files_info.return_value = {
            "file": {
                "id": "F12345",
                "name": "image.png",
                "size": 2048,
                "url_private": "https://files.slack.com/files-pri/T123/F12345/image.png",
            }
        }

        with patch("agno.tools.slack.requests.get") as mock_get:
            mock_get.return_value.content = b"\x89PNG\r\n\x1a\n"
            mock_get.return_value.raise_for_status = Mock()

            result = slack_tools.download_file(file_id="F12345")

            data = json.loads(result)
            assert data["file_id"] == "F12345"
            assert data["filename"] == "image.png"
            assert data["size"] == 2048
            assert "content_base64" in data
            assert "path" not in data

            decoded = base64.b64decode(data["content_base64"])
            assert decoded == b"\x89PNG\r\n\x1a\n"

    def test_download_file_error_no_url(self, slack_tools):
        slack_tools.client.files_info.return_value = {
            "file": {
                "id": "F12345",
                "name": "file.txt",
            }
        }

        result = slack_tools.download_file(file_id="F12345")
        data = json.loads(result)
        assert "error" in data
        assert "File URL not available" in data["error"]

    def test_download_file_slack_api_error(self, slack_tools):
        slack_tools.client.files_info.side_effect = SlackApiError(message="file_not_found", response=Mock())

        result = slack_tools.download_file(file_id="F12345")
        data = json.loads(result)
        assert "error" in data
        assert "file_not_found" in data["error"]

    def test_download_file_http_error(self, slack_tools):
        import requests as req

        slack_tools.client.files_info.return_value = {
            "file": {
                "id": "F12345",
                "name": "file.txt",
                "url_private": "https://files.slack.com/files-pri/T123/F12345/file.txt",
            }
        }

        with patch("agno.tools.slack.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("Connection timeout")

            result = slack_tools.download_file(file_id="F12345")
            data = json.loads(result)
            assert "error" in data
            assert "HTTP error" in data["error"]


class TestSearchMessages:
    def test_search_messages_success(self, slack_tools):
        slack_tools.client.search_messages.return_value = {
            "messages": {
                "matches": [
                    {
                        "text": "API redesign decision",
                        "user": "U123",
                        "channel": {"id": "C456", "name": "engineering"},
                        "ts": "1234.5678",
                        "permalink": "https://slack.com/archives/C456/p1234",
                    }
                ]
            }
        }
        result = slack_tools.search_messages("API redesign")
        data = json.loads(result)
        assert data["count"] == 1
        assert data["messages"][0]["text"] == "API redesign decision"
        assert data["messages"][0]["channel_name"] == "engineering"

    def test_search_messages_calls_api_correctly(self, slack_tools):
        slack_tools.client.search_messages.return_value = {"messages": {"matches": []}}
        slack_tools.search_messages("test query", limit=50)
        slack_tools.client.search_messages.assert_called_once_with(query="test query", count=50)

    def test_search_messages_limits_to_100(self, slack_tools):
        slack_tools.client.search_messages.return_value = {"messages": {"matches": []}}
        slack_tools.search_messages("test", limit=200)
        slack_tools.client.search_messages.assert_called_once_with(query="test", count=100)

    def test_search_messages_error(self, slack_tools):
        slack_tools.client.search_messages.side_effect = SlackApiError(message="search_failed", response=Mock())
        result = slack_tools.search_messages("test")
        data = json.loads(result)
        assert "error" in data


class TestGetThread:
    def test_get_thread_success(self, slack_tools):
        slack_tools.client.conversations_replies.return_value = {
            "messages": [
                {"text": "Parent message", "user": "U123", "ts": "1234.0000"},
                {"text": "First reply", "user": "U456", "ts": "1234.0001"},
                {"text": "Second reply", "user": "U789", "ts": "1234.0002"},
            ]
        }
        result = slack_tools.get_thread("C123", "1234.0000")
        data = json.loads(result)
        assert data["reply_count"] == 2
        assert len(data["messages"]) == 3
        assert data["messages"][0]["text"] == "Parent message"

    def test_get_thread_calls_api_correctly(self, slack_tools):
        slack_tools.client.conversations_replies.return_value = {"messages": []}
        slack_tools.get_thread("C123", "1234.5678", limit=50)
        slack_tools.client.conversations_replies.assert_called_once_with(channel="C123", ts="1234.5678", limit=50)

    def test_get_thread_limits_to_200(self, slack_tools):
        slack_tools.client.conversations_replies.return_value = {"messages": []}
        slack_tools.get_thread("C123", "1234.5678", limit=500)
        slack_tools.client.conversations_replies.assert_called_once_with(channel="C123", ts="1234.5678", limit=200)

    def test_get_thread_error(self, slack_tools):
        slack_tools.client.conversations_replies.side_effect = SlackApiError(
            message="thread_not_found", response=Mock()
        )
        result = slack_tools.get_thread("C123", "1234.5678")
        data = json.loads(result)
        assert "error" in data


class TestListUsers:
    def test_list_users_success(self, slack_tools):
        slack_tools.client.users_list.return_value = {
            "members": [
                {
                    "id": "U123",
                    "name": "jsmith",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {"real_name": "John Smith", "title": "Engineer"},
                },
                {"id": "U456", "name": "deleted_user", "deleted": True},
            ]
        }
        result = slack_tools.list_users()
        data = json.loads(result)
        assert data["count"] == 1
        assert data["users"][0]["name"] == "jsmith"
        assert data["users"][0]["title"] == "Engineer"

    def test_list_users_excludes_deleted(self, slack_tools):
        slack_tools.client.users_list.return_value = {
            "members": [
                {"id": "U123", "name": "active", "deleted": False, "is_bot": False, "profile": {}},
                {"id": "U456", "name": "deleted", "deleted": True, "is_bot": False, "profile": {}},
            ]
        }
        result = slack_tools.list_users()
        data = json.loads(result)
        assert data["count"] == 1
        assert data["users"][0]["name"] == "active"

    def test_list_users_error(self, slack_tools):
        slack_tools.client.users_list.side_effect = SlackApiError(message="users_list_failed", response=Mock())
        result = slack_tools.list_users()
        data = json.loads(result)
        assert "error" in data


class TestGetUserInfo:
    def test_get_user_info_success(self, slack_tools):
        slack_tools.client.users_info.return_value = {
            "user": {
                "id": "U123",
                "name": "jsmith",
                "tz": "America/New_York",
                "is_bot": False,
                "profile": {
                    "real_name": "John Smith",
                    "email": "john@example.com",
                    "title": "Engineer",
                },
            }
        }
        result = slack_tools.get_user_info("U123")
        data = json.loads(result)
        assert data["name"] == "jsmith"
        assert data["email"] == "john@example.com"
        assert data["title"] == "Engineer"
        assert data["tz"] == "America/New_York"

    def test_get_user_info_no_email(self, slack_tools):
        slack_tools.client.users_info.return_value = {
            "user": {
                "id": "U123",
                "name": "jsmith",
                "is_bot": False,
                "profile": {"real_name": "John Smith"},
            }
        }
        result = slack_tools.get_user_info("U123")
        data = json.loads(result)
        assert data["email"] == ""

    def test_get_user_info_error(self, slack_tools):
        slack_tools.client.users_info.side_effect = SlackApiError(message="user_not_found", response=Mock())
        result = slack_tools.get_user_info("U123")
        data = json.loads(result)
        assert "error" in data


class TestFormatHelpers:
    def test_format_bold(self):
        result = SlackTools.format_bold("hello")
        assert result == "*hello*"

    def test_format_italic(self):
        result = SlackTools.format_italic("hello")
        assert result == "_hello_"

    def test_format_code(self):
        result = SlackTools.format_code("print('hello')")
        assert result == "`print('hello')`"

    def test_format_code_block(self):
        result = SlackTools.format_code_block("def foo():\n    pass", "python")
        assert result == "```python\ndef foo():\n    pass\n```"

    def test_format_code_block_no_language(self):
        result = SlackTools.format_code_block("some code")
        assert result == "```\nsome code\n```"

    def test_format_link(self):
        result = SlackTools.format_link("https://example.com", "Example")
        assert result == "<https://example.com|Example>"

    def test_format_list_unordered(self):
        result = SlackTools.format_list(["item1", "item2", "item3"])
        assert result == "• item1\n• item2\n• item3"

    def test_format_list_ordered(self):
        result = SlackTools.format_list(["first", "second", "third"], ordered=True)
        assert result == "1. first\n2. second\n3. third"

    def test_format_list_empty(self):
        result = SlackTools.format_list([])
        assert result == ""
