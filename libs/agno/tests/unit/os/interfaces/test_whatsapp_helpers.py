import base64
import struct
import wave
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.os.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    extract_media_bytes,
    prepare_audio_for_whatsapp,
    send_whatsapp_message_async,
    upload_and_send_media_async,
)
from agno.os.interfaces.whatsapp.security import extract_earliest_timestamp

_TEST_CONFIG = WhatsAppConfig(access_token="test-token", phone_number_id="123456", verify_token="test-verify")

# === extract_media_bytes ===


def test_extract_media_bytes_base64_encoded_bytes():
    raw = b"hello world"
    encoded = base64.b64encode(raw)
    media_obj = SimpleNamespace(content=encoded)
    result = extract_media_bytes(media_obj)
    assert result == raw


def test_extract_media_bytes_raw_binary():
    raw = b"\x89PNG\r\n\x1a\n\x00"
    media_obj = SimpleNamespace(content=raw)
    result = extract_media_bytes(media_obj)
    # Non-UTF8 bytes returned as-is
    assert result == raw


def test_extract_media_bytes_str_input():
    raw = b"test data"
    encoded_str = base64.b64encode(raw).decode("utf-8")
    media_obj = SimpleNamespace(content=encoded_str)
    result = extract_media_bytes(media_obj)
    assert result == raw


def test_extract_media_bytes_none_content():
    media_obj = SimpleNamespace(content=None)
    result = extract_media_bytes(media_obj)
    assert result is None


def test_extract_media_bytes_int_content():
    media_obj = SimpleNamespace(content=12345)
    result = extract_media_bytes(media_obj)
    assert result is None


def test_extract_media_bytes_invalid_base64_str():
    media_obj = SimpleNamespace(content="not-valid-base64!!!")
    with pytest.raises(Exception):
        extract_media_bytes(media_obj)


# === prepare_audio_for_whatsapp ===


def test_prepare_audio_passthrough_supported_mime():
    audio_bytes = b"\xff\xfb\x90\x00"
    audio_obj = SimpleNamespace(format="mp3")
    result_bytes, result_mime, result_filename = prepare_audio_for_whatsapp(audio_bytes, "audio/mpeg", audio_obj)
    assert result_bytes == audio_bytes
    assert result_mime == "audio/mpeg"
    assert result_filename == "audio.mp3"


def test_prepare_audio_passthrough_wav():
    audio_bytes = b"RIFF\x00\x00\x00\x00WAVE"
    audio_obj = SimpleNamespace(format="wav")
    result_bytes, result_mime, result_filename = prepare_audio_for_whatsapp(audio_bytes, "audio/wav", audio_obj)
    assert result_bytes == audio_bytes
    assert result_mime == "audio/wav"


def test_prepare_audio_passthrough_no_format_attr():
    audio_bytes = b"\x00\x00\x00\x1cftypisom"
    audio_obj = SimpleNamespace()
    result_bytes, result_mime, result_filename = prepare_audio_for_whatsapp(audio_bytes, "audio/mp4", audio_obj)
    assert result_filename == "audio.mp4"


