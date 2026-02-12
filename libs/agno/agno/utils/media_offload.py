"""Media offloading utilities for uploading media to external storage before DB persistence."""

import hashlib
from typing import TYPE_CHECKING, List, Optional, Sequence, Union

from agno.media import Audio, File, Image, Video
from agno.media_storage.base import AsyncMediaStorage, MediaStorage
from agno.media_storage.reference import MediaReference
from agno.models.message import Message
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.session import Session


def _offload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
) -> None:
    """Upload a single media object to storage and attach a MediaReference."""
    # Skip if already offloaded
    if hasattr(media, "media_reference") and media.media_reference is not None:
        return

    # Skip File objects with external (managed by provider, e.g. GeminiFile)
    if isinstance(media, File) and media.external is not None:
        return

    # Get content bytes
    content_bytes: Optional[bytes] = None
    if media.content is not None:
        if isinstance(media.content, bytes):
            content_bytes = media.content
        elif isinstance(media.content, str):
            content_bytes = media.content.encode("utf-8")
    elif media.filepath:
        try:
            with open(media.filepath, "rb") as f:
                content_bytes = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {media.filepath} for offload: {e}")
            return

    # If no content yet and storage wants to persist remote URLs, try downloading
    if content_bytes is None and getattr(storage, "persist_remote_urls", False):
        content_bytes = media.get_content_bytes()

    if content_bytes is None:
        # No content to upload (URL-only media or empty)
        return

    media_id = media.id or "unknown"
    mime_type = media.mime_type
    filename: Optional[str] = None
    if isinstance(media, File) and media.filename:
        filename = media.filename
    elif media.filepath:
        from pathlib import Path

        filename = Path(str(media.filepath)).name

    content_hash = hashlib.sha256(content_bytes).hexdigest()

    storage_key = storage.upload(
        media_id,
        content_bytes,
        mime_type=mime_type,
        filename=filename,
        metadata=getattr(media, "metadata", None),
    )

    url = storage.get_url(storage_key)

    ref = MediaReference(
        media_id=media_id,
        storage_key=storage_key,
        storage_backend=getattr(storage, "backend_name", "unknown"),
        bucket=getattr(storage, "bucket", None),
        region=getattr(storage, "region", None),
        url=url,
        mime_type=mime_type,
        filename=filename,
        size=len(content_bytes),
        content_hash=content_hash,
        media_type=media_type,
        metadata=getattr(media, "metadata", None),
    )

    media.media_reference = ref  # type: ignore[attr-defined]
    # Set URL for frontend access
    if not media.url:
        media.url = url
    # Clear content bytes to save memory / DB space
    media.content = None  # type: ignore[assignment]


def _offload_media_list(
    media_list: Optional[Sequence[Union[Image, Audio, Video, File]]],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
) -> None:
    """Offload all items in a media list."""
    if not media_list:
        return
    for media in media_list:
        try:
            _offload_single_media(media, storage, session_id, run_id, media_type)
        except Exception as e:
            logger.warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


def _offload_message_media(message: Message, storage: MediaStorage, session_id: str, run_id: str) -> None:
    """Offload all media from a single Message."""
    if message.from_history:
        return
    _offload_media_list(message.images, storage, session_id, run_id, "image")
    _offload_media_list(message.audio, storage, session_id, run_id, "audio")
    _offload_media_list(message.videos, storage, session_id, run_id, "video")
    _offload_media_list(message.files, storage, session_id, run_id, "file")
    # audio_output is the only output field serialized by Message.to_dict()
    if message.audio_output:
        try:
            _offload_single_media(message.audio_output, storage, session_id, run_id, "audio")
        except Exception as e:
            logger.warning(f"Failed to offload audio_output: {e}")


def offload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
) -> None:
    """Upload all media content to external storage, replace with MediaReference.

    This function traverses the full RunOutput/TeamRunOutput and offloads all media
    that has content bytes. Media already offloaded (has media_reference) or with no
    content is skipped.
    """
    # 1. Input media
    if run_response.input is not None:
        _offload_media_list(getattr(run_response.input, "images", None), storage, session_id, run_id, "image")
        _offload_media_list(getattr(run_response.input, "videos", None), storage, session_id, run_id, "video")
        _offload_media_list(getattr(run_response.input, "audios", None), storage, session_id, run_id, "audio")
        _offload_media_list(getattr(run_response.input, "files", None), storage, session_id, run_id, "file")

    # 2. Messages
    if run_response.messages:
        for message in run_response.messages:
            _offload_message_media(message, storage, session_id, run_id)

    # 3. Top-level output media
    _offload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image")
    _offload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video")
    _offload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio")
    _offload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file")
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            _offload_single_media(response_audio, storage, session_id, run_id, "audio")
        except Exception as e:
            logger.warning(f"Failed to offload response_audio: {e}")

    # 4. Additional input
    if run_response.additional_input:
        for message in run_response.additional_input:
            _offload_message_media(message, storage, session_id, run_id)

    # 5. Reasoning messages
    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            _offload_message_media(message, storage, session_id, run_id)

    # 6. Member responses (TeamRunOutput only)
    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            offload_run_media(member_response, storage, session_id, run_id)


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


