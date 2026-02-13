"""Tests for the expanded TelegramTools toolkit."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.telegram import TelegramTools


FAKE_TOKEN = "123456:ABC-DEF"
FAKE_CHAT_ID = 99999


def _ok_response(result: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response that looks like a successful Telegram API call."""
    body = {"ok": True, "result": result or {}}
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _error_response(status_code: int = 400) -> MagicMock:
    """Build a mock httpx.Response that raises an HTTPStatusError."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request", request=MagicMock(), response=resp
    )
    return resp


@pytest.fixture
def tools():
    """TelegramTools with a fake token and default chat_id."""
    with patch.dict("os.environ", {"TELEGRAM_TOKEN": FAKE_TOKEN}):
        return TelegramTools(chat_id=FAKE_CHAT_ID)


@pytest.fixture
def tools_no_chat():
    """TelegramTools with a fake token but no default chat_id."""
    with patch.dict("os.environ", {"TELEGRAM_TOKEN": FAKE_TOKEN}):
        return TelegramTools()


# ---- Initialization ----


def test_init_registers_default_tools(tools):
    names = [f.name for f in tools.functions.values()]
    assert "send_message" in names
    assert "send_photo" in names
    assert "send_document" in names
    assert "send_audio" in names
    assert "send_video" in names
    assert "edit_message" in names
    assert "delete_message" in names
    assert "pin_message" in names
    assert "get_chat" in names
    assert "get_updates" in names
    assert "send_chat_action" in names
    assert len(names) == 11


def test_enable_flags():
    with patch.dict("os.environ", {"TELEGRAM_TOKEN": FAKE_TOKEN}):
        tools = TelegramTools(
            enable_send_message=True,
            enable_send_photo=False,
            enable_send_document=False,
            enable_send_audio=False,
            enable_send_video=False,
            enable_edit_message=False,
            enable_delete_message=False,
            enable_pin_message=False,
            enable_get_chat=False,
            enable_get_updates=False,
            enable_send_chat_action=False,
        )
        names = [f.name for f in tools.functions.values()]
        assert names == ["send_message"]


def test_all_flag():
    with patch.dict("os.environ", {"TELEGRAM_TOKEN": FAKE_TOKEN}):
        tools = TelegramTools(
            all=True,
            enable_send_message=False,
            enable_send_photo=False,
            enable_send_document=False,
            enable_send_audio=False,
            enable_send_video=False,
            enable_edit_message=False,
            enable_delete_message=False,
            enable_pin_message=False,
            enable_get_chat=False,
            enable_get_updates=False,
            enable_send_chat_action=False,
        )
        assert len(tools.functions) == 11


def test_missing_token_logs_error():
    with patch.dict("os.environ", {}, clear=True):
        # Should not raise — just logs an error
        tools = TelegramTools()
        assert tools.token is None


# ---- send_message ----


@patch("agno.tools.telegram.httpx.post")
def test_send_message(mock_post, tools):
    mock_post.return_value = _ok_response({"message_id": 1})
    result = json.loads(tools.send_message("Hello!"))
    assert result["ok"] is True

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["chat_id"] == FAKE_CHAT_ID
    assert call_kwargs[1]["json"]["text"] == "Hello!"
    assert call_kwargs[1]["json"]["parse_mode"] == "Markdown"


@patch("agno.tools.telegram.httpx.post")
def test_send_message_with_override_chat_id(mock_post, tools):
    mock_post.return_value = _ok_response()
    tools.send_message("Hi", chat_id=12345)
    payload = mock_post.call_args[1]["json"]
    assert payload["chat_id"] == 12345


@patch("agno.tools.telegram.httpx.post")
def test_send_message_parse_mode_override(mock_post, tools):
    mock_post.return_value = _ok_response()
    tools.send_message("Hi", parse_mode="HTML")
    payload = mock_post.call_args[1]["json"]
    assert payload["parse_mode"] == "HTML"


# ---- Media ----


@patch("agno.tools.telegram.httpx.post")
def test_send_photo(mock_post, tools):
    mock_post.return_value = _ok_response({"message_id": 2})
    result = json.loads(tools.send_photo("https://example.com/pic.jpg", caption="Nice pic"))
    assert result["ok"] is True

    payload = mock_post.call_args[1]["json"]
    assert payload["photo"] == "https://example.com/pic.jpg"
    assert payload["caption"] == "Nice pic"
    assert "sendPhoto" in mock_post.call_args[0][0]


@patch("agno.tools.telegram.httpx.post")
def test_send_document(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.send_document("https://example.com/file.pdf"))
    assert result["ok"] is True
    assert "sendDocument" in mock_post.call_args[0][0]


@patch("agno.tools.telegram.httpx.post")
def test_send_audio(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.send_audio("https://example.com/song.mp3", caption="A song"))
    assert result["ok"] is True
    assert "sendAudio" in mock_post.call_args[0][0]


@patch("agno.tools.telegram.httpx.post")
def test_send_video(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.send_video("https://example.com/video.mp4"))
    assert result["ok"] is True
    assert "sendVideo" in mock_post.call_args[0][0]


# ---- Message management ----


@patch("agno.tools.telegram.httpx.post")
def test_edit_message(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.edit_message(message_id=42, text="Updated text"))
    assert result["ok"] is True

    payload = mock_post.call_args[1]["json"]
    assert payload["message_id"] == 42
    assert payload["text"] == "Updated text"
    assert "editMessageText" in mock_post.call_args[0][0]


@patch("agno.tools.telegram.httpx.post")
def test_delete_message(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.delete_message(message_id=42))
    assert result["ok"] is True

    payload = mock_post.call_args[1]["json"]
    assert payload["message_id"] == 42
    assert "deleteMessage" in mock_post.call_args[0][0]


@patch("agno.tools.telegram.httpx.post")
def test_pin_message(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.pin_message(message_id=42))
    assert result["ok"] is True
    assert "pinChatMessage" in mock_post.call_args[0][0]


# ---- Chat info ----


@patch("agno.tools.telegram.httpx.post")
def test_get_chat(mock_post, tools):
    chat_data = {"id": FAKE_CHAT_ID, "type": "private", "title": "Test Chat"}
    mock_post.return_value = _ok_response(chat_data)
    result = json.loads(tools.get_chat())
    assert result["ok"] is True
    assert result["result"]["type"] == "private"


@patch("agno.tools.telegram.httpx.post")
def test_get_updates(mock_post, tools):
    updates = [{"update_id": 1, "message": {"text": "hi"}}]
    mock_post.return_value = _ok_response(updates)
    result = json.loads(tools.get_updates(limit=5))
    assert result["ok"] is True

    payload = mock_post.call_args[1]["json"]
    assert payload["limit"] == 5


# ---- Utility ----


@patch("agno.tools.telegram.httpx.post")
def test_send_chat_action(mock_post, tools):
    mock_post.return_value = _ok_response()
    result = json.loads(tools.send_chat_action(action="upload_photo"))
    assert result["ok"] is True

    payload = mock_post.call_args[1]["json"]
    assert payload["action"] == "upload_photo"
    assert "sendChatAction" in mock_post.call_args[0][0]


# ---- Error handling ----


def test_no_chat_id_raises(tools_no_chat):
    result = json.loads(tools_no_chat.send_message("Hi"))
    assert result["ok"] is False
    assert "chat_id" in result["error"]


@patch("agno.tools.telegram.httpx.post")
def test_http_error_returns_error_json(mock_post, tools):
    mock_post.return_value = _error_response(400)
    result = json.loads(tools.send_message("Hi"))
    assert result["ok"] is False
    assert "error" in result
