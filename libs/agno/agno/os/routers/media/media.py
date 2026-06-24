"""Media fetch router.

Serves stored media to the frontend by re-signing or streaming it from the configured
``media_storage`` backend. Access is scoped two ways: the caller must own the session
(``user_id`` is bound to the JWT subject via ``resolve_db_and_scope``), and the requested
``storage_key`` must actually belong to that session — so owning one session does not grant
access to another session's media.

The frontend stores the ``storage_key`` from a ``media_reference`` (never a presigned URL,
which expires) and calls this endpoint; the server re-signs or streams on every request, so
expiry is never the frontend's problem.
"""

import asyncio
import io
import mimetypes
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from agno.db.base import AsyncBaseDb, SessionType
from agno.media_storage.base import AsyncMediaStorage
from agno.db.utils import resolve_session_type
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import resolve_db_and_scope
from agno.os.schema import NotFoundResponse, UnauthenticatedResponse
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb
from agno.utils.log import log_warning


def _iter_media_objects(run: Any):
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
        yield from _iter_media_objects(member)
    # Workflow steps
    for step_result in getattr(run, "step_results", None) or []:
        for step_output in step_result if isinstance(step_result, list) else [step_result]:
            for attr in ("images", "videos", "audio", "files"):
                for media in getattr(step_output, attr, None) or []:
                    yield media
    for executor_run in getattr(run, "step_executor_runs", None) or []:
        yield from _iter_media_objects(executor_run)
    workflow_agent_run = getattr(run, "workflow_agent_run", None)
    if workflow_agent_run is not None:
        yield from _iter_media_objects(workflow_agent_run)


def _find_media_reference(session: Any, storage_key: str) -> Optional[Any]:
    """Return the MediaReference with this storage_key if it belongs to the session, else None."""
    for run in getattr(session, "runs", None) or []:
        for media in _iter_media_objects(run):
            ref = getattr(media, "media_reference", None)
            if ref is not None and getattr(ref, "storage_key", None) == storage_key:
                return ref
    return None


def get_media_router(
    dbs: dict,
    media_storage: Optional[Any] = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Media"])
    return attach_routes(router=router, dbs=dbs, media_storage=media_storage)


def attach_routes(router: APIRouter, dbs: dict, media_storage: Optional[Any]) -> APIRouter:
    @router.get(
        "/sessions/{session_id}/media/{storage_key:path}",
        status_code=200,
        operation_id="get_session_media",
        summary="Fetch stored media for a session",
        description=(
            "Stream (or, with redirect=true, redirect to a freshly-signed URL for) a piece of "
            "media stored in external media storage. Scoped to the caller's session ownership; the "
            "storage_key must belong to the session."
        ),
        responses={
            401: {"description": "Unauthenticated", "model": UnauthenticatedResponse},
            404: {"description": "Session or media not found", "model": NotFoundResponse},
            501: {"description": "Remote databases are not supported"},
            503: {"description": "Media storage is not configured"},
        },
    )
    async def get_session_media(
        request: Request,
        session_id: str = Path(description="Session ID the media belongs to"),
        storage_key: str = Path(description="Storage key of the media to fetch"),
        session_type: Optional[SessionType] = Query(default=None, alias="type"),
        user_id: Optional[str] = Query(default=None),
        db_id: Optional[str] = Query(default=None),
        table: Optional[str] = Query(default=None),
        redirect: bool = Query(
            default=False, description="Redirect to a freshly-signed URL instead of streaming bytes"
        ),
    ):
        if media_storage is None:
            raise HTTPException(status_code=503, detail="Media storage is not configured on AgentOS")

        db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, table, fallback_user_id=user_id)
        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Media fetch is not supported for remote databases")

        # Ownership: get_session is scoped to the JWT-bound user_id, so a caller can only read
        # sessions they own.
        if session_type is None:
            session_type, _ = await resolve_session_type(db, session_id, session_type, effective_user_id)
            if session_type is None:
                raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

        session: Optional[Any]
        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(  # type: ignore[union-attr]
                session_id=session_id, session_type=session_type, user_id=effective_user_id
            )
        else:
            session = db.get_session(  # type: ignore[union-attr]
                session_id=session_id, session_type=session_type, user_id=effective_user_id
            )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

        # Membership: the key must belong to THIS session, so owning one session doesn't grant
        # access to another session's media.
        ref = _find_media_reference(session, storage_key)
        if ref is None:
            raise HTTPException(status_code=404, detail="Media not found in this session")

        # Only serve media this backend actually offloaded; a backend/bucket mismatch would
        # otherwise surface as a confusing 500.
        backend_name = getattr(media_storage, "backend_name", None)
        ref_backend = getattr(ref, "storage_backend", None)
        if backend_name is not None and ref_backend is not None and ref_backend != backend_name:
            raise HTTPException(status_code=404, detail="Media is not served by the configured storage backend")

        is_async = isinstance(media_storage, AsyncMediaStorage)

        if redirect:
            try:
                url = (
                    await media_storage.get_url(storage_key)
                    if is_async
                    else await asyncio.to_thread(media_storage.get_url, storage_key)
                )
            except Exception as e:
                log_warning(f"Failed to generate media URL for {storage_key}: {e}")
                raise HTTPException(status_code=502, detail="Failed to generate a media URL")
            # A browser can only follow http(s); file:// (local backend) cannot be fetched, so
            # fall through to streaming the bytes instead.
            if url.startswith(("http://", "https://")):
                return RedirectResponse(url)

        # Proxy-stream the bytes (works for local and S3, keeps the bucket private, one CORS surface).
        try:
            data = (
                await media_storage.download(storage_key)
                if is_async
                else await asyncio.to_thread(media_storage.download, storage_key)
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Media object not found")
        except Exception as e:
            # Log the real error for debugging; never echo it (it can leak filesystem paths or bucket internals).
            log_warning(f"Failed to fetch media {storage_key}: {e}")
            raise HTTPException(status_code=502, detail="Failed to fetch media from storage")

        media_type = getattr(ref, "mime_type", None)
        if not media_type:
            media_type = mimetypes.guess_type(storage_key)[0] or "application/octet-stream"
        return StreamingResponse(io.BytesIO(data), media_type=media_type)

    return router