async def _aoffload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
) -> None:
    """Upload a single media object to async storage and attach a MediaReference."""
    if hasattr(media, "media_reference") and media.media_reference is not None:
        return

    if isinstance(media, File) and media.external is not None:
        return

    content_bytes: Optional[bytes] = None
    if media.content is not None:
        if isinstance(media.content, bytes):
            content_bytes = media.content
        elif isinstance(media.content, str):
            content_bytes = media.content.encode("utf-8")
    elif media.filepath:
        try:
            with open(media.filepath, "rb") as f:
                content_bytes = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {media.filepath} for offload: {e}")
            return

    # If no content yet and storage wants to persist remote URLs, try downloading
    if content_bytes is None and getattr(storage, "persist_remote_urls", False):
        content_bytes = media.get_content_bytes()

    if content_bytes is None:
        return

    media_id = media.id or "unknown"
    mime_type = media.mime_type
    filename: Optional[str] = None
    if isinstance(media, File) and media.filename:
        filename = media.filename
    elif media.filepath:
        from pathlib import Path

        filename = Path(str(media.filepath)).name

    content_hash = hashlib.sha256(content_bytes).hexdigest()

    storage_key = await storage.upload(
        media_id,
        content_bytes,
        mime_type=mime_type,
        filename=filename,
        metadata=getattr(media, "metadata", None),
    )

    url = await storage.get_url(storage_key)

    ref = MediaReference(
        media_id=media_id,
        storage_key=storage_key,
        storage_backend=getattr(storage, "backend_name", "unknown"),
        bucket=getattr(storage, "bucket", None),
        region=getattr(storage, "region", None),
        url=url,
        mime_type=mime_type,
        filename=filename,
        size=len(content_bytes),
        content_hash=content_hash,
        media_type=media_type,
        metadata=getattr(media, "metadata", None),
    )

    media.media_reference = ref  # type: ignore[attr-defined]
    if not media.url:
        media.url = url
    media.content = None  # type: ignore[assignment]


async def _aoffload_media_list(
    media_list: Optional[Sequence[Union[Image, Audio, Video, File]]],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
) -> None:
    if not media_list:
        return
    for media in media_list:
        try:
            await _aoffload_single_media(media, storage, session_id, run_id, media_type)
        except Exception as e:
            logger.warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


async def _aoffload_message_media(message: Message, storage: AsyncMediaStorage, session_id: str, run_id: str) -> None:
    if message.from_history:
        return
    await _aoffload_media_list(message.images, storage, session_id, run_id, "image")
    await _aoffload_media_list(message.audio, storage, session_id, run_id, "audio")
    await _aoffload_media_list(message.videos, storage, session_id, run_id, "video")
    await _aoffload_media_list(message.files, storage, session_id, run_id, "file")
    if message.audio_output:
        try:
            await _aoffload_single_media(message.audio_output, storage, session_id, run_id, "audio")
        except Exception as e:
            logger.warning(f"Failed to offload audio_output: {e}")


async def aoffload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
) -> None:
    """Async variant: upload all media content to external storage."""
    if run_response.input is not None:
        await _aoffload_media_list(getattr(run_response.input, "images", None), storage, session_id, run_id, "image")
        await _aoffload_media_list(getattr(run_response.input, "videos", None), storage, session_id, run_id, "video")
        await _aoffload_media_list(getattr(run_response.input, "audios", None), storage, session_id, run_id, "audio")
        await _aoffload_media_list(getattr(run_response.input, "files", None), storage, session_id, run_id, "file")

    if run_response.messages:
        for message in run_response.messages:
            await _aoffload_message_media(message, storage, session_id, run_id)

    await _aoffload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image")
    await _aoffload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video")
    await _aoffload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio")
    await _aoffload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file")
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            await _aoffload_single_media(response_audio, storage, session_id, run_id, "audio")
        except Exception as e:
            logger.warning(f"Failed to offload response_audio: {e}")

    if run_response.additional_input:
        for message in run_response.additional_input:
            await _aoffload_message_media(message, storage, session_id, run_id)

    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            await _aoffload_message_media(message, storage, session_id, run_id)

    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            await aoffload_run_media(member_response, storage, session_id, run_id)


# ---------------------------------------------------------------------------
# URL refresh utilities
# ---------------------------------------------------------------------------


