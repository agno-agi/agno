"""Media offloading utilities for uploading media to external storage before DB persistence."""

import hashlib
from typing import TYPE_CHECKING, Any, Dict, Iterator, Optional, Sequence, Union
from urllib.parse import parse_qs, urlsplit

from agno.media import Audio, File, Image, Video
from agno.media.reference import MediaReference
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


# Query parameters that mark a URL as signed and short-lived. The list spans the schemes a
# MediaStorage backend can hand back: SigV4 (S3, MinIO, R2, Spaces), GCS V2 and V4, Azure
# Blob SAS, and Supabase. Erring towards "expiring" is the safe direction — a false positive
# costs one re-sign on read, a false negative writes a credential into the database.
_EXPIRING_URL_PARAMS = frozenset(
    {
        "x-amz-signature",
        "x-amz-expires",
        "x-goog-signature",
        "x-goog-expires",
        "signature",
        "expires",
        "sig",
        "se",
        "token",
    }
)


def _is_expiring_url(url: Optional[str]) -> bool:
    """True if the URL carries a signature/expiry that goes stale (a presigned URL)."""
    if not url:
        return False
    return any(name.lower() in _EXPIRING_URL_PARAMS for name in parse_qs(urlsplit(url).query))


def _persistable_url(url: Optional[str]) -> Optional[str]:
    """Return ``url`` if it is safe to write to the database, else None.

    Three kinds are not: an empty one (GCS with non-signing credentials returns ``""``), a
    presigned one (it expires and carries credentials), and a ``file://`` one (it resolves
    only on the host that wrote it, so a shared database gets a link nothing else can
    follow). The read path re-derives a URL from ``storage_key`` on demand.
    """
    if not url or url.startswith("file://") or _is_expiring_url(url):
        return None
    return url


def offload_cache_for(run_response: Any) -> Dict[str, MediaReference]:
    """Per-run map of storage id to reference, kept on the live run across persists.

    Offload runs on a fresh deep copy each time, so the ``media_reference`` it attaches is
    thrown away with the copy and the next persist uploads the same bytes again — a HITL run
    that pauses three times sent its media five times over. The cache survives because it
    lives on the run the caller holds. It stores references, never media, so the promise that
    offload does not mutate the caller's media objects is untouched, and it is not a declared
    dataclass field so ``to_dict`` never sees it.
    """
    cache: Optional[Dict[str, MediaReference]] = getattr(run_response, "_offload_cache", None)
    if cache is None:
        cache = {}
        run_response._offload_cache = cache
    return cache


def _cache_key(media_type: str, mime_type: Optional[str], filename: Optional[str], storage_media_id: str) -> str:
    """Identify a stored object, not just its bytes.

    The storage key ends in an extension derived from the filename or the mime type, so the
    same id and the same bytes can legitimately produce two different objects — an Image and a
    File, say. Keying on the content-addressed id alone handed the second one the first one's
    reference and skipped its upload, so its object was never written.
    """
    return f"{media_type}|{mime_type or ''}|{filename or ''}|{storage_media_id}"


def _attach_reference(media: Union[Image, Audio, Video, File], ref: MediaReference) -> None:
    """Point ``media`` at a stored object and drop its inline bytes."""
    media.media_reference = ref  # type: ignore[attr-defined]
    # Surface the URL for frontend access. _persistable_url has already dropped the ones a
    # browser or a model API cannot fetch, so readers of those go through the backend instead.
    if not media.url:
        media.url = ref.url
    # Clear content bytes to save memory / DB space
    media.content = None  # type: ignore[assignment]


