import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.os.interfaces.lark.formatting import build_card_content, truncate_markdown
from agno.os.interfaces.lark.helpers import (
    LarkConfig,
    extract_message_payload,
    is_bot_mentioned,
    send_response_media,
    send_text_message,
    strip_mention_placeholders,
)

_TEST_CONFIG = LarkConfig(
    app_id="cli_test",
    app_secret="test_secret",
    verification_token="test_token",
    encrypt_key="test_key",
)


# === LarkConfig.init ===


def test_config_init_from_args():
    cfg = LarkConfig.init(app_id="cli_x", app_secret="secret_x")
    assert cfg.app_id == "cli_x"
    assert cfg.app_secret == "secret_x"


def test_config_init_from_env():
    with patch.dict("os.environ", {"LARK_APP_ID": "cli_env", "LARK_APP_SECRET": "secret_env"}):
        cfg = LarkConfig.init()
        assert cfg.app_id == "cli_env"
        assert cfg.app_secret == "secret_env"


def test_config_init_missing_app_id_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="LARK_APP_ID"):
            LarkConfig.init(app_secret="secret")


def test_config_init_missing_app_secret_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="LARK_APP_SECRET"):
            LarkConfig.init(app_id="cli_x")


def test_config_base_url():
    cfg = LarkConfig(app_id="x", app_secret="y")
    assert cfg.base_url == "https://open.feishu.cn/open-apis"


def test_config_custom_domain():
    cfg = LarkConfig(app_id="x", app_secret="y", domain="https://open.larksuite.com")
    assert "open.larksuite.com" in cfg.base_url


# === build_card_content ===


def test_card_content_only():
    card_json = build_card_content("hello world")
    card = json.loads(card_json)
    assert card["config"]["update_multi"] is True
    elements = card["elements"]
    assert len(elements) == 1
    assert elements[0]["tag"] == "markdown"
    assert elements[0]["content"] == "hello world"


def test_card_status_only():
    card_json = build_card_content("", status_lines=["searching..."])
    card = json.loads(card_json)
    elements = card["elements"]
    assert len(elements) == 1
    assert elements[0]["tag"] == "note"


def test_card_content_and_status():
    card_json = build_card_content("answer", status_lines=["tool: search..."])
    card = json.loads(card_json)
    elements = card["elements"]
    assert len(elements) == 2
    assert elements[0]["tag"] == "note"
    assert elements[1]["tag"] == "markdown"
    assert elements[1]["content"] == "answer"


def test_card_empty_has_fallback():
    card_json = build_card_content("", None)
    card = json.loads(card_json)
    assert len(card["elements"]) >= 1


# === truncate_markdown ===


def test_truncate_short_unchanged():
    text = "short text"
    assert truncate_markdown(text) == text


def test_truncate_long_cut():
    text = "x" * 50000
    result = truncate_markdown(text, max_bytes=1000)
    assert len(result.encode("utf-8")) <= 1100
    assert result.endswith("…(truncated)")


# === extract_message_payload ===


def _make_event(message_type: str, content: dict, chat_type: str = "p2p", **extra) -> dict:
    return {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_sender", "user_id": "u1"}},
            "message": {
                "message_id": "om_test",
                "chat_id": "oc_test",
                "chat_type": chat_type,
                "message_type": message_type,
                "content": json.dumps(content),
                **extra,
            },
        }
    }


@pytest.mark.asyncio
async def test_extract_text_message():
    client = AsyncMock()
    event = _make_event("text", {"text": "hello"})
    payload = await extract_message_payload(event, client)
    assert payload is not None
    assert payload.text == "hello"
    assert payload.chat_id == "oc_test"
    assert payload.sender_open_id == "ou_sender"


@pytest.mark.asyncio
async def test_extract_post_message():
    client = AsyncMock()
    post_content = {"zh_cn": {"title": "T", "content": [[{"tag": "text", "text": "line1"}]]}}
    event = _make_event("post", post_content)
    payload = await extract_message_payload(event, client)
    assert payload is not None
    assert "T" in payload.text
    assert "line1" in payload.text


@pytest.mark.asyncio
async def test_extract_image_message_downloads():
    client = AsyncMock()
    client.download_resource = AsyncMock(return_value=b"fake-image-bytes")
    event = _make_event("image", {"image_key": "img_v3_xxx"})
    payload = await extract_message_payload(event, client)
    assert payload is not None
    assert len(payload.images) == 1
    client.download_resource.assert_called_once_with("om_test", "img_v3_xxx", "image")