def refresh_message_media_urls(message: Message, storage: MediaStorage) -> None:
    """Refresh pre-signed URLs for all media with media_reference in a message."""
    for media_list in [message.images, message.audio, message.videos, message.files]:
        if media_list:
            for media in media_list:
                if hasattr(media, "media_reference") and media.media_reference is not None:
                    try:
                        fresh_url = storage.get_url(media.media_reference.storage_key)
                        media.media_reference.url = fresh_url
                        if fresh_url.startswith("file://"):
                            # Local file:// URLs are not accepted by model APIs.
                            # Read the bytes so the model adapter can base64-encode them.
                            media.content = storage.download(media.media_reference.storage_key)
                            media.url = None
                        else:
                            media.url = fresh_url
                    except Exception as e:
                        logger.warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")
    # audio_output is the only output field serialized by Message.to_dict()
    if (
        message.audio_output
        and hasattr(message.audio_output, "media_reference")
        and message.audio_output.media_reference is not None
    ):
        try:
            fresh_url = storage.get_url(message.audio_output.media_reference.storage_key)
            message.audio_output.media_reference.url = fresh_url
            if fresh_url.startswith("file://"):
                message.audio_output.content = storage.download(message.audio_output.media_reference.storage_key)
                message.audio_output.url = None
            else:
                message.audio_output.url = fresh_url
        except Exception as e:
            logger.warning(f"Failed to refresh URL for audio_output: {e}")


async def arefresh_message_media_urls(message: Message, storage: AsyncMediaStorage) -> None:
    """Async: refresh pre-signed URLs for all media with media_reference in a message."""
    for media_list in [message.images, message.audio, message.videos, message.files]:
        if media_list:
            for media in media_list:
                if hasattr(media, "media_reference") and media.media_reference is not None:
                    try:
                        fresh_url = await storage.get_url(media.media_reference.storage_key)
                        media.media_reference.url = fresh_url
                        if fresh_url.startswith("file://"):
                            # Local file:// URLs are not accepted by model APIs.
                            # Read the bytes so the model adapter can base64-encode them.
                            media.content = await storage.download(media.media_reference.storage_key)
                            media.url = None
                        else:
                            media.url = fresh_url
                    except Exception as e:
                        logger.warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")
    if (
        message.audio_output
        and hasattr(message.audio_output, "media_reference")
        and message.audio_output.media_reference is not None
    ):
        try:
            fresh_url = await storage.get_url(message.audio_output.media_reference.storage_key)
            message.audio_output.media_reference.url = fresh_url
            if fresh_url.startswith("file://"):
                message.audio_output.content = await storage.download(message.audio_output.media_reference.storage_key)
                message.audio_output.url = None
            else:
                message.audio_output.url = fresh_url
        except Exception as e:
            logger.warning(f"Failed to refresh URL for audio_output: {e}")


def refresh_media_urls(
    session: "Session",
    storage: MediaStorage,
    expires_in: int = 3600,
) -> None:
    """Regenerate expired presigned URLs for all media references in a session.

    Walks all runs in the session and refreshes URLs on every media object that
    has a media_reference. Skips references whose storage_backend doesn't match
    the provided storage's backend_name.
    """
    backend_name = getattr(storage, "backend_name", None)
    if not session.runs:
        return

    for run in session.runs:
        _refresh_run_media_urls(run, storage, backend_name)  # type: ignore[arg-type]


def _refresh_run_media_urls(
    run: Union["RunOutput", "TeamRunOutput"],
    storage: MediaStorage,
    backend_name: Optional[str],
) -> None:
    """Refresh URLs for all media in a single run."""

    def _refresh_media(media: Union[Image, Audio, Video, File]) -> None:
        if not hasattr(media, "media_reference") or media.media_reference is None:
            return
        ref = media.media_reference
        if backend_name and getattr(ref, "storage_backend", None) != backend_name:
            return
        try:
            fresh_url = storage.get_url(ref.storage_key)
            ref.url = fresh_url
            media.url = fresh_url
        except Exception as e:
            logger.warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")

    def _refresh_list(media_list: Optional[Sequence[Union[Image, Audio, Video, File]]]) -> None:
        if not media_list:
            return
        for m in media_list:
            _refresh_media(m)

    def _refresh_message(msg: Message) -> None:
        _refresh_list(msg.images)
        _refresh_list(msg.audio)
        _refresh_list(msg.videos)
        _refresh_list(msg.files)
        if msg.audio_output:
            _refresh_media(msg.audio_output)

    # Input
    if run.input is not None:
        _refresh_list(getattr(run.input, "images", None))
        _refresh_list(getattr(run.input, "videos", None))
        _refresh_list(getattr(run.input, "audios", None))
        _refresh_list(getattr(run.input, "files", None))

    # Messages
    if run.messages:
        for msg in run.messages:
            _refresh_message(msg)

    # Top-level output
    _refresh_list(getattr(run, "images", None))
    _refresh_list(getattr(run, "videos", None))
    _refresh_list(getattr(run, "audio", None))
    _refresh_list(getattr(run, "files", None))
    _response_audio = getattr(run, "response_audio", None)
    if _response_audio is not None:
        _refresh_media(_response_audio)

    # Additional input / reasoning
    if run.additional_input:
        for msg in run.additional_input:
            _refresh_message(msg)
    if run.reasoning_messages:
        for msg in run.reasoning_messages:
            _refresh_message(msg)

    # Member responses (TeamRunOutput)
    member_responses: Optional[List] = getattr(run, "member_responses", None)
    if member_responses:
        for member_run in member_responses:
            _refresh_run_media_urls(member_run, storage, backend_name)