def _offload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
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
            log_warning(f"Failed to read file {media.filepath} for offload: {e}")
            return

    # If no content yet and storage wants to persist remote URLs, try downloading
    if content_bytes is None and getattr(storage, "persist_remote_urls", False):
        content_bytes = media.get_content_bytes()

    if content_bytes is None:
        # No content to upload (URL-only media or empty)
        return

    media_id = media.id
    if not media_id:
        from uuid import uuid4

        media_id = str(uuid4())
        media.id = media_id
    mime_type = media.mime_type
    filename: Optional[str] = None
    if isinstance(media, File) and media.filename:
        filename = media.filename
    elif media.filepath:
        from pathlib import Path

        filename = Path(str(media.filepath)).name

    content_hash = hashlib.sha256(content_bytes).hexdigest()
    # Content-address the storage id so distinct payloads never collide on a reused id
    storage_media_id = f"{media_id}-{content_hash[:16]}"

    cache_key = _cache_key(media_type, mime_type, filename, storage_media_id)
    if cache is not None and cache_key in cache:
        # Same object as an earlier persist of this run: it is already in the bucket. The
        # media_reference skip above cannot catch this because every persist offloads a fresh
        # deep copy, so a paused HITL run re-sent all of its media on every gate. Attach the
        # reference the first upload produced instead.
        _attach_reference(media, cache[cache_key])
        return

    backend_name = getattr(storage, "backend_name", None)
    if not backend_name:
        # Checked before the upload, not after: building the reference is what needs this, and
        # failing there would leave the object written to the bucket with nothing pointing at
        # it while the row silently kept its base64.
        log_warning(f"media_storage has no backend_name; skipping offload of {media_type} {media_id}")
        return

    storage_key = storage.upload(
        storage_media_id,
        content_bytes,
        mime_type=mime_type,
        filename=filename,
        metadata=getattr(media, "metadata", None),
    )

    url = storage.get_url(storage_key)
    persisted_url = _persistable_url(url)

    ref = MediaReference(
        media_id=media_id,
        storage_key=storage_key,
        storage_backend=backend_name,
        bucket=getattr(storage, "bucket", None),
        region=getattr(storage, "region", None),
        url=persisted_url,
        mime_type=mime_type,
        filename=filename,
        size=len(content_bytes),
        content_hash=content_hash,
        media_type=media_type,
        metadata=getattr(media, "metadata", None),
    )

    if cache is not None:
        cache[cache_key] = ref
    _attach_reference(media, ref)


