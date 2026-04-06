import json
from unittest.mock import Mock, patch

import pytest
from slack_sdk.errors import SlackApiError

from agno.tools.slack import SlackTools


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
            assert len(tools.functions) == 12


# === Core Tools ===


def test_send_message(slack_tools):
    slack_tools.client.chat_postMessage.return_value = Mock(data={"ok": True})
    result = slack_tools.send_message("#general", "Hello")
    assert json.loads(result)["ok"] is True


def test_send_message_error(slack_tools):
    slack_tools.client.chat_postMessage.side_effect = SlackApiError("error", response=Mock())
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
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}
    result = slack_tools.get_channel_history("C1")
    messages = json.loads(result)
    assert messages[0]["text"] == "hi"
    assert messages[0]["user"] == "User One"


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
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}
    result = slack_tools.get_thread("C1", "1")
    data = json.loads(result)
    assert data["reply_count"] == 0
    assert data["messages"][0]["user"] == "User One"


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


def test_get_channel_info(slack_tools):
    slack_tools.client.conversations_info.return_value = {
        "channel": {
            "id": "C1",
            "name": "general",
            "topic": {"value": "General chat"},
            "purpose": {"value": ""},
            "num_members": 5,
            "is_private": False,
            "is_archived": False,
            "created": 1234567890,
            "creator": "U1",
        }
    }
    result = slack_tools.get_channel_info("C1")
    data = json.loads(result)
    assert data["name"] == "general"
    assert data["num_members"] == 5
    assert data["topic"] == "General chat"


# === Workspace Search ===


def test_search_workspace_no_action_token():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(enable_search_workspace=True)
            # No action_token in metadata
            ctx = Mock()
            ctx.metadata = {}
            result = json.loads(tools.search_workspace(ctx, "test query"))
            assert "error" in result
            assert "action_token" in result["error"]


def test_search_workspace_no_run_context():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(enable_search_workspace=True)
            result = json.loads(tools.search_workspace(None, "test query"))
            assert "error" in result


def test_search_workspace_success():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient") as mock_cls:
            mock_client = Mock()
            mock_cls.return_value = mock_client
            mock_client.api_call.return_value = {
                "ok": True,
                "results": {
                    "messages": [
                        {
                            "content": "discussed auth migration",
                            "author_name": "Alice",
                            "author_user_id": "U1",
                            "is_author_bot": False,
                            "channel_id": "C1",
                            "channel_name": "engineering",
                            "message_ts": "1700000000.000001",
                            "permalink": "https://slack.com/archives/C1/p1700000000000001",
                            "context_messages": {
                                "before": [{"text": "hey team", "user_id": "U2"}],
                                "after": [],
                            },
                        }
                    ],
                    "files": [
                        {"title": "RFC.pdf", "file_type": "pdf", "author_name": "Bob", "permalink": "https://..."}
                    ],
                    "users": [
                        {
                            "user_id": "U3",
                            "full_name": "Carol Smith",
                            "title": "Staff Engineer",
                            "email": "carol@example.com",
                            "permalink": "https://slack.com/team/U3",
                        }
                    ],
                },
            }

            tools = SlackTools(enable_search_workspace=True)
            tools.client = mock_client
            ctx = Mock()
            ctx.metadata = {"action_token": "xoxo-action-token"}

            result = json.loads(tools.search_workspace(ctx, "auth migration"))

            assert result["result_count"] == 3
            assert len(result["messages"]) == 1
            assert result["messages"][0]["author"] == "Alice"
            assert result["messages"][0]["context_before"] == [{"text": "hey team", "user_id": "U2"}]
            # Empty after list should be omitted
            assert "context_after" not in result["messages"][0]
            assert len(result["files"]) == 1
            assert result["files"][0]["title"] == "RFC.pdf"
            assert len(result["users"]) == 1
            assert result["users"][0]["full_name"] == "Carol Smith"
            assert result["users"][0]["title"] == "Staff Engineer"

            # Lists are joined to comma-separated strings for the API
            call_params = mock_client.api_call.call_args[1]["params"]
            assert call_params["content_types"] == "messages"
            assert call_params["channel_types"] == "public_channel"
            assert call_params["query"] == "auth migration"
            assert call_params["action_token"] == "xoxo-action-token"


def test_search_workspace_api_error():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient") as mock_cls:
            mock_client = Mock()
            mock_cls.return_value = mock_client
            mock_client.api_call.return_value = {"ok": False, "error": "not_allowed_token_type"}

            tools = SlackTools(enable_search_workspace=True)
            tools.client = mock_client
            ctx = Mock()
            ctx.metadata = {"action_token": "xoxo-token"}

            result = json.loads(tools.search_workspace(ctx, "query"))
            assert result["error"] == "not_allowed_token_type"


# === Dynamic Instructions ===


def test_build_instructions_single_tool_returns_empty():
    result = SlackTools._build_instructions(["get_channel_history"])
    assert result == ""


def test_build_instructions_multiple_tools():
    result = SlackTools._build_instructions(["search_workspace", "get_channel_history", "get_thread"])
    assert "## Slack Tool Selection" in result
    assert "search_workspace" in result
    assert "get_channel_history" in result
    assert "## When to use which" in result
    assert "Deep-dive into a message" in result


def test_build_instructions_search_messages_fallback():
    result = SlackTools._build_instructions(["search_workspace", "search_messages", "get_channel_history"])
    assert "Fallback (user-token only)" in result


def test_build_instructions_never_references_disabled_tools():
    # get_channel_history enabled without get_thread — should NOT mention get_thread
    result = SlackTools._build_instructions(["search_workspace", "get_channel_history"])
    assert "get_thread" not in result

    # get_thread enabled without search_workspace — should NOT mention search_workspace
    result = SlackTools._build_instructions(["get_channel_history", "get_thread"])
    assert "search_workspace" not in result

    # search_messages without search_workspace — should NOT mention "unavailable"
    result = SlackTools._build_instructions(["search_messages", "get_channel_history"])
    assert "unavailable" not in result
