"""Media offloading utilities for uploading media to external storage before DB persistence."""

import asyncio
import hashlib
import mimetypes
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Sequence, Set, Union
from urllib.parse import parse_qs, urlsplit

from agno.media import Audio, File, Image, Video
from agno.media.reference import MediaReference
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


# Query parameters that mark a URL as signed and short-lived (SigV4, GCS, Azure SAS, Supabase).
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

# How much of the caller-supplied session id a storage key carries, leaving room for the media
# id, content hash and extension under the 255-byte filename cap.
_MAX_SESSION_KEY_CHARS = 120


def _is_expiring_url(url: Optional[str]) -> bool:
    """True if the URL carries a signature/expiry that goes stale (a presigned URL)."""
    if not url:
        return False
    return any(name.lower() in _EXPIRING_URL_PARAMS for name in parse_qs(urlsplit(url).query))


def _persistable_url(url: Optional[str]) -> Optional[str]:
    """Return ``url`` if it is safe to write to the database, else None.

    Empty, presigned and ``file://`` URLs are not: they expire, carry credentials, or resolve
    only on the host that wrote them. The read path re-derives one from ``storage_key``.
    """
    if not url or url.startswith("file://") or _is_expiring_url(url):
        return None
    return url


def offload_cache_for(run_response: Any) -> Dict[str, MediaReference]:
    """Per-run map of storage id to reference, kept on the live run across persists.

    Offload runs on a fresh deep copy each time, so without this the next persist uploads the
    same bytes again. It holds references only, and is not a field, so ``to_dict`` never sees it.
    """
    cache: Optional[Dict[str, MediaReference]] = getattr(run_response, "_offload_cache", None)
    if cache is None:
        cache = {}
        run_response._offload_cache = cache
    return cache


def opted_out_media_ids_for(run_response: Any) -> Set[str]:
    """Per-run set of media ids a member refused to persist, kept on the live run.

    Scoping the ids to the run keeps two concurrent runs on one Team independent. Not a field,
    so ``to_dict`` never sees it.
    """
    ids: Optional[Set[str]] = getattr(run_response, "_opted_out_media_ids", None)
    if ids is None:
        ids = set()
        run_response._opted_out_media_ids = ids
    return ids


def collect_opted_out_media_ids(run_response: Any) -> Set[str]:
    """Ids opted out on this run and on every member run nested below it.

    A leaf's opt-out is recorded on whichever team ran the delegation, so a root team that
    read only its own ledger would upload media a sub-team's member had refused.
    """
    ids = set(getattr(run_response, "_opted_out_media_ids", None) or [])
    for member_response in getattr(run_response, "member_responses", None) or []:
        ids.update(collect_opted_out_media_ids(member_response))
    return ids


def _cache_key(media_type: str, mime_type: Optional[str], filename: Optional[str], storage_media_id: str) -> str:
    """Identify a stored object, not just its bytes.

    The key carries an extension derived from the filename or mime type, so the same bytes can
    legitimately produce two objects — an Image and a File — that must not share a reference.
    """
    return f"{media_type}|{mime_type or ''}|{filename or ''}|{storage_media_id}"


def _iter_message_media(message: Message) -> Iterator[Any]:
    """Every media object on a message, including the audio_output that to_dict() serializes."""
    for media_list in [message.images, message.audio, message.videos, message.files]:
        for media in media_list or []:
            yield media
    if message.audio_output is not None:
        yield message.audio_output


def reference_matches_storage(ref: Optional[MediaReference], storage: Union[MediaStorage, AsyncMediaStorage]) -> bool:
    """True if ``storage`` is the backend that minted ``ref``.

    A key only resolves against the backend that wrote it, so reading one team's S3 key
    through a member's local disk returns nothing the model can use.
    """
    if ref is None:
        return False
    backend_name = getattr(storage, "backend_name", None)
    if not backend_name or ref.storage_backend != backend_name or ref.bucket != getattr(storage, "bucket", None):
        return False
    # Two deployments can share a bucket name, so a region both sides name has to agree.
    # Only one side naming it is the common case of relying on the environment's default.
    storage_region = getattr(storage, "region", None)
    return not (ref.region and storage_region) or ref.region == storage_region


