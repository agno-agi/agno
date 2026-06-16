import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from slack_sdk.errors import SlackApiError

from agno.tools.slack import SlackTools


def _make_slack_tools_with_output_dir(output_dir: str) -> SlackTools:
    """Build SlackTools with a fake token for unit-testing _save_file_to_disk."""
    return SlackTools(token="fake-token-for-tests", output_directory=output_dir, save_downloads=True)


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
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            SlackTools()


def test_init_prefers_slack_bot_token_env():
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot", "SLACK_TOKEN": "xoxb-fallback"}):
        with patch("agno.tools.slack.WebClient") as mock_client:
            SlackTools()
            mock_client.assert_called_once()
            assert mock_client.call_args[1]["token"] == "xoxb-bot"


def test_init_falls_back_to_slack_token_env():
    with patch.dict("os.environ", {"SLACK_TOKEN": "xoxb-fallback"}, clear=True):
        with patch("agno.tools.slack.WebClient") as mock_client:
            SlackTools()
            mock_client.assert_called_once()
            assert mock_client.call_args[1]["token"] == "xoxb-fallback"


def test_init_creates_user_client_when_user_token_provided():
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot"}):
        with patch("agno.tools.slack.WebClient") as mock_client:
            tools = SlackTools(user_token="xoxp-user")
            assert mock_client.call_count == 2
            assert tools._user_token == "xoxp-user"
            assert tools._user_client is not None


def test_init_reads_user_token_from_env():
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot", "SLACK_USER_TOKEN": "xoxp-env"}):
        with patch("agno.tools.slack.WebClient") as mock_client:
            tools = SlackTools()
            assert mock_client.call_count == 2
            assert tools._user_token == "xoxp-env"


def test_init_no_user_client_without_user_token():
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot"}, clear=True):
        with patch("agno.tools.slack.WebClient") as mock_client:
            tools = SlackTools()
            assert mock_client.call_count == 1
            assert tools._user_client is None


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


def test_explicit_flags_expose_expected_surfaces():
    with patch.dict("os.environ", {"SLACK_TOKEN": "test"}):
        with patch("agno.tools.slack.WebClient"):
            read = SlackTools(
                enable_send_message=False,
                enable_send_message_thread=False,
                enable_upload_file=False,
                enable_download_file=False,
                enable_list_channels=True,
                enable_get_channel_history=True,
                enable_search_workspace=True,
                enable_get_thread=True,
                enable_list_users=True,
                enable_get_user_info=True,
                enable_get_channel_info=True,
            )
            write = SlackTools(
                enable_send_message=True,
                enable_send_message_thread=True,
                enable_upload_file=False,
                enable_download_file=False,
                enable_list_channels=True,
                enable_get_channel_history=False,
                enable_search_workspace=False,
                enable_get_thread=False,
                enable_list_users=True,
                enable_get_user_info=True,
                enable_get_channel_info=True,
            )

    assert "search_workspace" in read.functions
    assert "get_channel_history" in read.functions
    assert "get_thread" in read.functions
    assert "send_message" not in read.functions
    assert "send_message" in write.functions
    assert "get_channel_history" not in write.functions


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
    assert json.loads(result) == [{"id": "C1", "name": "general", "is_private": False}]


def test_get_channel_history(slack_tools):
    slack_tools.client.conversations_history.return_value = {"messages": [{"text": "hi", "user": "U1", "ts": "1.0"}]}
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}
    result = slack_tools.get_channel_history("C1")
    messages = json.loads(result)
    assert messages[0]["text"] == "hi"
    assert messages[0]["user"] == "User One"


def test_get_channel_history_resolves_channel_name(slack_tools):
    slack_tools.client.conversations_list.return_value = {
        "channels": [{"id": "C1", "name": "engineering"}],
        "response_metadata": {"next_cursor": ""},
    }
    slack_tools.client.conversations_history.return_value = {"messages": [{"text": "hi", "user": "U1", "ts": "1.0"}]}
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}

    result = slack_tools.get_channel_history("#engineering")

    assert json.loads(result)[0]["text"] == "hi"
    slack_tools.client.conversations_history.assert_called_with(channel="C1", limit=100)


def test_channel_resolution_cache_reuses_resolved_names(slack_tools):
    slack_tools.client.conversations_list.return_value = {
        "channels": [{"id": "C1", "name": "agents"}],
        "response_metadata": {"next_cursor": ""},
    }
    slack_tools.client.conversations_history.return_value = {"messages": [{"text": "hi", "user": "U1", "ts": "1.0"}]}
    slack_tools.client.conversations_replies.return_value = {
        "messages": [{"text": "parent", "user": "U1", "ts": "2.0"}]
    }
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}

    slack_tools.get_channel_history("#agents")
    slack_tools.get_thread("#agents", "2.0")

    assert slack_tools.client.conversations_list.call_count == 1
    slack_tools.client.conversations_replies.assert_called_with(channel="C1", ts="2.0", limit=20)


