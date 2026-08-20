"""Media API router — stream or re-sign session media held in external media storage."""

import asyncio
import mimetypes
import re
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import RedirectResponse

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.utils import resolve_session_type
from agno.exceptions import PathSecurityError
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import resolve_db_and_scope
from agno.os.schema import NotFoundResponse, UnauthenticatedResponse
from agno.os.settings import AgnoAPISettings
from agno.os.utils import iter_run_media
from agno.remote.base import RemoteDb
from agno.utils.log import log_warning
from agno.utils.media_offload import reference_matches_storage

# A type/subtype of RFC 9110 tokens and nothing else; the rest is octet-stream.
_MIME_TYPE_PATTERN = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+/[A-Za-z0-9!#$%&'*+.^_`|~-]+")

# Content types a browser can execute on the API origin, re-typed as octet-stream:
# nosniff only blocks execution when the declared type is not already executable.
_ACTIVE_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "text/xml",
    "application/xml",
}


def _find_media_reference(session: Any, storage_key: str) -> Optional[Any]:
    """Return the MediaReference with this storage_key if it belongs to the session, else None."""
    for run in getattr(session, "runs", None) or []:
        for media in iter_run_media(run):
            ref = getattr(media, "media_reference", None)
            if ref is not None and getattr(ref, "storage_key", None) == storage_key:
                return ref
    return None


def get_media_router(
    dbs: dict,
    media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Media"])
    return attach_routes(router=router, dbs=dbs, media_storage=media_storage)


def attach_routes(
    router: APIRouter, dbs: dict, media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]]
) -> APIRouter:
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
            200: {
                "description": "The media bytes, served with the stored mime type",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            401: {"description": "Unauthenticated", "model": UnauthenticatedResponse},
            404: {"description": "Session or media not found", "model": NotFoundResponse},
            500: {"description": "Media storage could not be reached"},
            501: {"description": "Remote databases are not supported"},
            503: {"description": "Media storage is not configured"},
        },
    )
    async def get_session_media(
        request: Request,
        session_id: str = Path(description="Session ID the media belongs to"),
        storage_key: str = Path(description="Storage key of the media to fetch"),
        session_type: Optional[SessionType] = Query(
            default=None,
            description="Session type (agent, team, or workflow). If not provided, auto-detected from session data.",
            alias="type",
        ),
        user_id: Optional[str] = Query(default=None, description="User ID to query session from"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query session from"),
        table: Optional[str] = Query(default=None, description="Table to query session from"),
        redirect: bool = Query(
            default=False, description="Redirect to a freshly-signed URL instead of streaming bytes"
        ),
    ):
        if media_storage is None:
            raise HTTPException(status_code=503, detail="Media storage is not configured on AgentOS")

        db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, table, fallback_user_id=user_id)
        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Media fetch is not supported for remote databases")

        # With user_isolation on, resolve_db_and_scope binds user_id to the JWT subject. Without
        # it the session membership check below is the only thing scoping the fetch.
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

        # Only serve media this backend offloaded, or a mismatch serves a same-named object
        # from the wrong bucket.
        if not reference_matches_storage(ref, media_storage):
            raise HTTPException(status_code=404, detail="Media is not served by the configured storage backend")

        if redirect:
            # Always re-derive the URL from storage_key. The key has just been checked against this
            # session; a stored url is opaque, so honouring it would make this an open redirect.
            try:
                if isinstance(media_storage, AsyncMediaStorage):
                    url = await media_storage.get_url(storage_key)
                else:
                    url = await asyncio.to_thread(media_storage.get_url, storage_key)
            except Exception as e:
                log_warning(f"Failed to generate media URL for {storage_key}: {e}")
                raise HTTPException(status_code=500, detail="Failed to generate a media URL")
            # A browser can only follow http(s); file:// (local backend) cannot be fetched, so
            # fall through to streaming the bytes instead.
            if url.startswith(("http://", "https://")):
                return RedirectResponse(url)

        # Proxy-stream the bytes (works for local and S3, keeps the bucket private, one CORS surface).
        try:
            if isinstance(media_storage, AsyncMediaStorage):
                data = await media_storage.download(storage_key)
            else:
                data = await asyncio.to_thread(media_storage.download, storage_key)
        except (FileNotFoundError, PathSecurityError):
            # A key the backend refuses to resolve is as absent as one that is missing, so a
            # path-security rejection answers 404 here rather than falling through to 500.
            raise HTTPException(status_code=404, detail="Media object not found")
        except Exception as e:
            # Log the real error for debugging; never echo it (it can leak filesystem paths or bucket internals).
            log_warning(f"Failed to fetch media {storage_key}: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch media from storage")

        media_type = getattr(ref, "mime_type", None)
        if not media_type:
            media_type = mimetypes.guess_type(storage_key)[0] or "application/octet-stream"
        # The mime type arrives from the client and is persisted, so it is validated on the way
        # out: Starlette copies it into Content-Type verbatim and a newline breaks the response.
        media_type = media_type.split(";")[0].strip().lower()
        if not _MIME_TYPE_PATTERN.fullmatch(media_type):
            media_type = "application/octet-stream"
        headers = {"X-Content-Type-Options": "nosniff"}
        if media_type in _ACTIVE_CONTENT_TYPES:
            # Content-Disposition is ignored for subresources; declaring a non-executable type is
            # what makes nosniff bite.
            headers["Content-Disposition"] = "attachment"
            media_type = "application/octet-stream"
        # download() returns the whole object, so send one body with a Content-Length.
        # StreamingResponse would iterate the bytes as lines, one frame per newline.
        return Response(content=data, media_type=media_type, headers=headers)

    return router