def _attach_reference(media: Union[Image, Audio, Video, File], ref: MediaReference) -> None:
    """Point ``media`` at a stored object and drop its inline bytes."""
    media.media_reference = ref  # type: ignore[attr-defined]
    # Surface a URL for frontend access; a dropped one is re-derived from the reference on read.
    media.url = _persistable_url(media.url) or ref.url
    media.content = None  # type: ignore[assignment]


def _drop_history_message_urls(message: Message) -> None:
    """Drop the transient URL a refresh put on already-stored media of a history message.

    History media is skipped by the offload, so the URL scrub :func:`_offload_single_media`
    does on its own early return has to happen here instead.
    """
    for media in _iter_message_media(message):
        if getattr(media, "media_reference", None) is not None:
            media.url = _persistable_url(media.url)


def _download_media_from_url(media: Union[Image, Audio, Video, File]) -> Optional[bytes]:
    """Fetch URL-only media, taking its mime type from the server's declared Content-Type.

    Without a mime type the stored object has no extension and no Content-Type. The url path is
    the fallback for a server that declares only ``application/octet-stream``.
    """
    from agno.media.media import bytes_and_mime_from_url

    content_bytes, declared = bytes_and_mime_from_url(media.url or "")
    if not media.mime_type:
        if declared and declared != "application/octet-stream":
            media.mime_type = declared
        else:
            media.mime_type = mimetypes.guess_type(urlsplit(media.url or "").path)[0] or declared
    return content_bytes


async def _adownload_media_from_url(media: Union[Image, Audio, Video, File]) -> Optional[bytes]:
    """Async variant of :func:`_download_media_from_url`."""
    from agno.media.media import abytes_and_mime_from_url

    content_bytes, declared = await abytes_and_mime_from_url(media.url or "")
    if not media.mime_type:
        if declared and declared != "application/octet-stream":
            media.mime_type = declared
        else:
            media.mime_type = mimetypes.guess_type(urlsplit(media.url or "").path)[0] or declared
    return content_bytes


