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
        def __init__(self, message="error", response=None):
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


# === Initialization ===


def test_init_requires_token():
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="SLACK_TOKEN"):
            SlackTools()


def test_init_registers_default_tools():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools()
            names = [f.name for f in tools.functions.values()]
            assert "send_message" in names
            assert "send_message_thread" in names
            assert len(names) == 6


def test_init_all_flag_enables_all():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(all=True)
            assert len(tools.functions) == 10


# === Core Tools ===


def test_send_message(slack_tools):
    slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
    result = slack_tools.send_message("#general", "Hello")
    assert json.loads(result)["ok"] is True


def test_send_message_error(slack_tools):
    slack_tools.client.chat_postMessage.side_effect = SlackApiError("error")
    result = slack_tools.send_message("#general", "Hello")
    assert "error" in json.loads(result)


def test_send_message_thread(slack_tools):
    slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True, "thread_ts": "1.0"})
    result = slack_tools.send_message_thread("C1", "reply", thread_ts="1.0")
    assert json.loads(result)["ok"] is True
    slack_tools.client.chat_postMessage.assert_called_with(channel="C1", text="reply", thread_ts="1.0", mrkdwn=True)


def test_list_channels(slack_tools):
    slack_tools.client.conversations_list.return_value = {"channels": [{"id": "C1", "name": "general"}]}
    result = slack_tools.list_channels()
    assert json.loads(result) == [{"id": "C1", "name": "general"}]


def test_get_channel_history(slack_tools):
    slack_tools.client.conversations_history.return_value = {"messages": [{"text": "hi", "user": "U1", "ts": "1.0"}]}
    result = slack_tools.get_channel_history("C1")
    messages = json.loads(result)
    assert messages[0]["text"] == "hi"


def test_upload_file(slack_tools):
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    result = slack_tools.upload_file("C1", "content", "file.txt")
    assert json.loads(result)["ok"] is True


def test_upload_file_bytes(slack_tools):
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    slack_tools.upload_file("C1", b"bytes", "file.bin")
    slack_tools.client.files_upload_v2.assert_called_once()
    assert slack_tools.client.files_upload_v2.call_args[1]["content"] == b"bytes"


def test_download_file_base64(slack_tools):
    slack_tools.client.files_info.return_value = {
        "file": {"id": "F1", "name": "f.txt", "size": 10, "url_private": "https://files.slack.com/f.txt"}
    }
    with patch("agno.tools.slack.httpx.get") as mock_get:
        mock_get.return_value.content = b"data"
        mock_get.return_value.raise_for_status = Mock()
        result = slack_tools.download_file("F1")
        assert "content_base64" in json.loads(result)


# === Extended Tools ===


def test_search_messages(slack_tools):
    slack_tools.client.search_messages.return_value = {
        "messages": {"matches": [{"text": "found", "user": "U1", "channel": {}, "ts": "1"}]}
    }
    result = slack_tools.search_messages("query")
    assert json.loads(result)["count"] == 1


def test_get_thread(slack_tools):
    slack_tools.client.conversations_replies.return_value = {"messages": [{"text": "parent", "user": "U1", "ts": "1"}]}
    result = slack_tools.get_thread("C1", "1")
    assert json.loads(result)["reply_count"] == 0


def test_list_users(slack_tools):
    slack_tools.client.users_list.return_value = {
        "members": [{"id": "U1", "name": "user", "deleted": False, "is_bot": False, "profile": {}}]
    }
    result = slack_tools.list_users()
    assert json.loads(result)["count"] == 1


def test_get_user_info(slack_tools):
    slack_tools.client.users_info.return_value = {"user": {"id": "U1", "name": "user", "profile": {}}}
    result = slack_tools.get_user_info("U1")
    assert json.loads(result)["name"] == "user"
