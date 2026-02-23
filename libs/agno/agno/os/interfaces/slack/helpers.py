from typing import Any, Dict, List, Optional, Tuple

from agno.media import Audio, File, Image, Video
from agno.tools.slack import SlackTools
from agno.utils.log import log_error


def task_id(agent_name: Optional[str], base_id: str) -> str:
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:20]
        return f"{safe}_{base_id}"
    return base_id


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
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
    return True


def extract_event_context(event: dict) -> Dict[str, Any]:
    return {
        "message_text": event.get("text", ""),
        "channel_id": event.get("channel", ""),
        "user": event.get("user", ""),
        "thread_id": event.get("thread_ts") or event.get("ts", ""),
    }


def download_event_files(
    slack_tools: SlackTools, event: dict
) -> Tuple[List[File], List[Image], List[Video], List[Audio]]:
    files: List[File] = []
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []

    if not event.get("files"):
        return files, images, videos, audio

    for file_info in event["files"]:
        file_id = file_info.get("id")
        filename = file_info.get("name", "file")
        mimetype = file_info.get("mimetype", "application/octet-stream")

        try:
            file_content = slack_tools.download_file_bytes(file_id)
            if file_content is not None:
                if mimetype.startswith("image/"):
                    fmt = mimetype.split("/")[-1]
                    images.append(Image(content=file_content, id=file_id, mime_type=mimetype, format=fmt))
                elif mimetype.startswith("video/"):
                    videos.append(Video(content=file_content, mime_type=mimetype))
                elif mimetype.startswith("audio/"):
                    audio.append(Audio(content=file_content, mime_type=mimetype))
                else:
                    # Slack sends MIME types (e.g. application/zip) that agno's File
                    # rejects. Pass mime_type=None so the file is still delivered.
                    safe_mime = mimetype if mimetype in File.valid_mime_types() else None
                    files.append(File(content=file_content, filename=filename, mime_type=safe_mime))
        except Exception as e:
            log_error(f"Failed to download file {file_id}: {e}")

    return files, images, videos, audio


def upload_response_media(slack_tools: SlackTools, response: Any, channel_id: str, thread_ts: str) -> None:
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
                    slack_tools.upload_file(
                        channel=channel_id,
                        content=content_bytes,
                        filename=getattr(item, "filename", None) or default_name,
                        thread_ts=thread_ts,
                    )
                except Exception as e:
                    log_error(f"Failed to upload {attr.rstrip('s')}: {e}")


def send_slack_message(
    slack_tools: SlackTools, channel: str, thread_ts: str, message: str, italics: bool = False
) -> None:
    if not message or not message.strip():
        return

    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    max_len = 39900  # Slack's limit is 40K; leave room for "[N/M] " batch prefix
    if len(message) <= max_len:
        slack_tools.send_message_thread(channel=channel, text=_format(message), thread_ts=thread_ts)
        return

    message_batches = [message[i : i + max_len] for i in range(0, len(message), max_len)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        slack_tools.send_message_thread(channel=channel, text=_format(batch_message), thread_ts=thread_ts)
