import asyncio
from typing import TYPE_CHECKING, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.agent import Agent
from agno.agent import _init as agent_init
from agno.exceptions import ComponentRehydrationError
from agno.fs import FileSystem, InvalidPathError
from agno.fs._paths import normalize_directory, normalize_path, path_sort_key
from agno.knowledge.page.types import PageError
from agno.os.auth import get_authentication_dependency, require_resource_access
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.filesystem.schema import (
    FileSource,
    FileSourceContentResponse,
    FileSourceListResponse,
    FileSourceSearchEntry,
    FileSourceSearchResponse,
    FileSystemContentResponse,
    FileSystemEntry,
    FileSystemListResponse,
    FileSystemSearchEntry,
    FileSystemSearchResponse,
    FileSystemUsage,
)
from agno.os.routers.filesystem.sources import (
    _list_sources,
    _page_entries,
    _page_error,
    _pagination,
    _resolve_source,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_agent_by_id
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS


_MAX_PREVIEW_CHARS = 100_000


def _get_agent_filesystem(os: "AgentOS", agent_id: str, request: Request) -> FileSystem:
    user_isolation_enabled = bool(getattr(request.state, "user_isolation_enabled", False))
    scoped_user_id = get_scoped_user_id(request)

    try:
        agent = get_agent_by_id(
            agent_id=agent_id,
            agents=os.agents,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
            user_id=scoped_user_id,
            published_only=False,
        )
    except ComponentRehydrationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        log_error(f"Error resolving filesystem agent '{agent_id}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not isinstance(agent, Agent):
        raise HTTPException(status_code=501, detail="This agent does not support filesystem browsing")
    if not agent.filesystem:
        raise HTTPException(status_code=404, detail="This agent does not have a filesystem")

    agent_init.set_filesystem_user_isolation(agent, user_isolation_enabled)
    try:
        filesystem = agent.filesystem_instance
    except Exception as e:
        log_error(f"Error initializing filesystem for agent '{agent_id}': {e}")
        raise HTTPException(status_code=503, detail="Agent filesystem is unavailable")
    if filesystem is None:
        raise HTTPException(status_code=503, detail="Agent filesystem is unavailable")
    if not isinstance(filesystem, FileSystem):
        raise HTTPException(status_code=501, detail="Use the Knowledge file source to browse this agent's pages")
    if not user_isolation_enabled:
        return filesystem
    effective_user_id = scoped_user_id or getattr(request.state, "user_id", None)
    if not isinstance(effective_user_id, str) or not effective_user_id.strip():
        raise HTTPException(status_code=403, detail="A user identity is required when user isolation is enabled")
    return filesystem.resolve(user_id=effective_user_id)


def _list_entries(filesystem: FileSystem, directory: str) -> list[FileSystemEntry]:
    normalized_directory = normalize_directory(directory)
    prefix = f"{normalized_directory}/" if normalized_directory else ""
    directories: Dict[str, FileSystemEntry] = {}
    files: list[FileSystemEntry] = []

    for meta in filesystem.list(normalized_directory):
        relative_path = meta.path[len(prefix) :] if prefix and meta.path.startswith(prefix) else meta.path
        name, separator, _ = relative_path.partition("/")
        if separator:
            directory_path = f"{prefix}{name}" if prefix else name
            existing = directories.get(directory_path)
            if existing is None:
                directories[directory_path] = FileSystemEntry(
                    path=directory_path,
                    type="directory",
                    size_bytes=meta.size_bytes,
                    updated_at=meta.updated_at,
                )
            else:
                existing.size_bytes = (existing.size_bytes or 0) + meta.size_bytes
                if meta.updated_at is not None:
                    existing.updated_at = max(existing.updated_at or meta.updated_at, meta.updated_at)
            continue
        files.append(
            FileSystemEntry(
                path=meta.path,
                type="file",
                size_bytes=meta.size_bytes,
                version=meta.version,
                updated_at=meta.updated_at,
            )
        )

    return sorted(directories.values(), key=lambda entry: path_sort_key(entry.path)) + sorted(
        files, key=lambda entry: path_sort_key(entry.path)
    )


def get_filesystem_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/agents/{agent_id}/files",
        response_model=FileSystemListResponse,
        tags=["FileSystem"],
        operation_id="list_agent_files",
        dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
    )
    async def list_agent_files(
        agent_id: str,
        request: Request,
        directory: str = Query("", description="Relative directory inside the agent filesystem"),
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemListResponse:
        filesystem = _get_agent_filesystem(os, agent_id, request)
        try:
            normalized_directory = normalize_directory(directory)
            entries = await asyncio.to_thread(_list_entries, filesystem, normalized_directory)
            usage = await filesystem.ausage()
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))

        total_count = len(entries)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemListResponse(
            agent_id=agent_id,
            directory=normalized_directory,
            entries=entries[start : start + limit],
            usage=FileSystemUsage(
                file_count=usage.file_count,
                total_bytes=usage.total_bytes,
                bytes_limit=filesystem.max_namespace_bytes,
            ),
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get(
        "/agents/{agent_id}/files/content",
        response_model=FileSystemContentResponse,
        tags=["FileSystem"],
        operation_id="read_agent_file",
        dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
    )
    async def read_agent_file(
        agent_id: str,
        request: Request,
        path: str = Query(..., description="Relative file path inside the agent filesystem"),
    ) -> FileSystemContentResponse:
        filesystem = _get_agent_filesystem(os, agent_id, request)
        try:
            normalized_path = normalize_path(path)
            metadata = await filesystem.astat(normalized_path)
            content = await filesystem.aread(normalized_path)
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if metadata is None or content is None:
            raise HTTPException(status_code=404, detail="File not found")
        preview = content[:_MAX_PREVIEW_CHARS]
        return FileSystemContentResponse(
            agent_id=agent_id,
            path=metadata.path,
            content=preview,
            size_bytes=metadata.size_bytes,
            version=metadata.version,
            updated_at=metadata.updated_at,
            line_count=0 if not content else content.count("\n") + (0 if content.endswith("\n") else 1),
            truncated=len(preview) < len(content),
        )

    @router.get(
        "/agents/{agent_id}/files/search",
        response_model=FileSystemSearchResponse,
        tags=["FileSystem"],
        operation_id="search_agent_files",
        dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
    )
    async def search_agent_files(
        agent_id: str,
        request: Request,
        query: str = Query(..., min_length=1, max_length=200),
        directory: str = Query(""),
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemSearchResponse:
        filesystem = _get_agent_filesystem(os, agent_id, request)
        try:
            normalized_directory = normalize_directory(directory)
            files = await filesystem.alist(normalized_directory)
            matches = await filesystem.asearch(
                query,
                directory=normalized_directory,
                limit=max(len(files), 1),
            )
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))

        total_count = len(matches)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemSearchResponse(
            agent_id=agent_id,
            query=query,
            directory=normalized_directory,
            entries=[
                FileSystemSearchEntry(
                    path=match.path,
                    size_bytes=match.size_bytes,
                    snippet=match.snippet,
                    line=match.line,
                    match_count=match.match_count,
                )
                for match in matches[start : start + limit]
            ],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get("/filesystem/sources", response_model=list[FileSource], tags=["FileSystem"])
    async def list_file_sources(request: Request) -> list[FileSource]:
        """List configured sources authorized for this caller, never database namespaces."""
        return await asyncio.to_thread(_list_sources, os, request)

    @router.get("/filesystem/sources/{source_id}/files", response_model=FileSourceListResponse, tags=["FileSystem"])
    async def list_source_files(
        source_id: str,
        request: Request,
        directory: str = Query(""),
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=100),
    ) -> FileSourceListResponse:
        agent_id, knowledge = _resolve_source(os, request, source_id)
        if agent_id is not None:
            result = await list_agent_files(agent_id, request, directory, page, limit)
            return FileSourceListResponse(source_id=source_id, **result.model_dump(exclude={"agent_id"}))
        if knowledge is None:
            raise HTTPException(status_code=404, detail="File source not found")
        try:
            directory = normalize_directory(directory)
            entries = await asyncio.wait_for(_page_entries(knowledge, directory), timeout=20)
        except PageError as error:
            raise _page_error(error) from error
        except (InvalidPathError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Invalid directory") from error
        except TimeoutError as error:
            raise HTTPException(status_code=503, detail="Knowledge listing timed out") from error
        start = (page - 1) * limit
        return FileSourceListResponse(
            source_id=source_id,
            directory=directory,
            entries=entries[start : start + limit],
            meta=_pagination(len(entries), page, limit),
        )

    @router.get(
        "/filesystem/sources/{source_id}/files/content", response_model=FileSourceContentResponse, tags=["FileSystem"]
    )
    async def read_source_file(
        source_id: str,
        request: Request,
        path: str = Query(...),
        revision: Optional[str] = Query(None),
    ) -> FileSourceContentResponse:
        agent_id, knowledge = _resolve_source(os, request, source_id)
        if agent_id is not None:
            result = await read_agent_file(agent_id, request, path)
            return FileSourceContentResponse(source_id=source_id, **result.model_dump(exclude={"agent_id"}))
        if knowledge is None:
            raise HTTPException(status_code=404, detail="File source not found")
        try:
            path = normalize_path(path)
            content = await knowledge.aread_page("/" + path, revision=revision, max_chars=24_000)
        except PageError as error:
            raise _page_error(error) from error
        except (InvalidPathError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Invalid page path") from error
        return FileSourceContentResponse(
            source_id=source_id,
            path=content.path.lstrip("/"),
            content=content.text,
            size_bytes=None if content.truncated else len(content.text.encode("utf-8")),
            title=content.title,
            url=content.url,
            revision=content.revision,
            next_offset=content.next_offset,
            truncated=content.truncated,
            line_count=None if content.truncated else len(content.text.splitlines()),
        )

    @router.get(
        "/filesystem/sources/{source_id}/files/search", response_model=FileSourceSearchResponse, tags=["FileSystem"]
    )
    async def search_source_files(
        source_id: str,
        request: Request,
        query: str = Query(..., min_length=1, max_length=200),
        directory: str = Query(""),
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=100),
    ) -> FileSourceSearchResponse:
        agent_id, knowledge = _resolve_source(os, request, source_id)
        if agent_id is not None:
            result = await search_agent_files(agent_id, request, query, directory, page, limit)
            return FileSourceSearchResponse(source_id=source_id, **result.model_dump(exclude={"agent_id"}))
        if knowledge is None:
            raise HTTPException(status_code=404, detail="File source not found")
        if not query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be blank")
        try:
            directory = normalize_directory(directory)
            prefix = f"/{directory}/" if directory else "/"
            matches = await knowledge.agrep_pages(query, prefix=prefix, ignore_case=True, limit=100)
        except PageError as error:
            raise _page_error(error) from error
        except (InvalidPathError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Invalid page search") from error
        entries: dict[str, FileSourceSearchEntry] = {}
        for match in matches.matches:
            path = match.path.lstrip("/")
            if path in entries:
                entries[path].match_count += 1
            else:
                entries[path] = FileSourceSearchEntry(
                    path=path,
                    snippet=match.text,
                    line=match.line_number,
                    match_count=1,
                    url=match.url,
                    revision=match.revision,
                )
        start = (page - 1) * limit
        return FileSourceSearchResponse(
            source_id=source_id,
            query=query,
            directory=directory,
            entries=list(entries.values())[start : start + limit],
            meta=_pagination(len(entries), page, limit),
            partial=not matches.complete,
        )

    return router
