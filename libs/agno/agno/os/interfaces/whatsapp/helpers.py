import base64
import io
import mimetypes
import wave
from dataclasses import dataclass
from typing import Optional

from agno.utils.log import log_info, log_warning
from agno.utils.whatsapp import (
    send_audio_message_async,
    send_document_message_async,
    send_image_message_async,
    send_text_message_async,
    upload_media_async,
)


@dataclass
class ParsedMessage:
    text: str
    image_id: Optional[str] = None
    video_id: Optional[str] = None
    audio_id: Optional[str] = None
    doc_id: Optional[str] = None


def parse_whatsapp_message(message: dict) -> Optional[ParsedMessage]:
    msg_type = message.get("type")

    if msg_type == "text":
        text = message["text"]["body"]
        log_info(text)
        return ParsedMessage(text=text)

    if msg_type == "image":
        return ParsedMessage(
            text=message.get("image", {}).get("caption", "Describe the image"),
            image_id=message["image"]["id"],
        )

    if msg_type == "video":
        return ParsedMessage(
            text=message.get("video", {}).get("caption", "Describe the video"),
            video_id=message["video"]["id"],
        )

    if msg_type == "audio":
        return ParsedMessage(text="Reply to audio", audio_id=message["audio"]["id"])

    if msg_type == "document":
        return ParsedMessage(
            text=message.get("document", {}).get("caption", "Process the document"),
            doc_id=message["document"]["id"],
        )

    # Interactive replies carry the selected option's title and description
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            text = reply.get("title", "")
            log_info(f"Button reply: id={reply.get('id')} title={text}")
            return ParsedMessage(text=text)
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            text = reply.get("title", "")
            description = reply.get("description", "")
            if description:
                text = f"{text}: {description}"
            log_info(f"List reply: id={reply.get('id')} title={text}")
            return ParsedMessage(text=text)
        log_warning(f"Unknown interactive type: {interactive_type}")
        return None

    log_warning(f"Unknown message type: {msg_type}")
    return None


def extract_media_bytes(media_obj) -> Optional[bytes]:
    # Content may arrive as raw bytes or base64-encoded string
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


async def send_whatsapp_message_async(recipient: str, message: str, italics: bool = False) -> None:
    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    # WhatsApp limit is 4096 chars; split at 4000 to leave room for batch prefix
    if len(message) <= 4096:
        await send_text_message_async(recipient=recipient, text=_format(message))
        return

    message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await send_text_message_async(recipient=recipient, text=_format(batch_message))


# Upload each image to Meta, then send with response text as caption
async def upload_response_images_async(response, recipient: str) -> None:
    for img in response.images:
        image_bytes = extract_media_bytes(img)
        if image_bytes:
            media_id = await upload_media_async(media_data=image_bytes, mime_type="image/png", filename="image.png")
            if isinstance(media_id, dict):
                log_warning(f"Image upload failed for user {recipient}: {media_id}")
                await send_whatsapp_message_async(recipient, response.content or "")
                continue
            await send_image_message_async(media_id=media_id, recipient=recipient, text=response.content)
        else:
            log_warning(f"Could not process image content for user {recipient}. Type: {type(img.content)}")
            await send_whatsapp_message_async(recipient, response.content or "")


async def upload_response_files_async(response, recipient: str) -> None:
    for file in response.files:
        file_bytes = extract_media_bytes(file)
        if file_bytes:
            filename = getattr(file, "name", None) or getattr(file, "filename", None) or "document"
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            media_id = await upload_media_async(media_data=file_bytes, mime_type=mime_type, filename=filename)
            if isinstance(media_id, dict):
                log_warning(f"File upload failed for user {recipient}: {media_id}")
                await send_whatsapp_message_async(recipient, response.content or "")
                continue
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
            if isinstance(media_id, dict):
                log_warning(f"Audio upload failed for user {recipient}: {media_id}")
                await send_whatsapp_message_async(recipient, response.content or "")
                continue
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
        if isinstance(media_id, dict):
            log_warning(f"Audio upload failed for user {recipient}: {media_id}")
            return
        await send_audio_message_async(media_id=media_id, recipient=recipient)
    else:
        log_warning(f"Could not process response_audio for user {recipient}.")
