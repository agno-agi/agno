from typing import Any, Dict, List, Optional, Tuple

import httpx

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error


def task_id(agent_name: Optional[str], base_id: str) -> str:
    # Prefix card IDs per agent so concurrent tool calls from different
    # team members don't collide in the Slack stream
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:20]
        return f"{safe}_{base_id}"
    return base_id


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
    # Return name only for team members (not leader) to prefix task card
    # labels like "Researcher: web_search" for disambiguation
    name = getattr(chunk, "agent_name", None)
    if name and isinstance(name, str) and name != entity_name:
        return name
    return None


def should_respond(event: dict, reply_to_mentions_only: bool) -> bool:
    event_type = event.get("type")
    if event_type not in ("app_mention", "message"):
        return False
    channel_type = event.get("channel_type", "")
    is_dm = channel_type == "im"
    if reply_to_mentions_only and event_type == "message" and not is_dm:
        return False
    # When responding to all messages, skip app_mention to avoid duplicates.
    # Slack fires both app_mention and message for the same @mention — the
    # message event already covers it.
    if not reply_to_mentions_only and event_type == "app_mention" and not is_dm:
        return False
    return True


def extract_event_context(event: dict) -> Dict[str, Any]:
    return {
        "message_text": event.get("text", ""),
        "channel_id": event.get("channel", ""),
        "user": event.get("user", ""),
        # Prefer existing thread; fall back to message ts for new conversations
        "thread_id": event.get("thread_ts") or event.get("ts", ""),
    }


async def download_event_files_async(
    token: str, event: dict, max_file_size: int
) -> Tuple[List[File], List[Image], List[Video], List[Audio], List[str]]:
    files: List[File] = []
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    skipped: List[str] = []

    if not event.get("files"):
        return files, images, videos, audio, skipped

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        for file_info in event["files"]:
            file_id = file_info.get("id")
            filename = file_info.get("name", "file")
            mimetype = file_info.get("mimetype", "application/octet-stream")
            file_size = file_info.get("size", 0)

            if file_size > max_file_size:
                limit_mb = max_file_size / (1024 * 1024)
                actual_mb = file_size / (1024 * 1024)
                skipped.append(f"{filename} ({actual_mb:.1f}MB — exceeds {limit_mb:.0f}MB limit)")
                continue

            url_private = file_info.get("url_private")
            if not url_private:
                continue

            try:
                resp = await client.get(url_private, headers=headers, timeout=30)
                resp.raise_for_status()
                file_content = resp.content

                if mimetype.startswith("image/"):
                    fmt = mimetype.split("/")[-1]
                    images.append(Image(content=file_content, id=file_id, mime_type=mimetype, format=fmt))
                elif mimetype.startswith("video/"):
                    videos.append(Video(content=file_content, mime_type=mimetype))
                elif mimetype.startswith("audio/"):
                    audio.append(Audio(content=file_content, mime_type=mimetype))
                else:
                    # Pass None for unsupported types to avoid File validation errors
                    safe_mime = mimetype if mimetype in File.valid_mime_types() else None
                    files.append(File(content=file_content, filename=filename, mime_type=safe_mime))
            except Exception as e:
                log_error(f"Failed to download file {file_id}: {e}")

    return files, images, videos, audio, skipped


async def upload_response_media_async(async_client: Any, response: Any, channel_id: str, thread_ts: str) -> None:
    media_attrs = [
        ("images", "image.png"),
        ("files", "file"),
        ("videos", "video.mp4"),
        ("audio", "audio.mp3"),
    ]
    for attr, default_name in media_attrs:
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            content_bytes = item.get_content_bytes()
            if content_bytes:
                try:
                    await async_client.files_upload_v2(
                        channel=channel_id,
                        content=content_bytes,
                        filename=getattr(item, "filename", None) or default_name,
                        thread_ts=thread_ts,
                    )
                except Exception as e:
                    log_error(f"Failed to upload {attr.rstrip('s')}: {e}")


async def send_slack_message_async(
    async_client: Any, channel: str, thread_ts: str, message: str, italics: bool = False
) -> None:
    if not message or not message.strip():
        return

    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    # Under Slack's 40K char limit with margin for batch prefix overhead
    max_len = 39900
    if len(message) <= max_len:
        await async_client.chat_postMessage(channel=channel, text=_format(message), thread_ts=thread_ts)
        return

    message_batches = [message[i : i + max_len] for i in range(0, len(message), max_len)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await async_client.chat_postMessage(channel=channel, text=_format(batch_message), thread_ts=thread_ts)
