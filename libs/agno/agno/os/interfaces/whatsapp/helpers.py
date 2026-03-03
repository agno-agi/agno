import base64
import io
import wave
from typing import Optional

from agno.utils.log import log_warning
from agno.utils.whatsapp import (
    send_audio_message_async,
    send_document_message_async,
    send_image_message_async,
    send_text_message_async,
    upload_media_async,
)

_MIME_MAP = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".json": "application/json",
    ".zip": "application/zip",
}


def extract_media_bytes(media_obj) -> Optional[bytes]:
    content = media_obj.content
    if isinstance(content, bytes):
        try:
            decoded_string = content.decode("utf-8")
            return base64.b64decode(decoded_string)
        except (UnicodeDecodeError, Exception):
            return content
    elif isinstance(content, str):
        return base64.b64decode(content)
    return None


def prepare_audio_for_whatsapp(audio_bytes: bytes, mime_type: str, audio_obj) -> tuple:
    """Convert raw PCM audio to WAV for WhatsApp compatibility.

    Gemini TTS returns raw PCM with mime_type like 'audio/L16;rate=24000'.
    WhatsApp requires a proper container format (mp3, ogg, wav, aac, amr).
    """
    WHATSAPP_AUDIO_MIMES = {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg", "audio/wav"}

    if mime_type in WHATSAPP_AUDIO_MIMES:
        fmt = getattr(audio_obj, "format", None) or mime_type.split("/")[-1]
        return audio_bytes, mime_type, f"audio.{fmt}"

    # Raw PCM from Gemini (e.g. "audio/L16;rate=24000") — wrap as WAV
    sample_rate = getattr(audio_obj, "sample_rate", None) or 24000
    channels = getattr(audio_obj, "channels", None) or 1
    if "rate=" in mime_type:
        try:
            sample_rate = int(mime_type.split("rate=")[1].split(";")[0])
        except (ValueError, IndexError):
            pass

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    return buf.getvalue(), "audio/wav", "audio.wav"


def extract_earliest_timestamp(body: dict) -> Optional[int]:
    timestamps = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                ts = msg.get("timestamp")
                if ts:
                    try:
                        timestamps.append(int(ts))
                    except (ValueError, TypeError):
                        pass
    return min(timestamps) if timestamps else None


async def send_whatsapp_message_async(recipient: str, message: str, italics: bool = False) -> None:
    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    if len(message) <= 4096:
        await send_text_message_async(recipient=recipient, text=_format(message))
        return

    message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await send_text_message_async(recipient=recipient, text=_format(batch_message))


async def upload_response_images_async(response, recipient: str) -> None:
    for img in response.images:
        image_bytes = extract_media_bytes(img)
        if image_bytes:
            media_id = await upload_media_async(media_data=image_bytes, mime_type="image/png", filename="image.png")
            await send_image_message_async(media_id=media_id, recipient=recipient, text=response.content)
        else:
            log_warning(f"Could not process image content for user {recipient}. Type: {type(img.content)}")
            await send_whatsapp_message_async(recipient, response.content or "")


async def upload_response_files_async(response, recipient: str) -> None:
    for file in response.files:
        file_bytes = extract_media_bytes(file)
        if file_bytes:
            filename = getattr(file, "name", None) or getattr(file, "filename", None) or "document"
            ext = ""
            if "." in filename:
                ext = "." + filename.rsplit(".", 1)[-1].lower()
            mime_type = _MIME_MAP.get(ext, "application/octet-stream")

            media_id = await upload_media_async(media_data=file_bytes, mime_type=mime_type, filename=filename)
            await send_document_message_async(
                media_id=media_id,
                recipient=recipient,
                filename=filename,
                caption=response.content,
            )
        else:
            log_warning(f"Could not process file content for user {recipient}. Type: {type(file.content)}")
            await send_whatsapp_message_async(recipient, response.content or "")


async def upload_response_audio_async(response, recipient: str) -> None:
    for aud in response.audio:
        audio_bytes = extract_media_bytes(aud)
        if audio_bytes:
            mime_type = getattr(aud, "mime_type", None) or "audio/mpeg"
            audio_bytes, mime_type, filename = prepare_audio_for_whatsapp(audio_bytes, mime_type, aud)
            media_id = await upload_media_async(media_data=audio_bytes, mime_type=mime_type, filename=filename)
            await send_audio_message_async(media_id=media_id, recipient=recipient)
        else:
            log_warning(f"Could not process audio content for user {recipient}. Type: {type(aud.content)}")
            await send_whatsapp_message_async(recipient, response.content or "")


async def upload_response_audio_single_async(audio_obj, recipient: str) -> None:
    audio_bytes = extract_media_bytes(audio_obj)
    if audio_bytes:
        mime_type = getattr(audio_obj, "mime_type", None) or "audio/mpeg"
        audio_bytes, mime_type, filename = prepare_audio_for_whatsapp(audio_bytes, mime_type, audio_obj)
        media_id = await upload_media_async(media_data=audio_bytes, mime_type=mime_type, filename=filename)
        await send_audio_message_async(media_id=media_id, recipient=recipient)
    else:
        log_warning(f"Could not process response_audio for user {recipient}.")