def _offload_media_list(
    media_list: Optional[Sequence[Union[Image, Audio, Video, File]]],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all items in a media list."""
    if not media_list:
        return
    for media in media_list:
        try:
            _offload_single_media(media, storage, session_id, run_id, media_type, cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


def _offload_message_media(
    message: Message,
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all media from a single Message."""
    if message.from_history:
        return
    _offload_media_list(message.images, storage, session_id, run_id, "image", cache=cache)
    _offload_media_list(message.audio, storage, session_id, run_id, "audio", cache=cache)
    _offload_media_list(message.videos, storage, session_id, run_id, "video", cache=cache)
    _offload_media_list(message.files, storage, session_id, run_id, "file", cache=cache)
    # audio_output is the only output field serialized by Message.to_dict()
    if message.audio_output:
        try:
            _offload_single_media(message.audio_output, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload audio_output: {e}")


def offload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Upload all media content to external storage, replace with MediaReference.

    This function traverses the full RunOutput/TeamRunOutput and offloads all media
    that has content bytes. Media already offloaded (has media_reference) or with no
    content is skipped.
    """
    # 1. Input media
    if run_response.input is not None:
        _offload_media_list(
            getattr(run_response.input, "images", None), storage, session_id, run_id, "image", cache=cache
        )
        _offload_media_list(
            getattr(run_response.input, "videos", None), storage, session_id, run_id, "video", cache=cache
        )
        _offload_media_list(
            getattr(run_response.input, "audios", None), storage, session_id, run_id, "audio", cache=cache
        )
        _offload_media_list(
            getattr(run_response.input, "files", None), storage, session_id, run_id, "file", cache=cache
        )

    # 2. Messages
    if run_response.messages:
        for message in run_response.messages:
            _offload_message_media(message, storage, session_id, run_id, cache=cache)

    # 3. Top-level output media
    _offload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image", cache=cache)
    _offload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video", cache=cache)
    _offload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio", cache=cache)
    _offload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            _offload_single_media(response_audio, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    # 4. Additional input
    if run_response.additional_input:
        for message in run_response.additional_input:
            _offload_message_media(message, storage, session_id, run_id, cache=cache)

    # 5. Reasoning messages
    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            _offload_message_media(message, storage, session_id, run_id, cache=cache)

    # 6. Member responses (TeamRunOutput only)
    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            offload_run_media(member_response, storage, session_id, run_id, cache=cache)


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


async def _aoffload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
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
            log_warning(f"Failed to read file {media.filepath} for offload: {e}")
            return

    # If no content yet and storage wants to persist remote URLs, try downloading
    if content_bytes is None and getattr(storage, "persist_remote_urls", False):
        content_bytes = await media.aget_content_bytes()

    if content_bytes is None:
        return

    media_id = media.id
    if not media_id:
        from uuid import uuid4

        media_id = str(uuid4())
        media.id = media_id
    mime_type = media.mime_type
    filename: Optional[str] = None
    if isinstance(media, File) and media.filename:
        filename = media.filename
    elif media.filepath:
        from pathlib import Path

        filename = Path(str(media.filepath)).name

    content_hash = hashlib.sha256(content_bytes).hexdigest()
    # Content-address the storage id so distinct payloads never collide on a reused id
    storage_media_id = f"{media_id}-{content_hash[:16]}"

    cache_key = _cache_key(media_type, mime_type, filename, storage_media_id)
    if cache is not None and cache_key in cache:
        # Same object as an earlier persist of this run: it is already in the bucket. The
        # media_reference skip above cannot catch this because every persist offloads a fresh
        # deep copy, so a paused HITL run re-sent all of its media on every gate. Attach the
        # reference the first upload produced instead.
        _attach_reference(media, cache[cache_key])
        return

    backend_name = getattr(storage, "backend_name", None)
    if not backend_name:
        # Checked before the upload, not after: building the reference is what needs this, and
        # failing there would leave the object written to the bucket with nothing pointing at
        # it while the row silently kept its base64.
        log_warning(f"media_storage has no backend_name; skipping offload of {media_type} {media_id}")
        return

    storage_key = await storage.upload(
        storage_media_id,
        content_bytes,
        mime_type=mime_type,
        filename=filename,
        metadata=getattr(media, "metadata", None),
    )

    url = await storage.get_url(storage_key)
    persisted_url = _persistable_url(url)

    ref = MediaReference(
        media_id=media_id,
        storage_key=storage_key,
        storage_backend=backend_name,
        bucket=getattr(storage, "bucket", None),
        region=getattr(storage, "region", None),
        url=persisted_url,
        mime_type=mime_type,
        filename=filename,
        size=len(content_bytes),
        content_hash=content_hash,
        media_type=media_type,
        metadata=getattr(media, "metadata", None),
    )

    if cache is not None:
        cache[cache_key] = ref
    _attach_reference(media, ref)


async def _aoffload_media_list(
    media_list: Optional[Sequence[Union[Image, Audio, Video, File]]],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    if not media_list:
        return
    for media in media_list:
        try:
            await _aoffload_single_media(media, storage, session_id, run_id, media_type, cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


async def _aoffload_message_media(
    message: Message,
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    if message.from_history:
        return
    await _aoffload_media_list(message.images, storage, session_id, run_id, "image", cache=cache)
    await _aoffload_media_list(message.audio, storage, session_id, run_id, "audio", cache=cache)
    await _aoffload_media_list(message.videos, storage, session_id, run_id, "video", cache=cache)
    await _aoffload_media_list(message.files, storage, session_id, run_id, "file", cache=cache)
    if message.audio_output:
        try:
            await _aoffload_single_media(message.audio_output, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload audio_output: {e}")


async def aoffload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant: upload all media content to external storage."""
    if run_response.input is not None:
        await _aoffload_media_list(
            getattr(run_response.input, "images", None), storage, session_id, run_id, "image", cache=cache
        )
        await _aoffload_media_list(
            getattr(run_response.input, "videos", None), storage, session_id, run_id, "video", cache=cache
        )
        await _aoffload_media_list(
            getattr(run_response.input, "audios", None), storage, session_id, run_id, "audio", cache=cache
        )
        await _aoffload_media_list(
            getattr(run_response.input, "files", None), storage, session_id, run_id, "file", cache=cache
        )

    if run_response.messages:
        for message in run_response.messages:
            await _aoffload_message_media(message, storage, session_id, run_id, cache=cache)

    await _aoffload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image", cache=cache)
    await _aoffload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video", cache=cache)
    await _aoffload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio", cache=cache)
    await _aoffload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            await _aoffload_single_media(response_audio, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    if run_response.additional_input:
        for message in run_response.additional_input:
            await _aoffload_message_media(message, storage, session_id, run_id, cache=cache)

    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            await _aoffload_message_media(message, storage, session_id, run_id, cache=cache)

    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            await aoffload_run_media(member_response, storage, session_id, run_id, cache=cache)


# ---------------------------------------------------------------------------
# Workflow offload
# ---------------------------------------------------------------------------


def iter_step_outputs(run_response: Any) -> Iterator[Any]:
    """Yield every media-bearing step object on a workflow run.

    A workflow run hangs media off three places, and a traversal that reaches only the
    first leaves the rest inline:

    - ``step_results``, one top-level entry per step;
    - ``StepOutput.steps``, where Loop, Condition, Router, Steps and Parallel keep the
      children they ran;
    - ``step_requirements``, where a paused HITL run keeps the input it prepared and the
      output awaiting review — a pause lasts as long as the human takes, so this is the
      one that holds a fat row longest.
    """

    def _walk(step_output: Any) -> Iterator[Any]:
        yield step_output
        for nested in getattr(step_output, "steps", None) or []:
            yield from _walk(nested)

    for step_result in getattr(run_response, "step_results", None) or []:
        for step_output in step_result if isinstance(step_result, list) else [step_result]:
            yield from _walk(step_output)

    for requirement in getattr(run_response, "step_requirements", None) or []:
        step_input = getattr(requirement, "step_input", None)
        if step_input is not None:
            yield step_input
            for previous in (getattr(step_input, "previous_step_outputs", None) or {}).values():
                yield from _walk(previous)
        step_output = getattr(requirement, "step_output", None)
        if step_output is not None:
            yield from _walk(step_output)


def offload_workflow_media(
    run_response: Any,
    storage: MediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all media in a WorkflowRunOutput: top-level media, step outputs, and the
    agent/team/nested-workflow runs captured during execution. Already-offloaded media is skipped."""
    from agno.run.workflow import WorkflowRunOutput

    _offload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image", cache=cache)
    _offload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video", cache=cache)
    _offload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio", cache=cache)
    _offload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            _offload_single_media(response_audio, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    # Step results, including the children nested inside container steps
    for step_output in iter_step_outputs(run_response):
        _offload_media_list(getattr(step_output, "images", None), storage, session_id, run_id, "image", cache=cache)
        _offload_media_list(getattr(step_output, "videos", None), storage, session_id, run_id, "video", cache=cache)
        _offload_media_list(getattr(step_output, "audio", None), storage, session_id, run_id, "audio", cache=cache)
        _offload_media_list(getattr(step_output, "files", None), storage, session_id, run_id, "file", cache=cache)

    # Step executor runs: agent/team RunOutputs, or nested workflow runs
    for executor_run in getattr(run_response, "step_executor_runs", None) or []:
        if isinstance(executor_run, WorkflowRunOutput):
            offload_workflow_media(executor_run, storage, session_id, run_id, cache=cache)
        else:
            offload_run_media(executor_run, storage, session_id, run_id, cache=cache)

    workflow_agent_run = getattr(run_response, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        offload_run_media(workflow_agent_run, storage, session_id, run_id, cache=cache)


async def aoffload_workflow_media(
    run_response: Any,
    storage: AsyncMediaStorage,
    session_id: str,
    run_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant of offload_workflow_media."""
    from agno.run.workflow import WorkflowRunOutput

    await _aoffload_media_list(getattr(run_response, "images", None), storage, session_id, run_id, "image", cache=cache)
    await _aoffload_media_list(getattr(run_response, "videos", None), storage, session_id, run_id, "video", cache=cache)
    await _aoffload_media_list(getattr(run_response, "audio", None), storage, session_id, run_id, "audio", cache=cache)
    await _aoffload_media_list(getattr(run_response, "files", None), storage, session_id, run_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            await _aoffload_single_media(response_audio, storage, session_id, run_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    for step_output in iter_step_outputs(run_response):
        await _aoffload_media_list(
            getattr(step_output, "images", None), storage, session_id, run_id, "image", cache=cache
        )
        await _aoffload_media_list(
            getattr(step_output, "videos", None), storage, session_id, run_id, "video", cache=cache
        )
        await _aoffload_media_list(
            getattr(step_output, "audio", None), storage, session_id, run_id, "audio", cache=cache
        )
        await _aoffload_media_list(
            getattr(step_output, "files", None), storage, session_id, run_id, "file", cache=cache
        )

    for executor_run in getattr(run_response, "step_executor_runs", None) or []:
        if isinstance(executor_run, WorkflowRunOutput):
            await aoffload_workflow_media(executor_run, storage, session_id, run_id, cache=cache)
        else:
            await aoffload_run_media(executor_run, storage, session_id, run_id, cache=cache)

    workflow_agent_run = getattr(run_response, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        await aoffload_run_media(workflow_agent_run, storage, session_id, run_id, cache=cache)


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
                        # The reference is the durable pointer; media.url below is the transient
                        # value this turn's model call uses.
                        media.media_reference.url = _persistable_url(fresh_url)
                        if not fresh_url or fresh_url.startswith("file://"):
                            # Local file:// URLs — and empty/unsigned URLs (e.g. GCS with
                            # non-signing credentials) — are not accepted by model APIs. Read
                            # the bytes so the model adapter can base64-encode them.
                            media.content = storage.download(media.media_reference.storage_key)
                            media.url = None
                        else:
                            media.url = fresh_url
                    except Exception as e:
                        log_warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")
    # audio_output is the only output field serialized by Message.to_dict()
    if (
        message.audio_output
        and hasattr(message.audio_output, "media_reference")
        and message.audio_output.media_reference is not None
    ):
        try:
            fresh_url = storage.get_url(message.audio_output.media_reference.storage_key)
            message.audio_output.media_reference.url = _persistable_url(fresh_url)
            if not fresh_url or fresh_url.startswith("file://"):
                message.audio_output.content = storage.download(message.audio_output.media_reference.storage_key)
                message.audio_output.url = None
            else:
                message.audio_output.url = fresh_url
        except Exception as e:
            log_warning(f"Failed to refresh URL for audio_output: {e}")


async def arefresh_message_media_urls(message: Message, storage: AsyncMediaStorage) -> None:
    """Async: refresh pre-signed URLs for all media with media_reference in a message."""
    for media_list in [message.images, message.audio, message.videos, message.files]:
        if media_list:
            for media in media_list:
                if hasattr(media, "media_reference") and media.media_reference is not None:
                    try:
                        fresh_url = await storage.get_url(media.media_reference.storage_key)
                        # The reference is the durable pointer; media.url below is the transient
                        # value this turn's model call uses.
                        media.media_reference.url = _persistable_url(fresh_url)
                        if not fresh_url or fresh_url.startswith("file://"):
                            # Local file:// URLs — and empty/unsigned URLs (e.g. GCS with
                            # non-signing credentials) — are not accepted by model APIs. Read
                            # the bytes so the model adapter can base64-encode them.
                            media.content = await storage.download(media.media_reference.storage_key)
                            media.url = None
                        else:
                            media.url = fresh_url
                    except Exception as e:
                        log_warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")
    if (
        message.audio_output
        and hasattr(message.audio_output, "media_reference")
        and message.audio_output.media_reference is not None
    ):
        try:
            fresh_url = await storage.get_url(message.audio_output.media_reference.storage_key)
            message.audio_output.media_reference.url = _persistable_url(fresh_url)
            if not fresh_url or fresh_url.startswith("file://"):
                message.audio_output.content = await storage.download(message.audio_output.media_reference.storage_key)
                message.audio_output.url = None
            else:
                message.audio_output.url = fresh_url
        except Exception as e:
            log_warning(f"Failed to refresh URL for audio_output: {e}")