def test_upload_file(slack_tools):
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    result = slack_tools.upload_file("C1", "content", "file.txt")
    assert json.loads(result)["ok"] is True


def test_upload_file_bytes(slack_tools):
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    slack_tools.upload_file("C1", b"bytes", "file.bin")
    slack_tools.client.files_upload_v2.assert_called_once()
    assert slack_tools.client.files_upload_v2.call_args[1]["content"] == b"bytes"


def test_download_file_saves_to_disk(slack_tools, tmp_path):
    """Download saves file to output_directory when save_downloads=True."""
    slack_tools.output_directory = tmp_path
    slack_tools.save_downloads = True
    slack_tools.client.files_info.return_value = {
        "file": {"id": "F1", "name": "f.txt", "size": 10, "url_private": "https://files.slack.com/f.txt"}
    }
    with patch("agno.tools.slack.httpx.get") as mock_get:
        mock_get.return_value.content = b"data"
        mock_get.return_value.raise_for_status = Mock()
        result = slack_tools.download_file("F1")
        parsed = json.loads(result)
        assert "path" in parsed
        assert (tmp_path / "f.txt").exists()


def test_upload_file_rejected_on_dangerous_filename(slack_tools, tmp_path):
    """Dangerous filename aborts the upload — Slack never sees the raw name."""
    slack_tools.output_directory = tmp_path
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    result = slack_tools.upload_file("C1", b"data", "evil\x00name.bin")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Invalid filename" in parsed["error"]
    slack_tools.client.files_upload_v2.assert_not_called()


def test_upload_file_sanitizes_filename_for_slack(slack_tools, tmp_path):
    """Path components in the filename are stripped before reaching Slack."""
    slack_tools.output_directory = tmp_path
    slack_tools.client.files_upload_v2.return_value = Mock(data={"ok": True})
    result = slack_tools.upload_file("C1", b"data", "subdir/../report.bin")
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert slack_tools.client.files_upload_v2.call_args[1]["filename"] == "report.bin"


def test_download_file_dest_path_traversal_falls_back_to_base64(slack_tools, tmp_path):
    """Test that download_file falls back to base64 when dest_path traversal fails."""
    slack_tools.output_directory = tmp_path
    slack_tools.save_downloads = True
    slack_tools.client.files_info.return_value = {
        "file": {"id": "F1", "name": "f.txt", "size": 4, "url_private": "https://files.slack.com/f.txt"}
    }
    with patch("agno.tools.slack.httpx.get") as mock_get:
        mock_get.return_value.content = b"data"
        mock_get.return_value.raise_for_status = Mock()
        result = slack_tools.download_file("F1", dest_path="../../escape.bin")
        parsed = json.loads(result)
        assert "save_error" in parsed
        assert "resolves outside" in parsed["save_error"]
        assert "content_base64" in parsed


def test_download_file_dest_path_subdir_lands_inside_output_directory(slack_tools, tmp_path):
    """Test that download_file accepts a legitimate subdir in dest_path."""
    slack_tools.output_directory = tmp_path
    slack_tools.save_downloads = True
    slack_tools.client.files_info.return_value = {
        "file": {"id": "F1", "name": "f.txt", "size": 4, "url_private": "https://files.slack.com/f.txt"}
    }
    (tmp_path / "subdir").mkdir()
    with patch("agno.tools.slack.httpx.get") as mock_get:
        mock_get.return_value.content = b"data"
        mock_get.return_value.raise_for_status = Mock()
        result = slack_tools.download_file("F1", dest_path="subdir/foo.bin")
        parsed = json.loads(result)
        assert "path" in parsed
        assert (tmp_path / "subdir" / "foo.bin").read_bytes() == b"data"


# === Extended Tools ===


def test_search_messages_requires_user_client():
    """search_messages returns error when no user token is configured."""
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot"}, clear=True):
        with patch("agno.tools.slack.WebClient"):
            tools = SlackTools(enable_search_messages=True)
            result = json.loads(tools.search_messages("query"))
            assert "error" in result
            assert "user token" in result["error"].lower()


