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
            assert len(tools.functions) == 18


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


# === Canvas Tools ===


@pytest.fixture
def canvas_tools():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test-token"}):
        with patch("agno.tools.slack.WebClient") as mock_web_client:
            mock_client = Mock()
            mock_web_client.return_value = mock_client
            tools = SlackTools(enable_canvas=True)
            tools.client = mock_client
            return tools


def test_init_canvas_flag_registers_canvas_tools():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(enable_canvas=True)
            names = [f.name for f in tools.functions.values()]
            assert "create_canvas" in names
            assert "create_channel_canvas" in names
            assert "edit_canvas" in names
            assert "delete_canvas" in names
            assert "lookup_canvas_sections" in names
            assert "set_canvas_access" in names
            # 6 default + 6 canvas
            assert len(names) == 12


def test_init_canvas_disabled_by_default():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools()
            names = [f.name for f in tools.functions.values()]
            assert not any("canvas" in n for n in names)


def test_create_canvas(canvas_tools):
    canvas_tools.client.canvases_create.return_value = {"ok": True, "canvas_id": "F123ABC"}
    result = json.loads(canvas_tools.create_canvas(title="My Canvas", markdown="# Hello\nWorld"))
    assert result["ok"] is True
    assert result["canvas_id"] == "F123ABC"
    canvas_tools.client.canvases_create.assert_called_once_with(
        title="My Canvas",
        document_content={"type": "markdown", "markdown": "# Hello\nWorld"},
    )


def test_create_canvas_no_args(canvas_tools):
    canvas_tools.client.canvases_create.return_value = {"ok": True, "canvas_id": "F456"}
    result = json.loads(canvas_tools.create_canvas())
    assert result["canvas_id"] == "F456"
    canvas_tools.client.canvases_create.assert_called_once_with()


def test_create_canvas_error(canvas_tools):
    canvas_tools.client.canvases_create.side_effect = SlackApiError("error", response=Mock())
    result = json.loads(canvas_tools.create_canvas(title="Test"))
    assert "error" in result


def test_create_channel_canvas(canvas_tools):
    canvas_tools.client.conversations_canvases_create.return_value = {"ok": True, "canvas_id": "F789"}
    result = json.loads(canvas_tools.create_channel_canvas("C1", title="Channel Doc"))
    assert result["canvas_id"] == "F789"
    canvas_tools.client.conversations_canvases_create.assert_called_once_with(
        channel_id="C1",
        title="Channel Doc",
    )


def test_edit_canvas_insert_at_end(canvas_tools):
    canvas_tools.client.canvases_edit.return_value = {"ok": True}
    result = json.loads(canvas_tools.edit_canvas("F123", "insert_at_end", markdown="- new item"))
    assert result["ok"] is True
    canvas_tools.client.canvases_edit.assert_called_once_with(
        canvas_id="F123",
        changes=[{"operation": "insert_at_end", "document_content": {"type": "markdown", "markdown": "- new item"}}],
    )


def test_edit_canvas_replace_with_section(canvas_tools):
    canvas_tools.client.canvases_edit.return_value = {"ok": True}
    result = json.loads(canvas_tools.edit_canvas("F123", "replace", markdown="# Updated", section_id="S1"))
    assert result["ok"] is True
    call_changes = canvas_tools.client.canvases_edit.call_args[1]["changes"]
    assert call_changes[0]["section_id"] == "S1"
    assert call_changes[0]["operation"] == "replace"


def test_edit_canvas_delete_section(canvas_tools):
    canvas_tools.client.canvases_edit.return_value = {"ok": True}
    result = json.loads(canvas_tools.edit_canvas("F123", "delete", section_id="S1"))
    assert result["ok"] is True


def test_edit_canvas_section_op_requires_section_id(canvas_tools):
    for op in ("insert_before", "insert_after", "replace", "delete"):
        result = json.loads(canvas_tools.edit_canvas("F123", op, markdown="text"))
        assert "error" in result
        assert "section_id" in result["error"]


def test_edit_canvas_non_delete_requires_markdown(canvas_tools):
    result = json.loads(canvas_tools.edit_canvas("F123", "insert_at_start"))
    assert "error" in result
    assert "markdown" in result["error"]


def test_delete_canvas(canvas_tools):
    canvas_tools.client.canvases_delete.return_value = {"ok": True}
    result = json.loads(canvas_tools.delete_canvas("F123"))
    assert result["ok"] is True
    canvas_tools.client.canvases_delete.assert_called_once_with(canvas_id="F123")


def test_delete_canvas_error(canvas_tools):
    canvas_tools.client.canvases_delete.side_effect = SlackApiError("not_found", response=Mock())
    result = json.loads(canvas_tools.delete_canvas("FXXX"))
    assert "error" in result


def test_lookup_canvas_sections(canvas_tools):
    canvas_tools.client.canvases_sections_lookup.return_value = {
        "ok": True,
        "sections": [{"id": "temp:C:abc123"}],
    }
    result = json.loads(canvas_tools.lookup_canvas_sections("F123", section_types=["h1"], contains_text="Intro"))
    assert result["ok"] is True
    assert len(result["sections"]) == 1
    canvas_tools.client.canvases_sections_lookup.assert_called_once_with(
        canvas_id="F123",
        criteria={"section_types": ["h1"], "contains_text": "Intro"},
    )


def test_lookup_canvas_sections_no_filters(canvas_tools):
    canvas_tools.client.canvases_sections_lookup.return_value = {"ok": True, "sections": []}
    result = json.loads(canvas_tools.lookup_canvas_sections("F123"))
    assert result["sections"] == []
    canvas_tools.client.canvases_sections_lookup.assert_called_once_with(canvas_id="F123", criteria={})


def test_set_canvas_access_users(canvas_tools):
    canvas_tools.client.canvases_access_set.return_value = {"ok": True}
    result = json.loads(canvas_tools.set_canvas_access("F123", "write", user_ids=["U1", "U2"]))
    assert result["ok"] is True
    canvas_tools.client.canvases_access_set.assert_called_once_with(
        canvas_id="F123", access_level="write", user_ids=["U1", "U2"]
    )


def test_set_canvas_access_channels(canvas_tools):
    canvas_tools.client.canvases_access_set.return_value = {"ok": True}
    result = json.loads(canvas_tools.set_canvas_access("F123", "read", channel_ids=["C1"]))
    assert result["ok"] is True


def test_set_canvas_access_requires_targets(canvas_tools):
    result = json.loads(canvas_tools.set_canvas_access("F123", "read"))
    assert "error" in result
    assert "required" in result["error"]


def test_set_canvas_access_rejects_both(canvas_tools):
    result = json.loads(canvas_tools.set_canvas_access("F123", "read", user_ids=["U1"], channel_ids=["C1"]))
    assert "error" in result
    assert "Cannot pass both" in result["error"]


def test_set_canvas_access_owner_rejects_channels(canvas_tools):
    result = json.loads(canvas_tools.set_canvas_access("F123", "owner", channel_ids=["C1"]))
    assert "error" in result
    assert "Owner" in result["error"]


def test_build_instructions_includes_canvas():
    result = SlackTools._build_instructions(["create_canvas", "edit_canvas", "get_channel_history"])
    assert "Canvas tools" in result
    assert "lookup_canvas_sections" in result


def test_all_flag_includes_canvas():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(all=True)
            names = [f.name for f in tools.functions.values()]
            assert "create_canvas" in names
            assert len(names) == 18
