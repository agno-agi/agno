import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.discord import DiscordTools


def _mock_session_response(tools, json_data=None, text=None, status_code=200):
    resp = Mock(status_code=status_code)
    resp.raise_for_status = Mock()
    if text is not None:
        resp.text = text
    elif json_data is not None:
        resp.text = json.dumps(json_data)
    else:
        resp.text = "{}"
    resp.json.return_value = json_data if json_data is not None else {}
    tools._session.request = Mock(return_value=resp)
    return resp


class TestInit:
    def test_requires_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="bot token is required"):
                DiscordTools()

    def test_token_from_env(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token"}):
            tools = DiscordTools()
            assert tools.bot_token == "env-token"

    def test_token_from_param_overrides_env(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token"}):
            tools = DiscordTools(bot_token="param-token")
            assert tools.bot_token == "param-token"

    def test_default_tools_registered(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools()
            names = [f.name for f in tools.functions.values()]
            assert "send_message" in names
            assert "send_message_thread" in names
            assert "upload_file" in names
            assert "download_file" in names
            assert "get_channel_messages" in names
            assert "get_channel_info" in names
            assert "list_channels" in names
            assert "delete_message" in names
            # Default off
            assert "search_messages" not in names
            assert "get_thread" not in names
            assert "list_users" not in names
            assert "get_user_info" not in names
            assert len(names) == 8

    def test_all_flag_enables_all_tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools(all=True)
            names = [f.name for f in tools.functions.values()]
            assert len(names) == 12
            assert "search_messages" in names
            assert "get_thread" in names
            assert "list_users" in names
            assert "get_user_info" in names

    def test_selective_tool_registration(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools(
                enable_send_message=True,
                enable_send_message_thread=False,
                enable_upload_file=False,
                enable_download_file=False,
                enable_get_channel_messages=False,
                enable_get_channel_info=False,
                enable_list_channels=False,
                enable_delete_message=False,
            )
            names = [f.name for f in tools.functions.values()]
            assert names == ["send_message"]

    def test_session_has_auth_headers(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools()
            assert "Bot test-token" in tools._session.headers.get("Authorization", "")


class TestSyncTools:
    @pytest.fixture
    def tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            t = DiscordTools(all=True)
        t._session = MagicMock()
        return t

    def test_send_message_success(self, tools):
        _mock_session_response(tools, json_data={"id": "1"})
        result = tools.send_message("ch1", "Hello")
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["message_id"] == "1"
        assert data["channel_id"] == "ch1"

    def test_send_message_error(self, tools):
        tools._session.request = Mock(side_effect=Exception("Network error"))
        result = tools.send_message("ch1", "Hello")
        data = json.loads(result)
        assert "error" in data

    def test_send_message_thread(self, tools):
        _mock_session_response(tools, json_data={"id": "2", "content": "reply"})
        result = tools.send_message_thread("ch1", "reply", "msg1")
        data = json.loads(result)
        assert data["content"] == "reply"
        payload = tools._session.request.call_args.kwargs["json"]
        assert payload["message_reference"]["message_id"] == "msg1"

    def test_upload_file(self, tools):
        resp = Mock(status_code=200, text='{"id":"3"}')
        resp.raise_for_status = Mock()
        resp.json.return_value = {"id": "3"}
        tools._session.post = Mock(return_value=resp)
        result = tools.upload_file("ch1", b"file-bytes", "test.txt", message="Here's a file")
        data = json.loads(result)
        assert data["id"] == "3"
        call_kwargs = tools._session.post.call_args
        assert "files" in call_kwargs.kwargs

    def test_upload_file_string_content(self, tools):
        resp = Mock(status_code=200, text='{"id":"4"}')
        resp.raise_for_status = Mock()
        resp.json.return_value = {"id": "4"}
        tools._session.post = Mock(return_value=resp)
        result = tools.upload_file("ch1", "text content", "test.txt")
        assert "error" not in result.lower()

    def test_download_file(self, tools):
        resp = Mock(content=b"file-bytes", status_code=200)
        resp.raise_for_status = Mock()
        tools._session.get = Mock(return_value=resp)
        result = tools.download_file("https://cdn.discordapp.com/attachments/1/2/image.png")
        data = json.loads(result)
        assert data["filename"] == "image.png"
        assert data["size"] == 10
        assert "content_base64" in data

    def test_download_file_with_query_params(self, tools):
        resp = Mock(content=b"data", status_code=200)
        resp.raise_for_status = Mock()
        tools._session.get = Mock(return_value=resp)
        result = tools.download_file("https://cdn.discordapp.com/attachments/1/2/file.pdf?ex=abc")
        data = json.loads(result)
        assert data["filename"] == "file.pdf"

    def test_download_file_rejects_non_discord_url(self, tools):
        result = tools.download_file("https://evil.com/steal-data")
        data = json.loads(result)
        assert "error" in data
        assert "not allowed" in data["error"]

    def test_get_channel_info(self, tools):
        _mock_session_response(tools, json_data={"id": "ch1", "name": "general"})
        result = tools.get_channel_info("ch1")
        data = json.loads(result)
        assert data["name"] == "general"

    def test_get_channel_info_error(self, tools):
        tools._session.request = Mock(side_effect=Exception("Not found"))
        result = tools.get_channel_info("ch1")
        data = json.loads(result)
        assert "error" in data

    def test_list_channels(self, tools):
        _mock_session_response(tools, json_data=[{"id": "ch1", "name": "general"}])
        result = tools.list_channels("guild1")
        data = json.loads(result)
        assert len(data) == 1

    def test_list_channels_error(self, tools):
        tools._session.request = Mock(side_effect=Exception("Forbidden"))
        result = tools.list_channels("guild1")
        data = json.loads(result)
        assert "error" in data

    def test_get_channel_messages(self, tools):
        _mock_session_response(tools, json_data=[{"content": "hi", "author": {"id": "u1"}}])
        result = tools.get_channel_messages("ch1", limit=10)
        data = json.loads(result)
        assert data[0]["content"] == "hi"

    def test_get_channel_messages_error(self, tools):
        tools._session.request = Mock(side_effect=Exception("Timeout"))
        result = tools.get_channel_messages("ch1")
        data = json.loads(result)
        assert "error" in data

    def test_delete_message(self, tools):
        _mock_session_response(tools, text="", status_code=204)
        result = tools.delete_message("ch1", "msg1")
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["channel_id"] == "ch1"
        assert data["message_id"] == "msg1"

    def test_delete_message_error(self, tools):
        tools._session.request = Mock(side_effect=Exception("Forbidden"))
        result = tools.delete_message("ch1", "msg1")
        data = json.loads(result)
        assert "error" in data

    def test_search_messages(self, tools):
        _mock_session_response(tools, json_data={"messages": [{"id": "1", "content": "test"}]})
        result = tools.search_messages("guild1", "test query", limit=10)
        data = json.loads(result)
        assert "messages" in data
        call_kwargs = tools._session.request.call_args
        assert call_kwargs.kwargs["params"]["content"] == "test query"
        assert call_kwargs.kwargs["params"]["limit"] == 10

    def test_search_messages_caps_limit(self, tools):
        _mock_session_response(tools, json_data={"messages": []})
        tools.search_messages("guild1", "query", limit=100)
        call_kwargs = tools._session.request.call_args
        assert call_kwargs.kwargs["params"]["limit"] == 25

    def test_get_thread(self, tools):
        _mock_session_response(tools, json_data=[{"content": "thread msg"}])
        result = tools.get_thread("thread123", limit=50)
        data = json.loads(result)
        assert data[0]["content"] == "thread msg"

    def test_list_users(self, tools):
        members = [
            {
                "user": {"id": "u1", "username": "alice", "global_name": "Alice", "bot": False},
                "nick": "ali",
                "joined_at": "2025-01-01T00:00:00Z",
            }
        ]
        _mock_session_response(tools, json_data=members)
        result = tools.list_users("guild1", limit=10)
        data = json.loads(result)
        assert data["count"] == 1
        assert data["members"][0]["username"] == "alice"
        assert data["members"][0]["display_name"] == "ali"

    def test_list_users_caps_limit(self, tools):
        _mock_session_response(tools, json_data=[])
        tools.list_users("guild1", limit=5000)
        call_kwargs = tools._session.request.call_args
        assert call_kwargs.kwargs["params"]["limit"] == 1000

    def test_get_user_info(self, tools):
        user_data = {"id": "u1", "username": "alice", "global_name": "Alice", "bot": False, "avatar": "abc123"}
        _mock_session_response(tools, json_data=user_data)
        result = tools.get_user_info("u1")
        data = json.loads(result)
        assert data["username"] == "alice"
        assert data["avatar"] == "abc123"