def test_search_messages_uses_user_client():
    """search_messages uses the user client, not the bot client."""
    with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-bot"}):
        with patch("agno.tools.slack.WebClient") as mock_client:
            mock_user_client = Mock()
            mock_bot_client = Mock()
            mock_client.side_effect = [mock_bot_client, mock_user_client]
            mock_user_client.search_messages.return_value = {
                "messages": {"matches": [{"text": "found", "user": "U1", "channel": {}, "ts": "1"}]}
            }
            tools = SlackTools(user_token="xoxp-user", enable_search_messages=True)
            result = tools.search_messages("query")
            mock_user_client.search_messages.assert_called_once_with(query="query", count=20)
            mock_bot_client.search_messages.assert_not_called()
            assert json.loads(result)["count"] == 1


def test_search_messages(slack_tools):
    # Legacy test - uses fixture with mocked client
    slack_tools._user_client = slack_tools.client
    slack_tools._user_client.search_messages.return_value = {
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


def test_get_thread_resolves_channel_name(slack_tools):
    slack_tools.client.conversations_list.return_value = {
        "channels": [{"id": "C1", "name": "agents"}],
        "response_metadata": {"next_cursor": ""},
    }
    slack_tools.client.conversations_replies.return_value = {"messages": [{"text": "parent", "user": "U1", "ts": "1"}]}
    slack_tools.client.users_info.return_value = {"user": {"profile": {"display_name": "User One"}}}

    result = slack_tools.get_thread("#agents", "1")

    assert json.loads(result)["messages"][0]["text"] == "parent"
    slack_tools.client.conversations_replies.assert_called_with(channel="C1", ts="1", limit=20)


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
    slack_tools.client.conversations_list.return_value = {
        "channels": [{"id": "C1", "name": "general"}],
        "response_metadata": {"next_cursor": ""},
    }
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
    result = slack_tools.get_channel_info("#general")
    data = json.loads(result)
    assert data["name"] == "general"
    assert data["num_members"] == 5
    assert data["topic"] == "General chat"
    slack_tools.client.conversations_info.assert_called_with(channel="C1", include_num_members=True)


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


# === Path safety (_save_file_to_disk) ===


def test_save_file_traversal_filename_lands_inside_output_dir():
    """Traversal '../../escape' is sanitized via safe_join_filename; file lands inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools_with_output_dir(tmp_dir)
        path, error = tool._save_file_to_disk(b"payload", "../../escape.bin")
        assert path == str((Path(tmp_dir) / "escape.bin").resolve())
        assert error is None
        assert (Path(tmp_dir) / "escape.bin").exists()
        assert not (Path(tmp_dir).parent / "escape.bin").exists()


def test_save_file_absolute_path_lands_inside_output_dir():
    """Absolute paths are stripped to bare filename via safe_join_filename; file lands inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools_with_output_dir(tmp_dir)
        path, error = tool._save_file_to_disk(b"payload", "/tmp/test_slack_abs_xyz.bin")
        assert path is not None
        assert error is None
        assert (Path(tmp_dir) / "test_slack_abs_xyz.bin").exists()
        assert not Path("/tmp/test_slack_abs_xyz.bin").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_save_file_symlink_escape_returns_none():
    """A symlink inside output_dir pointing outside is dropped — no write, returns error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        outside = Path(tmp_dir) / "outside"
        outside.mkdir()
        inside = Path(tmp_dir) / "inside"
        inside.mkdir()
        try:
            (inside / "escape").symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        tool = _make_slack_tools_with_output_dir(str(inside))
        path, error = tool._save_file_to_disk(b"payload", "escape")
        assert path is None
        assert error is not None


def test_save_file_control_char_filename_returns_none():
    """Control characters in the filename cause _save_file_to_disk to return error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools_with_output_dir(tmp_dir)
        path, error = tool._save_file_to_disk(b"payload", "report\x00hacked.bin")
        assert path is None
        assert error is not None


def test_save_file_normal_filename_saves_correctly():
    """Happy path: 'report.bin' is written into output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools_with_output_dir(tmp_dir)
        path, error = tool._save_file_to_disk(b"payload-bytes", "report.bin")
        assert path == str((Path(tmp_dir) / "report.bin").resolve())
        assert error is None
        assert (Path(tmp_dir) / "report.bin").read_bytes() == b"payload-bytes"


def test_save_file_oserror_returns_none(monkeypatch):
    """OSError is caught and returned as error (disk-full is advisory, not security)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools_with_output_dir(tmp_dir)

        def _raise_oserror(self, _data):
            raise OSError("simulated disk full")

        monkeypatch.setattr(Path, "write_bytes", _raise_oserror)
        path, error = tool._save_file_to_disk(b"payload", "ok.bin")
        assert path is None
        assert error == "simulated disk full"
