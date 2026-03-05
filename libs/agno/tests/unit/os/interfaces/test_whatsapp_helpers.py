import struct
from unittest.mock import AsyncMock, patch

import pytest

from agno.media import Audio, File, Image
from agno.os.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    send_whatsapp_message_async,
    upload_and_send_media_async,
)

_TEST_CONFIG = WhatsAppConfig(access_token="test-token", phone_number_id="123456", verify_token="test-verify")


# === send_whatsapp_message_async ===


@pytest.mark.asyncio
async def test_send_message_short():
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "short message", _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text="short message", config=_TEST_CONFIG)


@pytest.mark.asyncio
async def test_send_message_exactly_4096():
    msg = "x" * 4096
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", msg, _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text=msg, config=_TEST_CONFIG)


@pytest.mark.asyncio
async def test_send_message_4097_batched():
    msg = "x" * 4097
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", msg, _TEST_CONFIG)
        # 4097 chars → 2 batches (4000 + 97)
        assert mock_send.call_count == 2
        first_text = mock_send.call_args_list[0].kwargs["text"]
        assert first_text.startswith("[1/2]")
        second_text = mock_send.call_args_list[1].kwargs["text"]
        assert second_text.startswith("[2/2]")


@pytest.mark.asyncio
async def test_send_message_italics():
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "line1\nline2", _TEST_CONFIG, italics=True)
        sent_text = mock_send.call_args.kwargs["text"]
        assert sent_text == "_line1_\n_line2_"


@pytest.mark.asyncio
async def test_send_message_empty():
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "", _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text="", config=_TEST_CONFIG)


# === upload_and_send_media_async — images ===


@pytest.mark.asyncio
async def test_upload_images_success():
    items = [Image(content=b"fake_png")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_123"
        await upload_and_send_media_async(items, "image", "recipient_phone", _TEST_CONFIG, "caption text")
        mock_upload.assert_called_once()
        mock_send.assert_called_once_with(
            media_type="image",
            media_id="media_123",
            recipient="recipient_phone",
            config=_TEST_CONFIG,
            caption="caption text",
            filename=None,
        )


@pytest.mark.asyncio
async def test_upload_images_long_caption_truncated():
    items = [Image(content=b"fake_png")]
    long_caption = "x" * 1500
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_123"
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, long_caption)
        sent_caption = mock_send.call_args.kwargs["caption"]
        assert len(sent_caption) == 1024
        assert sent_caption.endswith("...")


@pytest.mark.asyncio
async def test_upload_images_upload_failure_sends_text_fallback():
    items = [Image(content=b"fake_png")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
    ):
        mock_upload.return_value = {"error": "upload failed"}
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, "fallback text")
        mock_send_text.assert_called_once()


@pytest.mark.asyncio
async def test_upload_images_empty_bytes_sends_text_fallback():
    # Empty content → get_content_bytes() returns None → triggers fallback
    items = [Image(content=b"")]
    with patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text:
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, "fallback")
        mock_send_text.assert_called_once()


# === upload_and_send_media_async — documents ===


@pytest.mark.asyncio
async def test_upload_files_pdf_correct_mime():
    items = [File(content=b"fake_pdf", name="report.pdf")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_456"
        await upload_and_send_media_async(items, "document", "phone", _TEST_CONFIG, "caption")
        upload_call = mock_upload.call_args
        assert upload_call.kwargs["mime_type"] == "application/pdf"
        assert upload_call.kwargs["filename"] == "report.pdf"
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["filename"] == "report.pdf"


@pytest.mark.asyncio
async def test_upload_files_unknown_extension():
    items = [File(content=b"data", name="file.qzx7")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "media_789"
        await upload_and_send_media_async(items, "document", "phone", _TEST_CONFIG, "text")
        assert mock_upload.call_args.kwargs["mime_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_upload_files_no_extension():
    items = [File(content=b"data", name="document")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "m_id"
        await upload_and_send_media_async(items, "document", "phone", _TEST_CONFIG, "")
        assert mock_upload.call_args.kwargs["mime_type"] == "application/octet-stream"


# === upload_and_send_media_async — audio ===


@pytest.mark.asyncio
async def test_upload_audio_mpeg_passthrough():
    items = [Audio(content=b"\xff\xfb\x90\x00", mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "audio_media_id"
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG)
        assert mock_upload.call_args.kwargs["mime_type"] == "audio/mpeg"
        mock_send.assert_called_once()
        # Audio has no caption
        assert mock_send.call_args.kwargs["caption"] is None


@pytest.mark.asyncio
async def test_upload_audio_pcm_converted():
    pcm = struct.pack("<" + "h" * 10, *range(10))
    items = [Audio(content=pcm, mime_type="audio/L16;rate=24000")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "audio_media_id"
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG)
        assert mock_upload.call_args.kwargs["mime_type"] == "audio/wav"
        assert mock_upload.call_args.kwargs["filename"] == "audio.wav"


@pytest.mark.asyncio
async def test_upload_audio_failure_sends_text_fallback():
    items = [Audio(content=b"data", mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
    ):
        mock_upload.return_value = {"error": "fail"}
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, "fallback")
        mock_send_text.assert_called_once()


# === upload_and_send_media_async — single audio (response_audio) ===


@pytest.mark.asyncio
async def test_upload_audio_single_success():
    items = [Audio(content=b"audio_data", mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_single"
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["media_id"] == "media_single"


@pytest.mark.asyncio
async def test_upload_audio_single_failure_no_fallback():
    items = [Audio(content=b"audio_data", mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers._send_media", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = {"error": "upload fail"}
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        # No text fallback, no send — just skip
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_upload_audio_single_empty_bytes():
    # Empty content → get_content_bytes() returns None → skip
    items = [Audio(content=b"")]
    with patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload:
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        mock_upload.assert_not_called()