def _offload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: MediaStorage,
    session_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Upload a single media object to storage and attach a MediaReference."""
    if media.media_reference is not None:
        if media.media_reference.session_id in (None, session_id):
            # Already this session's object; drop the URL this turn's model call signed for it.
            media.url = _persistable_url(media.url)
            return
        # Inherited from another session (a fork): copy it so both can be deleted independently.
        if not reference_matches_storage(media.media_reference, storage):
            return
        try:
            media.content = storage.download(media.media_reference.storage_key)
        except Exception as e:
            log_warning(f"Failed to copy inherited media {getattr(media, 'id', '?')}: {e}")
            return
        media.media_reference = None
        # Cleared with it: the url names the source's object, and the copy gets its own.
        media.url = None

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
        content_bytes = _download_media_from_url(media) if media.url else media.get_content_bytes()

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
    # Scoped to the session and content-addressed, so a reused id never collides and deleting one
    # session's media never reaches another session that sent the same bytes.
    storage_media_id = f"{session_id[:_MAX_SESSION_KEY_CHARS]}-{media_id}-{content_hash[:16]}"

    cache_key = _cache_key(media_type, mime_type, filename, storage_media_id)
    if cache is not None and cache_key in cache:
        # Same object as an earlier persist of this run, which offloads a fresh deep copy each time.
        _attach_reference(media, cache[cache_key])
        return

    backend_name = getattr(storage, "backend_name", None)
    if not backend_name:
        # Checked before the upload so a written object is never left with nothing pointing at it.
        log_warning(f"media_storage has no backend_name, skipping offload of {media_type} {media_id}")
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
        session_id=session_id,
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
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all items in a media list."""
    if not media_list:
        return
    for media in media_list:
        try:
            _offload_single_media(media, storage, session_id, media_type, cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


def _offload_message_media(
    message: Message,
    storage: MediaStorage,
    session_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all media from a single Message."""
    if message.from_history:
        # Already stored; only the signed URL the refresh put on it needs dropping.
        _drop_history_message_urls(message)
        return
    _offload_media_list(message.images, storage, session_id, "image", cache=cache)
    _offload_media_list(message.audio, storage, session_id, "audio", cache=cache)
    _offload_media_list(message.videos, storage, session_id, "video", cache=cache)
    _offload_media_list(message.files, storage, session_id, "file", cache=cache)
    # audio_output is the only output field serialized by Message.to_dict()
    if message.audio_output:
        try:
            _offload_single_media(message.audio_output, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload audio_output: {e}")


def offload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: MediaStorage,
    session_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Upload all media content to external storage, replacing it with a MediaReference.

    Media that is already offloaded or carries no content is skipped.
    """
    # 1. Input media
    if run_response.input is not None:
        _offload_media_list(getattr(run_response.input, "images", None), storage, session_id, "image", cache=cache)
        _offload_media_list(getattr(run_response.input, "videos", None), storage, session_id, "video", cache=cache)
        _offload_media_list(getattr(run_response.input, "audios", None), storage, session_id, "audio", cache=cache)
        _offload_media_list(getattr(run_response.input, "files", None), storage, session_id, "file", cache=cache)

    # 2. Messages
    if run_response.messages:
        for message in run_response.messages:
            _offload_message_media(message, storage, session_id, cache=cache)

    # 3. Top-level output media
    _offload_media_list(getattr(run_response, "images", None), storage, session_id, "image", cache=cache)
    _offload_media_list(getattr(run_response, "videos", None), storage, session_id, "video", cache=cache)
    _offload_media_list(getattr(run_response, "audio", None), storage, session_id, "audio", cache=cache)
    _offload_media_list(getattr(run_response, "files", None), storage, session_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            _offload_single_media(response_audio, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    # 4. Additional input
    if run_response.additional_input:
        for message in run_response.additional_input:
            _offload_message_media(message, storage, session_id, cache=cache)

    # 5. Reasoning messages
    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            _offload_message_media(message, storage, session_id, cache=cache)

    # 6. Member responses (TeamRunOutput only)
    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            offload_run_media(member_response, storage, session_id, cache=cache)


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


async def _aoffload_single_media(
    media: Union[Image, Audio, Video, File],
    storage: AsyncMediaStorage,
    session_id: str,
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Upload a single media object to async storage and attach a MediaReference."""
    if media.media_reference is not None:
        if media.media_reference.session_id in (None, session_id):
            media.url = _persistable_url(media.url)
            return
        # See the sync variant: a fork gets its own copy of what it inherited.
        if not reference_matches_storage(media.media_reference, storage):
            return
        try:
            media.content = await storage.download(media.media_reference.storage_key)
        except Exception as e:
            log_warning(f"Failed to copy inherited media {getattr(media, 'id', '?')}: {e}")
            return
        media.media_reference = None
        # Cleared with it, as in the sync variant.
        media.url = None

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
        content_bytes = await _adownload_media_from_url(media) if media.url else await media.aget_content_bytes()

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
    # Scoped to the session and content-addressed, so a reused id never collides and deleting one
    # session's media never reaches another session that sent the same bytes.
    storage_media_id = f"{session_id[:_MAX_SESSION_KEY_CHARS]}-{media_id}-{content_hash[:16]}"

    cache_key = _cache_key(media_type, mime_type, filename, storage_media_id)
    if cache is not None and cache_key in cache:
        # Same object as an earlier persist of this run, which offloads a fresh deep copy each time.
        _attach_reference(media, cache[cache_key])
        return

    backend_name = getattr(storage, "backend_name", None)
    if not backend_name:
        # Checked before the upload so a written object is never left with nothing pointing at it.
        log_warning(f"media_storage has no backend_name, skipping offload of {media_type} {media_id}")
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
        session_id=session_id,
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
    media_type: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant of :func:`_offload_media_list`."""
    if not media_list:
        return
    for media in media_list:
        try:
            await _aoffload_single_media(media, storage, session_id, media_type, cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload {media_type} {getattr(media, 'id', '?')}: {e}")


async def _aoffload_message_media(
    message: Message,
    storage: AsyncMediaStorage,
    session_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant of :func:`_offload_message_media`."""
    if message.from_history:
        _drop_history_message_urls(message)
        return
    await _aoffload_media_list(message.images, storage, session_id, "image", cache=cache)
    await _aoffload_media_list(message.audio, storage, session_id, "audio", cache=cache)
    await _aoffload_media_list(message.videos, storage, session_id, "video", cache=cache)
    await _aoffload_media_list(message.files, storage, session_id, "file", cache=cache)
    if message.audio_output:
        try:
            await _aoffload_single_media(message.audio_output, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload audio_output: {e}")


async def aoffload_run_media(
    run_response: Union["RunOutput", "TeamRunOutput"],
    storage: AsyncMediaStorage,
    session_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant: upload all media content to external storage."""
    if run_response.input is not None:
        await _aoffload_media_list(
            getattr(run_response.input, "images", None), storage, session_id, "image", cache=cache
        )
        await _aoffload_media_list(
            getattr(run_response.input, "videos", None), storage, session_id, "video", cache=cache
        )
        await _aoffload_media_list(
            getattr(run_response.input, "audios", None), storage, session_id, "audio", cache=cache
        )
        await _aoffload_media_list(getattr(run_response.input, "files", None), storage, session_id, "file", cache=cache)

    if run_response.messages:
        for message in run_response.messages:
            await _aoffload_message_media(message, storage, session_id, cache=cache)

    await _aoffload_media_list(getattr(run_response, "images", None), storage, session_id, "image", cache=cache)
    await _aoffload_media_list(getattr(run_response, "videos", None), storage, session_id, "video", cache=cache)
    await _aoffload_media_list(getattr(run_response, "audio", None), storage, session_id, "audio", cache=cache)
    await _aoffload_media_list(getattr(run_response, "files", None), storage, session_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            await _aoffload_single_media(response_audio, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    if run_response.additional_input:
        for message in run_response.additional_input:
            await _aoffload_message_media(message, storage, session_id, cache=cache)

    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            await _aoffload_message_media(message, storage, session_id, cache=cache)

    member_responses = getattr(run_response, "member_responses", None)
    if member_responses:
        for member_response in member_responses:
            await aoffload_run_media(member_response, storage, session_id, cache=cache)


# ---------------------------------------------------------------------------
# Workflow offload
# ---------------------------------------------------------------------------


def iter_step_outputs(run_response: Any) -> Iterator[Any]:
    """Yield every media-bearing step object on a workflow run.

    Media hangs off ``step_results``, off ``StepOutput.steps`` for the children a container
    step ran, and off ``step_requirements`` while a HITL run is paused.
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
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Offload all media in a WorkflowRunOutput: top-level media, step outputs, and the
    agent/team/nested-workflow runs captured during execution. Already-offloaded media is skipped.
    """
    from agno.run.workflow import WorkflowRunOutput

    _offload_media_list(getattr(run_response, "images", None), storage, session_id, "image", cache=cache)
    _offload_media_list(getattr(run_response, "videos", None), storage, session_id, "video", cache=cache)
    _offload_media_list(getattr(run_response, "audio", None), storage, session_id, "audio", cache=cache)
    _offload_media_list(getattr(run_response, "files", None), storage, session_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            _offload_single_media(response_audio, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    # Step results, including the children nested inside container steps
    for step_output in iter_step_outputs(run_response):
        _offload_media_list(getattr(step_output, "images", None), storage, session_id, "image", cache=cache)
        _offload_media_list(getattr(step_output, "videos", None), storage, session_id, "video", cache=cache)
        _offload_media_list(getattr(step_output, "audio", None), storage, session_id, "audio", cache=cache)
        _offload_media_list(getattr(step_output, "files", None), storage, session_id, "file", cache=cache)

    # Step executor runs: agent/team RunOutputs, or nested workflow runs
    for executor_run in getattr(run_response, "step_executor_runs", None) or []:
        if isinstance(executor_run, WorkflowRunOutput):
            offload_workflow_media(executor_run, storage, session_id, cache=cache)
        else:
            offload_run_media(executor_run, storage, session_id, cache=cache)

    workflow_agent_run = getattr(run_response, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        offload_run_media(workflow_agent_run, storage, session_id, cache=cache)


async def aoffload_workflow_media(
    run_response: Any,
    storage: AsyncMediaStorage,
    session_id: str,
    cache: Optional[Dict[str, MediaReference]] = None,
) -> None:
    """Async variant of offload_workflow_media."""
    from agno.run.workflow import WorkflowRunOutput

    await _aoffload_media_list(getattr(run_response, "images", None), storage, session_id, "image", cache=cache)
    await _aoffload_media_list(getattr(run_response, "videos", None), storage, session_id, "video", cache=cache)
    await _aoffload_media_list(getattr(run_response, "audio", None), storage, session_id, "audio", cache=cache)
    await _aoffload_media_list(getattr(run_response, "files", None), storage, session_id, "file", cache=cache)
    response_audio = getattr(run_response, "response_audio", None)
    if response_audio is not None:
        try:
            await _aoffload_single_media(response_audio, storage, session_id, "audio", cache=cache)
        except Exception as e:
            log_warning(f"Failed to offload response_audio: {e}")

    for step_output in iter_step_outputs(run_response):
        await _aoffload_media_list(getattr(step_output, "images", None), storage, session_id, "image", cache=cache)
        await _aoffload_media_list(getattr(step_output, "videos", None), storage, session_id, "video", cache=cache)
        await _aoffload_media_list(getattr(step_output, "audio", None), storage, session_id, "audio", cache=cache)
        await _aoffload_media_list(getattr(step_output, "files", None), storage, session_id, "file", cache=cache)

    for executor_run in getattr(run_response, "step_executor_runs", None) or []:
        if isinstance(executor_run, WorkflowRunOutput):
            await aoffload_workflow_media(executor_run, storage, session_id, cache=cache)
        else:
            await aoffload_run_media(executor_run, storage, session_id, cache=cache)

    workflow_agent_run = getattr(run_response, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        await aoffload_run_media(workflow_agent_run, storage, session_id, cache=cache)


# ---------------------------------------------------------------------------
# URL refresh utilities
# ---------------------------------------------------------------------------


def refresh_message_media_urls(message: Message, storage: MediaStorage) -> None:
    """Refresh pre-signed URLs for all media with media_reference in a message."""
    for media in _iter_message_media(message):
        ref: Optional[MediaReference] = getattr(media, "media_reference", None)
        if ref is None:
            continue
        if not reference_matches_storage(ref, storage):
            log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
            continue
        try:
            fresh_url = storage.get_url(ref.storage_key)
            # The reference is the durable pointer; media.url is this turn's transient value.
            ref.url = _persistable_url(fresh_url)
            if not fresh_url or fresh_url.startswith("file://"):
                # Model APIs reject file:// and unsigned URLs, so hand them the bytes instead.
                media.content = storage.download(ref.storage_key)
                media.url = None
            else:
                media.url = fresh_url
        except Exception as e:
            log_warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")


async def arefresh_message_media_urls(message: Message, storage: AsyncMediaStorage) -> None:
    """Async: refresh pre-signed URLs for all media with media_reference in a message."""
    for media in _iter_message_media(message):
        ref: Optional[MediaReference] = getattr(media, "media_reference", None)
        if ref is None:
            continue
        if not reference_matches_storage(ref, storage):
            log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
            continue
        try:
            fresh_url = await storage.get_url(ref.storage_key)
            ref.url = _persistable_url(fresh_url)
            if not fresh_url or fresh_url.startswith("file://"):
                media.content = await storage.download(ref.storage_key)
                media.url = None
            else:
                media.url = fresh_url
        except Exception as e:
            log_warning(f"Failed to refresh URL for {getattr(media, 'id', '?')}: {e}")


def iter_run_media(run: Any) -> Iterator[Any]:
    """Yield every media object hanging off a run, across agent/team/workflow shapes."""
    run_input = getattr(run, "input", None)
    for attr in ("images", "videos", "audios", "files"):
        for media in getattr(run_input, attr, None) or []:
            yield media
    for message in getattr(run, "messages", None) or []:
        for attr in ("images", "videos", "audio", "files"):
            for media in getattr(message, attr, None) or []:
                yield media
        audio_output = getattr(message, "audio_output", None)
        if audio_output is not None:
            yield audio_output
    for attr in ("images", "videos", "audio", "files"):
        for media in getattr(run, attr, None) or []:
            yield media
    response_audio = getattr(run, "response_audio", None)
    if response_audio is not None:
        yield response_audio
    for collection in ("additional_input", "reasoning_messages"):
        for message in getattr(run, collection, None) or []:
            for attr in ("images", "videos", "audio", "files"):
                for media in getattr(message, attr, None) or []:
                    yield media
    # Team members
    for member in getattr(run, "member_responses", None) or []:
        yield from iter_run_media(member)
    # Workflow steps, including the children nested inside container steps
    for step_output in iter_step_outputs(run):
        for attr in ("images", "videos", "audio", "files"):
            for media in getattr(step_output, attr, None) or []:
                yield media
    for executor_run in getattr(run, "step_executor_runs", None) or []:
        yield from iter_run_media(executor_run)
    workflow_agent_run = getattr(run, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        yield from iter_run_media(workflow_agent_run)


# ---------------------------------------------------------------------------
# Session media deletion
# ---------------------------------------------------------------------------


def session_media_keys(
    session: Any,
    session_ids: Sequence[str],
    storage: Union[MediaStorage, AsyncMediaStorage],
) -> List[str]:
    """Storage keys these sessions own, read before the rows that name them are deleted.

    The reference is the only record of which object belongs to which session. A run that
    merely inherited a reference names the session that uploaded the object, and is left be.
    """
    keys: List[str] = []
    skipped = 0
    for run in getattr(session, "runs", None) or []:
        for media in iter_run_media(run):
            ref = getattr(media, "media_reference", None)
            if ref is None or not ref.storage_key:
                continue
            if ref.session_id not in session_ids:
                continue
            # A key only resolves against the backend that wrote it.
            if not reference_matches_storage(ref, storage):
                skipped += 1
                continue
            keys.append(ref.storage_key)
    if skipped:
        # Counted rather than reported per reference, so a large session yields one line.
        log_warning(f"{skipped} media objects were stored on another backend, skipping deletion")
    return keys


def delete_media_keys(keys: Sequence[str], storage: MediaStorage) -> None:
    """Best-effort: the rows are already gone, so a storage failure must not fail the delete."""
    unique = list(dict.fromkeys(keys))
    try:
        storage.delete_many(unique)
    except Exception as e:
        log_warning(f"Failed to delete {len(unique)} media objects: {e}")


async def adelete_media_keys(keys: Sequence[str], storage: Union[MediaStorage, AsyncMediaStorage]) -> None:
    """Async variant of :func:`delete_media_keys`."""
    unique = list(dict.fromkeys(keys))
    try:
        if isinstance(storage, AsyncMediaStorage):
            await storage.delete_many(unique)
        else:
            await asyncio.to_thread(storage.delete_many, unique)
    except Exception as e:
        log_warning(f"Failed to delete {len(unique)} media objects: {e}")


def refresh_messages_media(messages: Sequence[Message], storage: Union[MediaStorage, AsyncMediaStorage]) -> None:
    """Re-read offloaded media on messages headed for the model."""
    if isinstance(storage, AsyncMediaStorage):
        raise ValueError("Cannot use sync run() with an AsyncMediaStorage. Use arun() instead.")
    for message in messages:
        refresh_message_media_urls(message, storage)


async def arefresh_messages_media(messages: Sequence[Message], storage: Union[MediaStorage, AsyncMediaStorage]) -> None:
    """Async variant of :func:`refresh_messages_media`."""
    if isinstance(storage, AsyncMediaStorage):
        for message in messages:
            await arefresh_message_media_urls(message, storage)
    else:
        # A sync backend does blocking I/O per message, so keep it off the event loop.
        for message in messages:
            await asyncio.to_thread(refresh_message_media_urls, message, storage)