def test_prepare_audio_pcm_to_wav_conversion():
    # Raw 16-bit PCM samples
    pcm_data = struct.pack("<" + "h" * 100, *range(100))
    audio_obj = SimpleNamespace()
    result_bytes, result_mime, result_filename = prepare_audio_for_whatsapp(pcm_data, "audio/L16;rate=24000", audio_obj)
    assert result_mime == "audio/wav"
    assert result_filename == "audio.wav"
    # Verify valid WAV header
    buf = BytesIO(result_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 24000
        assert wf.getsampwidth() == 2
        assert wf.readframes(100) == pcm_data


def test_prepare_audio_pcm_custom_rate_from_obj():
    pcm_data = struct.pack("<" + "h" * 50, *range(50))
    audio_obj = SimpleNamespace(sample_rate=16000, channels=2)
    result_bytes, result_mime, result_filename = prepare_audio_for_whatsapp(pcm_data, "audio/raw", audio_obj)
    buf = BytesIO(result_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 2


def test_prepare_audio_pcm_rate_from_malformed_mime():
    pcm_data = struct.pack("<" + "h" * 10, *range(10))
    audio_obj = SimpleNamespace()
    # Missing rate value after "rate="
    result_bytes, result_mime, _ = prepare_audio_for_whatsapp(pcm_data, "audio/L16;rate=", audio_obj)
    assert result_mime == "audio/wav"
    # Should fall back to default 24000
    buf = BytesIO(result_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getframerate() == 24000


# === extract_earliest_timestamp ===


def test_extract_earliest_timestamp_single_message():
    body = {
        "entry": [{"changes": [{"value": {"messages": [{"timestamp": "1700000000"}]}}]}],
    }
    assert extract_earliest_timestamp(body) == 1700000000


def test_extract_earliest_timestamp_multiple_messages():
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"timestamp": "1700000300"},
                                {"timestamp": "1700000100"},
                                {"timestamp": "1700000200"},
                            ]
                        }
                    }
                ]
            }
        ],
    }
    assert extract_earliest_timestamp(body) == 1700000100


def test_extract_earliest_timestamp_no_messages():
    body = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    assert extract_earliest_timestamp(body) is None


def test_extract_earliest_timestamp_empty_body():
    assert extract_earliest_timestamp({}) is None


def test_extract_earliest_timestamp_invalid_timestamps():
    body = {
        "entry": [{"changes": [{"value": {"messages": [{"timestamp": "not_a_number"}]}}]}],
    }
    assert extract_earliest_timestamp(body) is None


def test_extract_earliest_timestamp_mixed_valid_invalid():
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"timestamp": "bad"},
                                {"timestamp": "1700000500"},
                            ]
                        }
                    }
                ]
            }
        ],
    }
    assert extract_earliest_timestamp(body) == 1700000500


def test_extract_earliest_timestamp_missing_fields():
    body = {"entry": [{"changes": [{"value": {}}]}]}
    assert extract_earliest_timestamp(body) is None


# === send_whatsapp_message_async ===


@pytest.mark.asyncio
async def test_send_message_short():
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "short message", _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text="short message", config=_TEST_CONFIG)


@pytest.mark.asyncio
async def test_send_message_exactly_4096():
    msg = "x" * 4096
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", msg, _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text=msg, config=_TEST_CONFIG)


@pytest.mark.asyncio
async def test_send_message_4097_batched():
    msg = "x" * 4097
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", msg, _TEST_CONFIG)
        # 4097 chars → 2 batches (4000 + 97)
        assert mock_send.call_count == 2
        first_text = mock_send.call_args_list[0].kwargs["text"]
        assert first_text.startswith("[1/2]")
        second_text = mock_send.call_args_list[1].kwargs["text"]
        assert second_text.startswith("[2/2]")


@pytest.mark.asyncio
async def test_send_message_italics():
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "line1\nline2", _TEST_CONFIG, italics=True)
        sent_text = mock_send.call_args.kwargs["text"]
        assert sent_text == "_line1_\n_line2_"


@pytest.mark.asyncio
async def test_send_message_empty():
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send:
        await send_whatsapp_message_async("123", "", _TEST_CONFIG)
        mock_send.assert_called_once_with(recipient="123", text="", config=_TEST_CONFIG)


# === upload_and_send_media_async — images ===


@pytest.mark.asyncio
async def test_upload_images_success():
    img_bytes = base64.b64encode(b"fake_png")
    items = [SimpleNamespace(content=img_bytes)]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
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
    img_bytes = base64.b64encode(b"fake_png")
    items = [SimpleNamespace(content=img_bytes)]
    long_caption = "x" * 1500
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_123"
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, long_caption)
        sent_caption = mock_send.call_args.kwargs["caption"]
        assert len(sent_caption) == 1024
        assert sent_caption.endswith("...")


