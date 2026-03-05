import io
import mimetypes
import os
from dataclasses import dataclass
from typing import Optional, Union

import httpx

from agno.media import File
from agno.utils.audio import pcm_to_wav_bytes
from agno.utils.log import log_error, log_info, log_warning

_BASE_URL = "https://graph.facebook.com"
_API_VERSION = "v22.0"


@dataclass
class WhatsAppConfig:
    # Resolved once at startup by attach_routes; passed to all helpers
    access_token: str
    phone_number_id: str
    verify_token: Optional[str] = None

    @classmethod
    def init(
        cls,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
    ) -> "WhatsAppConfig":
        token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        v_token = verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN")
        if not token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not set. Set the environment variable or pass access_token.")
        if not phone_id:
            raise ValueError(
                "WHATSAPP_PHONE_NUMBER_ID is not set. Set the environment variable or pass phone_number_id."
            )
        return cls(access_token=token, phone_number_id=phone_id, verify_token=v_token)

    def messages_url(self) -> str:
        return f"{_BASE_URL}/{_API_VERSION}/{self.phone_number_id}/messages"

    def media_url(self) -> str:
        return f"{_BASE_URL}/{_API_VERSION}/{self.phone_number_id}/media"

    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass
class MessageContent:
    text: str
    image_id: Optional[str] = None
    video_id: Optional[str] = None
    audio_id: Optional[str] = None
    doc_id: Optional[str] = None


def extract_message_content(message: dict) -> Optional[MessageContent]:
    msg_type = message.get("type")

    if msg_type == "text":
        text = message["text"]["body"]
        log_info(text)
        return MessageContent(text=text)

    if msg_type == "image":
        return MessageContent(
            text=message.get("image", {}).get("caption", "Describe the image"),
            image_id=message["image"]["id"],
        )

    if msg_type == "video":
        return MessageContent(
            text=message.get("video", {}).get("caption", "Describe the video"),
            video_id=message["video"]["id"],
        )

    if msg_type == "audio":
        return MessageContent(text="Reply to audio", audio_id=message["audio"]["id"])

    if msg_type == "document":
        return MessageContent(
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
            return MessageContent(text=text)
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            text = reply.get("title", "")
            description = reply.get("description", "")
            if description:
                text = f"{text}: {description}"
            log_info(f"List reply: id={reply.get('id')} title={text}")
            return MessageContent(text=text)
        log_warning(f"Unknown interactive type: {interactive_type}")
        return None

    log_warning(f"Unknown message type: {msg_type}")
    return None


_WHATSAPP_AUDIO_MIMES = {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg", "audio/wav"}


async def get_media_async(media_id: str, config: WhatsAppConfig) -> Union[dict, bytes]:
    url = f"{_BASE_URL}/{_API_VERSION}/{media_id}"
    headers = config.auth_headers()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        media_url = data.get("url")
    except httpx.HTTPError as e:
        return {"error": str(e)}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, headers=headers)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as e:
        return {"error": str(e)}


async def upload_media_async(
    media_data: bytes, mime_type: str, filename: str, config: WhatsAppConfig
) -> Union[str, dict]:
    url = config.media_url()
    headers = config.auth_headers()
    data = {"messaging_product": "whatsapp", "type": mime_type}

    try:
        file_data = io.BytesIO(media_data)
        files = {"file": (filename, file_data, mime_type)}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            json_resp = response.json()
            result_id = json_resp.get("id")
            if not result_id:
                return {"error": "Media ID not found in response", "response": json_resp}
            return result_id
    except httpx.HTTPError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


async def _send_text(recipient: str, text: str, config: WhatsAppConfig, preview_url: bool = False) -> None:
    url = config.messages_url()
    headers = config.auth_headers()

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": preview_url, "body": text},
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log_error(f"Failed to send WhatsApp text message: {e}")
        log_error(f"Error response: {e.response.text}")
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp text message: {str(e)}")
        raise


async def _send_media(
    media_type: str,
    media_id: str,
    recipient: str,
    config: WhatsAppConfig,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> None:
    url = config.messages_url()
    headers = config.auth_headers()

    media_payload: dict = {"id": media_id}
    if caption:
        media_payload["caption"] = caption
    if filename and media_type == "document":
        media_payload["filename"] = filename

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": media_type,
        media_type: media_payload,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log_error(f"Failed to send WhatsApp {media_type} message: {e}")
        log_error(f"Error response: {e.response.text}")
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp {media_type} message: {str(e)}")
        raise


async def typing_indicator_async(message_id: Optional[str], config: WhatsAppConfig) -> Optional[dict]:
    if not message_id:
        return None

    url = config.messages_url()
    headers = config.auth_headers()
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}
    return None


async def send_whatsapp_message_async(
    recipient: str, message: str, config: WhatsAppConfig, italics: bool = False
) -> None:
    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    # WhatsApp limit is 4096 chars; split at 4000 to leave room for batch prefix
    if len(message) <= 4096:
        await _send_text(recipient=recipient, text=_format(message), config=config)
        return

    message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await _send_text(recipient=recipient, text=_format(batch_message), config=config)


async def upload_and_send_media_async(
    media_items: list,
    media_type: str,
    recipient: str,
    config: WhatsAppConfig,
    response_content: Optional[str] = None,
    send_text_fallback: bool = True,
) -> None:
    for item in media_items:
        raw_bytes = item.get_content_bytes()
        if not raw_bytes:
            log_warning(f"Could not process {media_type} content for user {recipient}. Type: {type(item.content)}")
            if send_text_fallback:
                await send_whatsapp_message_async(recipient, response_content or "", config)
            continue

        if media_type == "image":
            mime_type, filename = "image/png", "image.png"
        elif media_type == "document":
            filename = item.name or item.filename or "document"
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        elif media_type == "audio":
            mime_type = item.mime_type or "audio/mpeg"
            if mime_type.split(";")[0] in _WHATSAPP_AUDIO_MIMES:
                fmt = item.format or mime_type.split("/")[-1]
                filename = f"audio.{fmt}"
            else:
                # Raw PCM (e.g. Gemini TTS "audio/L16;rate=24000") — wrap as WAV
                raw_bytes = pcm_to_wav_bytes(raw_bytes, channels=item.channels, rate=item.sample_rate)
                mime_type, filename = "audio/wav", "audio.wav"
        else:
            mime_type, filename = "application/octet-stream", media_type

        mid = await upload_media_async(media_data=raw_bytes, mime_type=mime_type, filename=filename, config=config)
        if isinstance(mid, dict):
            log_warning(f"{media_type.title()} upload failed for user {recipient}: {mid}")
            if send_text_fallback:
                await send_whatsapp_message_async(recipient, response_content or "", config)
            continue

        # Caption only for image/document; audio has no caption field
        # WhatsApp caps captions at 1024 chars — truncate explicitly
        caption = response_content if media_type in ("image", "document") else None
        if caption and len(caption) > 1024:
            caption = caption[:1021] + "..."
        await _send_media(
            media_type=media_type,
            media_id=mid,
            recipient=recipient,
            config=config,
            caption=caption,
            filename=filename if media_type == "document" else None,
        )
