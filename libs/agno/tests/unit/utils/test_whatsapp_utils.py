from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

WHATSAPP_ENV = {
    "WHATSAPP_ACCESS_TOKEN": "test-token",
    "WHATSAPP_PHONE_NUMBER_ID": "123456",
}


# === get_access_token / get_phone_number_id ===


def test_get_access_token_success():
    with patch.dict("os.environ", WHATSAPP_ENV):
        from agno.utils.whatsapp import get_access_token

        assert get_access_token() == "test-token"


def test_get_access_token_missing():
    with patch.dict("os.environ", {}, clear=True):
        from agno.utils.whatsapp import get_access_token

        with pytest.raises(ValueError, match="WHATSAPP_ACCESS_TOKEN"):
            get_access_token()


def test_get_phone_number_id_success():
    with patch.dict("os.environ", WHATSAPP_ENV):
        from agno.utils.whatsapp import get_phone_number_id

        assert get_phone_number_id() == "123456"


def test_get_phone_number_id_missing():
    with patch.dict("os.environ", {}, clear=True):
        from agno.utils.whatsapp import get_phone_number_id

        with pytest.raises(ValueError, match="WHATSAPP_PHONE_NUMBER_ID"):
            get_phone_number_id()


# === get_media_async ===


@pytest.mark.asyncio
async def test_get_media_async_success():
    from agno.utils.whatsapp import get_media_async

    mock_metadata_response = Mock()
    mock_metadata_response.json.return_value = {"url": "https://cdn.example.com/media/123"}
    mock_metadata_response.raise_for_status = Mock()

    mock_media_response = Mock()
    mock_media_response.content = b"\x89PNG\r\n"
    mock_media_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_metadata_response, mock_media_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await get_media_async("media_123")
        assert result == b"\x89PNG\r\n"


@pytest.mark.asyncio
async def test_get_media_async_metadata_error():
    from agno.utils.whatsapp import get_media_async

    mock_request = Mock()
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=mock_request, response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await get_media_async("bad_id")
        assert isinstance(result, dict)
        assert "error" in result


# === upload_media_async ===


@pytest.mark.asyncio
async def test_upload_media_async_success():
    from agno.utils.whatsapp import upload_media_async

    mock_response = Mock()
    mock_response.json.return_value = {"id": "uploaded_media_123"}
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await upload_media_async(b"file_bytes", "image/png", "image.png")
        assert result == "uploaded_media_123"


@pytest.mark.asyncio
async def test_upload_media_async_missing_id_in_response():
    from agno.utils.whatsapp import upload_media_async

    mock_response = Mock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await upload_media_async(b"data", "image/png", "img.png")
        assert isinstance(result, dict)
        assert "error" in result


@pytest.mark.asyncio
async def test_upload_media_async_http_error():
    from agno.utils.whatsapp import upload_media_async

    mock_request = Mock()
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error", request=mock_request, response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await upload_media_async(b"data", "image/png", "img.png")
        assert isinstance(result, dict)
        assert "error" in result


# === send_text_message_async ===


@pytest.mark.asyncio
async def test_send_text_message_async_payload():
    from agno.utils.whatsapp import send_text_message_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        await send_text_message_async(recipient="+1234567890", text="Hello")
        call_kwargs = mock_client.post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["type"] == "text"
        assert payload["to"] == "+1234567890"
        assert payload["text"]["body"] == "Hello"
        assert payload["text"]["preview_url"] is False


@pytest.mark.asyncio
async def test_send_text_message_async_http_error_raises():
    from agno.utils.whatsapp import send_text_message_async

    mock_request = Mock()
    mock_response = Mock(text="error body")
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400 Bad Request", request=mock_request, response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await send_text_message_async(recipient="+1234567890", text="fail")


# === send_image_message_async ===


@pytest.mark.asyncio
async def test_send_image_message_async_payload():
    from agno.utils.whatsapp import send_image_message_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.text = '{"success": true}'

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        await send_image_message_async(media_id="media_123", recipient="+1234567890", text="Caption")
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["type"] == "image"
        assert payload["image"]["id"] == "media_123"
        assert payload["image"]["caption"] == "Caption"


# === send_document_message_async ===


@pytest.mark.asyncio
async def test_send_document_message_async_payload():
    from agno.utils.whatsapp import send_document_message_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.text = '{"success": true}'

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        await send_document_message_async(
            media_id="doc_media_123", recipient="+1234567890", filename="report.pdf", caption="Monthly"
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["type"] == "document"
        assert payload["document"]["id"] == "doc_media_123"
        assert payload["document"]["filename"] == "report.pdf"
        assert payload["document"]["caption"] == "Monthly"


@pytest.mark.asyncio
async def test_send_document_message_async_no_caption():
    from agno.utils.whatsapp import send_document_message_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.text = "{}"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        await send_document_message_async(media_id="doc_123", recipient="+1234567890")
        payload = mock_client.post.call_args.kwargs["json"]
        assert "caption" not in payload["document"]


# === send_audio_message_async ===


@pytest.mark.asyncio
async def test_send_audio_message_async_payload():
    from agno.utils.whatsapp import send_audio_message_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.text = "{}"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        await send_audio_message_async(media_id="audio_123", recipient="+1234567890")
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["type"] == "audio"
        assert payload["audio"]["id"] == "audio_123"


# === typing_indicator_async ===


@pytest.mark.asyncio
async def test_typing_indicator_async_none_message_id():
    from agno.utils.whatsapp import typing_indicator_async

    # Should return immediately without making HTTP call
    with patch("agno.utils.whatsapp.httpx.AsyncClient") as mock_cls:
        result = await typing_indicator_async(message_id=None)
        assert result is None
        mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_typing_indicator_async_success():
    from agno.utils.whatsapp import typing_indicator_async

    mock_response = Mock()
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await typing_indicator_async(message_id="wamid.123")
        assert result is None
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["message_id"] == "wamid.123"
        assert payload["typing_indicator"]["type"] == "text"


@pytest.mark.asyncio
async def test_typing_indicator_async_http_error_returns_dict():
    from agno.utils.whatsapp import typing_indicator_async

    mock_request = Mock()
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503 Unavailable", request=mock_request, response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", WHATSAPP_ENV),
        patch("agno.utils.whatsapp.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await typing_indicator_async(message_id="wamid.123")
        assert isinstance(result, dict)
        assert "error" in result