@pytest.mark.asyncio
async def test_upload_images_upload_failure_sends_text_fallback():
    img_bytes = base64.b64encode(b"fake_png")
    items = [SimpleNamespace(content=img_bytes)]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send_text,
    ):
        mock_upload.return_value = {"error": "upload failed"}
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, "fallback text")
        mock_send_text.assert_called_once()


@pytest.mark.asyncio
async def test_upload_images_none_bytes_sends_text_fallback():
    items = [SimpleNamespace(content=42)]
    with patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send_text:
        await upload_and_send_media_async(items, "image", "phone", _TEST_CONFIG, "fallback")
        mock_send_text.assert_called_once()


# === upload_and_send_media_async — documents ===


@pytest.mark.asyncio
async def test_upload_files_pdf_correct_mime():
    file_bytes = base64.b64encode(b"fake_pdf")
    items = [SimpleNamespace(content=file_bytes, name="report.pdf")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
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
    file_bytes = base64.b64encode(b"data")
    items = [SimpleNamespace(content=file_bytes, name="file.qzx7")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "media_789"
        await upload_and_send_media_async(items, "document", "phone", _TEST_CONFIG, "text")
        assert mock_upload.call_args.kwargs["mime_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_upload_files_no_extension():
    file_bytes = base64.b64encode(b"data")
    items = [SimpleNamespace(content=file_bytes, name="document")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "m_id"
        await upload_and_send_media_async(items, "document", "phone", _TEST_CONFIG, "")
        assert mock_upload.call_args.kwargs["mime_type"] == "application/octet-stream"


# === upload_and_send_media_async — audio ===


@pytest.mark.asyncio
async def test_upload_audio_mpeg_passthrough():
    audio_bytes = base64.b64encode(b"\xff\xfb\x90\x00")
    items = [SimpleNamespace(content=audio_bytes, mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
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
    audio_bytes_b64 = base64.b64encode(pcm)
    items = [SimpleNamespace(content=audio_bytes_b64, mime_type="audio/L16;rate=24000")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock),
    ):
        mock_upload.return_value = "audio_media_id"
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG)
        assert mock_upload.call_args.kwargs["mime_type"] == "audio/wav"
        assert mock_upload.call_args.kwargs["filename"] == "audio.wav"


@pytest.mark.asyncio
async def test_upload_audio_failure_sends_text_fallback():
    audio_bytes = base64.b64encode(b"data")
    items = [SimpleNamespace(content=audio_bytes, mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_text_message_async", new_callable=AsyncMock) as mock_send_text,
    ):
        mock_upload.return_value = {"error": "fail"}
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, "fallback")
        mock_send_text.assert_called_once()


# === upload_and_send_media_async — single audio (response_audio) ===


@pytest.mark.asyncio
async def test_upload_audio_single_success():
    audio_bytes = base64.b64encode(b"audio_data")
    items = [SimpleNamespace(content=audio_bytes, mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "media_single"
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["media_id"] == "media_single"


@pytest.mark.asyncio
async def test_upload_audio_single_failure_no_fallback():
    audio_bytes = base64.b64encode(b"audio_data")
    items = [SimpleNamespace(content=audio_bytes, mime_type="audio/mpeg")]
    with (
        patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload,
        patch("agno.os.interfaces.whatsapp.helpers.send_media_message_async", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = {"error": "upload fail"}
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        # No text fallback, no send — just skip
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_upload_audio_single_none_bytes():
    items = [SimpleNamespace(content=999)]
    with patch("agno.os.interfaces.whatsapp.helpers.upload_media_async", new_callable=AsyncMock) as mock_upload:
        await upload_and_send_media_async(items, "audio", "phone", _TEST_CONFIG, send_text_fallback=False)
        mock_upload.assert_not_called()