@pytest.mark.asyncio
async def test_extract_file_message_downloads():
    client = AsyncMock()
    client.download_resource = AsyncMock(return_value=b"fake-file-bytes")
    event = _make_event("file", {"file_key": "file_v3_xxx", "file_name": "report.pdf"})
    payload = await extract_message_payload(event, client)
    assert payload is not None
    assert len(payload.files) == 1
    assert payload.files[0].filename == "report.pdf"


@pytest.mark.asyncio
async def test_extract_unsupported_type_returns_none():
    client = AsyncMock()
    event = _make_event("sticker", {})
    payload = await extract_message_payload(event, client)
    assert payload is None


@pytest.mark.asyncio
async def test_extract_carries_mentions():
    client = AsyncMock()
    event = _make_event("text", {"text": "@_user_1 hi"})
    event["event"]["message"]["mentions"] = [{"key": "@_user_1", "id": {"open_id": "ou_bot"}}]
    payload = await extract_message_payload(event, client)
    assert payload is not None
    assert len(payload.mentions) == 1


# === send_text_message ===


@pytest.mark.asyncio
async def test_send_text_short():
    client = AsyncMock()
    await send_text_message(client, "oc_chat", "short")
    client.send_message.assert_called_once()
    args = client.send_message.call_args
    assert args[0][0] == "oc_chat"
    assert args[0][1] == "text"


@pytest.mark.asyncio
async def test_send_text_empty_skipped():
    client = AsyncMock()
    await send_text_message(client, "oc_chat", "")
    client.send_message.assert_not_called()
    await send_text_message(client, "oc_chat", "   ")
    client.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_text_long_chunked():
    client = AsyncMock()
    long_msg = "x" * 200000
    await send_text_message(client, "oc_chat", long_msg)
    assert client.send_message.call_count >= 2


# === send_response_media ===


@pytest.mark.asyncio
async def test_send_response_image():
    client = AsyncMock()
    client.upload_image = AsyncMock(return_value="img_key_123")
    image = Mock()
    image.aget_content_bytes = AsyncMock(return_value=b"fake-png")
    response = Mock(images=[image], videos=None, audio=None, files=None)
    result = await send_response_media(client, response, "oc_chat")
    assert result is True
    client.upload_image.assert_called_once()
    client.send_message.assert_called_once()
    sent_args = client.send_message.call_args
    assert sent_args[0][1] == "image"


@pytest.mark.asyncio
async def test_send_response_file():
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value="file_key_456")
    file = Mock()
    file.aget_content_bytes = AsyncMock(return_value=b"fake-pdf")
    file.name = "doc.pdf"
    file.filename = None
    response = Mock(images=None, videos=None, audio=None, files=[file])
    result = await send_response_media(client, response, "oc_chat")
    assert result is True
    client.upload_file.assert_called_once()


@pytest.mark.asyncio
async def test_send_response_empty_bytes_skipped():
    client = AsyncMock()
    image = Mock()
    image.aget_content_bytes = AsyncMock(return_value=b"")
    response = Mock(images=[image], videos=None, audio=None, files=None)
    result = await send_response_media(client, response, "oc_chat")
    assert result is False
    client.upload_image.assert_not_called()


# === strip_mention_placeholders ===


def test_strip_mentions():
    assert strip_mention_placeholders("@_user_1 hello @_user_2") == "hello"


def test_strip_no_mentions():
    assert strip_mention_placeholders("plain text") == "plain text"


# === is_bot_mentioned ===


def test_bot_mentioned():
    mentions = [{"id": {"open_id": "ou_bot"}, "key": "@_user_1"}]
    assert is_bot_mentioned(mentions, "ou_bot") is True


def test_bot_not_mentioned():
    mentions = [{"id": {"open_id": "ou_other"}, "key": "@_user_1"}]
    assert is_bot_mentioned(mentions, "ou_bot") is False


def test_bot_mentioned_no_bot_open_id():
    mentions = [{"id": {"open_id": "ou_bot"}}]
    assert is_bot_mentioned(mentions, None) is False


def test_bot_mentioned_empty_mentions():
    assert is_bot_mentioned([], "ou_bot") is False
